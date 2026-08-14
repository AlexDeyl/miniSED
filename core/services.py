"""
Утилиты ядра: запись аудита и создание интеграционных событий.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

from .models import AuditLog, IntegrationEvent, SeenMark, UserProfile


def mark_seen(user_b24_id: int, obj) -> None:
    """Отметить карточку `obj` просмотренной пользователем (upsert, seen_at=now)."""
    if not user_b24_id or obj is None:
        return
    ct = ContentType.objects.get_for_model(obj.__class__)
    mark, created = SeenMark.objects.get_or_create(
        user_b24_id=user_b24_id, content_type=ct, object_id=obj.pk
    )
    if not created:
        mark.save(update_fields=["seen_at"])  # auto_now обновит seen_at


def unseen_pks(user_b24_id: int, queryset) -> set:
    """
    Множество pk из queryset, которые пользователь НЕ видел после последнего
    изменения (нет отметки ИЛИ отметка старше updated_at элемента).

    Модель queryset должна иметь поле updated_at.
    """
    if not user_b24_id:
        return set()
    model = queryset.model
    ct = ContentType.objects.get_for_model(model)
    items = list(queryset.values_list("pk", "updated_at"))
    if not items:
        return set()
    seen = dict(
        SeenMark.objects.filter(
            user_b24_id=user_b24_id, content_type=ct,
            object_id__in=[pk for pk, _ in items],
        ).values_list("object_id", "seen_at")
    )
    out = set()
    for pk, updated in items:
        s = seen.get(pk)
        if s is None or (updated is not None and s < updated):
            out.add(pk)
    return out


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
