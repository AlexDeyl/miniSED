"""
Заявка на согласование должностной инструкции (ТЗ отдела по работе с
персоналом).

Две фазы: согласование по последовательному маршруту (движок approvalflow,
как у договоров и комплиментов) и исполнение отделом по работе с персоналом
в его разделе — готовая ДИ, способ передачи, «Получил / ознакомился».
"""

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from core.models import CFO, Facility, Organization

from . import constants


class HrStaff(models.Model):
    """Сотрудник отдела по работе с персоналом.

    Список подтягивается из Битрикса (сотрудники подразделения, команда
    sync_hr_staff и кнопка в разделе) и дополняется вручную в админке.
    Ручные записи синхронизация не трогает — портал недоступен или человек
    числится в другом подразделении, а работать с ДИ ему нужно."""

    SOURCE_BITRIX = "bitrix"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [(SOURCE_BITRIX, "Битрикс24"), (SOURCE_MANUAL, "Вручную")]

    b24_user_id = models.IntegerField("Сотрудник (ID Б24)", unique=True)
    fio = models.CharField("ФИО", max_length=255, blank=True)
    position = models.CharField("Должность", max_length=255, blank=True)
    source = models.CharField(
        "Источник", max_length=16, choices=SOURCE_CHOICES, default=SOURCE_MANUAL
    )
    is_active = models.BooleanField("Активен", default=True)
    synced_at = models.DateTimeField("Синхронизирован", null=True, blank=True)

    class Meta:
        ordering = ["fio"]
        verbose_name = "Сотрудник отдела персонала"
        verbose_name_plural = "Сотрудники отдела персонала"

    def __str__(self):
        return self.fio or f"USER #{self.b24_user_id}"


class JobDescription(models.Model):
    number = models.CharField("Номер", max_length=32, blank=True, db_index=True)
    # Должность, на которую пишется инструкция — по ней заявку и ищут.
    position_name = models.CharField("Должность", max_length=500)

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT,
        related_name="job_descriptions", verbose_name="Организация",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="job_descriptions", verbose_name="Объект / проект",
    )
    # Подразделение — через ЦФО: его руководитель согласует, а категория
    # определяет дополнительных согласующих (ответ заказчика 13.10.2026).
    cfo = models.ForeignKey(
        CFO, on_delete=models.PROTECT,
        related_name="job_descriptions", verbose_name="ЦФО (подразделение)",
    )

    # Нестандартная форма / изменены шаблонные условия → юротдел и
    # финансовый директор (п. 4.1.2 ТЗ).
    is_nonstandard = models.BooleanField("Нестандартная форма", default=False)
    description = models.TextField("Комментарий", blank=True)

    initiator_b24_id = models.IntegerField("Инициатор (ID Б24)", null=True, blank=True)

    status = models.CharField(
        "Статус", max_length=20, choices=constants.STATUS_CHOICES,
        default=constants.STATUS_DRAFT,
    )

    # --- исполнение отделом по работе с персоналом ---
    executor_b24_id = models.IntegerField("Исполнитель (ID Б24)", null=True, blank=True)
    taken_at = models.DateTimeField("Взята в работу", null=True, blank=True)
    executed_at = models.DateTimeField("Исполнена", null=True, blank=True)
    transfer_method = models.CharField(
        "Способ передачи", max_length=20, choices=constants.TRANSFER_CHOICES, blank=True
    )
    execution_comment = models.CharField("Комментарий исполнителя", max_length=500, blank=True)
    received_at = models.DateTimeField("Получено инициатором", null=True, blank=True)

    data = models.JSONField("Доп. поля", default=dict, blank=True)

    documents = GenericRelation(
        "documents.Document", content_type_field="content_type",
        object_id_field="object_id", related_query_name="job_description",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Заявка на согласование ДИ"
        verbose_name_plural = "Заявки на согласование ДИ"

    def __str__(self):
        return f"{self.number or '#' + str(self.pk)} {self.position_name}"

    @property
    def status_label(self) -> str:
        return dict(constants.STATUS_CHOICES).get(self.status, self.status)

    @property
    def transfer_label(self) -> str:
        return dict(constants.TRANSFER_CHOICES).get(self.transfer_method, self.transfer_method)
