"""
Построение маршрута согласования регламентной заявки по правилам (ТЗ доработка).

Маршрут последовательный. Базовые роли — всегда, условные — по категории ЦФО
или проекту. Для каждой роли ищем исполнителя (RoleAssignment) по самому
специфичному контексту; если не найден обязательный — слот помечается как
требующий ручного выбора инициатором (что затем фиксируется в истории).
"""

from __future__ import annotations

from . import constants
from .models import RegulatoryRequest, RoleAssignment

C = constants


def _cat(request: RegulatoryRequest) -> str:
    return request.cfo.category if request.cfo else ""


def _is_nevesomost(request: RegulatoryRequest) -> bool:
    name = (request.facility.name if request.facility else "").lower()
    return "невесом" in name


# Правила: (role_code, condition(request) -> bool). Порядок = порядок маршрута.
ROUTE_RULES = [
    (C.ROLE_CFO_HEAD, lambda r: True),
    (C.ROLE_SALES_HEAD, lambda r: _cat(r) == "sales"),
    (C.ROLE_COMMERCIAL_DIRECTOR, lambda r: _cat(r) in ("revenue", "marketing", "booking")),
    (C.ROLE_CHIEF_ACCOUNTANT, lambda r: _cat(r) == "accounting"),
    (C.ROLE_HR_HEAD, lambda r: _cat(r) in ("hr_kdp", "hr_recruit", "hr_training")),
    (C.ROLE_TECH_DIRECTOR, lambda r: _cat(r) == "its_it"),
    (C.ROLE_OPS_DIRECTOR, lambda r: _cat(r) in ("its_it", "sgh", "territory", "warehouse")),
    (C.ROLE_RESTAURANT_DIRECTOR, lambda r: _is_nevesomost(r) or _cat(r) == "restaurant"),
    (C.ROLE_FINANCE_DIRECTOR, lambda r: True),
    (C.ROLE_LEGAL_DEPT, lambda r: True),
    (C.ROLE_FINAL_SIGNER, lambda r: True),
]


def resolve_role(role_code: str, request: RegulatoryRequest) -> RoleAssignment | None:
    """Находит исполнителя роли по самому специфичному контексту (ЦФО→объект→орг→глобально)."""
    qs = RoleAssignment.objects.filter(role_code=role_code, is_active=True)

    candidates = [
        {"cfo": request.cfo} if request.cfo_id else None,
        {"facility": request.facility} if request.facility_id else None,
        {"organization": request.organization},
        {"organization__isnull": True, "cfo__isnull": True, "facility__isnull": True},
    ]
    for flt in candidates:
        if flt is None:
            continue
        match = qs.filter(**flt).first()
        if match:
            return match
    return None


def build_route(request: RegulatoryRequest) -> list[dict]:
    """
    Возвращает упорядоченный маршрут-слоты:
      [{role_code, role_name, required, resolved(bool),
        b24_user_id|None, user_name, needs_manual(bool)}]
    """
    route = []
    order = 0
    for role_code, condition in ROUTE_RULES:
        if not condition(request):
            continue

        # Юротдел — групповой слот: согласовать может ЛЮБОЙ юрист, конкретного
        # исполнителя не назначаем и ручной выбор не требуется.
        if role_code == C.ROLE_LEGAL_DEPT:
            route.append(
                {
                    "order": order,
                    "role_code": role_code,
                    "role_name": C.ROLE_NAMES[role_code],
                    "required": True,
                    "group": True,
                    "resolved": True,
                    "b24_user_id": None,
                    "user_name": "Юридический отдел",
                    "needs_manual": False,
                }
            )
            order += 1
            continue

        assignment = resolve_role(role_code, request)
        route.append(
            {
                "order": order,
                "role_code": role_code,
                "role_name": C.ROLE_NAMES[role_code],
                "required": True,
                "group": False,
                "resolved": assignment is not None,
                "b24_user_id": assignment.user_b24_id if assignment else None,
                "user_name": assignment.user_name if assignment else "",
                "needs_manual": assignment is None,
            }
        )
        order += 1
    return route
