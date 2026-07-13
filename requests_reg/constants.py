"""
Каталог типов, статусов и маршрутных ролей регламентных заявок (ТЗ п.9 + доработка).

Приоритет первой очереди — заявка на доверенность/МЧД (двухэтапный процесс:
согласование → исполнение юридическим отделом). ЭЦП архитектурно предусмотрена,
но не в приоритете.
"""

TYPE_POA = "poa"
TYPE_MCHD = "mchd"
TYPE_ECP = "ecp"

# code -> (название, префикс номера)
REQUEST_TYPES = {
    TYPE_POA: ("Заявка на доверенность", "ДОВ"),
    TYPE_MCHD: ("Заявка на МЧД", "МЧД"),
    TYPE_ECP: ("Заявка на ЭЦП", "ЭЦП"),
}

TYPE_CHOICES = [(code, name) for code, (name, _p) in REQUEST_TYPES.items()]

# --- Статусы (ТЗ, доработка по доверенности) --------------------------------
STATUS_DRAFT = "draft"
STATUS_ON_APPROVAL = "on_approval"
STATUS_RETURNED = "returned"
STATUS_REJECTED = "rejected"
STATUS_APPROVED = "approved"
STATUS_TO_LEGAL = "to_legal"
STATUS_LEGAL_WORK = "legal_work"
STATUS_SIGNING = "signing"
STATUS_EXECUTED = "executed"
STATUS_CLOSED = "closed"

STATUS_CHOICES = [
    (STATUS_DRAFT, "Черновик"),
    (STATUS_ON_APPROVAL, "На согласовании"),
    (STATUS_RETURNED, "Возвращена на доработку"),
    (STATUS_REJECTED, "Отклонена"),
    (STATUS_APPROVED, "Согласована"),
    (STATUS_TO_LEGAL, "Передана юристам"),
    (STATUS_LEGAL_WORK, "В работе у юристов"),
    (STATUS_SIGNING, "На подписании"),
    (STATUS_EXECUTED, "Исполнена"),
    (STATUS_CLOSED, "Закрыта"),
]

# статусы, попадающие в раздел «Заявки для юристов»
LEGAL_QUEUE_STATUSES = [STATUS_TO_LEGAL, STATUS_LEGAL_WORK, STATUS_SIGNING]

# --- Способ передачи готового документа -------------------------------------
DELIVERY_CHOICES = [
    ("personally", "Лично"),
    ("courier", "Курьером"),
    ("post", "Почтой"),
    ("edo", "ЭДО / электронно"),
    ("other", "Другое"),
]

# --- Категории ЦФО (для условий маршрута) -----------------------------------
CFO_CATEGORY_CHOICES = [
    ("sales", "Отдел продаж"),
    ("revenue", "Управление доходами"),
    ("marketing", "Маркетинг"),
    ("booking", "Бронирование"),
    ("accounting", "Бухгалтерия"),
    ("hr_kdp", "КДП"),
    ("hr_recruit", "Подбор / адаптация"),
    ("hr_training", "Обучение"),
    ("its_it", "ИТС / ИТ"),
    ("sgh", "СГХ"),
    ("territory", "Содержание территории"),
    ("warehouse", "Склад"),
    ("restaurant", "Ресторанная служба"),
    ("other", "Прочее"),
]

# --- Маршрутные роли --------------------------------------------------------
ROLE_CFO_HEAD = "cfo_head"
ROLE_SALES_HEAD = "sales_head"
ROLE_COMMERCIAL_DIRECTOR = "commercial_director"
ROLE_CHIEF_ACCOUNTANT = "chief_accountant"
ROLE_HR_HEAD = "hr_head"
ROLE_TECH_DIRECTOR = "tech_director"
ROLE_OPS_DIRECTOR = "ops_director"
ROLE_RESTAURANT_DIRECTOR = "restaurant_director"
ROLE_FINANCE_DIRECTOR = "finance_director"
ROLE_LEGAL_DEPT = "legal_dept"
ROLE_FINAL_SIGNER = "final_signer"

ROLE_NAMES = {
    ROLE_CFO_HEAD: "Руководитель ЦФО",
    ROLE_SALES_HEAD: "Руководитель отдела продаж",
    ROLE_COMMERCIAL_DIRECTOR: "Коммерческий директор",
    ROLE_CHIEF_ACCOUNTANT: "Главный бухгалтер УК",
    ROLE_HR_HEAD: "Руководитель отдела по работе с персоналом",
    ROLE_TECH_DIRECTOR: "Технический директор",
    ROLE_OPS_DIRECTOR: "Операционный директор",
    ROLE_RESTAURANT_DIRECTOR: "Директор ресторанной службы",
    ROLE_FINANCE_DIRECTOR: "Финансовый директор УК",
    ROLE_LEGAL_DEPT: "Юридический отдел",
    ROLE_FINAL_SIGNER: "Финальный подписант / генеральный директор",
}


def number_prefix(request_type: str) -> str:
    entry = REQUEST_TYPES.get(request_type)
    return entry[1] if entry else "ЗАЯВ"
