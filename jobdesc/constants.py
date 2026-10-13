"""
Статусы, маршрутные роли и справочники заявок на согласование должностных
инструкций (ТЗ «Регламентные заявки — Иное: заявка на согласование ДИ» +
ответы заказчика 13.10.2026).

Роли общефирменные — берём из requests_reg.constants (там же справочник
RoleAssignment), новые роли добавлены туда же, второй реестр не заводим.
"""

from requests_reg import constants as roles

# --- Статусы ---------------------------------------------------------------
# Две фазы: согласование (статусы двигает маршрут) и исполнение отделом по
# работе с персоналом. Утверждённая заявка не уходит письмом, а сразу
# «Передана в отдел по работе с персоналом» — это и есть «Новые» его раздела.
STATUS_DRAFT = "draft"
STATUS_ON_APPROVAL = "on_approval"
STATUS_RETURNED = "returned"
STATUS_REJECTED = "rejected"
STATUS_TO_HR = "to_hr"
STATUS_HR_WORK = "hr_work"
STATUS_SIGNING = "signing"
STATUS_EXECUTED = "executed"
STATUS_CLOSED = "closed"
STATUS_CANCELED = "canceled"

STATUS_CHOICES = [
    (STATUS_DRAFT, "Черновик"),
    (STATUS_ON_APPROVAL, "На согласовании"),
    (STATUS_RETURNED, "Возвращена на доработку"),
    (STATUS_REJECTED, "Отклонена"),
    (STATUS_TO_HR, "Передана в отдел по работе с персоналом"),
    (STATUS_HR_WORK, "В работе у отдела по работе с персоналом"),
    (STATUS_SIGNING, "На подписании"),
    (STATUS_EXECUTED, "Исполнена"),
    (STATUS_CLOSED, "Закрыта"),
    (STATUS_CANCELED, "Отменена"),
]

# Отменить можно только до утверждения: дальше заявка — работа отдела персонала.
CANCELABLE_STATUSES = [STATUS_DRAFT, STATUS_ON_APPROVAL, STATUS_RETURNED, STATUS_REJECTED]

# Править поля — до круга и после возврата/отклонения; на согласовании и в
# исполнении карточка заморожена: согласующие визируют то, что видели.
EDITABLE_STATUSES = [STATUS_DRAFT, STATUS_RETURNED, STATUS_REJECTED]

# Статусы, которые отдел персонала ставит руками («изменить статус» по ТЗ).
# «На подписании» — бумажная ДИ у подписанта; позже — подписание в HR-link.
HR_MANUAL_STATUSES = [STATUS_HR_WORK, STATUS_SIGNING]

# Раздел «Заявки для отдела по работе с персоналом».
HR_SCOPES = {
    "new": [STATUS_TO_HR],
    "work": [STATUS_HR_WORK],
    "signing": [STATUS_SIGNING],
    "done": [STATUS_EXECUTED, STATUS_CLOSED],
}
# При поиске вкладка не сужает выборку — статус искомой заявки неизвестен.
HR_ALL_STATUSES = [s for scope in HR_SCOPES.values() for s in scope]

NUMBER_PREFIX = "ДИ"

# Тип документа «готовая ДИ» — без него заявку нельзя отметить исполненной.
DOC_TYPE_FINAL = "jd_final"

# --- Способ передачи готовой ДИ (ТЗ: «отметить способ передачи») ------------
TRANSFER_CHOICES = [
    ("in_person", "Лично на руки"),
    ("email", "По электронной почте"),
    ("hrlink", "Через HR-link"),
    ("bitrix", "В Битрикс24"),
    ("other", "Другое"),
]

# --- Маршрутные роли --------------------------------------------------------
ROLE_HR_SPECIALIST = roles.ROLE_HR_SPECIALIST
ROLE_CFO_HEAD = roles.ROLE_CFO_HEAD
ROLE_ADMIN_HEAD = roles.ROLE_ADMIN_HEAD
ROLE_FUNCTIONAL_HEAD = roles.ROLE_FUNCTIONAL_HEAD
ROLE_COMMERCIAL_DIRECTOR = roles.ROLE_COMMERCIAL_DIRECTOR
ROLE_CHIEF_ACCOUNTANT = roles.ROLE_CHIEF_ACCOUNTANT
ROLE_TECH_DIRECTOR = roles.ROLE_TECH_DIRECTOR
ROLE_OPS_DIRECTOR = roles.ROLE_OPS_DIRECTOR
ROLE_RESTAURANT_DIRECTOR = roles.ROLE_RESTAURANT_DIRECTOR
ROLE_FINANCE_DIRECTOR = roles.ROLE_FINANCE_DIRECTOR
ROLE_PROCUREMENT_HEAD = roles.ROLE_PROCUREMENT_HEAD
ROLE_LEGAL_DEPT = roles.ROLE_LEGAL_DEPT
ROLE_HR_HEAD = roles.ROLE_HR_HEAD
ROLE_FINAL_SIGNER = roles.ROLE_FINAL_SIGNER

ROLE_NAMES = roles.ROLE_NAMES

# Дополнительные согласующие по категории ЦФО — порядок как в ТЗ.
# Операционный директор — только СГХ/СПиР/территория/склад; ИТС/ИТ согласует
# технический директор (ответ заказчика 13.10.2026).
CATEGORY_EXTRA_ROLES = [
    (ROLE_COMMERCIAL_DIRECTOR, {"sales", "revenue", "marketing", "booking"}),
    (ROLE_CHIEF_ACCOUNTANT, {"accounting"}),
    (ROLE_TECH_DIRECTOR, {"its_it"}),
    (ROLE_OPS_DIRECTOR, {"sgh", "reception", "territory", "warehouse"}),
    (ROLE_RESTAURANT_DIRECTOR, {"restaurant"}),
    (ROLE_FINANCE_DIRECTOR, {"finance"}),
    (ROLE_PROCUREMENT_HEAD, {"mts"}),
]

# Директор ресторанной службы согласует и любые ДИ юрлица «Невесомость».
RESTAURANT_ORG_MARKER = "Невесомость"
