"""
Ядро MiniSED: общие справочники, роли/права, внешние связи, интеграционные
события и аудит. На этих сущностях строятся все модули (согласования,
регламентные заявки, иско-претензионная работа).

Модели сразу содержат внешние идентификаторы (external_1c_id, diadoc_*),
чтобы будущие интеграции подключались без переработки схемы (ТЗ п.13, 14, 20).
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


# ===========================================================================
#  Справочники (ТЗ п.8)
# ===========================================================================
class Organization(models.Model):
    """Юридическое лицо компании."""

    short_name = models.CharField("Краткое название", max_length=255)
    full_name = models.CharField("Полное юр. название", max_length=500, blank=True)
    inn = models.CharField("ИНН", max_length=12, blank=True)
    kpp = models.CharField("КПП", max_length=9, blank=True)
    ogrn = models.CharField("ОГРН", max_length=15, blank=True)
    legal_address = models.CharField("Юридический адрес", max_length=500, blank=True)
    is_active = models.BooleanField("Активна", default=True)
    comment = models.TextField("Комментарий", blank=True)

    # на будущее — интеграции
    external_1c_id = models.CharField("Внешний ID в 1С", max_length=64, blank=True)
    diadoc_box_id = models.CharField("boxId Диадока", max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["short_name"]
        verbose_name = "Организация"
        verbose_name_plural = "Организации"

    def __str__(self):
        return self.short_name


class Facility(models.Model):
    """Объект / отель."""

    name = models.CharField("Название объекта", max_length=255)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="facilities",
        verbose_name="Организация",
    )
    address = models.CharField("Адрес", max_length=500, blank=True)
    ops_director = models.CharField("Операционный директор", max_length=255, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    external_id = models.CharField("Внешний ID", max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Объект / отель"
        verbose_name_plural = "Объекты / отели"

    def __str__(self):
        return self.name


class Department(models.Model):
    """Подразделение (иерархия внутри организации)."""

    name = models.CharField("Название", max_length=255)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="departments",
        verbose_name="Организация",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Вышестоящее подразделение",
    )
    is_active = models.BooleanField("Активно", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Подразделение"
        verbose_name_plural = "Подразделения"

    def __str__(self):
        return self.name


class Position(models.Model):
    """Должность."""

    name = models.CharField("Название", max_length=255, unique=True)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Должность"
        verbose_name_plural = "Должности"

    def __str__(self):
        return self.name


class CFO(models.Model):
    """Центр финансовой ответственности."""

    CATEGORY_CHOICES = [
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

    name = models.CharField("Название", max_length=255)
    code = models.CharField("Код", max_length=64, blank=True)
    category = models.CharField(
        "Категория", max_length=32, choices=CATEGORY_CHOICES, blank=True
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="cfos",
        verbose_name="Организация",
    )
    head = models.CharField("Руководитель ЦФО", max_length=255, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    external_1c_id = models.CharField(
        "Внешний ID в 1С/БИТ.ФИНАНС", max_length=64, blank=True
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "ЦФО"
        verbose_name_plural = "ЦФО"

    def __str__(self):
        return f"{self.code} {self.name}".strip()


class Counterparty(models.Model):
    """Контрагент (в будущем — синхронизация из 1С/Диадок/Битрикс)."""

    name = models.CharField("Название", max_length=500)
    inn = models.CharField("ИНН", max_length=12, blank=True)
    kpp = models.CharField("КПП", max_length=9, blank=True)
    ogrn = models.CharField("ОГРН", max_length=15, blank=True)
    legal_address = models.CharField("Юридический адрес", max_length=500, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    external_1c_id = models.CharField("Внешний ID в 1С", max_length=64, blank=True)
    diadoc_counterparty_id = models.CharField(
        "ID в Диадоке", max_length=64, blank=True
    )
    bitrix_company_id = models.CharField(
        "ID компании в Битрикс24", max_length=64, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Контрагент"
        verbose_name_plural = "Контрагенты"

    def __str__(self):
        return self.name


# ===========================================================================
#  Роли и права (ТЗ п.8.4, 15.3, 15.4)
# ===========================================================================
class Permission(models.Model):
    """Атомарное право. Проверяется на backend (ТЗ п.15)."""

    CATEGORY_SYSTEM = "system"
    CATEGORY_PROCESS = "process"
    CATEGORY_CHOICES = [
        (CATEGORY_SYSTEM, "Системное"),
        (CATEGORY_PROCESS, "Процессное"),
    ]

    code = models.CharField("Код", max_length=64, unique=True)
    name = models.CharField("Название", max_length=255)
    category = models.CharField(
        "Категория", max_length=16, choices=CATEGORY_CHOICES, default=CATEGORY_PROCESS
    )

    class Meta:
        ordering = ["category", "code"]
        verbose_name = "Право"
        verbose_name_plural = "Права"

    def __str__(self):
        return self.code


class Role(models.Model):
    """Роль — набор прав. Бывает системная и процессная."""

    KIND_SYSTEM = "system"
    KIND_PROCESS = "process"
    KIND_CHOICES = [
        (KIND_SYSTEM, "Системная"),
        (KIND_PROCESS, "Процессная"),
    ]

    code = models.CharField("Код", max_length=64, unique=True)
    name = models.CharField("Название", max_length=255)
    kind = models.CharField(
        "Тип", max_length=16, choices=KIND_CHOICES, default=KIND_PROCESS
    )
    permissions = models.ManyToManyField(
        Permission, related_name="roles", blank=True, verbose_name="Права"
    )

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "Роль"
        verbose_name_plural = "Роли"

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """
    Пользователь MiniSED.

    Каноничная сущность пользователя. Пока личность в API определяется по
    bitrix_id (переходный контракт X-B24-User), но роли, доступные организации
    и объекты уже привязаны сюда — это основа для разграничения доступа.
    Связь с django-auth (для будущего логина) — опциональная OneToOne.
    """

    auth_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="minised_profile",
        verbose_name="Учётка Django (для входа)",
    )

    fio = models.CharField("ФИО", max_length=255)
    email = models.EmailField("Email", blank=True)
    phone = models.CharField("Телефон", max_length=32, blank=True)

    bitrix_id = models.IntegerField(
        "ID в Битрикс24", unique=True, null=True, blank=True
    )
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="users", verbose_name="Должность",
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="users", verbose_name="Подразделение",
    )
    is_active = models.BooleanField("Активен", default=True)

    roles = models.ManyToManyField(
        Role, related_name="users", blank=True, verbose_name="Роли"
    )
    organizations = models.ManyToManyField(
        Organization, related_name="users", blank=True,
        verbose_name="Доступные организации",
    )
    facilities = models.ManyToManyField(
        Facility, related_name="users", blank=True,
        verbose_name="Доступные объекты",
    )

    external_1c_id = models.CharField("Внешний ID в 1С", max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fio"]
        verbose_name = "Пользователь MiniSED"
        verbose_name_plural = "Пользователи MiniSED"

    def __str__(self):
        return self.fio or (f"USER#{self.bitrix_id}" if self.bitrix_id else f"#{self.pk}")

    def has_perm(self, code: str) -> bool:
        """Проверка права через роли пользователя."""
        return (
            self.is_active
            and self.roles.filter(permissions__code=code).exists()
        )


# ===========================================================================
#  Универсальные внешние связи (ТЗ п.11)
# ===========================================================================
class ExternalLink(models.Model):
    """
    Связь любой карточки MiniSED с внешней сущностью (сделка Битрикс24,
    контрагент/договор 1С, документ Диадока и т.д.). Полиморфна через
    ContentType, поэтому не нужно плодить костыли под каждую интеграцию.
    """

    SOURCE_BITRIX = "bitrix24"
    SOURCE_1C = "1c"
    SOURCE_DIADOC = "diadoc"
    SOURCE_MANUAL = "manual"
    SOURCE_OTHER = "other"
    SOURCE_CHOICES = [
        (SOURCE_BITRIX, "Битрикс24"),
        (SOURCE_1C, "1С"),
        (SOURCE_DIADOC, "Диадок"),
        (SOURCE_MANUAL, "Вручную"),
        (SOURCE_OTHER, "Другое"),
    ]

    ENTITY_DEAL = "deal"
    ENTITY_USER = "user"
    ENTITY_COMPANY = "company"
    ENTITY_COUNTERPARTY = "counterparty"
    ENTITY_CONTRACT = "contract"
    ENTITY_DOCUMENT = "document"
    ENTITY_ORGANIZATION = "organization"
    ENTITY_REQUEST = "request"
    ENTITY_CHOICES = [
        (ENTITY_DEAL, "Сделка"),
        (ENTITY_USER, "Пользователь"),
        (ENTITY_COMPANY, "Компания"),
        (ENTITY_COUNTERPARTY, "Контрагент"),
        (ENTITY_CONTRACT, "Договор"),
        (ENTITY_DOCUMENT, "Документ"),
        (ENTITY_ORGANIZATION, "Организация"),
        (ENTITY_REQUEST, "Заявка"),
    ]

    # владелец связи — любая карточка MiniSED
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    linked_object = GenericForeignKey("content_type", "object_id")

    source = models.CharField("Источник", max_length=16, choices=SOURCE_CHOICES)
    entity_type = models.CharField(
        "Тип сущности", max_length=32, choices=ENTITY_CHOICES
    )
    external_id = models.CharField("Внешний ID", max_length=128)
    external_url = models.URLField("Ссылка", max_length=1000, blank=True)
    title = models.CharField("Название", max_length=500, blank=True)
    status = models.CharField("Статус", max_length=64, blank=True)
    snapshot_json = models.JSONField("Снимок данных", default=dict, blank=True)
    last_sync_at = models.DateTimeField("Последняя синхронизация", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Внешняя связь"
        verbose_name_plural = "Внешние связи"
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["source", "entity_type", "external_id"]),
        ]

    def __str__(self):
        return f"{self.get_source_display()}:{self.entity_type}#{self.external_id}"


# ===========================================================================
#  Интеграционные события (ТЗ п.12)
# ===========================================================================
class IntegrationEvent(models.Model):
    """
    Событие обмена с внешними системами. На первом этапе просто пишется в
    журнал; структура готова к обработке фоновыми воркерами (1С/Диадок).
    """

    STATUS_NEW = "new"
    STATUS_PROCESSING = "processing"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_NEW, "Новое"),
        (STATUS_PROCESSING, "В обработке"),
        (STATUS_DONE, "Обработано"),
        (STATUS_ERROR, "Ошибка"),
    ]

    event_type = models.CharField("Тип события", max_length=64)

    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("content_type", "object_id")

    source_system = models.CharField("Система-источник", max_length=32, blank=True)
    target_system = models.CharField("Система-получатель", max_length=32, blank=True)

    status = models.CharField(
        "Статус", max_length=16, choices=STATUS_CHOICES, default=STATUS_NEW
    )
    payload_json = models.JSONField("Данные", default=dict, blank=True)
    error_message = models.TextField("Ошибка", blank=True)
    retry_count = models.PositiveIntegerField("Попыток", default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField("Обработано в", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Интеграционное событие"
        verbose_name_plural = "Интеграционные события"
        indexes = [models.Index(fields=["status", "event_type"])]

    def __str__(self):
        return f"{self.event_type} [{self.get_status_display()}]"


# ===========================================================================
#  Аудит (ТЗ п.15.5)
# ===========================================================================
class AuditLog(models.Model):
    """Журнал значимых действий пользователей."""

    actor = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_entries", verbose_name="Кто",
    )
    actor_repr = models.CharField("Кто (текст)", max_length=255, blank=True)
    action = models.CharField("Действие", max_length=64)

    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField("Объект (текст)", max_length=255, blank=True)

    old_value = models.JSONField("Старое значение", null=True, blank=True)
    new_value = models.JSONField("Новое значение", null=True, blank=True)

    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("User-Agent", max_length=500, blank=True)

    created_at = models.DateTimeField("Время", auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M}"
