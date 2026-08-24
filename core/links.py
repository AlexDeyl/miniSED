"""
Ссылки на карточки MiniSED — для писем и уведомлений Битрикс24.

Уведомление должно приводить человека прямо в нужную карточку, а не на
главную. Куда именно вести — зависит от настроек:

* задан BITRIX_APP_URL (страница приложения в портале, вида
  https://<портал>.bitrix24.ru/marketplace/app/<ID>/) — ведём туда, человек
  остаётся ВНУТРИ Битрикса, приложение открывается в его интерфейсе;
* иначе — на сам MiniSED (PUBLIC_BASE_URL + /app/), приложение откроется
  отдельной вкладкой.

Маршрут SPA передаётся параметром `to`; его читает approvals.views.app_view и
вкладывает во фронт (window.__MINISED_BOOT__.route).
"""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings


def app_link(route: str) -> str:
    """Ссылка, открывающая карточку по маршруту SPA (например /contracts/5).

    Пустая строка, если ни BITRIX_APP_URL, ни PUBLIC_BASE_URL не заданы —
    вызывающая сторона тогда просто не добавляет ссылку в уведомление."""
    if not route:
        return ""
    param = f"to={quote(route, safe='')}"

    portal_app = (getattr(settings, "BITRIX_APP_URL", "") or "").strip()
    if portal_app:
        base = portal_app if portal_app.endswith("/") else portal_app + "/"
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{param}"

    public = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if not public:
        return ""
    return f"{public}/app/?{param}"


# --- маршруты карточек по модулям -------------------------------------------
def agreement_route(agreement_id) -> str:
    """Старый модуль: карточка живёт внутри списка «Согласования»."""
    return f"/svetofor?open={agreement_id}"


def contract_route(contract_id) -> str:
    return f"/contracts/{contract_id}"


def request_route(request_id) -> str:
    return f"/requests/{request_id}"


def compliment_route(compliment_id) -> str:
    return f"/compliments/{compliment_id}"
