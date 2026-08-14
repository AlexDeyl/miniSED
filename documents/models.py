"""
Универсальное версионируемое хранилище документов (ТЗ п.7.1-7.3).

Document — логический документ, привязанный к любой карточке MiniSED
(согласование, заявка, юр. дело) через ContentType.
DocumentVersion — конкретная версия файла. Старые версии НЕ теряются:
новая загрузка создаёт новую версию, помечая её актуальной.

Модель специально устроена так, чтобы позже подключить онлайн-редактор
(OnlyOffice/Р7) без переработки хранения — редактор просто создаёт версию.

Личность (кто загрузил) пока хранится как b24_user_id (переходный контракт,
как в approvals); консолидация с core.UserProfile — на этапе авторизации.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Document(models.Model):
    # --- к какой карточке относится документ ---
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    linked_object = GenericForeignKey("content_type", "object_id")

    document_type = models.CharField("Тип документа", max_length=64, blank=True)
    title = models.CharField("Название", max_length=500)

    current_version = models.ForeignKey(
        "DocumentVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Актуальная версия",
    )
    is_confidential = models.BooleanField("Конфиденциально", default=False)

    created_by_b24_id = models.IntegerField("Создал (ID Б24)", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField("Удалён (soft delete)", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Документ"
        verbose_name_plural = "Документы"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return self.title

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class DocumentVersion(models.Model):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField("Номер версии", default=1)
    file = models.FileField("Файл", upload_to="documents/%Y/%m/", max_length=500)
    original_filename = models.CharField("Оригинальное имя", max_length=500, blank=True)

    uploaded_by_b24_id = models.IntegerField("Загрузил (ID Б24)", null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    change_comment = models.TextField("Комментарий к версии", blank=True)

    is_current = models.BooleanField("Актуальная", default=False)
    file_size = models.BigIntegerField("Размер, байт", null=True, blank=True)
    mime_type = models.CharField("MIME-тип", max_length=128, blank=True)
    checksum = models.CharField("SHA-256", max_length=64, blank=True)

    class Meta:
        ordering = ["document_id", "version_number"]
        verbose_name = "Версия документа"
        verbose_name_plural = "Версии документов"
        unique_together = ("document", "version_number")

    def __str__(self):
        return f"{self.document_id} v{self.version_number}"


class EditSession(models.Model):
    """
    Сессия онлайн-редактирования документа (ТЗ п.7.2-7.3).

    Одна активная сессия на пару (документ, базовая версия): при совместном
    редактировании несколько пользователей делят один `editor_key`, поэтому
    вторая попытка открыть тот же документ переиспользует сессию, а не плодит.

    Сервер документов (OnlyOffice/Р7) присылает результат в callback асинхронно
    (по закрытию последнего соавтора). На статус «готово к сохранению» мы
    скачиваем итоговый файл и создаём НОВУЮ версию через documents.services —
    хранение при этом не меняется, редактор лишь ещё один источник версий.
    """

    STATUS_ACTIVE = "active"      # редактируется
    STATUS_SAVING = "saving"      # пришёл результат, сохраняем версию
    STATUS_CLOSED = "closed"      # закрыта (сохранена либо без изменений)
    STATUS_ERROR = "error"        # ошибка сохранения на стороне сервера документов
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Редактируется"),
        (STATUS_SAVING, "Сохранение"),
        (STATUS_CLOSED, "Закрыта"),
        (STATUS_ERROR, "Ошибка"),
    ]

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="edit_sessions"
    )
    base_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="Редактируемая версия",
    )
    # Ключ документа для сервера документов: обязан меняться при смене содержимого,
    # иначе сервер отдаёт закэшированную копию (см. documents.editing.editor_key).
    editor_key = models.CharField("Ключ редактора", max_length=128, db_index=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )

    opened_by_b24_id = models.IntegerField("Открыл (ID Б24)", null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    last_callback_status = models.IntegerField(null=True, blank=True)
    saved_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Сохранённая версия",
    )
    error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Сессия редактирования"
        verbose_name_plural = "Сессии редактирования"
        indexes = [models.Index(fields=["document", "status"])]

    def __str__(self):
        return f"edit doc={self.document_id} key={self.editor_key} [{self.status}]"

    @property
    def is_active(self) -> bool:
        return self.status in (self.STATUS_ACTIVE, self.STATUS_SAVING)
