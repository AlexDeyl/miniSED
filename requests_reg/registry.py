"""
Реестр доверенностей и МЧД (ТЗ «Нумерация доверенностей и реестр»).

Номер присваивается, когда юрист берёт заявку в работу; в тот же момент
доверенность вносится в реестр. Номер строится по маске юрлица: ХХ —
порядковый номер в календарном году (сквозной по доверенностям и МЧД юрлица),
ГГГГ/ГГ — год, ММ — месяц выдачи.

Графы реестра по умолчанию переносятся из заявки, потом юрист их уточняет;
каждая правка пишется в PoaRegistryChange (видит суперпользователь).
"""

from __future__ import annotations

import re
from datetime import date

from django.db import transaction
from django.utils import timezone

from . import constants as C
from .models import (
    PoaNumbering,
    PoaRegistryChange,
    PoaRegistryEntry,
    PowerTemplate,
    RegulatoryRequest,
)
from .validators import is_machine_readable


class RegistryError(Exception):
    pass


# --- маски и нумерация ------------------------------------------------------
def org_key(name: str) -> str:
    """Название юрлица без кавычек, регистра и лишних пробелов."""
    s = (name or "").lower().replace("ё", "е")
    s = re.sub(r"[\"'«»“”„]", " ", s)
    return " ".join(s.split())


def default_mask(organization) -> str:
    return C.POA_NUMBER_MASKS.get(org_key(organization.short_name), C.POA_DEFAULT_MASK)


def mask_error(mask: str) -> str | None:
    if "{ХХ}" not in (mask or ""):
        return "В маске нужен порядковый номер {ХХ}."
    rest = mask
    for token in C.POA_MASK_TOKENS:
        rest = rest.replace(token, "")
    if "{" in rest or "}" in rest:
        return "Неизвестная подстановка в маске: допустимы {ХХ}, {ГГГГ}, {ГГ}, {ММ}."
    return None


def numbering_for(organization) -> PoaNumbering:
    obj, _ = PoaNumbering.objects.get_or_create(
        organization=organization, defaults={"mask": default_mask(organization)},
    )
    return obj


def format_number(mask: str, seq: int, on_date: date) -> str:
    # ХХ — минимум две цифры (01, 11), трёхзначные — как есть (ТЗ)
    return (
        mask.replace("{ХХ}", f"{seq:02d}")
        .replace("{ГГГГ}", f"{on_date.year:04d}")
        .replace("{ГГ}", f"{on_date.year % 100:02d}")
        .replace("{ММ}", f"{on_date.month:02d}")
    )


def next_seq(numbering: PoaNumbering, year: int) -> int:
    return (numbering.last_seq if numbering.year == year else 0) + 1


def allocate_number(organization, on_date: date | None = None) -> tuple[str, int, int]:
    """Следующий номер юрлица: (номер, порядковый, год). Счётчик под
    блокировкой строки — два юриста, взявшие заявки одновременно, не получат
    один номер. Номер, уже занятый в реестре (внесён руками), пропускаем."""
    on_date = on_date or timezone.localdate()
    with transaction.atomic():
        numbering_for(organization)  # завести строку до блокировки
        n = PoaNumbering.objects.select_for_update().get(organization=organization)
        seq = next_seq(n, on_date.year)
        number = format_number(n.mask, seq, on_date)
        while PoaRegistryEntry.objects.filter(organization=organization, number=number).exists():
            seq += 1
            number = format_number(n.mask, seq, on_date)
        n.year, n.last_seq = on_date.year, seq
        n.save(update_fields=["year", "last_seq"])
    return number, seq, on_date.year


# --- перенос граф из заявки -------------------------------------------------
def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _representative(req: RegulatoryRequest) -> str:
    rep = (req.data or {}).get("rep") or {}
    fio = " ".join(filter(None, [rep.get("last_name"), rep.get("first_name"), rep.get("middle_name")]))
    return req.subject_name or fio


def _powers(req: RegulatoryRequest) -> str:
    """Полномочия из анкеты одним текстом: куда, отмеченные пункты, иные,
    затем расшифровка кодов доверенности по матрице."""
    data = req.data or {}
    lines = []
    if data.get("target_org"):
        lines.append(f"Представлять интересы: {data['target_org']}")
    lines += C.labels(C.ANKETA_POWERS, data.get("powers"))
    if data.get("powers_other"):
        lines.append(str(data["powers_other"]))
    codes = data.get("power_templates") or []
    if codes:
        by_code = {t.code: t for t in PowerTemplate.objects.filter(code__in=codes)}
        for code in codes:
            t = by_code.get(code)
            lines.append(f"{code}: {t.powers}" if t and t.powers else code)
    return "\n".join(lines)


def _valid_until(req: RegulatoryRequest):
    data = req.data or {}
    return req.valid_until or (
        _parse_date(data.get("term_to")) if data.get("term_type") == "period" else None
    )


def defaults_from_request(req: RegulatoryRequest) -> dict:
    data = req.data or {}
    return {
        "kind": C.REGISTRY_MCHD if is_machine_readable(req.request_type, data) else C.REGISTRY_POA,
        "organization": req.organization,
        "code": ", ".join(data.get("power_templates") or []),
        "representative": _representative(req),
        "powers": _powers(req),
        "valid_until": _valid_until(req),
    }


def is_registrable(req: RegulatoryRequest) -> bool:
    return req.request_type in (C.TYPE_POA, C.TYPE_MCHD)


def register_request(req: RegulatoryRequest, *, by_b24_id=None) -> PoaRegistryEntry | None:
    """Внести заявку в реестр с новым номером (при «Взять в работу»).

    Повторный вызов ничего не меняет: номер выдаётся один раз."""
    if not is_registrable(req):
        return None
    existing = PoaRegistryEntry.objects.filter(request=req).first()
    if existing is not None:
        return existing
    today = timezone.localdate()
    number, seq, year = allocate_number(req.organization, today)
    return PoaRegistryEntry.objects.create(
        request=req, number=number, seq=seq, seq_year=year, issue_date=today,
        created_by_b24_id=by_b24_id, **defaults_from_request(req),
    )


# --- срок действия ----------------------------------------------------------
def validity(entry: PoaRegistryEntry, today: date | None = None) -> str:
    today = today or timezone.localdate()
    if entry.revoked_at and entry.revoked_at <= today:
        return C.VALIDITY_REVOKED
    if not entry.valid_until:
        return C.VALIDITY_NO_TERM
    if entry.valid_until < today:
        return C.VALIDITY_EXPIRED
    if (entry.valid_until - today).days <= C.VALIDITY_WARN_DAYS:
        return C.VALIDITY_EXPIRING
    return C.VALIDITY_ACTIVE


# --- правка и журнал правок -------------------------------------------------
EDITABLE_FIELDS = [
    "kind", "organization", "number", "reg_number", "issue_date", "code",
    "representative", "powers", "valid_until", "cert_valid_until",
    "revoked_at", "comment",
]


def _str(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "short_name"):
        return value.short_name
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value)


@transaction.atomic
def update_entry(entry: PoaRegistryEntry, changes: dict, *, by_b24_id=None) -> list[str]:
    """Применить правки и записать каждую изменённую графу в журнал."""
    changed = []
    for field, value in changes.items():
        if field not in EDITABLE_FIELDS:
            continue
        old = getattr(entry, field)
        if field == "organization":
            same = getattr(old, "pk", None) == getattr(value, "pk", None)
        else:
            same = _str(old) == _str(value)
        if same:
            continue
        PoaRegistryChange.objects.create(
            entry=entry, field=field, old_value=_str(old), new_value=_str(value),
            changed_by_b24_id=by_b24_id,
        )
        setattr(entry, field, value)
        changed.append(field)
    if "number" in changed:
        # номер правили руками — порядковый больше не выводим из него
        entry.seq = entry.seq_year = None
        changed += ["seq", "seq_year"]
    if changed:
        entry.save(update_fields=[*changed, "updated_at"])
    return changed


def mark_revoked(source: RegulatoryRequest, *, on_date: date | None = None, by_b24_id=None):
    """Отзыв исполнен — отметить отозванную доверенность в реестре."""
    entry = PoaRegistryEntry.objects.filter(request=source).first()
    if entry is None or entry.revoked_at:
        return entry
    update_entry(entry, {"revoked_at": on_date or timezone.localdate()}, by_b24_id=by_b24_id)
    return entry
