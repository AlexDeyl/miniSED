"""
API заявок на согласование ДИ. Личность — b24_user_id (заголовок X-B24-User),
как в остальных модулях.

Видимость: инициатор — свои заявки; согласующие — те, где участвуют (юрист —
и групповой юр-этап); сотрудники отдела по работе с персоналом — все
отправленные заявки (они их исполняют и проверяют).
"""

import io

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http import FileResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from approvalflow import sheet as flow_sheet
from approvalflow.models import ApprovalParticipant
from core.auth import can_view_all, get_current_b24_id, is_admin_mode, is_lawyer
from core.models import CFO, Facility, Organization
from core.search import query_param
from core.services import log_action

from . import constants, hr_staff, services
from .models import JobDescription
from .search import search
from .serializers import JobDescDetailSerializer, JobDescListSerializer, JobDescWriteSerializer


def _participants(data):
    raw = data.get("participants")
    if not isinstance(raw, list):
        return []
    return [
        {
            "type": p.get("type", "internal"),
            "b24_user_id": p.get("b24_user_id"),
            "email": p.get("email", ""),
            "name": p.get("name", ""),
            "role": p.get("role", ""),
            "order": p.get("order", i),
            "is_required": p.get("is_required", True),
        }
        for i, p in enumerate(raw)
        if isinstance(p, dict)
    ]


@method_decorator(csrf_exempt, name="dispatch")
class JobDescViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        self.b24_id = get_current_b24_id(request)
        if not self.b24_id:
            raise AuthenticationFailed("Требуется авторизация Битрикс24.")
        return super().initial(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return JobDescWriteSerializer
        if self.action == "list":
            return JobDescListSerializer
        return JobDescDetailSerializer

    # --- доступ ---
    def _is_hr(self) -> bool:
        if not hasattr(self, "_hr_cache"):
            self._hr_cache = hr_staff.is_hr_staff(self.b24_id)
        return self._hr_cache

    def _participant_ids(self):
        """ID заявок, где я согласующий; юристу — и весь групповой юр-этап."""
        ct = ContentType.objects.get_for_model(JobDescription)
        cond = Q(b24_user_id=self.b24_id)
        if is_lawyer(self.b24_id):
            cond |= Q(role=constants.ROLE_LEGAL_DEPT)
        return (
            ApprovalParticipant.objects
            .filter(Q(round__approval__content_type=ct) & cond)
            .values_list("round__approval__object_id", flat=True)
            .distinct()
        )

    def get_queryset(self):
        qs = JobDescription.objects.select_related("organization", "cfo", "facility")
        query = query_param(self.request, "q").strip() if self.action == "list" else ""
        if self.action == "list" and is_admin_mode(self.request):
            pass  # режим администратора — все заявки
        elif self.action == "list":
            scope = self.request.query_params.get("scope") or "mine"
            mine = Q(initiator_b24_id=self.b24_id)
            participant = Q(id__in=self._participant_ids())
            if scope == "participant":
                qs = qs.filter(participant)
            elif scope == "all":
                if self._is_hr():
                    # отдел персонала видит все отправленные заявки (чужие
                    # черновики — ещё не заявки)
                    qs = qs.filter(mine | ~Q(status=constants.STATUS_DRAFT))
                else:
                    qs = qs.filter(mine | participant | Q(executor_b24_id=self.b24_id))
            else:
                qs = qs.filter(mine)
        status_f = self.request.query_params.get("status") if not query else None
        if status_f:
            qs = qs.filter(status=status_f)
        return search(qs, query)

    def _can_view(self, jd) -> bool:
        if can_view_all(self.b24_id) or jd.initiator_b24_id == self.b24_id:
            return True
        if jd.executor_b24_id == self.b24_id:
            return True
        if self._is_hr() and jd.status != constants.STATUS_DRAFT:
            return True
        return JobDescription.objects.filter(pk=jd.pk, id__in=self._participant_ids()).exists()

    def get_object(self):
        obj = super().get_object()
        if not self._can_view(obj):
            raise NotFound()
        return obj

    def _require_initiator(self, jd):
        if jd.initiator_b24_id != self.b24_id:
            raise PermissionDenied("Действие доступно только инициатору заявки.")

    def _require_hr(self):
        if not (self._is_hr() or is_admin_mode(self.request)):
            raise PermissionDenied("Действие доступно сотрудникам отдела по работе с персоналом.")

    def _detail(self, jd):
        jd.refresh_from_db()
        return Response(JobDescDetailSerializer(jd).data)

    def _run(self, fn):
        try:
            fn()
        except services.JobDescError as e:
            return Response({"detail": str(e)}, status=400)
        return None

    # --- CRUD ---
    def create(self, request, *args, **kwargs):
        ser = JobDescWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        jd = services.create_jobdesc(initiator_b24_id=self.b24_id, **ser.validated_data)
        return Response(JobDescDetailSerializer(jd).data, status=201)

    def update(self, request, *args, **kwargs):
        jd = self.get_object()
        self._require_initiator(jd)
        if jd.status not in constants.EDITABLE_STATUSES:
            raise PermissionDenied(
                "Править заявку можно, пока она черновик, возвращена на доработку или отклонена."
            )
        ser = self.get_serializer(jd, data=request.data, partial=kwargs.get("partial", False))
        ser.is_valid(raise_exception=True)
        ser.save()
        log_action(
            "jobdesc_edited", target=jd, request=request,
            new_value={"fields": sorted(ser.validated_data.keys()), "by_b24_id": self.b24_id},
        )
        return self._detail(jd)

    def destroy(self, request, *args, **kwargs):
        jd = self.get_object()
        self._require_initiator(jd)
        if jd.status != constants.STATUS_CANCELED:
            raise PermissionDenied("Удалить можно только отменённую заявку.")
        return super().destroy(request, *args, **kwargs)

    # --- маршрут и согласование ---
    @action(detail=True, methods=["get"], url_path="route_preview")
    def route_preview(self, request, pk=None):
        return Response({"route": services.build_route(self.get_object())})

    @action(detail=False, methods=["get"])
    def todo(self, request):
        """Требует моего действия: решение по этапу либо «Получил / ознакомился»."""
        out = []
        lawyer = is_lawyer(self.b24_id)
        qs = JobDescription.objects.select_related("organization", "cfo", "facility")
        for jd in qs.filter(status=constants.STATUS_ON_APPROVAL):
            pending = services.current_pending_participant(services.get_approval(jd))
            if pending is None:
                continue
            if pending.b24_user_id == self.b24_id or (services.is_group_legal(pending) and lawyer):
                out.append(jd)
        out += list(qs.filter(status=constants.STATUS_EXECUTED, initiator_b24_id=self.b24_id))
        return Response(JobDescListSerializer(out, many=True).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        jd = self.get_object()
        self._require_initiator(jd)
        err = self._run(lambda: services.submit(
            jd, _participants(request.data), actor_b24_id=self.b24_id,
            comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(jd)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        jd = self.get_object()
        admin_id = self.b24_id if is_admin_mode(request) else None
        err = self._run(lambda: services.decide(
            jd, request.data.get("participant_id"), request.data.get("decision"),
            (request.data.get("comment") or "").strip(),
            actor_b24_id=self.b24_id, admin_b24_id=admin_id,
        ))
        if err is None and admin_id is not None:
            log_action(
                "admin_override_decision", target=jd, request=request,
                new_value={
                    "participant_id": request.data.get("participant_id"),
                    "decision": request.data.get("decision"),
                    "by_b24_id": admin_id,
                },
            )
        return err or self._detail(jd)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_revision(self, request, pk=None):
        """Инициатор забирает заявку с круга на доработку. Согласующему, которому
        нужны правки, — «Отклонить» с комментарием: инициатор поправит и
        перезапустит согласование новым кругом."""
        jd = self.get_object()
        self._require_initiator(jd)
        err = self._run(lambda: services.return_for_revision(
            jd, by_b24_id=self.b24_id, comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(jd)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        jd = self.get_object()
        self._require_initiator(jd)
        err = self._run(lambda: services.cancel(jd, by_b24_id=self.b24_id))
        return err or self._detail(jd)

    # --- исполнение отделом по работе с персоналом ---
    @action(detail=False, methods=["get"], url_path="hr_queue")
    def hr_queue(self, request):
        """Раздел «Заявки для отдела по работе с персоналом»."""
        self._require_hr()
        scope = request.query_params.get("scope") or "new"
        query = query_param(request, "q").strip()
        statuses = (
            constants.HR_ALL_STATUSES if query
            else constants.HR_SCOPES.get(scope, constants.HR_SCOPES["new"])
        )
        qs = JobDescription.objects.select_related("organization", "cfo", "facility")
        qs = search(qs.filter(status__in=statuses), query)
        return Response(JobDescListSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def take(self, request, pk=None):
        jd = self.get_object()
        self._require_hr()
        err = self._run(lambda: services.take_in_work(jd, executor_b24_id=self.b24_id))
        return err or self._detail(jd)

    @action(detail=True, methods=["post"], url_path="set_status")
    def set_status(self, request, pk=None):
        jd = self.get_object()
        self._require_hr()
        err = self._run(lambda: services.set_status(
            jd, request.data.get("status") or "", by_b24_id=self.b24_id,
        ))
        return err or self._detail(jd)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        jd = self.get_object()
        self._require_hr()
        err = self._run(lambda: services.execute(
            jd, executor_b24_id=self.b24_id,
            transfer_method=request.data.get("transfer_method") or "",
            comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(jd)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        jd = self.get_object()
        self._require_initiator(jd)
        err = self._run(lambda: services.acknowledge(jd, by_b24_id=self.b24_id))
        return err or self._detail(jd)

    # --- сотрудники отдела персонала ---
    @action(detail=False, methods=["get"], url_path="hr_staff")
    def hr_staff_list(self, request):
        return Response(hr_staff.staff_options())

    @action(detail=False, methods=["post"], url_path="hr_staff/sync")
    def hr_staff_sync(self, request):
        """Подтянуть сотрудников отдела из Битрикс24 (кнопка в разделе)."""
        if not (self._is_hr() or can_view_all(self.b24_id)):
            raise PermissionDenied("Доступно сотрудникам отдела по работе с персоналом.")
        try:
            result = hr_staff.sync()
        except hr_staff.HrSyncError as e:
            return Response({"detail": str(e)}, status=502)
        log_action("jobdesc_hr_staff_synced", request=request, new_value=result)
        return Response({**result, "staff": hr_staff.staff_options()})

    # --- документы на выходе ---
    @action(detail=True, methods=["get"], url_path="sheet_pdf")
    def sheet_pdf(self, request, pk=None):
        """Лист согласования (PDF) — по всем кругам."""
        jd = self.get_object()
        approval = services.get_approval(jd)
        if approval is None:
            return Response({"detail": "Заявка ещё не отправлена на согласование."}, status=400)
        pdf = flow_sheet.render_pdf(approval, role_names=constants.ROLE_NAMES)
        return FileResponse(
            io.BytesIO(pdf), content_type="application/pdf",
            filename=f"Лист_согласования_{jd.number}.pdf",
        )

    @action(detail=False, methods=["get"])
    def meta(self, request):
        """Справочники формы и флаг «я из отдела персонала»."""
        cat_names = dict(CFO.CATEGORY_CHOICES)
        return Response({
            "statuses": [{"code": c, "name": n} for c, n in constants.STATUS_CHOICES],
            "transfer_methods": [{"code": c, "name": n} for c, n in constants.TRANSFER_CHOICES],
            "roles": [{"code": c, "name": n} for c, n in constants.ROLE_NAMES.items()],
            "organizations": [
                {"id": o.id, "name": o.short_name}
                for o in Organization.objects.filter(is_active=True).order_by("short_name")
            ],
            "facilities": [
                {"id": f.id, "name": f.name, "organization": f.organization_id}
                for f in Facility.objects.filter(is_active=True).order_by("name")
            ],
            "cfos": [
                {
                    "id": c.id, "name": c.name, "organization": c.organization_id,
                    "category": c.category, "category_name": cat_names.get(c.category, ""),
                }
                for c in CFO.objects.filter(is_active=True).order_by("name")
            ],
            "is_hr_staff": self._is_hr(),
        })
