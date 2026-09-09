"""
Построение маршрута согласования договора (базовый маршрут коммерческого
департамента: отделы продаж/маркетинга/бронирования/доходов).

Маршрут последовательный. Правила (по таблице юристов):

  согласующие:
    - Руководитель ЦФО ............... всегда
    - Юридический отдел (группой) .... если «нестандартный» ИЛИ «с протоколом
                                       разногласий»
    - Финансовый директор УК ......... всегда
  подписанты (по ЦФО, «либо-либо»):
    - Руководитель отдела продаж ..... ЦФО = продажи
    - Коммерческий директор .......... ЦФО = доходы / маркетинг / бронирование
    - ГД юрлица (напр. ГД «Невесомость») ... если у ЮО задан ГД (RoleAssignment
                                       final_signer на эту организацию)

Роли/справочник исполнителей (RoleAssignment) — общефирменные, берём из
requests_reg (не дублируем). Нераспознанные обязательные роли помечаются
needs_manual — инициатор выбирает исполнителя вручную (фиксируется в аудите).
Класс роли (approver/signer) хранится на слоте — пока единый поток.
"""

from __future__ import annotations

from requests_reg import constants as C
from requests_reg.models import RoleAssignment

from . import constants as K


# Согласующих договора инициатор выбирает ВРУЧНУЮ, КРОМЕ ролей, которые всегда
# подставляются автоматически (как юротдел): финансовый директор — без права
# выбора, из RoleAssignment. Юротдел обрабатывается отдельно (групповой слот).
AUTO_RESOLVE_NON_LEGAL = False
AUTO_ROLES = {C.ROLE_FINANCE_DIRECTOR}


def _cat(contract) -> str:
    return contract.cfo.category if contract.cfo_id else ""


# Условие «нетиповой ИЛИ с протоколом разногласий» — включает и юротдел, и финдиректора.
def _needs_extra_control(c) -> bool:
    return bool(c.is_nonstandard or c.has_disagreement_protocol)


# (role_code, role_class, condition). Порядок = порядок маршрута.
ROUTE_RULES = [
    (C.ROLE_CFO_HEAD, K.CLASS_APPROVER, lambda c: True),
    (C.ROLE_LEGAL_DEPT, K.CLASS_APPROVER, _needs_extra_control),
    # Финдиректор — по тому же условию, что и юротдел: только если договор
    # нетиповой или с протоколом разногласий.
    (C.ROLE_FINANCE_DIRECTOR, K.CLASS_APPROVER, _needs_extra_control),
    (C.ROLE_SALES_HEAD, K.CLASS_SIGNER, lambda c: _cat(c) == "sales"),
    (C.ROLE_COMMERCIAL_DIRECTOR, K.CLASS_SIGNER,
     lambda c: _cat(c) in ("revenue", "marketing", "booking")),
    (C.ROLE_FINAL_SIGNER, K.CLASS_SIGNER, lambda c: _org_gd(c) is not None),
]


def _org_gd(contract) -> RoleAssignment | None:
    """ГД юрлица — назначение final_signer, привязанное к организации договора.

    Так «ГД Невесомость при ЮО Невесомость» задаётся данными (seed назначения),
    без хардкода имени; для других ЮО с заданным ГД шаг появится автоматически."""
    if not contract.organization_id:
        return None
    return RoleAssignment.objects.filter(
        role_code=C.ROLE_FINAL_SIGNER, organization=contract.organization,
        is_active=True,
    ).first()


def resolve_role(role_code: str, contract) -> RoleAssignment | None:
    """Исполнитель роли по самому специфичному контексту: ЦФО → организация → глобально."""
    qs = RoleAssignment.objects.filter(role_code=role_code, is_active=True)
    for flt in (
        {"cfo": contract.cfo} if contract.cfo_id else None,
        {"organization": contract.organization} if contract.organization_id else None,
        {"organization__isnull": True, "cfo__isnull": True, "facility__isnull": True},
    ):
        if flt is None:
            continue
        match = qs.filter(**flt).first()
        if match:
            return match
    return None


def build_route(contract) -> list[dict]:
    """Упорядоченные слоты маршрута договора."""
    route: list[dict] = []
    order = 0
    for role_code, role_class, condition in ROUTE_RULES:
        if not condition(contract):
            continue

        # Юротдел — групповой слот: согласовать может ЛЮБОЙ юрист.
        if role_code == C.ROLE_LEGAL_DEPT:
            route.append({
                "order": order,
                "role_code": role_code,
                "role_name": C.ROLE_NAMES[role_code],
                "role_class": role_class,
                "required": True,
                "group": True,
                "resolved": True,
                "b24_user_id": None,
                "user_name": "Юридический отдел",
                "needs_manual": False,
                # согласует любой юрист — заменять некого
                "replaceable": False,
            })
            order += 1
            continue

        # ГД юрлица: слот показываем только если у ЮО есть назначение; человека
        # ставит инициатор вручную (если не включён общий авто-резолв).
        if role_code == C.ROLE_FINAL_SIGNER:
            assignment = _org_gd(contract)
            if assignment is None:
                continue  # у ЮО нет ГД → слот не показываем
            auto = AUTO_RESOLVE_NON_LEGAL and assignment is not None
        # Роли из AUTO_ROLES (финдиректор) — ВСЕГДА авто-подстановка, без выбора.
        elif role_code in AUTO_ROLES:
            assignment = resolve_role(role_code, contract)
            auto = assignment is not None
        # Остальные согласующие — вручную (пока AUTO_RESOLVE_NON_LEGAL=False).
        else:
            assignment = resolve_role(role_code, contract) if AUTO_RESOLVE_NON_LEGAL else None
            auto = AUTO_RESOLVE_NON_LEGAL and assignment is not None
        route.append({
            "order": order,
            "role_code": role_code,
            "role_name": C.ROLE_NAMES[role_code],
            "role_class": role_class,
            "required": True,
            "group": False,
            "resolved": auto,
            "b24_user_id": assignment.user_b24_id if auto else None,
            "user_name": assignment.user_name if auto else "",
            "needs_manual": not auto,
            # Финдиректора инициатор не выбирает и не заменяет (AUTO_ROLES) —
            # это решение по маршруту договора, а не техническое ограничение.
            "replaceable": role_code not in AUTO_ROLES,
        })
        order += 1
    return route
