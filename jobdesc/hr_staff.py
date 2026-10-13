"""
Кто работает в отделе по работе с персоналом.

Источник — подразделение портала Битрикс24: сотрудников подтягиваем по REST
(department.get → user.get по UF_DEPARTMENT) в таблицу HrStaff. Синхронизация
идёт фоном (команда sync_hr_staff по cron) или кнопкой в разделе, а не на
каждый запрос: портал отвечает медленно и бывает недоступен, а флаг «я из
отдела персонала» нужен уже при входе.

Отдел ищем по подстроке в названии (настройка JOBDESC_HR_DEPARTMENT_MATCH),
вместе с вложенными подразделениями. Руководитель отдела по работе с
персоналом (роль hr_head) и назначенные на роль hr_specialist считаются
сотрудниками отдела всегда — даже без синхронизации.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from requests_reg.models import RoleAssignment

from . import constants as K
from .models import HrStaff

DEFAULT_DEPARTMENT_MATCH = "по работе с персоналом"
PAGE = 50  # Битрикс отдаёт списки страницами по 50


class HrSyncError(Exception):
    pass


def _role_ids() -> set[int]:
    return set(
        RoleAssignment.objects
        .filter(role_code__in=[K.ROLE_HR_SPECIALIST, K.ROLE_HR_HEAD], is_active=True)
        .values_list("user_b24_id", flat=True)
    )


def staff_ids() -> set[int]:
    """ID Б24 всех сотрудников отдела по работе с персоналом."""
    ids = set(HrStaff.objects.filter(is_active=True).values_list("b24_user_id", flat=True))
    return ids | _role_ids()


def is_hr_staff(b24_id) -> bool:
    if not b24_id:
        return False
    return (
        HrStaff.objects.filter(b24_user_id=b24_id, is_active=True).exists()
        or RoleAssignment.objects.filter(
            role_code__in=[K.ROLE_HR_SPECIALIST, K.ROLE_HR_HEAD],
            user_b24_id=b24_id, is_active=True,
        ).exists()
    )


def staff_options() -> list[dict]:
    """Сотрудники отдела для выбора в маршруте: [{bitrix_id, fio, position}]."""
    out: dict[int, dict] = {}
    for s in HrStaff.objects.filter(is_active=True):
        out[s.b24_user_id] = {"bitrix_id": s.b24_user_id, "fio": s.fio, "position": s.position}
    for ra in RoleAssignment.objects.filter(
        role_code__in=[K.ROLE_HR_SPECIALIST, K.ROLE_HR_HEAD], is_active=True
    ):
        out.setdefault(ra.user_b24_id, {
            "bitrix_id": ra.user_b24_id, "fio": ra.user_name,
            "position": K.ROLE_NAMES.get(ra.role_code, ""),
        })
    return sorted(out.values(), key=lambda x: x["fio"] or "")


# --- синхронизация с Битриксом ----------------------------------------------
def _paged(client, method: str, params: dict) -> list[dict]:
    """Все страницы списочного метода (client.call отдаёт только result)."""
    out: list[dict] = []
    start = 0
    while True:
        chunk = client.call(method, {**params, "start": start})
        chunk = chunk if isinstance(chunk, list) else []
        out.extend(chunk)
        if len(chunk) < PAGE:
            return out
        start += PAGE


def _hr_department_ids(departments: list[dict], match: str) -> set[str]:
    """Отделы с подстрокой в названии + все вложенные в них подразделения."""
    match = match.lower()
    roots = {str(d.get("ID")) for d in departments if match in (d.get("NAME") or "").lower()}
    children: dict[str, list[str]] = {}
    for d in departments:
        children.setdefault(str(d.get("PARENT") or ""), []).append(str(d.get("ID")))
    found, stack = set(), list(roots)
    while stack:
        dep = stack.pop()
        if dep in found:
            continue
        found.add(dep)
        stack.extend(children.get(dep, []))
    return found


def _fio(u: dict) -> str:
    return " ".join(
        x.strip() for x in (u.get("LAST_NAME"), u.get("NAME"), u.get("SECOND_NAME"))
        if x and x.strip()
    )


def fetch_from_bitrix(client=None) -> tuple[list[str], list[dict]]:
    """(названия найденных отделов, сотрудники) из портала."""
    from bitrix.client import BitrixClient, get_active_portal

    if client is None:
        portal = get_active_portal()
        if portal is None:
            raise HrSyncError("Портал Битрикс24 не подключён.")
        client = BitrixClient(portal)

    match = getattr(settings, "JOBDESC_HR_DEPARTMENT_MATCH", "") or DEFAULT_DEPARTMENT_MATCH
    try:
        departments = _paged(client, "department.get", {})
    except Exception as e:
        raise HrSyncError(
            f"Не удалось получить подразделения из Битрикс24 ({e}). Возможно, у "
            f"приложения нет права «department» — его нужно добавить и переустановить приложение."
        ) from e
    dep_ids = _hr_department_ids(departments, match)
    if not dep_ids:
        raise HrSyncError(f"В Битрикс24 не найден отдел, в названии которого есть «{match}».")
    names = [d.get("NAME") for d in departments if str(d.get("ID")) in dep_ids]

    users: dict[int, dict] = {}
    for dep in sorted(dep_ids):
        try:
            chunk = _paged(client, "user.get", {"FILTER": {"UF_DEPARTMENT": dep, "ACTIVE": True}})
        except Exception as e:
            raise HrSyncError(f"Не удалось получить сотрудников отдела ({e}).") from e
        for u in chunk:
            try:
                uid = int(u.get("ID"))
            except (TypeError, ValueError):
                continue
            users[uid] = {
                "b24_user_id": uid,
                "fio": _fio(u),
                "position": (u.get("WORK_POSITION") or "").strip(),
            }
    return names, list(users.values())


@transaction.atomic
def sync(client=None) -> dict:
    """Сверяет HrStaff с порталом. Ручные записи не трогает."""
    departments, users = fetch_from_bitrix(client)
    now = timezone.now()
    seen = set()
    added = 0
    for u in users:
        seen.add(u["b24_user_id"])
        obj, created = HrStaff.objects.get_or_create(
            b24_user_id=u["b24_user_id"],
            defaults={"fio": u["fio"], "position": u["position"],
                      "source": HrStaff.SOURCE_BITRIX, "synced_at": now},
        )
        added += int(created)
        if not created:
            obj.fio = u["fio"] or obj.fio
            obj.position = u["position"] or obj.position
            obj.synced_at = now
            if obj.source == HrStaff.SOURCE_BITRIX:
                obj.is_active = True
            obj.save(update_fields=["fio", "position", "synced_at", "is_active"])
    # Ушёл из отдела в портале — снимаем, но только тех, кто пришёл из портала.
    removed = (
        HrStaff.objects
        .filter(source=HrStaff.SOURCE_BITRIX, is_active=True)
        .exclude(b24_user_id__in=seen)
        .update(is_active=False)
    )
    return {"departments": departments, "total": len(users), "added": added, "removed": removed}
