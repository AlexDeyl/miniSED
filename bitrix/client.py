"""
Серверный клиент REST API Битрикс24.

Инкапсулирует всё общение с порталом: авторизацию по сохранённому
access_token, автоматическое обновление по refresh_token и вызовы методов.
Фронтенд больше не должен обращаться к BX24.callMethod за данными —
он ходит в наши endpoint'ы, а те используют этот клиент.
"""

from __future__ import annotations

import requests
from django.conf import settings
from django.utils import timezone

from .models import BitrixApiLog, BitrixPortal, BitrixToken

DEFAULT_TIMEOUT = 15


class BitrixError(Exception):
    """Ошибка вызова REST Битрикс24 (сетевая или прикладная)."""


class BitrixAuthError(BitrixError):
    """Не удалось авторизоваться / обновить токен."""


def flatten_params(params, parent_key: str = "") -> list[tuple[str, str]]:
    """
    Разворачивает вложенные dict/list в PHP-совместимые пары ключ-значение,
    которые понимает Битрикс: {"filter": {"%TITLE": "x"}} -> filter[%TITLE]=x.
    """
    items: list[tuple[str, str]] = []
    if isinstance(params, dict):
        for key, value in params.items():
            new_key = f"{parent_key}[{key}]" if parent_key else str(key)
            items.extend(flatten_params(value, new_key))
    elif isinstance(params, (list, tuple)):
        for idx, value in enumerate(params):
            new_key = f"{parent_key}[{idx}]"
            items.extend(flatten_params(value, new_key))
    else:
        if params is None:
            params = ""
        items.append((parent_key, str(params)))
    return items


def get_active_portal(domain: str | None = None) -> BitrixPortal | None:
    """
    Выбирает портал для запроса:
      - по домену, если он передан (multi-portal готовность);
      - иначе единственный активный портал.
    """
    qs = BitrixPortal.objects.filter(is_active=True)
    if domain:
        return qs.filter(domain=domain).first()
    return qs.order_by("-updated_at").first()


class BitrixClient:
    def __init__(self, portal: BitrixPortal):
        self.portal = portal

    @property
    def token(self) -> BitrixToken:
        token = getattr(self.portal, "token", None)
        if token is None:
            raise BitrixAuthError(
                f"Для портала {self.portal.domain} не сохранён токен доступа."
            )
        return token

    def call(self, method: str, params: dict | None = None, _retry: bool = True):
        """
        Вызывает REST-метод (например, 'crm.deal.list').
        При протухшем токене — обновляет и повторяет один раз.
        """
        token = self.token
        if token.is_expired and _retry:
            self.refresh()
            token = self.token

        url = f"https://{self.portal.domain}/rest/{method}"
        data = flatten_params(params or {})
        data.append(("auth", token.access_token))

        try:
            resp = requests.post(url, data=data, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            self._log(method, ok=False, error=f"network: {exc}")
            raise BitrixError(f"Сеть недоступна: {exc}") from exc

        payload = self._parse(resp, method)

        if isinstance(payload, dict) and payload.get("error"):
            err = payload.get("error")
            if err in ("expired_token", "invalid_token") and _retry:
                self.refresh()
                return self.call(method, params, _retry=False)
            desc = payload.get("error_description") or err
            self._log(method, ok=False, status_code=resp.status_code, error=str(desc))
            raise BitrixError(f"Битрикс вернул ошибку: {desc}")

        self._log(method, ok=True, status_code=resp.status_code)
        return payload.get("result") if isinstance(payload, dict) else payload

    def refresh(self):
        """Обновляет access_token по refresh_token."""
        token = self.token
        if not token.refresh_token:
            raise BitrixAuthError("Нет refresh_token — требуется повторная авторизация.")

        try:
            resp = requests.get(
                settings.BITRIX_OAUTH_TOKEN_URL,
                params={
                    "grant_type": "refresh_token",
                    "client_id": settings.BITRIX_CLIENT_ID,
                    "client_secret": settings.BITRIX_CLIENT_SECRET,
                    "refresh_token": token.refresh_token,
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise BitrixAuthError(f"Не удалось обновить токен: {exc}") from exc

        data = resp.json()
        if data.get("error") or not data.get("access_token"):
            raise BitrixAuthError(
                f"Обновление токена отклонено: {data.get('error_description') or data.get('error')}"
            )

        store_token(self.portal, data)
        self.portal.refresh_from_db()

    # --- вспомогательное ---
    def _parse(self, resp, method):
        try:
            return resp.json()
        except ValueError:
            self._log(
                method, ok=False, status_code=resp.status_code, error="bad json"
            )
            raise BitrixError(
                f"Некорректный ответ Битрикс (HTTP {resp.status_code})."
            )

    def _log(self, method, ok, status_code=None, error=""):
        try:
            BitrixApiLog.objects.create(
                portal=self.portal,
                method=method,
                ok=ok,
                status_code=status_code,
                error=error[:2000],
            )
        except Exception:
            # логирование не должно ронять основной запрос
            pass


def store_token(portal: BitrixPortal, token_data: dict) -> BitrixToken:
    """
    Сохраняет/обновляет токены портала из ответа OAuth
    (поля access_token, refresh_token, expires_in / expires).
    """
    expires_at = None
    expires_in = token_data.get("expires_in")
    if expires_in:
        try:
            expires_at = timezone.now() + timezone.timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None

    token, _ = BitrixToken.objects.update_or_create(
        portal=portal,
        defaults={
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token", "")
            or getattr(getattr(portal, "token", None), "refresh_token", ""),
            "expires_at": expires_at,
        },
    )
    return token


# ---------------------------------------------------------------------------
# Высокоуровневые операции (используются во views)
# ---------------------------------------------------------------------------
def search_deals(client: BitrixClient, query: str, limit: int = 20) -> list[dict]:
    """Поиск сделок по названию. Замена клиентского BX24.selectCRM."""
    result = client.call(
        "crm.deal.list",
        {
            "filter": {"%TITLE": query} if query else {},
            "select": ["ID", "TITLE", "OPPORTUNITY", "CURRENCY_ID", "COMPANY_ID"],
            "order": {"ID": "DESC"},
            "start": 0,
        },
    )
    deals = result if isinstance(result, list) else []
    return deals[:limit]


def get_deal(client: BitrixClient, deal_id: int) -> dict:
    """Карточка сделки по ID."""
    result = client.call("crm.deal.get", {"id": deal_id})
    return result if isinstance(result, dict) else {}


def search_users(client: BitrixClient, query: str, limit: int = 20) -> list[dict]:
    """Поиск сотрудников. Замена клиентского BX24.selectUsers."""
    result = client.call(
        "user.search",
        {"FIND": query, "ACTIVE": True} if query else {"ACTIVE": True},
    )
    users = result if isinstance(result, list) else []
    return users[:limit]


def get_users_by_ids(client: BitrixClient, ids: list[int]) -> list[dict]:
    """Сотрудники по списку ID (ФИО/должность) — чтобы показывать имена,
    как в старом миниседе, а не «USER #id»."""
    out = []
    for uid in ids[:50]:
        try:
            res = client.call("user.get", {"ID": uid})
            if isinstance(res, list) and res:
                out.append(res[0])
        except Exception:
            continue
    return out


def profiles_by_ids(ids) -> dict[int, dict[str, str]]:
    """{b24_id: {"fio", "position"}} для сотрудников портала — best-effort.

    Нужно для участников, которых нет в матрице UserProfile (их выбрали
    поиском по Битриксу): без этого они попадают в листы согласования как
    «USER #id». Без активного портала или при ошибке API — пустой словарь."""
    bids = [int(x) for x in ids if x]
    if not bids:
        return {}
    try:
        portal = get_active_portal()
        if not portal:
            return {}
        users = get_users_by_ids(BitrixClient(portal), bids)
    except Exception:
        return {}
    out: dict[int, dict[str, str]] = {}
    for u in users:
        try:
            uid = int(u.get("ID"))
        except (TypeError, ValueError):
            continue
        fio = " ".join(
            x.strip()
            for x in (u.get("LAST_NAME"), u.get("NAME"), u.get("SECOND_NAME"))
            if x and x.strip()
        )
        if fio:
            out[uid] = {"fio": fio, "position": (u.get("WORK_POSITION") or "").strip()}
    return out


def notify_user(
    client: BitrixClient, user_id, message: str, *,
    link: str = "", link_text: str = "Перейти к согласованию",
) -> None:
    """Системное уведомление пользователю портала (колокольчик Битрикс24).

    Требует scope `im` у приложения; при отсутствии — вызов бросит ошибку,
    которую вызывающая сторона гасит (уведомления best-effort).

    link — куда вести из уведомления. Оформляем BB-кодом [URL]: в колокольчике
    видна подпись («Перейти к согласованию»), а не голый адрес. Кнопок как
    таковых у уведомлений нет — KEYBOARD доступен только сообщениям чат-ботов,
    поэтому ссылка-подпись это максимум, что даёт im.notify.system.add."""
    if link:
        message = f"{message}\n\n[URL={link}]{link_text}[/URL]"
    client.call("im.notify.system.add", {"USER_ID": user_id, "MESSAGE": message})


def add_timeline_comment(client: BitrixClient, deal_id: int, comment: str) -> dict:
    """Добавляет комментарий в таймлайн сделки (статус согласования)."""
    return client.call(
        "crm.timeline.comment.add",
        {
            "fields": {
                "ENTITY_ID": deal_id,
                "ENTITY_TYPE": "deal",
                "COMMENT": comment,
            }
        },
    )
