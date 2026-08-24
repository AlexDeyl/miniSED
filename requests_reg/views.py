"""
API регламентных заявок: согласование (через движок) + исполнение юротделом.
Личность — b24_user_id (заголовок X-B24-User).
"""

from urllib.parse import unquote_to_bytes

import requests as http
from django.conf import settings


def _query_param(request, name, default=""):
    """GET-параметр с устойчивым декодированием кириллицы.

    Периметр (openresty) перекодирует кириллицу в query-строке из UTF-8 в CP1251,
    поэтому читаем СЫРЫЕ байты query и пробуем UTF-8, затем CP1251 (иначе Django
    декодирует cp1251-байты как UTF-8 и получается мусор).

    QUERY_STRING по WSGI — это байты, декодированные как latin-1, поэтому перед
    раскодированием %XX возвращаем строку в байты тем же latin-1. Иначе клиент,
    приславший кириллицу в query БЕЗ процентного кодирования, доезжал мусором.
    """
    qs = request.META.get("QUERY_STRING", "") or ""
    prefix = name + "="
    for part in qs.split("&"):
        if part.startswith(prefix):
            value = part[len(prefix):].replace("+", " ")
            try:
                raw = unquote_to_bytes(value.encode("latin-1"))
            except UnicodeEncodeError:  # не из WSGI (тесты, внутренние вызовы)
                raw = unquote_to_bytes(value)
            for enc in ("utf-8", "cp1251"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
    return default
from django.http import FileResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from rest_framework.exceptions import NotFound, PermissionDenied

from approvalflow.models import ApprovalParticipant
from core.auth import can_view_all, get_current_b24_id, is_lawyer

from . import constants, services
from .models import PowerTemplate, RegulatoryRequest
from .search import search
from .serializers import (
    RegulatoryRequestDetailSerializer,
    RegulatoryRequestListSerializer,
    RegulatoryRequestWriteSerializer,
)


@api_view(["GET"])
@permission_classes([AllowAny])
def fms_unit(request):
    """Подсказка «кем выдан» по коду подразделения ФМС (XXX-XXX) через DaData.

    Без настроенного DADATA_API_KEY возвращает пустой список (фронт не подставляет).
    """
    code = _query_param(request, "code").strip()
    key = getattr(settings, "DADATA_API_KEY", "") or ""
    if not code or not key:
        return Response({"results": []})
    try:
        resp = http.post(
            "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/fms_unit",
            json={"query": code, "count": 10},
            headers={"Accept": "application/json", "Authorization": f"Token {key}"},
            timeout=8,
        )
        suggestions = resp.json().get("suggestions", []) if resp.ok else []
    except Exception:
        suggestions = []
    # приоритет — точные совпадения по коду
    exact = [s for s in suggestions if (s.get("data") or {}).get("code") == code]
    picked = exact or suggestions
    results = [
        {"value": s.get("value", ""), "code": (s.get("data") or {}).get("code", "")}
        for s in picked
    ]
    return Response({"results": results})


@api_view(["GET"])
@permission_classes([AllowAny])
def address_suggest(request):
    """Подсказки по адресу (DaData) для автокомплита. ?q=... → список адресов.

    Без DADATA_API_KEY или при query < 3 символов возвращает пустой список.
    """
    q = _query_param(request, "q").strip()
    key = getattr(settings, "DADATA_API_KEY", "") or ""
    if len(q) < 3 or not key:
        return Response({"results": []})
    try:
        resp = http.post(
            "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
            json={"query": q, "count": 8},
            headers={"Accept": "application/json", "Authorization": f"Token {key}"},
            timeout=8,
        )
        suggestions = resp.json().get("suggestions", []) if resp.ok else []
    except Exception:
        suggestions = []
    results = [
        {
            "value": s.get("value", ""),
            "postal_code": (s.get("data") or {}).get("postal_code") or "",
        }
        for s in suggestions
    ]
    return Response({"results": results})


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
        if self.action in ("list", "legal_queue"):
            return RegulatoryRequestListSerializer
        return RegulatoryRequestDetailSerializer

    def get_queryset(self):
        qs = RegulatoryRequest.objects.select_related("organization")
        # Раздел «Регламентные заявки» = только СВОИ (созданные мной);
        # сотрудник с правом сквозного просмотра видит все.
        if self.action == "list" and not can_view_all(self.b24_id):
            qs = qs.filter(initiator_b24_id=self.b24_id)
        rtype = self.request.query_params.get("type")
        if rtype:
            qs = qs.filter(request_type=rtype)
        status_f = self.request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        if self.action == "list":
            qs = search(qs, _query_param(self.request, "q"))
        return qs

    def _is_participant(self, req) -> bool:
        approval = services.get_approval(req)
        if approval is None:
            return False
        return ApprovalParticipant.objects.filter(
            round__approval=approval, b24_user_id=self.b24_id
        ).exists()

    def _can_view(self, req) -> bool:
        """Кто видит карточку заявки: инициатор, любой её согласующий, юрист."""
        return (
            req.initiator_b24_id == self.b24_id
            or self._is_participant(req)
            or is_lawyer(self.b24_id)
            or can_view_all(self.b24_id)
        )

    def get_object(self):
        obj = super().get_object()
        if not self._can_view(obj):
            raise NotFound()
        return obj

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

    # --- маршрут ---
    @action(detail=True, methods=["get"], url_path="route_preview")
    def route_preview(self, request, pk=None):
        req = self.get_object()
        return Response({"route": services.build_route(req)})

    def _require_initiator(self, req):
        if req.initiator_b24_id != self.b24_id:
            raise PermissionDenied("Действие доступно только инициатору заявки.")

    def _require_lawyer(self, *, read_only=False):
        """Действия юротдела — только юристам. Для чтения очереди пускаем и
        сотрудника со сквозным просмотром (администратора)."""
        if is_lawyer(self.b24_id):
            return
        if read_only and can_view_all(self.b24_id):
            return
        raise PermissionDenied("Раздел доступен только сотрудникам юридического отдела.")

    # --- инбокс: заявки, ждущие моего решения (для общего «Требует действия») ---
    @action(detail=False, methods=["get"])
    def todo(self, request):
        out = []
        qs = RegulatoryRequest.objects.select_related("organization").filter(
            status=constants.STATUS_ON_APPROVAL
        )
        lawyer = is_lawyer(self.b24_id)
        for req in qs:
            pending = services.current_pending_participant(services.get_approval(req))
            if pending is None:
                continue
            mine = (
                (services.is_group_legal(pending) and lawyer)
                or pending.b24_user_id == self.b24_id
            )
            if mine:
                out.append(req)
        return Response(RegulatoryRequestListSerializer(out, many=True).data)

    # --- согласование ---
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        req = self.get_object()
        self._require_initiator(req)
        flow_type = request.data.get("flow_type")
        comment = (request.data.get("comment") or "").strip()
        err = self._run(lambda: services.submit(
            req, _participants(request.data), flow_type=flow_type,
            actor_b24_id=self.b24_id, comment=comment,
        ))
        return err or self._detail(req)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        req = self.get_object()
        err = self._run(lambda: services.decide(
            req, request.data.get("participant_id"),
            request.data.get("decision"), (request.data.get("comment") or "").strip(),
            actor_b24_id=self.b24_id,
        ))
        return err or self._detail(req)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_revision(self, request, pk=None):
        req = self.get_object()
        self._require_initiator(req)
        err = self._run(lambda: services.return_for_revision(
            req, by_b24_id=self.b24_id, comment=(request.data.get("comment") or "").strip(),
        ))
        return err or self._detail(req)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        self._require_initiator(req)
        err = self._run(lambda: services.cancel(req, by_b24_id=self.b24_id))
        return err or self._detail(req)

    def destroy(self, request, *args, **kwargs):
        # Удалять можно только отменённую заявку и только инициатору.
        req = self.get_object()
        self._require_initiator(req)
        if req.status != constants.STATUS_CANCELED:
            raise PermissionDenied("Удалить можно только отменённую заявку.")
        return super().destroy(request, *args, **kwargs)

    # --- исполнение юротделом (только юристы) ---
    @action(detail=False, methods=["get"], url_path="legal_queue")
    def legal_queue(self, request):
        self._require_lawyer(read_only=True)
        # scope: new (новые) / work (в работе) / archive (закрытые) / all;
        # по умолчанию — активные
        scope = (request.query_params.get("scope") or "").strip()
        query = _query_param(request, "q").strip()
        # При поиске вкладка не сужает выборку: ищут дубли, а в каком статусе
        # лежит найденное — заранее неизвестно. Фронт об этом предупреждает.
        statuses = (
            constants.LEGAL_ALL_STATUSES if query
            else constants.LEGAL_SCOPES.get(scope, constants.LEGAL_QUEUE_STATUSES)
        )
        qs = (
            RegulatoryRequest.objects.select_related("organization")
            .filter(status__in=statuses)
            .order_by("-id")
        )
        qs = search(qs, query)
        return Response(RegulatoryRequestListSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="take")
    def take(self, request, pk=None):
        req = self.get_object()
        self._require_lawyer()
        return self._run(lambda: services.take_in_work(req)) or self._detail(req)

    @action(detail=True, methods=["post"], url_path="to_signing")
    def to_signing(self, request, pk=None):
        req = self.get_object()
        self._require_lawyer()
        return self._run(lambda: services.to_signing(req)) or self._detail(req)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        req = self.get_object()
        self._require_lawyer()
        return self._run(lambda: services.execute(
            req,
            delivery_method=(request.data.get("delivery_method") or "").strip(),
            delivery_comment=(request.data.get("delivery_comment") or "").strip(),
        )) or self._detail(req)

    @action(detail=True, methods=["post"], url_path="confirm_receipt")
    def confirm_receipt(self, request, pk=None):
        req = self.get_object()
        # Закрыть заявку («получил/ознакомился») может только инициатор —
        # юрист не закрывает заявку за него.
        self._require_initiator(req)
        return self._run(lambda: services.confirm_receipt(req, by_b24_id=self.b24_id)) or self._detail(req)

    @action(detail=False, methods=["get"])
    def types(self, request):
        return Response({
            "types": [{"code": c, "name": n} for c, (n, _p) in constants.REQUEST_TYPES.items()],
            "statuses": [{"code": c, "name": n} for c, n in constants.STATUS_CHOICES],
            "delivery_methods": [{"code": c, "name": n} for c, n in constants.DELIVERY_CHOICES],
            "roles": [{"code": c, "name": n} for c, n in constants.ROLE_NAMES.items()],
        })

    @action(detail=True, methods=["get"], url_path="sheet_pdf")
    def sheet_pdf(self, request, pk=None):
        """Лист согласования заявки (PDF) — с ФИО, должностью и ролями."""
        import io

        from approvalflow import sheet as flow_sheet

        req = self.get_object()
        approval = services.get_approval(req)
        if approval is None:
            return Response({"detail": "Заявка ещё не отправлена на согласование."}, status=400)
        pdf = flow_sheet.render_pdf(approval, role_names=constants.ROLE_NAMES)
        return FileResponse(
            io.BytesIO(pdf), content_type="application/pdf",
            filename=f"Лист_согласования_{req.number}.pdf",
        )

    @action(detail=True, methods=["get"], url_path="anketa_pdf")
    def anketa_pdf(self, request, pk=None):
        """Заполненное PDF-заявление (формируется на лету из анкеты)."""
        from . import anketa_pdf as anketa

        req = self.get_object()
        import io

        pdf = anketa.render_pdf(req)
        return FileResponse(
            io.BytesIO(pdf), content_type="application/pdf",
            filename=f"anketa_{req.number}.pdf",
        )

    @action(detail=False, methods=["get"], url_path="power_templates")
    def power_templates(self, request):
        """Матрица шаблонов доверенностей (для выбора полномочий в анкете)."""
        qs = PowerTemplate.objects.filter(is_active=True)
        return Response([
            {"code": t.code, "name": t.name, "powers": t.powers} for t in qs
        ])
