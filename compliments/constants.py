"""
Категории, статусы и маршрутные роли заявок на комплименты (ТЗ отдела продаж
от 06.08.2026 + ответы заказчика от 15.08.2026).

Роли общефирменные — берём из requests_reg.constants (там же живёт справочник
RoleAssignment), новые роли добавлены туда же, чтобы не плодить второй реестр.
"""

from requests_reg import constants as roles

# --- Статусы ---------------------------------------------------------------
# Согласование и исполнение — две фазы одного процесса. Статусы согласования
# двигает маршрут, исполнитель их НЕ меняет (решение заказчика): ему доступны
# только «взять в работу» и «исполнена».
STATUS_DRAFT = "draft"
STATUS_ON_APPROVAL = "on_approval"
STATUS_RETURNED = "returned"
STATUS_REJECTED = "rejected"
STATUS_APPROVED = "approved"
STATUS_IN_WORK = "in_work"
STATUS_EXECUTED = "executed"
STATUS_CANCELED = "canceled"

STATUS_CHOICES = [
    (STATUS_DRAFT, "Черновик"),
    (STATUS_ON_APPROVAL, "На согласовании"),
    (STATUS_RETURNED, "Возвращена на доработку"),
    (STATUS_REJECTED, "Отклонена"),
    (STATUS_APPROVED, "Согласована"),
    (STATUS_IN_WORK, "В работе у исполнителя"),
    (STATUS_EXECUTED, "Исполнена"),
    (STATUS_CANCELED, "Отменена"),
]

# Отменить можно только ДО согласования: судьба согласованной заявки не
# меняется (решение заказчика — «ничего не делаем»).
CANCELABLE_STATUSES = [STATUS_DRAFT, STATUS_ON_APPROVAL, STATUS_RETURNED, STATUS_REJECTED]

# Раздел «Заявки для исполнения»: новые / в работе / архив.
EXECUTION_NEW_STATUSES = [STATUS_APPROVED]
EXECUTION_WORK_STATUSES = [STATUS_IN_WORK]
EXECUTION_ARCHIVE_STATUSES = [STATUS_EXECUTED]
EXECUTION_SCOPES = {
    "new": EXECUTION_NEW_STATUSES,
    "work": EXECUTION_WORK_STATUSES,
    "archive": EXECUTION_ARCHIVE_STATUSES,
}
# При поиске вкладка очереди не сужает выборку — статус искомой заявки заранее
# неизвестен (тот же принцип, что в очереди юротдела).
EXECUTION_ALL_STATUSES = (
    EXECUTION_NEW_STATUSES + EXECUTION_WORK_STATUSES + EXECUTION_ARCHIVE_STATUSES
)

NUMBER_PREFIX = "КМП"

# --- Категории комплимента --------------------------------------------------
# Категория определяет ВЕСЬ маршрут: и согласующих, и исполнителя.
CATEGORY_CONFECTIONERY = "confectionery"
CATEGORY_RESTAURANT = "restaurant"
CATEGORY_STAY = "stay"

CATEGORY_CHOICES = [
    (CATEGORY_CONFECTIONERY, "Кондитерские изделия (торты, печенье)"),
    (CATEGORY_RESTAURANT, "Сертификаты на рестораны и алкоголь"),
    (CATEGORY_STAY, "Сертификаты на проживание, цветы, подарки"),
]

# --- Маршрутные роли --------------------------------------------------------
ROLE_SALES_HEAD = roles.ROLE_SALES_HEAD                    # Ткачёва Дарья
ROLE_COMMERCIAL_DIRECTOR = roles.ROLE_COMMERCIAL_DIRECTOR  # Корнейчук Ксения
ROLE_FINAL_SIGNER = roles.ROLE_FINAL_SIGNER                # ГД (ТАР) — по всем ЮЛ
ROLE_RESTAURANT_DIRECTOR = roles.ROLE_RESTAURANT_DIRECTOR  # Шахов
ROLE_CEO_ASSISTANT = roles.ROLE_CEO_ASSISTANT              # Соколинская
ROLE_CONFECTIONER = roles.ROLE_CONFECTIONER                # Вика (кондитерский цех)

ROLE_NAMES = roles.ROLE_NAMES

# Класс этапа: согласование или исполнение. Инициатор должен видеть весь путь
# «от направления до исполнения» (требование ТЗ), поэтому исполнение — такой же
# слот предпросмотра, хотя решения «согласовать/отклонить» на нём нет.
CLASS_APPROVER = "approver"
CLASS_EXECUTOR = "executor"
CLASS_NAMES = {CLASS_APPROVER: "Согласующий", CLASS_EXECUTOR: "Исполнитель"}

# Маршрут по категориям: согласующие по порядку + исполнитель.
CATEGORY_ROUTES = {
    CATEGORY_CONFECTIONERY: {
        "approvers": [ROLE_SALES_HEAD, ROLE_RESTAURANT_DIRECTOR],
        "executor": ROLE_CONFECTIONER,
    },
    CATEGORY_RESTAURANT: {
        "approvers": [ROLE_SALES_HEAD, ROLE_COMMERCIAL_DIRECTOR, ROLE_FINAL_SIGNER],
        "executor": ROLE_RESTAURANT_DIRECTOR,
    },
    CATEGORY_STAY: {
        "approvers": [ROLE_SALES_HEAD, ROLE_COMMERCIAL_DIRECTOR, ROLE_FINAL_SIGNER],
        "executor": ROLE_CEO_ASSISTANT,
    },
}

# Флажок «согласование с ГД» — свободный выбор инициатора. Он добавляет
# коммерческого директора и ГД там, где их нет по категории (кондитерка).
CEO_EXTRA_ROLES = [ROLE_COMMERCIAL_DIRECTOR, ROLE_FINAL_SIGNER]
