from django.db import models
from django.utils import timezone


class BitrixPortal(models.Model):
    """
    Портал Битрикс24, к которому подключён MiniSED.

    Обычно один, но модель рассчитана на несколько порталов
    (мультиарендность в будущем). Идентифицируется по member_id —
    стабильному идентификатору портала, который Битрикс отдаёт
    вместе с токенами (домен может меняться, member_id — нет).
    """

    domain = models.CharField("Домен портала", max_length=255)
    member_id = models.CharField(
        "member_id портала",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Портал Битрикс24"
        verbose_name_plural = "Порталы Битрикс24"

    def __str__(self):
        return self.domain


class BitrixToken(models.Model):
    """
    OAuth-токены доступа к порталу.

    Именно этого не хватало в текущем коде: access_token получался
    разово и терялся. Здесь токены хранятся и обновляются по refresh_token,
    что позволяет серверу вызывать REST Битрикса вне iframe (в т.ч. при
    прямом открытии MiniSED с домена).
    """

    portal = models.OneToOneField(
        BitrixPortal,
        on_delete=models.CASCADE,
        related_name="token",
        verbose_name="Портал",
    )
    access_token = models.TextField("access_token")
    refresh_token = models.TextField("refresh_token", blank=True)
    expires_at = models.DateTimeField("Истекает", null=True, blank=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Токен Битрикс24"
        verbose_name_plural = "Токены Битрикс24"

    def __str__(self):
        return f"Токен {self.portal.domain}"

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        # Запас 60 секунд, чтобы не попасть на границу протухания.
        return timezone.now() >= self.expires_at - timezone.timedelta(seconds=60)


class BitrixApiLog(models.Model):
    """
    Журнал вызовов и ошибок интеграции (требование п.5.1 ТЗ).

    Пишем в первую очередь ошибки, чтобы диагностировать проблемы связи
    с порталом. Успешные вызовы можно логировать выборочно.
    """

    portal = models.ForeignKey(
        BitrixPortal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_logs",
    )
    method = models.CharField("REST-метод", max_length=128)
    ok = models.BooleanField("Успех", default=False)
    status_code = models.IntegerField("HTTP-код", null=True, blank=True)
    error = models.TextField("Ошибка", blank=True)
    created_at = models.DateTimeField("Время", auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Лог вызова Битрикс24"
        verbose_name_plural = "Логи вызовов Битрикс24"

    def __str__(self):
        return f"{self.method} {'OK' if self.ok else 'ERR'}"
