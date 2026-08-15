"""
Заявка на комплимент партнёру (ТЗ отдела продаж).

Процесс из двух фаз: согласование по последовательному маршруту (движок
approvalflow, как у договоров и регламентных заявок) и ИСПОЛНЕНИЕ — выдача
комплимента ответственным сотрудником в разделе «Заявки для исполнения».
Маршрут целиком определяется категорией комплимента (compliments.routing).
"""

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from core.models import Facility, Organization

from . import constants


class Compliment(models.Model):
    number = models.CharField("Номер", max_length=32, blank=True, db_index=True)
    title = models.CharField("Наименование заявки", max_length=500)

    category = models.CharField(
        "Категория комплимента", max_length=32, choices=constants.CATEGORY_CHOICES
    )
    # Расшифровка из бланка: «2 сертификата на проживание… до 30.12.2026».
    category_details = models.TextField("Что именно предоставляем", blank=True)

    # Кому вручаем.
    company = models.CharField("Компания (получатель)", max_length=500)
    guest_name = models.CharField("Ф.И.О. гостя", max_length=255, blank=True)

    # Когда вручаем (в бланке — «дата и время»).
    event_at = models.DateTimeField("Дата и время комплимента", null=True, blank=True)

    facility = models.ForeignKey(
        Facility, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="compliments", verbose_name="Отель",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="compliments", verbose_name="Юрлицо",
    )

    description = models.TextField("Описание заявки", blank=True)

    initiator_b24_id = models.IntegerField("Инициатор (ID Б24)", null=True, blank=True)
    # Подразделение инициатора — снимок строкой: в бланке печатается то, что
    # было на момент заявки, даже если человек потом сменил отдел.
    department = models.CharField("Подразделение инициатора", max_length=255, blank=True)

    # Свободный выбор инициатора: подключить коммерческого директора и ГД там,
    # где по категории их нет.
    needs_ceo = models.BooleanField("Согласование с ГД", default=False)

    status = models.CharField(
        "Статус", max_length=20, choices=constants.STATUS_CHOICES,
        default=constants.STATUS_DRAFT,
    )

    # --- исполнение ---
    executor_b24_id = models.IntegerField("Исполнитель (ID Б24)", null=True, blank=True)
    taken_at = models.DateTimeField("Взята в работу", null=True, blank=True)
    executed_at = models.DateTimeField("Исполнена", null=True, blank=True)
    execution_comment = models.CharField(
        "Комментарий исполнителя", max_length=500, blank=True
    )

    data = models.JSONField("Доп. поля", default=dict, blank=True)

    documents = GenericRelation(
        "documents.Document", content_type_field="content_type",
        object_id_field="object_id", related_query_name="compliment",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Заявка на комплимент"
        verbose_name_plural = "Заявки на комплименты"

    def __str__(self):
        return f"{self.number or '#' + str(self.pk)} {self.title}"

    @property
    def status_label(self) -> str:
        return dict(constants.STATUS_CHOICES).get(self.status, self.status)

    @property
    def category_label(self) -> str:
        return dict(constants.CATEGORY_CHOICES).get(self.category, self.category)
