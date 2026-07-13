"""
DRF API движка согласований.

Личность — b24_user_id (заголовок X-B24-User), как в approvals.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http import FileResponse, Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.auth import get_current_b24_id

from . import services
from .models import Approval, ApprovalParticipant
from .serializers import (
    ApprovalCreateSerializer,
    ApprovalDetailSerializer,
    ApprovalListSerializer,
)
from .sheet import generate_sheet


def _parse_participants(data) -> list[dict]:
    """Достаёт список участников из тела запроса (list of dict)."""
    raw = data.get("participants")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "type": item.get("type", "internal"),
                "b24_user_id": item.get("b24_user_id"),
                "email": item.get("email", ""),
                "name": item.get("name", ""),
                "role": item.get("role", ""),
                "order": item.get("order", 0),
                "is_required": item.get("is_required", True),
            }
        )
    return out


@method_decorator(csrf_exempt, name="dispatch")
class ApprovalViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    pagination_class = None

    def get_serializer_class(self):
        if self.action == "create":
            return ApprovalCreateSerializer
        if self.action in ("list",):
            return ApprovalListSerializer
        return ApprovalDetailSerializer

    def initial(self, request, *args, **kwargs):
        self.b24_id = get_current_b24_id(request)
        if not self.b24_id:
            raise AuthenticationFailed("Требуется авторизация Битрикс24.")
        return super().initial(request, *args, **kwargs)

    def get_queryset(self):
        uid = getattr(self, "b24_id", None)
        qs = Approval.objects.prefetch_related(
            "rounds__participants", "sheets", "route_changes"
        )
        if not uid:
            return qs.none()
        return qs.filter(
            Q(initiator_b24_id=uid) | Q(rounds__participants__b24_user_id=uid)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(initiator_b24_id=self.b24_id, status=Approval.STATUS_DRAFT)

    def _detail(self, approval):
        # свежий инстанс без устаревшего prefetch-кэша (после мутаций)
        fresh = Approval.objects.get(pk=approval.pk)
        return Response(ApprovalDetailSerializer(fresh).data)

    # --- действия процесса ---
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        approval = self.get_object()
        participants = _parse_participants(request.data)
        try:
            services.submit(approval, participants)
        except services.ApprovalError as e:
            return Response({"detail": str(e)}, status=400)
        return self._detail(approval)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        approval = self.get_object()
        participant_id = request.data.get("participant_id")
        decision = request.data.get("decision")
        comment = (request.data.get("comment") or "").strip()

        try:
            participant = ApprovalParticipant.objects.get(
                id=participant_id, round__approval=approval
            )
        except ApprovalParticipant.DoesNotExist:
            return Response({"detail": "Участник не найден."}, status=404)

        if (
            participant.type == ApprovalParticipant.TYPE_INTERNAL
            and str(participant.b24_user_id) != str(self.b24_id)
        ):
            return Response({"detail": "Недостаточно прав."}, status=403)

        try:
            services.decide(participant, decision, comment)
        except services.ApprovalError as e:
            return Response({"detail": str(e)}, status=400)
        return self._detail(approval)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_revision(self, request, pk=None):
        approval = self.get_object()
        comment = (request.data.get("comment") or "").strip()
        try:
            services.return_for_revision(
                approval, by_b24_id=self.b24_id, comment=comment
            )
        except services.ApprovalError as e:
            return Response({"detail": str(e)}, status=400)
        return self._detail(approval)

    @action(detail=True, methods=["post"], url_path="new_round")
    def new_round(self, request, pk=None):
        approval = self.get_object()
        participants = _parse_participants(request.data)
        try:
            services.start_new_round(approval, participants)
        except services.ApprovalError as e:
            return Response({"detail": str(e)}, status=400)
        return self._detail(approval)

    @action(detail=True, methods=["post"], url_path="change_route")
    def change_route(self, request, pk=None):
        approval = self.get_object()
        participants = _parse_participants(request.data)
        reason = (request.data.get("reason") or "").strip()
        try:
            services.change_route(
                approval, participants, by_b24_id=self.b24_id, reason=reason
            )
        except services.ApprovalError as e:
            return Response({"detail": str(e)}, status=400)
        return self._detail(approval)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        approval = self.get_object()
        if approval.initiator_b24_id != self.b24_id:
            return Response({"detail": "Отменить может только инициатор."}, status=403)
        try:
            services.cancel(approval)
        except services.ApprovalError as e:
            return Response({"detail": str(e)}, status=400)
        return self._detail(approval)

    @action(detail=True, methods=["post"], url_path="generate_sheet")
    def generate_sheet(self, request, pk=None):
        approval = self.get_object()
        sheet = generate_sheet(approval, generated_by_b24_id=self.b24_id)
        return Response(
            {
                "id": sheet.id,
                "file_url": f"/api/approvalflow/approvals/{approval.id}/sheet/{sheet.id}/download/",
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path=r"sheet/(?P<sheet_id>\d+)/download",
    )
    def sheet_download(self, request, pk=None, sheet_id=None):
        approval = self.get_object()
        sheet = approval.sheets.filter(id=sheet_id).first()
        if sheet is None or not sheet.generated_file:
            raise Http404("Лист согласования не найден.")
        return FileResponse(
            sheet.generated_file.open("rb"),
            content_type="application/pdf",
            filename=f"approval_{approval.id}_sheet.pdf",
        )
