"""
Уведомления по флоу регламентных заявок.

Каналы: Битрикс24 (im.notify — «колокольчик») + дублирование на e-mail.
Всё best-effort: сбой уведомления не должен ломать процесс. Отправка —
после commit транзакции (см. services._notify → transaction.on_commit).

События:
  - согласующему, когда до него дошла очередь (в т.ч. юротделу — всем юристам);
  - юристам, когда заявка передана на исполнение (раздел «Новые»);
  - инициатору, когда заявка исполнена (нужно подтвердить получение);
  - юристам, когда инициатор подтвердил получение (заявка закрыта).
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail

from approvalflow.models import ApprovalParticipant
from core.models import UserProfile


def lawyer_b24_ids() -> list[int]:
    """b24-id всех активных сотрудников с правом юриста (legal_manage)."""
    return list(
        UserProfile.objects.filter(
            is_active=True,
            bitrix_id__isnull=False,
            roles__permissions__code="legal_manage",
        )
        .values_list("bitrix_id", flat=True)
        .distinct()
    )


def _emails_via_bitrix(b24_ids) -> dict:
    """Почты сотрудников из Битрикса (для тех, кого нет в профилях)."""
    try:
        from bitrix.client import BitrixClient, get_active_portal, get_users_by_ids

        portal = get_active_portal()
        if not portal:
            return {}
        out = {}
        for u in get_users_by_ids(BitrixClient(portal), list(b24_ids)):
            try:
                out[int(u["ID"])] = (u.get("EMAIL") or u.get("WORK_EMAIL") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue
        return out
    except Exception:
        return {}


def _recipients(b24_ids):
    """(список b24-id, список e-mail) — почты из профилей, недостающие — из Битрикса."""
    b24_ids = [int(b) for b in b24_ids if b]
    emails: set[str] = set()
    profs = {p.bitrix_id: p for p in UserProfile.objects.filter(bitrix_id__in=b24_ids)}
    missing = []
    for b in b24_ids:
        p = profs.get(b)
        if p and p.email:
            emails.add(p.email)
        else:
            missing.append(b)
    if missing:
        for _b, em in _emails_via_bitrix(missing).items():
            if em:
                emails.add(em)
    return b24_ids, list(emails)


def _bitrix_notify(b24_ids, message):
    try:
        from bitrix.client import BitrixClient, get_active_portal, notify_user

        portal = get_active_portal()
        if not portal:
            return
        client = BitrixClient(portal)
        for uid in b24_ids:
            try:
                notify_user(client, uid, message)
            except Exception:
                continue
    except Exception:
        pass


def _email(emails, subject, body):
    emails = [e for e in emails if e]
    if not emails:
        return
    try:
        send_mail(
            subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", None),
            emails, fail_silently=True,
        )
    except Exception:
        pass


def _dispatch(b24_ids, emails, subject, message):
    _bitrix_notify(b24_ids, message)
    _email(emails, subject, message)


def _label(request) -> str:
    base = f"{request.number} · {request.get_request_type_display()}"
    return f"{base} — {request.subject_name}" if request.subject_name else base


# --- события -----------------------------------------------------------------
def notify_current_approver(request):
    """Тому, чья сейчас очередь согласовать (юрэтап — всем юристам)."""
    from . import services

    p = services.current_pending_participant(services.get_approval(request))
    if p is None:
        return
    label = _label(request)
    if services.is_group_legal(p):
        b24, emails = _recipients(lawyer_b24_ids())
        _dispatch(b24, emails, "Требуется согласование юротдела",
                  f"Требуется согласование юридического отдела: {label}")
    elif p.type == ApprovalParticipant.TYPE_INTERNAL and p.b24_user_id:
        b24, emails = _recipients([p.b24_user_id])
        _dispatch(b24, emails, "Требуется ваше согласование",
                  f"Требуется ваше согласование: {label}")
    elif p.email:
        _dispatch([], [p.email], "Требуется ваше согласование",
                  f"Требуется ваше согласование: {label}")


def notify_legal_queue(request):
    """Юристам — заявка передана на исполнение (раздел «Новые»)."""
    b24, emails = _recipients(lawyer_b24_ids())
    _dispatch(b24, emails, "Новая заявка на исполнение",
              f"Заявка передана юристам на исполнение: {_label(request)}")


def notify_initiator_executed(request):
    """Инициатору — заявка исполнена, нужно подтвердить получение."""
    b24, emails = _recipients([request.initiator_b24_id])
    _dispatch(b24, emails, "Заявка исполнена",
              f"Заявка исполнена, подтвердите получение: {_label(request)}")


def notify_legal_closed(request):
    """Юристам — инициатор подтвердил получение, заявка закрыта."""
    b24, emails = _recipients(lawyer_b24_ids())
    _dispatch(b24, emails, "Заявка закрыта",
              f"Инициатор подтвердил получение, заявка закрыта: {_label(request)}")
