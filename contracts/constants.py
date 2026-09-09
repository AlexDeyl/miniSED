"""
Статусы договоров и переиспользование ОБЩЕФИРМЕННЫХ ролей/категорий ЦФО.

Роли маршрута и категории ЦФО едины на весь проект — не дублируем, берём из
requests_reg.constants (там же живёт справочник RoleAssignment). При будущем
рефакторе их можно поднять в core; здесь — единственная точка ссылки.
"""

from requests_reg import constants as roles  # общие роли/категории ЦФО

# --- Статусы договора (согласование без юр-исполнения) ----------------------
STATUS_DRAFT = "draft"
STATUS_ON_APPROVAL = "on_approval"
STATUS_RETURNED = "returned"
STATUS_REJECTED = "rejected"
STATUS_APPROVED = "approved"
STATUS_CANCELED = "canceled"

STATUS_CHOICES = [
    (STATUS_DRAFT, "Черновик"),
    (STATUS_ON_APPROVAL, "На согласовании"),
    (STATUS_RETURNED, "Возвращён на доработку"),
    (STATUS_REJECTED, "Отклонён"),
    (STATUS_APPROVED, "Согласован"),
    (STATUS_CANCELED, "Отменён"),
]

# из каких статусов инициатор может отменить договор
CANCELABLE_STATUSES = [STATUS_DRAFT, STATUS_ON_APPROVAL, STATUS_RETURNED, STATUS_REJECTED]

# Из каких статусов инициатор может править карточку договора: пока он не на
# круге и не согласован. Вернули на доработку — правим и отправляем заново.
EDITABLE_STATUSES = [STATUS_DRAFT, STATUS_RETURNED, STATUS_REJECTED]

NUMBER_PREFIX = "ДОГ"

# --- Классы роли в маршруте (пока единый поток) -----------------------------
# «согласующий» и «подписант» сейчас проходят одинаково; класс хранится меткой
# на слоте, чтобы позже (HR-link/Диадок) выделять подписантов и подтягивать им
# договор на подпись.
CLASS_APPROVER = "approver"
CLASS_SIGNER = "signer"
CLASS_NAMES = {CLASS_APPROVER: "Согласующий", CLASS_SIGNER: "Подписант"}

# Прокидываем общие справочники ролей/категорий для удобства импортов.
ROLE_NAMES = roles.ROLE_NAMES
CFO_CATEGORY_CHOICES = roles.CFO_CATEGORY_CHOICES
