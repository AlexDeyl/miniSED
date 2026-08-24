"""
Универсальное ядро согласований (ТЗ п.7).

Заменяет жёсткую связку Agreement→Participant на процесс с КРУГАМИ:
Approval → ApprovalRound → ApprovalParticipant. Один объект может пройти
несколько кругов (возврат на доработку → повторная отправка), и история
каждого круга сохраняется отдельно.

Approval полиморфен (linked_object) — используется для скидок, регламентных
заявок, претензий/исков, договоров и будущего ЭДО без дублирования логики.

Личность участников — b24_user_id (переходный контракт, как в approvals);
консолидация с core.UserProfile — на этапе авторизации.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.crypto import get_random_string


class Approval(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_RETURNED = "returned"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELED = "canceled"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_IN_PROGRESS, "На согласовании"),
        (STATUS_RETURNED, "Возвращено на доработку"),
        (STATUS_COMPLETED, "Согласовано"),
        (STATUS_REJECTED, "Отклонено"),
        (STATUS_CANCELED, "Отменено"),
        (STATUS_CLOSED, "Закрыто"),
    ]

    FLOW_PARALLEL = "parallel"
    FLOW_SEQUENTIAL = "sequential"
    FLOW_CHOICES = [
        (FLOW_PARALLEL, "Параллельное"),
        (FLOW_SEQUENTIAL, "Последовательное"),
    ]

    approval_type = models.CharField("Тип согласования", max_length=64, default="generic")
    title = models.CharField("Название", max_length=500, blank=True)

    # к какой карточке относится (скидка, заявка, юр. дело…)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    linked_object = GenericForeignKey("content_type", "object_id")

    flow_type = models.CharField(
        "Тип", max_length=20, choices=FLOW_CHOICES, default=FLOW_PARALLEL
    )
    status = models.CharField(
        "Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    current_round = models.PositiveIntegerField("Текущий круг", default=0)

    initiator_b24_id = models.IntegerField("Инициатор (ID Б24)", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField("Отправлено", null=True, blank=True)
    completed_at = models.DateTimeField("Завершено", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Согласование"
        verbose_name_plural = "Согласования (ядро)"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"#{self.pk} {self.title}".strip()


class ApprovalRound(models.Model):
    RESULT_PENDING = "pending"
    RESULT_APPROVED = "approved"
    RESULT_REJECTED = "rejected"
    RESULT_RETURNED = "returned"
    RESULT_CHOICES = [
        (RESULT_PENDING, "В процессе"),
        (RESULT_APPROVED, "Согласовано"),
        (RESULT_REJECTED, "Отклонено"),
        (RESULT_RETURNED, "Возвращено на доработку"),
    ]

    approval = models.ForeignKey(
        Approval, on_delete=models.CASCADE, related_name="rounds"
    )
    round_number = models.PositiveIntegerField("Номер круга")
    result = models.CharField(
        "Итог", max_length=16, choices=RESULT_CHOICES, default=RESULT_PENDING
    )
    # comment — чем круг ЗАКРЫЛИ (причина возврата на доработку),
    # opening_comment — с чем инициатор круг ОТКРЫЛ (что изменилось после
    # доработки). Два разных момента жизни круга, поэтому два поля.
    comment = models.TextField("Комментарий", blank=True)
    opening_comment = models.TextField(
        "Комментарий инициатора при направлении", blank=True
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField("Завершён", null=True, blank=True)

    class Meta:
        ordering = ["approval_id", "round_number"]
        verbose_name = "Круг согласования"
        verbose_name_plural = "Круги согласования"
        unique_together = ("approval", "round_number")

    def __str__(self):
        return f"{self.approval_id} круг {self.round_number}"


class ApprovalParticipant(models.Model):
    TYPE_INTERNAL = "internal"
    TYPE_EXTERNAL = "external"
    TYPE_CHOICES = [
        (TYPE_INTERNAL, "Сотрудник"),
        (TYPE_EXTERNAL, "Внешний email"),
    ]

    DECISION_WAITING = "waiting"
    DECISION_APPROVED = "approved"
    DECISION_REJECTED = "rejected"
    DECISION_CHOICES = [
        (DECISION_WAITING, "Ожидает"),
        (DECISION_APPROVED, "Согласовано"),
        (DECISION_REJECTED, "Отклонено"),
    ]

    round = models.ForeignKey(
        ApprovalRound, on_delete=models.CASCADE, related_name="participants"
    )

    type = models.CharField("Тип", max_length=10, choices=TYPE_CHOICES)
    b24_user_id = models.IntegerField("ID сотрудника Б24", null=True, blank=True)
    email = models.EmailField("Email", blank=True)
    name = models.CharField("Имя", max_length=255, blank=True)

    role = models.CharField("Процессная роль", max_length=64, blank=True)
    order = models.PositiveIntegerField("Порядок", default=0)
    is_required = models.BooleanField("Обязателен", default=True)

    decision = models.CharField(
        "Решение", max_length=16, choices=DECISION_CHOICES, default=DECISION_WAITING
    )
    decision_comment = models.TextField("Комментарий к решению", blank=True)
    decided_at = models.DateTimeField("Дата решения", null=True, blank=True)

    external_token = models.CharField(
        "Токен внешней ссылки", max_length=32, unique=True, null=True, blank=True
    )

    class Meta:
        ordering = ["round_id", "order"]
        verbose_name = "Согласующий"
        verbose_name_plural = "Согласующие"

    def save(self, *args, **kwargs):
        # Токен генерируем всем участникам: по ссылке согласуют и внутренние.
        if not self.external_token:
            self.external_token = get_random_string(24)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.type == self.TYPE_INTERNAL and self.b24_user_id:
            return f"USER#{self.b24_user_id}"
        return self.email or self.name or "участник"


class ApprovalRouteChangeLog(models.Model):
    """Журнал изменений маршрута (ТЗ п.7.6): кто, когда, что и почему изменил."""

    approval = models.ForeignKey(
        Approval, on_delete=models.CASCADE, related_name="route_changes"
    )
    changed_by_b24_id = models.IntegerField("Кто изменил", null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    old_route_snapshot = models.JSONField("Маршрут до", default=list, blank=True)
    new_route_snapshot = models.JSONField("Маршрут после", default=list, blank=True)
    reason = models.CharField("Причина", max_length=500, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Изменение маршрута"
        verbose_name_plural = "Изменения маршрута"

    def __str__(self):
        return f"{self.approval_id} @ {self.changed_at:%Y-%m-%d %H:%M}"


class ApprovalSheet(models.Model):
    """Сформированный лист согласования (ТЗ п.7.7)."""

    FORMAT_PDF = "pdf"
    FORMAT_DOCX = "docx"
    FORMAT_XLSX = "xlsx"
    FORMAT_CHOICES = [
        (FORMAT_PDF, "PDF"),
        (FORMAT_DOCX, "DOCX"),
        (FORMAT_XLSX, "XLSX"),
    ]

    approval = models.ForeignKey(
        Approval, on_delete=models.CASCADE, related_name="sheets"
    )
    generated_file = models.FileField(
        "Файл", upload_to="approval_sheets/%Y/%m/", max_length=500
    )
    format = models.CharField(
        "Формат", max_length=8, choices=FORMAT_CHOICES, default=FORMAT_PDF
    )
    generated_by_b24_id = models.IntegerField("Кто сформировал", null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Лист согласования"
        verbose_name_plural = "Листы согласования"

    def __str__(self):
        return f"Лист {self.approval_id} ({self.format})"
