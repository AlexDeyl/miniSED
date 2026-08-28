"""
API заявок на комплименты. Личность — b24_user_id (заголовок X-B24-User),
как в остальных модулях.

Видимость (решение заказчика): свои заявки видит инициатор; руководитель
отдела продаж согласует все заявки, поэтому видит все. Согласующие и
исполнители видят те заявки, где они участвуют.
"""

import io

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http import FileResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotFound,
    PermissionDenied,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from approvalflow import sheet as flow_sheet
from approvalflow.models import ApprovalParticipant
from core.auth import can_view_all, get_current_b24_id
from core.search import query_param
from requests_reg.models import RoleAssignment

from . import constants, form_pdf, services
from .models import Compliment
from .search import search
from .serializers import (
    ComplimentDetailSerializer,
    ComplimentListSerializer,
    ComplimentWriteSerializer,
)


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
class ComplimentViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        self.b24_id = get_current_b24_id(request)
        if not self.b24_id:
            raise AuthenticationFailed("Требуется авторизация Битрикс24.")
        return super().initial(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ComplimentWriteSerializer
        if self.action == "list":
            return ComplimentListSerializer
        return ComplimentDetailSerializer

    # --- доступ ---
    def _is_sales_head(self) -> bool:
        """Руководитель отдела продаж согласует все заявки → видит все."""
        return RoleAssignment.objects.filter(
            role_code=constants.ROLE_SALES_HEAD, user_b24_id=self.b24_id, is_active=True
        ).exists()

    def _participant_ids(self):
        ct = ContentType.objects.get_for_model(Compliment)
        return (
            ApprovalParticipant.objects
            .filter(round__approval__content_type=ct, b24_user_id=self.b24_id)
            .values_list("round__approval__object_id", flat=True)
            .distinct()
        )

    def get_queryset(self):
        qs = Compliment.objects.select_related("facility", "organization")
        # Поиск (?q=) — по компании, гостю, отелю, содержанию комплимента и
        # ИМЕНАМ прикреплённых файлов.
        query = query_param(self.request, "q").strip() if self.action == "list" else ""
        if self.action == "list":
            scope = self.request.query_params.get("scope") or "mine"
            if can_view_all(self.b24_id) and scope == "all":
                pass  # сквозной просмотр (администратор) — все заявки
            elif self._is_sales_head() and scope == "all":
                pass  # руководитель продаж видит всё
            elif scope == "participant":
                qs = qs.filter(id__in=self._participant_ids())
            elif scope == "all":
                qs = qs.filter(
                    Q(initiator_b24_id=self.b24_id)
                    | Q(id__in=self._participant_ids())
                    | Q(executor_b24_id=self.b24_id)
                )
            else:
                qs = qs.filter(initiator_b24_id=self.b24_id)
        # При поиске вкладка (статус) не сужает выборку: ищут конкретную
        # заявку, а в каком она статусе — заранее неизвестно.
        status_f = self.request.query_params.get("status") if not query else None
        if status_f:
            qs = qs.filter(status=status_f)
        return search(qs, query)

    def _is_executor_role(self, compliment) -> bool:
        """Я на роли исполнителя этой категории (даже если персонально не назначен)."""
        role_code = services.routing.executor_role(compliment)
        return bool(role_code) and RoleAssignment.objects.filter(
            role_code=role_code, user_b24_id=self.b24_id, is_active=True
        ).exists()

    def _can_view(self, compliment) -> bool:
        if can_view_all(self.b24_id):
            return True
        if compliment.initiator_b24_id == self.b24_id:
            return True
        if compliment.executor_b24_id == self.b24_id:
            return True
        if self._is_sales_head():
            return True
        # исполнитель по роли видит заявки своей категории — они в его очереди
        if self._is_executor_role(compliment):
            return True
        approval = services.get_approval(compliment)
        return approval is not None and ApprovalParticipant.objects.filter(
            round__approval=approval, b24_user_id=self.b24_id
        ).exists()

    def get_object(self):
        obj = super().get_object()
        if not self._can_view(obj):
            raise NotFound()
        return obj

    def _require_initiator(self, compliment):
        if compliment.initiator_b24_id != self.b24_id:
            raise PermissionDenied("Действие доступно только инициатору заявки.")

    # --- CRUD ---
    def create(self, request, *args, **kwargs):
        ser = ComplimentWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        compliment = services.create_compliment(
            initiator_b24_id=self.b24_id, **ser.validated_data
        )
        return Response(ComplimentDetailSerializer(compliment).data, status=201)

    def _detail(self, compliment):
        compliment.refresh_from_db()
        return Response(ComplimentDetailSerializer(compliment).data)

    def _run(self, fn):
        try:
            fn()
        except services.ComplimentError as e:
            return Response({"detail": str(e)}, status=400)
        return None

    def destroy(self, request, *args, **kwargs):
        compliment = self.get_object()
        self._require_initiator(compliment)
        if compliment.status != constants.STATUS_CANCELED:
            raise PermissionDenied("Удалить можно только отменённую заявку.")
        return super().destroy(request, *args, **kwargs)

    # --- маршрут и согласование ---
    @action(detail=True, methods=["get"], url_path="route_preview")
    def route_preview(self, request, pk=None):
        compliment = self.get_object()
        return Response({"route": services.build_route(compliment)})

    @action(detail=False, methods=["get"])
    def todo(self, request):
        """Заявки, ждущие моего решения — в общий «Требует действия»."""
        out = []
        for compliment in Compliment.objects.filter(status=constants.STATUS_ON_APPROVAL):
            pending = services.current_pending_participant(services.get_approval(compliment))
            if pending is not None and pending.b24_user_id == self.b24_id:
                out.append(compliment)
        return Response(ComplimentListSerializer(out, many=True).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        compliment = self.get_object()
        self._require_initiator(compliment)
        comment = (request.data.get("comment") or "").strip()
        err = self._run(lambda: services.submit(
            compliment, _participants(request.data), actor_b24_id=self.b24_id,
            comment=comment,
        ))
        return err or self._detail(compliment)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        compliment = self.get_object()
        err = self._run(lambda: services.decide(
            compliment, request.data.get("participant_id"),
            request.data.get("decision"), (request.data.get("comment") or "").strip(),
            actor_b24_id=self.b24_id,
        ))
        return err or self._detail(compliment)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_revision(self, request, pk=None):
        compliment = self.get_object()
        self._require_initiator(compliment)
        err = self._run(lambda: services.return_for_revision(
            compliment, by_b24_id=self.b24_id,
            comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(compliment)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        compliment = self.get_object()
        self._require_initiator(compliment)
        err = self._run(lambda: services.cancel(compliment, by_b24_id=self.b24_id))
        return err or self._detail(compliment)

    # --- исполнение ---
    def _require_executor(self, compliment):
        """Исполнять может назначенный исполнитель либо сотрудник на роли
        исполнителя этой категории (если персонально ещё не назначен)."""
        if compliment.executor_b24_id:
            if compliment.executor_b24_id != self.b24_id:
                raise PermissionDenied("Заявка закреплена за другим исполнителем.")
            return
        role_code = services.routing.executor_role(compliment)
        if not role_code or not RoleAssignment.objects.filter(
            role_code=role_code, user_b24_id=self.b24_id, is_active=True
        ).exists():
            raise PermissionDenied("Вы не исполнитель этой заявки.")

    @action(detail=False, methods=["get"], url_path="execution_queue")
    def execution_queue(self, request):
        """Раздел «Заявки для исполнения»: новые / в работе / архив."""
        scope = request.query_params.get("scope") or "new"
        query = query_param(request, "q").strip()
        # При поиске вкладка не сужает выборку: заявку ищут, не зная её статуса.
        statuses = (
            constants.EXECUTION_ALL_STATUSES if query
            else constants.EXECUTION_SCOPES.get(scope, constants.EXECUTION_NEW_STATUSES)
        )
        qs = Compliment.objects.select_related("facility").filter(status__in=statuses)

        # Мои роли исполнителя → какие категории мне показывать.
        my_roles = set(
            RoleAssignment.objects
            .filter(user_b24_id=self.b24_id, is_active=True)
            .values_list("role_code", flat=True)
        )
        my_categories = [
            code for code, plan in constants.CATEGORY_ROUTES.items()
            if plan["executor"] in my_roles
        ]
        qs = qs.filter(Q(executor_b24_id=self.b24_id) | Q(category__in=my_categories))
        qs = search(qs, query)
        return Response(ComplimentListSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="take")
    def take(self, request, pk=None):
        compliment = self.get_object()
        self._require_executor(compliment)
        err = self._run(lambda: services.take_in_work(compliment, executor_b24_id=self.b24_id))
        return err or self._detail(compliment)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        compliment = self.get_object()
        self._require_executor(compliment)
        err = self._run(lambda: services.execute(
            compliment, executor_b24_id=self.b24_id,
            comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(compliment)

    # --- документы на выходе ---
    @action(detail=True, methods=["get"], url_path="sheet_pdf")
    def sheet_pdf(self, request, pk=None):
        """Лист согласования (PDF)."""
        compliment = self.get_object()
        approval = services.get_approval(compliment)
        if approval is None:
            return Response(
                {"detail": "Заявка ещё не отправлена на согласование."}, status=400
            )
        pdf = flow_sheet.render_pdf(approval, role_names=constants.ROLE_NAMES)
        return FileResponse(
            io.BytesIO(pdf), content_type="application/pdf",
            filename=f"Лист_согласования_{compliment.number}.pdf",
        )

    @action(detail=True, methods=["get"], url_path="form_pdf")
    def form_pdf_view(self, request, pk=None):
        """Бланк заявки по форме из ТЗ; ?with_sheet=1 — вместе с листом."""
        compliment = self.get_object()
        with_sheet = request.query_params.get("with_sheet") in ("1", "true", "yes")
        approval = services.get_approval(compliment) if with_sheet else None
        pdf = form_pdf.render_pdf(compliment, approval=approval)
        return FileResponse(
            io.BytesIO(pdf), content_type="application/pdf",
            filename=f"Заявка_{compliment.number}.pdf",
        )

    @action(detail=False, methods=["get"])
    def meta(self, request):
        """Справочники для формы заявки."""
        return Response({
            "statuses": [{"code": c, "name": n} for c, n in constants.STATUS_CHOICES],
            "categories": [{"code": c, "name": n} for c, n in constants.CATEGORY_CHOICES],
            "roles": [{"code": c, "name": n} for c, n in constants.ROLE_NAMES.items()],
        })
