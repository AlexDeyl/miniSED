"""
API регламентных заявок. Согласование проксируется в движок approvalflow.
Личность — b24_user_id (заголовок X-B24-User), как в остальных модулях.
"""

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.auth import get_current_b24_id

from . import constants, services
from .models import RegulatoryRequest
from .serializers import (
    RegulatoryRequestDetailSerializer,
    RegulatoryRequestListSerializer,
    RegulatoryRequestWriteSerializer,
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
class RegulatoryRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        self.b24_id = get_current_b24_id(request)
        if not self.b24_id:
            raise AuthenticationFailed("Требуется авторизация Битрикс24.")
        return super().initial(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return RegulatoryRequestWriteSerializer
        if self.action == "list":
            return RegulatoryRequestListSerializer
        return RegulatoryRequestDetailSerializer

    def get_queryset(self):
        qs = RegulatoryRequest.objects.select_related("organization")
        rtype = self.request.query_params.get("type")
        if rtype:
            qs = qs.filter(request_type=rtype)
        status_f = self.request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        return qs

    def create(self, request, *args, **kwargs):
        ser = RegulatoryRequestWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        req = services.create_request(
            request_type=data.pop("request_type"),
            organization=data.pop("organization"),
            initiator_b24_id=self.b24_id,
            **data,
        )
        return Response(RegulatoryRequestDetailSerializer(req).data, status=201)

    def _detail(self, req):
        req.refresh_from_db()
        return Response(RegulatoryRequestDetailSerializer(req).data)

    def _run(self, fn):
        try:
            fn()
        except services.RequestError as e:
            return Response({"detail": str(e)}, status=400)
        return None

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        req = self.get_object()
        flow_type = request.data.get("flow_type")
        err = self._run(lambda: services.submit(req, _participants(request.data), flow_type=flow_type))
        return err or self._detail(req)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        req = self.get_object()
        err = self._run(lambda: services.decide(
            req, request.data.get("participant_id"),
            request.data.get("decision"), (request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(req)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_revision(self, request, pk=None):
        req = self.get_object()
        err = self._run(lambda: services.return_for_revision(
            req, by_b24_id=self.b24_id, comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(req)

    @action(detail=True, methods=["post"], url_path="in_work")
    def in_work(self, request, pk=None):
        req = self.get_object()
        return self._run(lambda: services.mark_in_work(req)) or self._detail(req)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        req = self.get_object()
        return self._run(lambda: services.mark_issued(req)) or self._detail(req)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        req = self.get_object()
        return self._run(lambda: services.close(req)) or self._detail(req)

    @action(detail=False, methods=["get"])
    def types(self, request):
        """Справочник типов и статусов для фронта."""
        return Response(
            {
                "types": [{"code": c, "name": n} for c, (n, _p) in constants.REQUEST_TYPES.items()],
                "statuses": [{"code": c, "name": n} for c, n in constants.STATUS_CHOICES],
            }
        )
