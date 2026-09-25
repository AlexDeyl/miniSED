"""
Заявка на проверку лица (ТЗ): правила анкеты и доступ к разделу СБ.

Анкета живёт в RegulatoryRequest.data, как у остальных регламентных заявок.
Тип лица задаёт и состав полей, и маршрут:
  - юрлицо / ИП      → согласует юротдел (группа), исполняет СБ;
  - физлицо          → согласует советник ГД по безопасности, исполняет СБ.

Раздел «Работа службы безопасности» открыт тем, у кого есть назначение
security_advisor, — а на время передачи функций (SecurityDelegation) ещё и
юристам.
"""

from __future__ import annotations

import re
from datetime import date

from core.auth import is_lawyer
from core.models import Facility, Organization

from . import constants as C

# Объект из ТЗ → как его искать в базе (подстроки названия, без регистра).
# Названия в базе заведены по-разному («Отель Svet», «Дом Бутик Отель»),
# поэтому ищем по нескольким вариантам, а не по точному совпадению.
_PLACE_FACILITY_HINTS = {
    "vvedensky": ("введенск",),
    "demetra": ("деметр",),
    "svet": ("svet", "свет"),
    "saga": ("saga", "сага"),
    "dom": ("бутик", "boutique"),
}
_PLACE_ORG_HINTS = {"nevesomost": ("невесом",)}
# Юрлицо, от которого идут заявки «на несколько объектов» — управляющая компания.
_UK_HINTS = ("управлени",)


def _label(choices, code) -> str:
    return C.label(choices, code) if code else ""


# Подстроки сравниваем в Python: в SQLite (локальная база) icontains не
# складывает регистр кириллицы, а объектов и юрлиц — единицы.
def _matches(text, hints) -> bool:
    text = (text or "").lower()
    return any(h in text for h in hints)


def _find_facility(hints):
    for f in Facility.objects.select_related("organization").order_by("id"):
        if _matches(f.name, hints):
            return f
    return None


def _find_org(hints):
    for o in Organization.objects.order_by("id"):
        if _matches(o.short_name, hints) or _matches(o.full_name, hints):
            return o
    return None


def resolve_place(code: str) -> tuple[Organization | None, Facility | None]:
    """Юрлицо и объект базы для кода объекта из анкеты.

    Юрлицо у регламентной заявки обязательно, а в анкете проверки его нет —
    его выводим из объекта. Не нашли (объект не заведён) — управляющая
    компания, затем первое юрлицо: заявку это не блокирует, СБ видит объект
    в анкете в любом случае."""
    facility = None
    org = None
    if code in _PLACE_FACILITY_HINTS:
        facility = _find_facility(_PLACE_FACILITY_HINTS[code])
        org = facility.organization if facility else None
    elif code in _PLACE_ORG_HINTS:
        org = _find_org(_PLACE_ORG_HINTS[code])
    if org is None:
        org = _find_org(_UK_HINTS) or Organization.objects.order_by("id").first()
    return org, facility


def person_type(data) -> str:
    return (data or {}).get("person_type") or ""


def is_individual(req) -> bool:
    return person_type(req.data) == C.CHECK_PERSON_INDIVIDUAL


def subject_name(data) -> str:
    """Кого проверяем — для списков, поиска и заголовка карточки."""
    data = data or {}
    if person_type(data) == C.CHECK_PERSON_INDIVIDUAL:
        ind = data.get("individual") or {}
        return " ".join(
            p for p in (ind.get("last_name"), ind.get("first_name"), ind.get("middle_name")) if p
        ).strip()
    return ((data.get("legal") or {}).get("name") or "").strip()


def place_code(data) -> str:
    data = data or {}
    if person_type(data) == C.CHECK_PERSON_INDIVIDUAL:
        return (data.get("individual") or {}).get("place") or ""
    return (data.get("legal") or {}).get("place") or ""


def _codes(choices):
    return {c for c, _ in choices}


def _s(d, key) -> str:
    v = d.get(key)
    return v.strip() if isinstance(v, str) else ""


def data_error(data) -> str | None:
    """Первая ошибка анкеты или None. Те же правила проверяет форма на фронте."""
    if not isinstance(data, dict):
        return "Заполните анкету заявки."
    ptype = person_type(data)
    if ptype not in _codes(C.CHECK_PERSON_TYPES):
        return "Укажите тип лица."
    if data.get("urgency") not in _codes(C.ANKETA_URGENCY):
        return "Укажите срочность."

    if ptype == C.CHECK_PERSON_LEGAL:
        legal = data.get("legal") or {}
        if not _s(legal, "name"):
            return "Раздел 1: укажите наименование."
        inn = re.sub(r"\D", "", _s(legal, "inn_ogrn"))
        if not inn:
            return "Раздел 1: укажите ИНН / ОГРН."
        # ИНН юрлица — 10, ИП — 12; ОГРН — 13, ОГРНИП — 15 цифр.
        if len(inn) not in (10, 12, 13, 15):
            return "Раздел 1: ИНН — 10 или 12 цифр, ОГРН — 13 или 15."
        if legal.get("direction") not in _codes(C.CHECK_LEGAL_DIRECTIONS):
            return "Раздел 1: укажите направление планируемой деятельности."
        if legal.get("contract_kind") not in _codes(C.CHECK_CONTRACT_KINDS):
            return "Раздел 1: укажите вид планируемого договора."
        if legal.get("place") not in _codes(C.CHECK_PLACES):
            return "Раздел 1: укажите объект, на котором планируется сотрудничество."
        if legal.get("place") == C.CHECK_PLACE_MULTIPLE and not _s(legal, "other_info"):
            return "Раздел 1: выбрано «Несколько объектов» — перечислите их в графе «Иная информация»."
    else:
        ind = data.get("individual") or {}
        if not _s(ind, "last_name"):
            return "Раздел 1: укажите фамилию."
        if not _s(ind, "first_name"):
            return "Раздел 1: укажите имя."
        birth = _s(ind, "birth_date")
        if not birth:
            return "Раздел 1: укажите дату рождения."
        try:
            if date.fromisoformat(birth[:10]) > date.today():
                return "Раздел 1: дата рождения не может быть в будущем."
        except ValueError:
            return "Раздел 1: некорректная дата рождения."
        passport = re.sub(r"\s", "", _s(ind, "passport"))
        if not re.fullmatch(r"\d{10}", passport):
            return "Раздел 1: паспорт — 10 цифр (серия 4 + номер 6)."
        if not _s(ind, "position"):
            return "Раздел 1: укажите должность/статус."
        place = ind.get("place")
        if place not in _codes(C.CHECK_PLACES) or place == C.CHECK_PLACE_MULTIPLE:
            return "Раздел 1: укажите место сотрудничества."
        if data.get("direction") not in _codes(C.CHECK_DIRECTIONS):
            return "Раздел 2: укажите направление деятельности."
    return None


def summary_rows(req) -> list[tuple[str, str]]:
    """Анкета строками «поле — значение»: для письма и поиска глазами."""
    data = req.data or {}
    rows = [
        ("Тип лица", _label(C.CHECK_PERSON_TYPES, person_type(data))),
        ("Срочность", _label(C.ANKETA_URGENCY, data.get("urgency"))),
    ]
    if person_type(data) == C.CHECK_PERSON_INDIVIDUAL:
        ind = data.get("individual") or {}
        rows += [
            ("ФИО", subject_name(data)),
            ("Дата рождения", ind.get("birth_date") or ""),
            ("Паспорт", ind.get("passport") or ""),
            ("Должность/Статус", ind.get("position") or ""),
            ("Место сотрудничества", _label(C.CHECK_PLACES, ind.get("place"))),
            ("Направление деятельности", _label(C.CHECK_DIRECTIONS, data.get("direction"))),
        ]
    else:
        legal = data.get("legal") or {}
        rows += [
            ("Наименование", legal.get("name") or ""),
            ("ИНН / ОГРН", legal.get("inn_ogrn") or ""),
            ("Направление деятельности", _label(C.CHECK_LEGAL_DIRECTIONS, legal.get("direction"))),
            ("Вид договора", _label(C.CHECK_CONTRACT_KINDS, legal.get("contract_kind"))),
            ("Объект", _label(C.CHECK_PLACES, legal.get("place"))),
            ("Иная информация", legal.get("other_info") or ""),
        ]
    rows.append(("Иная информация о сотрудничестве", data.get("coop_info") or ""))
    return [(k, v) for k, v in rows if v]


# --- доступ к разделу «Работа службы безопасности» --------------------------
def security_officer_ids() -> list[int]:
    """Сотрудники СБ — по назначению роли security_advisor."""
    from .models import RoleAssignment

    return list(
        RoleAssignment.objects.filter(
            role_code=C.ROLE_SECURITY_ADVISOR, is_active=True
        ).values_list("user_b24_id", flat=True).distinct()
    )


def is_security_officer(b24_id) -> bool:
    return bool(b24_id) and int(b24_id) in security_officer_ids()


def delegation_active() -> bool:
    from .models import SecurityDelegation

    return SecurityDelegation.active() is not None


def can_work_security(b24_id) -> bool:
    """Может ли человек работать в разделе СБ: сотрудник СБ, а на время
    передачи функций — и юрист."""
    if not b24_id:
        return False
    if is_security_officer(b24_id):
        return True
    return is_lawyer(b24_id) and delegation_active()


def security_recipient_ids() -> list[int]:
    """Кого звать в раздел СБ: сотрудников СБ и — при передаче — юристов."""
    from core.auth import lawyer_b24_ids

    ids = set(security_officer_ids())
    if delegation_active():
        ids |= set(lawyer_b24_ids())
    return sorted(ids)
