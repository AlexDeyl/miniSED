"""
Маршрут согласования должностной инструкции. Строго последовательный.

  1. Сотрудник отдела по работе с персоналом .. всегда. Обычно это сам
                                                инициатор: тогда этап
                                                закрывается автоматически при
                                                отправке (services.submit)
  2. Руководитель ЦФО ......................... всегда (cfo_head выбранного ЦФО)
  3. Административный руководитель ............ при наличии — выбирает инициатор
  4. Функциональный руководитель .............. при наличии — выбирает инициатор
  5. Доп. согласующие по категории ЦФО ........ constants.CATEGORY_EXTRA_ROLES;
                                                директор ресторанной службы —
                                                ещё и для юрлица «Невесомость»
  6. Юротдел (группой) + финансовый директор .. если форма нестандартная
  7. Руководитель отдела по работе с персоналом УК — всегда
  8. Финальный подписант юрлица ............... всегда (final_signer юрлица)

Один и тот же человек на нескольких этапах (напр. руководитель ЦФО он же
коммерческий директор) согласует один раз — на первом своём этапе; роли
повторов показываются на этом этапе (merged_roles).

Роли — общефирменные (requests_reg.RoleAssignment). Роль без назначения —
needs_manual: согласующего выбирает инициатор, выбор пишется в историю.
"""

from __future__ import annotations

from requests_reg.models import RoleAssignment

from . import constants as K
from . import hr_staff

CLASS_APPROVER = "approver"
CLASS_SIGNER = "signer"

# Этапы «при наличии»: их можно оставить пустыми — тогда этапа не будет.
OPTIONAL_ROLES = {K.ROLE_ADMIN_HEAD, K.ROLE_FUNCTIONAL_HEAD}


def _category(jd) -> str:
    return jd.cfo.category if jd.cfo_id else ""


def _is_restaurant_org(jd) -> bool:
    return bool(jd.organization_id) and K.RESTAURANT_ORG_MARKER.lower() in (
        jd.organization.short_name or ""
    ).lower()


def resolve_role(role_code: str, jd) -> RoleAssignment | None:
    """Назначение роли по самому специфичному контексту:
    ЦФО → объект → юрлицо → глобально."""
    qs = RoleAssignment.objects.filter(role_code=role_code, is_active=True)
    for flt in (
        {"cfo": jd.cfo} if jd.cfo_id else None,
        {"facility": jd.facility} if jd.facility_id else None,
        {"organization": jd.organization} if jd.organization_id else None,
        {"organization__isnull": True, "cfo__isnull": True, "facility__isnull": True},
    ):
        if flt is None:
            continue
        match = qs.filter(**flt).first()
        if match:
            return match
    return None


def _cfo_head(jd) -> RoleAssignment | None:
    """Руководитель именно этого ЦФО — глобальный «руководитель ЦФО» не имеет смысла."""
    if not jd.cfo_id:
        return None
    return RoleAssignment.objects.filter(
        role_code=K.ROLE_CFO_HEAD, cfo=jd.cfo, is_active=True
    ).first()


def _org_signer(jd) -> RoleAssignment | None:
    """Подписант юрлица — назначение final_signer на эту организацию.

    Глобальное назначение (ГД УК) сюда не подходит: у каждого юрлица свой
    подписант (список ТЗ), иначе ДИ «Отеля Введенский» ушла бы не тому."""
    if not jd.organization_id:
        return None
    return RoleAssignment.objects.filter(
        role_code=K.ROLE_FINAL_SIGNER, organization=jd.organization, is_active=True
    ).first()


def role_codes(jd) -> list[str]:
    """Коды ролей маршрута по порядку (без повторов)."""
    cat = _category(jd)
    codes = [K.ROLE_HR_SPECIALIST, K.ROLE_CFO_HEAD, K.ROLE_ADMIN_HEAD, K.ROLE_FUNCTIONAL_HEAD]
    for code, categories in K.CATEGORY_EXTRA_ROLES:
        if cat in categories or (code == K.ROLE_RESTAURANT_DIRECTOR and _is_restaurant_org(jd)):
            codes.append(code)
    if jd.is_nonstandard:
        codes += [K.ROLE_LEGAL_DEPT, K.ROLE_FINANCE_DIRECTOR]
    codes += [K.ROLE_HR_HEAD, K.ROLE_FINAL_SIGNER]
    out: list[str] = []
    for c in codes:
        if c not in out:
            out.append(c)
    return out


def _resolve(code: str, jd) -> tuple[int, str] | None:
    if code == K.ROLE_HR_SPECIALIST:
        # Инициатор из отдела персонала — он и есть первый согласующий.
        if jd.initiator_b24_id and hr_staff.is_hr_staff(jd.initiator_b24_id):
            opt = next(
                (o for o in hr_staff.staff_options() if o["bitrix_id"] == jd.initiator_b24_id),
                None,
            )
            return jd.initiator_b24_id, (opt["fio"] if opt else "")
        return None
    if code in OPTIONAL_ROLES:
        return None
    if code == K.ROLE_CFO_HEAD:
        a = _cfo_head(jd)
    elif code == K.ROLE_FINAL_SIGNER:
        a = _org_signer(jd)
    else:
        a = resolve_role(code, jd)
    return (a.user_b24_id, a.user_name) if a else None


def build_route(jd) -> list[dict]:
    """Упорядоченные слоты маршрута для предпросмотра и отправки."""
    route: list[dict] = []
    by_user: dict[int, dict] = {}
    for code in role_codes(jd):
        if code == K.ROLE_LEGAL_DEPT:
            route.append({
                "order": len(route), "role_code": code, "role_name": K.ROLE_NAMES[code],
                "role_class": CLASS_APPROVER, "required": True, "optional": False,
                "group": True, "resolved": True, "b24_user_id": None,
                "user_name": "Юридический отдел", "needs_manual": False,
                "replaceable": False, "auto_by_initiator": False, "hr_pick": False,
                "merged_roles": [],
            })
            continue

        found = _resolve(code, jd)
        if found and found[0] in by_user:
            # Тот же человек уже согласует раньше — второй раз не спрашиваем.
            by_user[found[0]]["merged_roles"].append(K.ROLE_NAMES.get(code, code))
            continue

        optional = code in OPTIONAL_ROLES
        slot = {
            "order": len(route),
            "role_code": code,
            "role_name": K.ROLE_NAMES.get(code, code),
            "role_class": CLASS_SIGNER if code == K.ROLE_FINAL_SIGNER else CLASS_APPROVER,
            "required": not optional,
            "optional": optional,
            "group": False,
            "resolved": found is not None,
            "b24_user_id": found[0] if found else None,
            "user_name": found[1] if found else "",
            # «при наличии» — не обязаловка: пустой выбор = этапа нет
            "needs_manual": found is None and not optional,
            "replaceable": True,
            "auto_by_initiator": code == K.ROLE_HR_SPECIALIST and found is not None,
            # первый этап выбирают из сотрудников отдела персонала
            "hr_pick": code == K.ROLE_HR_SPECIALIST,
            "merged_roles": [],
        }
        route.append(slot)
        if found:
            by_user[found[0]] = slot
    return route
