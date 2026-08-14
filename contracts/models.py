"""
Договор — заявка на согласование договора коммерческого департамента.

Маршрут строится автоматически по правилам (contracts.routing) на основе
юрлица (ЮО), ЦФО и признаков договора («нестандартный», «с протоколом
разногласий»). Само согласование идёт на движке approvalflow (как заявки),
документы — через приложение documents (значит онлайн-редактирование работает).
"""

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from core.models import CFO, Organization

from . import constants


class Contract(models.Model):
    number = models.CharField("Номер", max_length=32, blank=True, db_index=True)
    title = models.CharField("Название договора", max_length=500)

    # Юрлицо (ЮО) — выбирается при создании, определяет ГД-подписанта.
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="contracts",
        verbose_name="Юрлицо (ЮО)",
    )
    # ЦФО — определяет подписанта (рук. продаж / коммерческий директор).
    cfo = models.ForeignKey(
        CFO, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="contracts", verbose_name="ЦФО",
    )
    amount = models.DecimalField(
        "Сумма", max_digits=16, decimal_places=2, null=True, blank=True
    )

    # Признаки, включающие юр-этап (Юротдел — при условии).
    is_nonstandard = models.BooleanField(
        "Нестандартный (не по шаблону)", default=False
    )
    has_disagreement_protocol = models.BooleanField(
        "С протоколом разногласий", default=False
    )

    initiator_b24_id = models.IntegerField("Инициатор (ID Б24)", null=True, blank=True)
    crm_link = models.CharField("Ссылка на CRM / сделку", max_length=500, blank=True)
    comment = models.TextField("Комментарий", blank=True)

    status = models.CharField(
        "Статус", max_length=20, choices=constants.STATUS_CHOICES,
        default=constants.STATUS_DRAFT,
    )

    # задел на интеграции/доп. поля без миграций
    data = models.JSONField("Доп. поля", default=dict, blank=True)

    documents = GenericRelation(
        "documents.Document", content_type_field="content_type",
        object_id_field="object_id", related_query_name="contract",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Договор"
        verbose_name_plural = "Договоры"

    def __str__(self):
        return f"{self.number or '#' + str(self.pk)} {self.title}"

    @property
    def status_label(self) -> str:
        return dict(constants.STATUS_CHOICES).get(self.status, self.status)
