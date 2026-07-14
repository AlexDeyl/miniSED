"""
API Bitrix Connector.

Серверные endpoint'ы, заменяющие клиентские вызовы BX24.* :
  POST /api/bitrix/auth/        — сохранить токены портала (из BX24.getAuth или OAuth)
  GET  /api/bitrix/deals/       — поиск CRM-сделок           (замена BX24.selectCRM)
  GET  /api/bitrix/deals/<id>/  — карточка сделки
  GET  /api/bitrix/users/       — поиск сотрудников           (замена BX24.selectUsers)
  POST /api/bitrix/timeline/    — комментарий в таймлайн сделки
  GET  /api/bitrix/status/      — подключён ли портал (для фронта)
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .client import (
    BitrixAuthError,
    BitrixClient,
    BitrixError,
    add_timeline_comment,
    get_active_portal,
    get_deal,
    get_users_by_ids,
    search_deals,
    search_users,
    store_token,
)
from .models import BitrixPortal


def _resolve_client(request) -> BitrixClient:
    """Находит подключённый портал (по ?domain= или единственный активный)."""
    domain = request.GET.get("domain") or request.data.get("domain")
    portal = get_active_portal(domain)
    if portal is None:
        raise BitrixAuthError(
            "Портал Битрикс24 не подключён. Откройте приложение из Битрикс24 "
            "или пройдите авторизацию."
        )
    return BitrixClient(portal)


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def bitrix_auth(request):
    """
    Сохраняет токены портала.

    Ожидает: domain, (member_id), access_token, refresh_token, expires_in.
    Фронт внутри iframe берёт их из BX24.getAuth(); при прямой авторизации
    с домена их кладёт OAuth-callback.
    """
    domain = (request.data.get("domain") or "").strip()
    access_token = (request.data.get("access_token") or "").strip()
    if not domain or not access_token:
        return Response(
            {"detail": "Нужны как минимум domain и access_token."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    member_id = (request.data.get("member_id") or "").strip() or None
    portal = _upsert_portal(domain, member_id)
    store_token(
        portal,
        {
            "access_token": access_token,
            "refresh_token": (request.data.get("refresh_token") or "").strip(),
            "expires_in": request.data.get("expires_in") or request.data.get("expires"),
        },
    )
    return Response({"domain": portal.domain, "connected": True})


def _upsert_portal(domain: str, member_id: str | None) -> BitrixPortal:
    portal = None
    if member_id:
        portal = BitrixPortal.objects.filter(member_id=member_id).first()
    if portal is None:
        portal = BitrixPortal.objects.filter(domain=domain).first()

    if portal is None:
        portal = BitrixPortal.objects.create(
            domain=domain, member_id=member_id, is_active=True
        )
    else:
        changed = False
        if portal.domain != domain:
            portal.domain = domain
            changed = True
        if member_id and portal.member_id != member_id:
            portal.member_id = member_id
            changed = True
        if not portal.is_active:
            portal.is_active = True
            changed = True
        if changed:
            portal.save()
    return portal


@api_view(["GET"])
@permission_classes([AllowAny])
def bitrix_status(request):
    """Сообщает фронту, подключён ли портал (можно ли искать на сервере)."""
    portal = get_active_portal(request.GET.get("domain"))
    connected = bool(portal and getattr(portal, "token", None))
    return Response(
        {"connected": connected, "domain": portal.domain if portal else None}
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def deals_search(request):
    query = (request.GET.get("q") or "").strip()
    try:
        client = _resolve_client(request)
        deals = search_deals(client, query)
    except (BitrixError, BitrixAuthError) as exc:
        return Response({"detail": str(exc)}, status=_err_status(exc))
    return Response({"results": deals})


@api_view(["GET"])
@permission_classes([AllowAny])
def deal_detail(request, deal_id: int):
    try:
        client = _resolve_client(request)
        deal = get_deal(client, deal_id)
    except (BitrixError, BitrixAuthError) as exc:
        return Response({"detail": str(exc)}, status=_err_status(exc))
    if not deal:
        return Response({"detail": "Сделка не найдена."}, status=404)
    return Response(deal)


@api_view(["GET"])
@permission_classes([AllowAny])
def users_search(request):
    query = (request.GET.get("q") or "").strip()
    ids_raw = (request.GET.get("ids") or "").strip()
    try:
        client = _resolve_client(request)
        if ids_raw:
            ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
            users = get_users_by_ids(client, ids)
        else:
            users = search_users(client, query)
    except (BitrixError, BitrixAuthError) as exc:
        return Response({"detail": str(exc)}, status=_err_status(exc))
    return Response({"results": users})


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def timeline_comment(request):
    deal_id = request.data.get("deal_id")
    comment = (request.data.get("comment") or "").strip()
    if not deal_id or not comment:
        return Response(
            {"detail": "Нужны deal_id и comment."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        client = _resolve_client(request)
        result = add_timeline_comment(client, int(deal_id), comment)
    except (BitrixError, BitrixAuthError) as exc:
        return Response({"detail": str(exc)}, status=_err_status(exc))
    except (TypeError, ValueError):
        return Response({"detail": "Некорректный deal_id."}, status=400)
    return Response({"id": result})


def _err_status(exc) -> int:
    # Проблемы авторизации -> 409 (нужно переподключить портал),
    # прочие ошибки интеграции -> 502 (внешний сервис).
    return status.HTTP_409_CONFLICT if isinstance(exc, BitrixAuthError) else 502
