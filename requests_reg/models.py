"""
Регламентные заявки (ТЗ п.9): ЭЦП, МЧД, доверенности и будущие типы.

Общая карточка с type-специфичными полями в JSON (data). Согласование
идёт через универсальный движок approvalflow (Approval, привязанный к заявке
generic-связью). Документы — через приложение documents.
"""

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from core.models import CFO, Facility, Organization
from . import constants


class PowerTemplate(models.Model):
    """
    Справочник шаблонов доверенностей (матрица полномочий, УПР1/ФНС1/…).
    Используется в анкете заявки на доверенность для выбора полномочий.
    """

    code = models.CharField("Код", max_length=32, unique=True)
    name = models.CharField("Наименование", max_length=255)
    powers = models.TextField("Полномочия", blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Шаблон доверенности"
        verbose_name_plural = "Шаблоны доверенностей (матрица)"

    def __str__(self):
        return f"{self.code} — {self.name}"


class RoleAssignment(models.Model):
    """
    Кто исполняет маршрутную роль в заданном контексте (организация/ЦФО/объект).

    Используется движком построения маршрута: для каждой роли-слота ищем самое
    специфичное назначение. Если не найдено — инициатору предлагается ручной
    выбор (что фиксируется в истории заявки).
    """

    ROLE_CHOICES = [(code, name) for code, name in constants.ROLE_NAMES.items()]

    role_code = models.CharField("Роль", max_length=32, choices=ROLE_CHOICES)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True,
        related_name="role_assignments", verbose_name="Организация",
    )
    cfo = models.ForeignKey(
        CFO, on_delete=models.CASCADE, null=True, blank=True,
        related_name="role_assignments", verbose_name="ЦФО",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, null=True, blank=True,
        related_name="role_assignments", verbose_name="Объект",
    )
    user_b24_id = models.IntegerField("Сотрудник (ID Б24)")
    user_name = models.CharField("ФИО", max_length=255, blank=True)
    is_active = models.BooleanField("Активно", default=True)

    class Meta:
        verbose_name = "Назначение роли"
        verbose_name_plural = "Назначения ролей (маршрут)"
        indexes = [models.Index(fields=["role_code"])]

    def __str__(self):
        return f"{self.get_role_code_display()} → USER#{self.user_b24_id}"


class RegulatoryRequest(models.Model):
    number = models.CharField("Номер", max_length=32, blank=True, db_index=True)
    request_type = models.CharField(
        "Тип заявки", max_length=32, choices=constants.TYPE_CHOICES
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="reg_requests",
        verbose_name="Организация",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reg_requests", verbose_name="Объект",
    )
    cfo = models.ForeignKey(
        CFO, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reg_requests", verbose_name="ЦФО",
    )

    initiator_b24_id = models.IntegerField("Инициатор (ID Б24)", null=True, blank=True)

    # Заявка на отзыв ссылается на карточку отзываемой доверенности/МЧД.
    # Необязательная: бумажную доверенность, выданную до MiniSED, карточкой не
    # опишешь — её реквизиты инициатор вводит руками (data["source"]).
    # SET_NULL, а не CASCADE: отзыв — самостоятельный юридический факт и должен
    # пережить удаление карточки-первоисточника.
    source_request = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="revocations", verbose_name="Отзываемая доверенность",
    )

    # сотрудник, на которого оформляется ЭЦП/МЧД/доверенность
    subject_name = models.CharField("ФИО сотрудника", max_length=255, blank=True)
    subject_b24_id = models.IntegerField("Сотрудник (ID Б24)", null=True, blank=True)
    position = models.CharField("Должность", max_length=255, blank=True)
    department = models.CharField("Подразделение", max_length=255, blank=True)

    basis = models.TextField("Основание оформления", blank=True)
    valid_from = models.DateField("Действует с", null=True, blank=True)
    valid_until = models.DateField("Действует по", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)

    status = models.CharField(
        "Статус", max_length=20, choices=constants.STATUS_CHOICES,
        default=constants.STATUS_DRAFT,
    )

    # исполнение юридическим отделом
    delivery_method = models.CharField(
        "Способ передачи", max_length=20, choices=constants.DELIVERY_CHOICES, blank=True
    )
    delivery_comment = models.CharField("Комментарий к передаче", max_length=500, blank=True)
    # Кто исполнил заявку. Для ЭЦП это ИТ-специалист объекта, взявший её в
    # работу (у доверенностей исполнителем выступает юротдел как группа).
    executor_b24_id = models.IntegerField("Исполнитель (ID Б24)", null=True, blank=True)
    executed_at = models.DateTimeField("Исполнена", null=True, blank=True)
    received_at = models.DateTimeField("Получено инициатором", null=True, blank=True)

    # type-специфичные поля (доверитель, полномочия, нотариат, тип ЭЦП и т.д.)
    data = models.JSONField("Доп. поля", default=dict, blank=True)

    external_1c_id = models.CharField("Внешний ID в 1С", max_length=64, blank=True)
    external_diadoc_id = models.CharField("Внешний ID Диадока", max_length=64, blank=True)

    documents = GenericRelation(
        "documents.Document", content_type_field="content_type",
        object_id_field="object_id", related_query_name="reg_request",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Регламентная заявка"
        verbose_name_plural = "Регламентные заявки"
        indexes = [models.Index(fields=["request_type", "status"])]

    def __str__(self):
        return f"{self.number or f'#{self.pk}'} {self.get_request_type_display()}"

    def status_label(self) -> str:
        return self.get_status_display()
