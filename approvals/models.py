from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.utils.crypto import get_random_string


class Agreement(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELED = "canceled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_IN_PROGRESS, "В работе"),
        (STATUS_COMPLETED, "Согласован"),
        (STATUS_REJECTED, "Отклонён"),
        (STATUS_CANCELED, "Отменено"),
    ]

    FLOW_PARALLEL = "parallel"
    FLOW_SEQUENTIAL = "sequential"
    FLOW_CHOICES = [
        (FLOW_PARALLEL, "Параллельное"),
        (FLOW_SEQUENTIAL, "Последовательное"),
    ]

    title = models.CharField("Название", max_length=250)
    description = models.TextField("Описание", blank=True)
    amount = models.DecimalField(
        "Сумма",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    author_b24_id = models.IntegerField("Автор (ID в Б24)")
    deadline = models.DateField("Дедлайн", null=True, blank=True)
    crm_link = models.CharField(
        "Ссылка на CRM",
        max_length=255,
        blank=True,
    )
    flow_type = models.CharField(
        "Тип согласования",
        max_length=20,
        choices=FLOW_CHOICES,
        default=FLOW_PARALLEL,
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_IN_PROGRESS,
    )
    current_round = models.PositiveIntegerField("Текущий круг", default=1)

    # Версионируемые документы (приложение documents). Исторические файлы
    # согласования лежат в AgreementDocument (related_name="documents"), новые
    # грузятся через documents — поиск по имени файла обязан видеть и те, и те.
    versioned_documents = GenericRelation(
        "documents.Document", content_type_field="content_type",
        object_id_field="object_id", related_query_name="agreement",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Согласование"
        verbose_name_plural = "Согласования"

    def __str__(self):
        return f"#{self.id} {self.title}"   # type: ignore


class AgreementDocument(models.Model):
    TYPE_FILE = "file"
    TYPE_LINK = "link"

    TYPE_CHOICES = [
        (TYPE_FILE, "Файл"),
        (TYPE_LINK, "Ссылка"),
    ]

    agreement = models.ForeignKey(
        Agreement,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    type = models.CharField(
        "Тип",
        max_length=10,
        choices=TYPE_CHOICES,
        default=TYPE_FILE,
    )
    file = models.FileField(
        "Файл",
        upload_to="agreements/",
        null=True,
        blank=True,
        max_length=500,
    )
    url = models.URLField("Ссылка", blank=True)

    class Meta:
        verbose_name = "Документ"
        verbose_name_plural = "Документы"

    def __str__(self):
        return f"Документ для #{self.agreement_id}"   # type: ignore


class Participant(models.Model):
    TYPE_INTERNAL = "internal"
    TYPE_EXTERNAL = "external"

    TYPE_CHOICES = [
        (TYPE_INTERNAL, "Сотрудник Б24"),
        (TYPE_EXTERNAL, "Внешний email"),
    ]

    STATUS_WAITING = "waiting"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_WAITING, "Ожидает"),
        (STATUS_APPROVED, "Согласовано"),
        (STATUS_REJECTED, "Отклонено"),
    ]

    agreement = models.ForeignKey(
        Agreement,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    type = models.CharField(
        "Тип участника",
        max_length=10,
        choices=TYPE_CHOICES,
    )

    # внутренний участник
    b24_user_id = models.IntegerField(
        "ID пользователя Б24",
        null=True,
        blank=True,
    )

    # внешний участник
    email = models.EmailField("Email", blank=True)
    name = models.CharField("Имя", max_length=255, blank=True)

    status = models.CharField(
        "Статус",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_WAITING,
    )

    prev_status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
    )
    prev_comment = models.TextField(blank=True)

    comment = models.TextField("Комментарий", blank=True)
    decided_at = models.DateTimeField(
        "Дата решения",
        null=True,
        blank=True,
    )

    external_token = models.CharField(
        "Токен внешней ссылки",
        max_length=32,
        unique=True,
        blank=True,
        null=True,
    )

    order_index = models.PositiveIntegerField(
        "Порядок согласования",
        default=0,
    )
    round_number = models.PositiveIntegerField("Круг", default=1)

    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Участник"
        verbose_name_plural = "Участники"

    def save(self, *args, **kwargs):
        # Токен генерируем всем участникам (не только внешним): по нему теперь
        # согласуют и внутренние — им уходит такое же письмо со ссылкой.
        if not self.external_token:
            self.external_token = get_random_string(24)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.agreement_id} — {self.display_label}"   # type: ignore

    @property
    def display_label(self):
        if self.type == self.TYPE_INTERNAL and self.b24_user_id:
            return f"USER#{self.b24_user_id}"
        return self.email or self.name or "Участник"


class DecisionLog(models.Model):
    agreement = models.ForeignKey(
        Agreement,
        related_name="decision_logs",
        on_delete=models.CASCADE,
    )
    participant = models.ForeignKey(
        Participant,
        related_name="decision_logs",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        max_length=20,
        choices=Participant.STATUS_CHOICES,
    )
    comment = models.TextField(blank=True)
    round_number = models.PositiveIntegerField("Круг", default=1)
    decided_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["decided_at"]


class RoundNote(models.Model):
    """Комментарий инициатора при направлении круга на согласование.

    Пишется в момент открытия круга (обычно повторного — «что изменилось после
    доработки»). Не решение участника, поэтому в DecisionLog не помещается: там
    обязателен participant, а автор круга участником не является."""

    agreement = models.ForeignKey(
        Agreement, related_name="round_notes", on_delete=models.CASCADE
    )
    round_number = models.PositiveIntegerField("Круг")
    author_b24_id = models.IntegerField("Автор (Б24)", null=True, blank=True)
    comment = models.TextField("Комментарий")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["round_number", "id"]
        verbose_name = "Комментарий к кругу"
        verbose_name_plural = "Комментарии к кругам"

    def __str__(self):
        return f"#{self.agreement_id} круг {self.round_number}"


class B24Identity(models.Model):
    b24_user_id = models.IntegerField("ID пользователя Б24", unique=True)
    email = models.EmailField("Корпоративный email")
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Связка Б24 ↔ email"
        verbose_name_plural = "Связки Б24 ↔ email"

    def __str__(self):
        return f"{self.b24_user_id} — {self.email}"


class ApprovalTemplate(models.Model):
    SCOPE_PRIVATE = "private"
    SCOPE_PUBLIC = "public"
    SCOPE_GROUP = "group"

    SCOPE_CHOICES = [
        (SCOPE_PRIVATE, "Только мне"),
        (SCOPE_PUBLIC, "Всем пользователям"),
        (SCOPE_GROUP, "Определённой группе"),
    ]

    name = models.CharField("Название шаблона", max_length=255)
    description = models.TextField("Описание", blank=True)

    author_b24_id = models.IntegerField("Автор (ID в Б24)")
    scope = models.CharField(
        "Область видимости",
        max_length=20,
        choices=SCOPE_CHOICES,
        default=SCOPE_PRIVATE,
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        verbose_name = "Шаблон согласования"
        verbose_name_plural = "Шаблоны согласований"

    def __str__(self):
        return f"[{self.get_scope_display()}] {self.name}"   # type: ignore


class ApprovalTemplateParticipant(models.Model):
    TYPE_INTERNAL = "internal"
    TYPE_EXTERNAL = "external"

    TYPE_CHOICES = [
        (TYPE_INTERNAL, "Сотрудник Б24"),
        (TYPE_EXTERNAL, "Внешний email"),
    ]

    template = models.ForeignKey(
        ApprovalTemplate,
        related_name="participants",
        on_delete=models.CASCADE,
    )

    type = models.CharField(
        "Тип",
        max_length=10,
        choices=TYPE_CHOICES,
        default=TYPE_INTERNAL,
    )
    b24_user_id = models.IntegerField(
        "ID пользователя Б24",
        null=True,
        blank=True,
    )
    email = models.EmailField("Email", blank=True)
    name = models.CharField("Имя", max_length=255, blank=True)
    order_index = models.PositiveIntegerField(
        "Порядок согласования",
        default=0,
    )
    note = models.CharField(
        "Описание / инструкция для участника",
        max_length=500,
        blank=True,
    )

    class Meta:
        ordering = ["order_index"]
        verbose_name = "Участник шаблона"
        verbose_name_plural = "Участники шаблона"

    def __str__(self):
        if self.type == self.TYPE_INTERNAL and self.b24_user_id:
            return f"USER#{self.b24_user_id} (#{self.order_index})"
        return f"{self.email or self.name} (#{self.order_index})"


class ApprovalTemplateAccess(models.Model):
    template = models.ForeignKey(
        ApprovalTemplate,
        related_name="accesses",
        on_delete=models.CASCADE,
    )
    b24_user_id = models.IntegerField("ID пользователя Б24")

    class Meta:
        verbose_name = "Доступ к шаблону"
        verbose_name_plural = "Доступы к шаблонам"
        unique_together = ("template", "b24_user_id")

    def __str__(self):
        return f"{self.template_id} -> USER#{self.b24_user_id}"  # type: ignore


class B24UserEmail(models.Model):
    b24_user_id = models.IntegerField("ID пользователя Б24")
    email = models.EmailField("Email")

    class Meta:
        unique_together = ("b24_user_id", "email")
        verbose_name = "Email пользователя Б24"
        verbose_name_plural = "Email-адреса пользователей Б24"
        ordering = ["b24_user_id", "email"]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"USER#{self.b24_user_id} → {self.email}"
