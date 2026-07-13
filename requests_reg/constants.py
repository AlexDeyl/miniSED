"""
Каталог типов регламентных заявок и статусов (ТЗ п.9).

Модуль спроектирован расширяемым: чтобы добавить новый тип заявки,
достаточно дописать запись в REQUEST_TYPES и (при необходимости) набор
type-специфичных полей в TYPE_FIELDS — без переработки моделей/логики.
Type-специфичные поля хранятся в JSON-поле RegulatoryRequest.data.
"""

TYPE_ECP = "ecp"
TYPE_MCHD = "mchd"
TYPE_POA = "poa"

# code -> (название, префикс номера)
REQUEST_TYPES = {
    TYPE_ECP: ("Заявка на ЭЦП", "ЭЦП"),
    TYPE_MCHD: ("Заявка на МЧД", "МЧД"),
    TYPE_POA: ("Заявка на доверенность", "ДОВ"),
}

TYPE_CHOICES = [(code, name) for code, (name, _prefix) in REQUEST_TYPES.items()]


# Общий набор статусов покрывает все три типа (ТЗ п.9.2-9.4).
# Ярлык «выпущена/оформлена» различается по типу — задаётся в ISSUED_LABEL.
STATUS_DRAFT = "draft"
STATUS_ON_APPROVAL = "on_approval"
STATUS_RETURNED = "returned"
STATUS_APPROVED = "approved"
STATUS_IN_WORK = "in_work"
STATUS_ISSUED = "issued"
STATUS_REJECTED = "rejected"
STATUS_CLOSED = "closed"

STATUS_CHOICES = [
    (STATUS_DRAFT, "Черновик"),
    (STATUS_ON_APPROVAL, "На согласовании"),
    (STATUS_RETURNED, "Возвращена на доработку"),
    (STATUS_APPROVED, "Согласована"),
    (STATUS_IN_WORK, "В работе"),
    (STATUS_ISSUED, "Выпущена / оформлена"),
    (STATUS_REJECTED, "Отклонена"),
    (STATUS_CLOSED, "Закрыта"),
]

# Ярлык статуса «выпущена» по типу — для отображения.
ISSUED_LABEL = {
    TYPE_ECP: "ЭЦП выпущена",
    TYPE_MCHD: "МЧД оформлена",
    TYPE_POA: "Доверенность оформлена",
}

# Рекомендованные type-специфичные поля (для форм/подсказок; в JSON data).
TYPE_FIELDS = {
    TYPE_ECP: ["ecp_type", "target_organization", "systems", "responsible", "issued_at", "expires_at"],
    TYPE_MCHD: ["principal", "representative", "powers", "operators", "issued_at", "expires_at"],
    TYPE_POA: ["principal", "representative", "powers", "poa_type", "notarization", "issued_at", "expires_at"],
}


def number_prefix(request_type: str) -> str:
    entry = REQUEST_TYPES.get(request_type)
    return entry[1] if entry else "ЗАЯВ"
