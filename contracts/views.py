"""
API согласования договоров. Личность — b24_user_id (заголовок X-B24-User),
как в остальных модулях. Маршрут строится автоматически (contracts.routing),
согласование идёт на движке approvalflow.
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
from core.auth import get_current_b24_id, is_lawyer

from . import constants, services
from .models import Contract
from .serializers import (
    ContractDetailSerializer,
    ContractListSerializer,
    ContractWriteSerializer,
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
class ContractViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        self.b24_id = get_current_b24_id(request)
        if not self.b24_id:
            raise AuthenticationFailed("Требуется авторизация Битрикс24.")
        return super().initial(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ContractWriteSerializer
        if self.action == "list":
            return ContractListSerializer
        return ContractDetailSerializer

    def _participant_contract_ids(self):
        """ID договоров, где я согласующий (в любом круге).

        Юристу засчитываем ВЕСЬ групповой юр-этап — и ещё не согласованный
        (b24_user_id пуст), и уже закрытый другим юристом (после решения в
        participant проставляется id решавшего). Иначе договор, согласованный
        коллегой, пропадал из вкладок остальных сотрудников юротдела."""
        ct = ContentType.objects.get_for_model(Contract)
        cond = Q(b24_user_id=self.b24_id)
        if is_lawyer(self.b24_id):
            cond |= Q(role=constants.roles.ROLE_LEGAL_DEPT)
        return (
            ApprovalParticipant.objects
            .filter(Q(round__approval__content_type=ct) & cond)
            .values_list("round__approval__object_id", flat=True)
            .distinct()
        )

    def get_queryset(self):
        qs = Contract.objects.select_related("organization", "cfo")
        # Раздел «Договоры» по умолчанию = только СВОИ (созданные мной).
        # ?scope=participant — где я согласующий, ?scope=all — и мои, и чужие,
        # в которых я участвую (вкладки списка).
        if self.action == "list":
            scope = self.request.query_params.get("scope") or "mine"
            mine = Q(initiator_b24_id=self.b24_id)
            participant = Q(id__in=self._participant_contract_ids())
            if scope == "participant":
                qs = qs.filter(participant)
            elif scope == "all":
                if is_lawyer(self.b24_id):
                    # Юротделу во вкладке «Все» показываем все договоры, кроме
                    # чужих черновиков: юрист и так вправе открыть любую карточку
                    # (_can_view), а без общего списка невозможно ловить дубли —
                    # типовые договоры вообще не проходят через юр-этап маршрута.
                    qs = qs.filter(mine | ~Q(status=constants.STATUS_DRAFT))
                else:
                    qs = qs.filter(mine | participant)
            else:
                qs = qs.filter(mine)
        status_f = self.request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        return qs

    def _is_participant(self, contract) -> bool:
        approval = services.get_approval(contract)
        if approval is None:
            return False
        return ApprovalParticipant.objects.filter(
            round__approval=approval, b24_user_id=self.b24_id
        ).exists()

    def _can_view(self, contract) -> bool:
        """Карточку договора видит инициатор, любой его согласующий или юрист."""
        return (
            contract.initiator_b24_id == self.b24_id
            or self._is_participant(contract)
            or is_lawyer(self.b24_id)
        )

    def get_object(self):
        obj = super().get_object()
        if not self._can_view(obj):
            raise NotFound()
        return obj

    def create(self, request, *args, **kwargs):
        ser = ContractWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        contract = services.create_contract(
            organization=data.pop("organization"),
            initiator_b24_id=self.b24_id,
            **data,
        )
        return Response(ContractDetailSerializer(contract).data, status=201)

    def _detail(self, contract):
        contract.refresh_from_db()
        return Response(ContractDetailSerializer(contract).data)

    def _run(self, fn):
        try:
            fn()
        except services.ContractError as e:
            return Response({"detail": str(e)}, status=400)
        return None

    def _require_initiator(self, contract):
        if contract.initiator_b24_id != self.b24_id:
            raise PermissionDenied("Действие доступно только инициатору договора.")

    # --- маршрут ---
    @action(detail=True, methods=["get"], url_path="route_preview")
    def route_preview(self, request, pk=None):
        contract = self.get_object()
        return Response({"route": services.build_route(contract)})

    # --- инбокс: договоры, ждущие моего решения (для общего «Требует действия») ---
    @action(detail=False, methods=["get"])
    def todo(self, request):
        out = []
        qs = Contract.objects.select_related("organization", "cfo").filter(
            status=constants.STATUS_ON_APPROVAL
        )
        lawyer = is_lawyer(self.b24_id)
        for contract in qs:
            pending = services.current_pending_participant(services.get_approval(contract))
            if pending is None:
                continue
            mine = (
                (services.is_group_legal(pending) and lawyer)
                or pending.b24_user_id == self.b24_id
            )
            if mine:
                out.append(contract)
        return Response(ContractListSerializer(out, many=True).data)

    # --- согласование ---
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        contract = self.get_object()
        self._require_initiator(contract)
        flow_type = request.data.get("flow_type")
        comment = (request.data.get("comment") or "").strip()
        err = self._run(lambda: services.submit(
            contract, _participants(request.data),
            flow_type=flow_type, actor_b24_id=self.b24_id, comment=comment,
        ))
        return err or self._detail(contract)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        contract = self.get_object()
        err = self._run(lambda: services.decide(
            contract, request.data.get("participant_id"),
            request.data.get("decision"), (request.data.get("comment") or "").strip(),
            actor_b24_id=self.b24_id,
        ))
        return err or self._detail(contract)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_revision(self, request, pk=None):
        contract = self.get_object()
        self._require_initiator(contract)
        err = self._run(lambda: services.return_for_revision(
            contract, by_b24_id=self.b24_id,
            comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(contract)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        contract = self.get_object()
        self._require_initiator(contract)
        err = self._run(lambda: services.cancel(contract, by_b24_id=self.b24_id))
        return err or self._detail(contract)

    def destroy(self, request, *args, **kwargs):
        contract = self.get_object()
        self._require_initiator(contract)
        if contract.status != constants.STATUS_CANCELED:
            raise PermissionDenied("Удалить можно только отменённый договор.")
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"], url_path="sheet_pdf")
    def sheet_pdf(self, request, pk=None):
        """Лист согласования договора (PDF) — как у заявок (ТЗ п.7.7)."""
        contract = self.get_object()
        approval = services.get_approval(contract)
        if approval is None:
            return Response(
                {"detail": "Договор ещё не отправлен на согласование."}, status=400
            )
        pdf = flow_sheet.render_pdf(approval, role_names=constants.ROLE_NAMES)
        return FileResponse(
            io.BytesIO(pdf), content_type="application/pdf",
            filename=f"Лист_согласования_{contract.number}.pdf",
        )

    @action(detail=False, methods=["get"])
    def meta(self, request):
        """Справочники для формы договора."""
        return Response({
            "statuses": [{"code": c, "name": n} for c, n in constants.STATUS_CHOICES],
            "roles": [{"code": c, "name": n} for c, n in constants.ROLE_NAMES.items()],
            "cfo_categories": [
                {"code": c, "name": n} for c, n in constants.CFO_CATEGORY_CHOICES
            ],
        })
