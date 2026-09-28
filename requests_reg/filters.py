"""
Отбор регламентных заявок «как в 1С»: галочки по компании (юрлицу),
инициатору, ЦФО и статусу.

Параметры запроса — списки через запятую:
  ?organization=1,3  ?cfo=2,none  ?initiator=1071,929  ?status=to_legal,signing
Внутри одного поля значения объединяются по ИЛИ, между полями — по И.
«none» у ЦФО — заявки без ЦФО (у проверки лица и части старых его нет).

facets() — варианты для галочек: только значения, которые реально есть в
доступной пользователю выборке, со счётчиками. Счётчик поля считается с
учётом остальных выбранных полей, но без своего — так в 1С: отметил юрлицо,
и в списке инициаторов остались те, кто подавал заявки от этого юрлица.
"""

from __future__ import annotations

from django.db.models import Count, Q

from core.models import UserProfile

from . import constants

FIELDS = ("organization", "cfo", "initiator", "status")
NONE = "none"


def _split(raw: str) -> list[str]:
    return [v.strip() for v in (raw or "").split(",") if v.strip()]


def _ints(values) -> list[int]:
    out = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def parse(query_params) -> dict[str, list[str]]:
    """Выбранные значения по полям (пустые поля опускаются)."""
    out = {}
    for f in FIELDS:
        vals = _split(query_params.get(f, ""))
        if vals:
            out[f] = vals
    return out


def _q(field: str, values: list[str]) -> Q:
    if field == "organization":
        return Q(organization_id__in=_ints(values))
    if field == "initiator":
        return Q(initiator_b24_id__in=_ints(values))
    if field == "cfo":
        q = Q(cfo_id__in=_ints(values))
        if NONE in values:
            q |= Q(cfo__isnull=True)
        return q
    if field == "status":
        return Q(status__in=values)
    raise ValueError(field)


def apply(qs, selected: dict[str, list[str]], *, skip: str | None = None):
    for field, values in selected.items():
        if field != skip:
            qs = qs.filter(_q(field, values))
    return qs


def _names(b24_ids) -> dict[int, str]:
    return dict(
        UserProfile.objects.filter(bitrix_id__in=list(b24_ids))
        .values_list("bitrix_id", "fio")
    )


def facets(base_qs, selected: dict[str, list[str]]) -> dict:
    """Варианты галочек по каждому полю: [{value, label, count}], по убыванию."""
    status_names = dict(constants.STATUS_CHOICES)
    out = {}

    rows = (
        apply(base_qs, selected, skip="organization")
        .values("organization_id", "organization__short_name")
        .annotate(n=Count("id")).order_by("-n", "organization__short_name")
    )
    out["organization"] = [
        {"value": str(r["organization_id"]), "label": r["organization__short_name"], "count": r["n"]}
        for r in rows
    ]

    rows = (
        apply(base_qs, selected, skip="cfo")
        .values("cfo_id", "cfo__name")
        .annotate(n=Count("id")).order_by("-n", "cfo__name")
    )
    out["cfo"] = [
        {"value": str(r["cfo_id"]) if r["cfo_id"] else NONE,
         "label": r["cfo__name"] or "Без ЦФО", "count": r["n"]}
        for r in rows
    ]

    rows = list(
        apply(base_qs, selected, skip="initiator")
        .exclude(initiator_b24_id__isnull=True)
        .values("initiator_b24_id")
        .annotate(n=Count("id")).order_by("-n")
    )
    names = _names(r["initiator_b24_id"] for r in rows)
    out["initiator"] = sorted(
        (
            {"value": str(r["initiator_b24_id"]),
             "label": names.get(r["initiator_b24_id"]) or f"USER #{r['initiator_b24_id']}",
             "count": r["n"]}
            for r in rows
        ),
        key=lambda x: (-x["count"], x["label"]),
    )

    rows = (
        apply(base_qs, selected, skip="status")
        .values("status").annotate(n=Count("id"))
    )
    by_status = {r["status"]: r["n"] for r in rows}
    # статусы — в порядке жизненного цикла, а не по количеству
    out["status"] = [
        {"value": code, "label": name, "count": by_status[code]}
        for code, name in constants.STATUS_CHOICES if code in by_status
    ]
    return out
