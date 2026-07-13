"""
Утилиты ядра: запись аудита и создание интеграционных событий.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

from .models import AuditLog, IntegrationEvent, UserProfile


def _client_meta(request):
    if request is None:
        return None, ""
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get(
        "REMOTE_ADDR"
    )
    ua = request.META.get("HTTP_USER_AGENT", "")[:500]
    return ip or None, ua


def log_action(
    action: str,
    *,
    actor: UserProfile | None = None,
    target=None,
    old_value=None,
    new_value=None,
    request=None,
    object_repr: str = "",
) -> AuditLog:
    """
    Пишет запись в журнал аудита (ТЗ п.15.5).

    Не должен ронять основной поток: любые ошибки логирования гасятся.
    """
    ip, ua = _client_meta(request)

    ct = None
    obj_id = None
    if target is not None:
        ct = ContentType.objects.get_for_model(target.__class__)
        obj_id = getattr(target, "pk", None)
        if not object_repr:
            object_repr = str(target)[:255]

    return AuditLog.objects.create(
        actor=actor,
        actor_repr=(str(actor)[:255] if actor else ""),
        action=action,
        content_type=ct,
        object_id=obj_id,
        object_repr=object_repr,
        old_value=old_value,
        new_value=new_value,
        ip=ip,
        user_agent=ua,
    )


def emit_event(
    event_type: str,
    *,
    related=None,
    source_system: str = "",
    target_system: str = "",
    payload: dict | None = None,
) -> IntegrationEvent:
    """
    Создаёт интеграционное событие (ТЗ п.12). Пока просто журналируется;
    в будущем его подхватит фоновый воркер обмена с 1С/Диадоком.
    """
    ct = None
    obj_id = None
    if related is not None:
        ct = ContentType.objects.get_for_model(related.__class__)
        obj_id = getattr(related, "pk", None)

    return IntegrationEvent.objects.create(
        event_type=event_type,
        content_type=ct,
        object_id=obj_id,
        source_system=source_system,
        target_system=target_system,
        payload_json=payload or {},
    )
