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

    # type-специфичные поля (тип ЭЦП, доверитель, полномочия, нотариат и т.д.)
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
        """Ярлык статуса с учётом типа (ЭЦП выпущена / МЧД оформлена…)."""
        if self.status == constants.STATUS_ISSUED:
            return constants.ISSUED_LABEL.get(self.request_type, "Выпущена / оформлена")
        return self.get_status_display()
