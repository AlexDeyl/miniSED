"""
Маршрут заявки на комплимент.

Маршрут ЦЕЛИКОМ определяется категорией комплимента (ответы заказчика
15.08.2026):

  1. Кондитерские изделия ....... рук. отдела продаж → ресторанная служба
                                  исполняет кондитерский цех
  2. Рестораны и алкоголь ....... рук. продаж → коммерческий директор → ГД
                                  исполняет ресторанная служба
  3. Проживание, цветы, подарки . рук. продаж → коммерческий директор → ГД
                                  исполняет помощник генерального директора

Флажок «согласование с ГД» — свободный выбор инициатора: добавляет
коммерческого директора и ГД туда, где их нет по категории (кондитерка).
Плюс инициатор может добавить своих согласующих (до двух по ТЗ) — это делает
фронт поверх готового маршрута, как в договорах.

Исполнение показывается в предпросмотре отдельным слотом: ТЗ требует, чтобы
инициатор видел путь «от направления до исполнения». Решения на этом слоте
нет — это работа, а не голос.

Исполнитель ресторанной категории зависит от ВЫБРАННОГО РЕСТОРАНА (разделение
зон ответственности, 13.10.2026): у ресторана может быть свой исполнитель
(compliments.Restaurant.executor_b24_id). Не задан — исполняет директор
ресторанной службы по общей роли.

Роли — общефирменные (requests_reg.RoleAssignment), не дублируем. Роль без
назначения помечается needs_manual: исполнителя выбирает инициатор вручную.
"""

from __future__ import annotations

from requests_reg import constants as C
from requests_reg.models import RoleAssignment

from . import constants as K


def resolve_role(role_code: str, compliment) -> RoleAssignment | None:
    """Исполнитель роли: сначала по отелю/юрлицу заявки, затем глобально.

    ГД (ТАР) согласует по ВСЕМ юрлицам, поэтому глобальное назначение —
    нормальный и ожидаемый случай."""
    qs = RoleAssignment.objects.filter(role_code=role_code, is_active=True)
    for flt in (
        {"facility": compliment.facility} if compliment.facility_id else None,
        {"organization": compliment.organization} if compliment.organization_id else None,
        {"organization__isnull": True, "cfo__isnull": True, "facility__isnull": True},
    ):
        if flt is None:
            continue
        match = qs.filter(**flt).first()
        if match:
            return match
    return None


def approver_roles(compliment) -> list[str]:
    """Коды ролей согласующих по категории (+ГД по флажку), без повторов."""
    plan = K.CATEGORY_ROUTES.get(compliment.category)
    if plan is None:
        return []
    codes = list(plan["approvers"])
    if compliment.needs_ceo:
        for code in K.CEO_EXTRA_ROLES:
            if code not in codes:
                codes.append(code)
    return codes


def executor_role(compliment) -> str | None:
    plan = K.CATEGORY_ROUTES.get(compliment.category)
    return plan["executor"] if plan else None


def restaurant_executor(compliment) -> tuple[int, str] | None:
    """Персональный исполнитель выбранного ресторана (b24_id, ФИО), если задан."""
    if compliment.category != K.CATEGORY_RESTAURANT or not compliment.restaurant_id:
        return None
    r = compliment.restaurant
    if r.executor_b24_id:
        return r.executor_b24_id, r.executor_name
    return None


def resolve_executor(compliment) -> tuple[int, str] | None:
    """Кто исполняет заявку по умолчанию: исполнитель ресторана, иначе роль."""
    personal = restaurant_executor(compliment)
    if personal:
        return personal
    code = executor_role(compliment)
    assignment = resolve_role(code, compliment) if code else None
    return (assignment.user_b24_id, assignment.user_name) if assignment else None


def _slot(order: int, role_code: str, role_class: str, compliment) -> dict:
    if role_class == K.CLASS_EXECUTOR:
        found = resolve_executor(compliment)
    else:
        assignment = resolve_role(role_code, compliment)
        found = (assignment.user_b24_id, assignment.user_name) if assignment else None
    role_name = C.ROLE_NAMES.get(role_code, role_code)
    if role_class == K.CLASS_EXECUTOR and compliment.restaurant_id:
        role_name = f"{role_name} · {compliment.restaurant.name}"
    return {
        "order": order,
        "role_code": role_code,
        "role_name": role_name,
        "role_class": role_class,
        "required": True,
        "resolved": found is not None,
        "b24_user_id": found[0] if found else None,
        "user_name": found[1] if found else "",
        "needs_manual": found is None,
        # Согласующего инициатор может заменить (отпуск, устаревшее
        # назначение); исполнителя — нет, он определяется категорией.
        "replaceable": role_class == K.CLASS_APPROVER,
    }


def build_route(compliment) -> list[dict]:
    """Упорядоченные слоты: согласующие, затем исполнение."""
    route: list[dict] = []
    for code in approver_roles(compliment):
        route.append(_slot(len(route), code, K.CLASS_APPROVER, compliment))

    code = executor_role(compliment)
    if code:
        route.append(_slot(len(route), code, K.CLASS_EXECUTOR, compliment))
    return route


def default_executor(compliment) -> tuple[str | None, int | None]:
    """Роль исполнителя и сотрудник (исполнитель ресторана или назначенный на
    роль) — для подстановки."""
    code = executor_role(compliment)
    if not code:
        return None, None
    found = resolve_executor(compliment)
    return code, (found[0] if found else None)
