"""
Уведомления участникам согласования (модуль Agreement).

Единая логика для внутренних и внешних участников:
  - всем на e-mail уходит письмо со ссылкой на страницу согласования по токену
    (внутренние теперь тоже могут согласовать по ссылке, как внешние);
  - тем, кто есть в Битрикс24 (внутренний — по b24_user_id, внешний — по email
    через связку B24UserEmail), дополнительно уходит уведомление-«колокольчик».

Всё best-effort: сбой канала не должен ломать процесс согласования.
E-mail внутреннего участника ищем в профиле, затем в B24UserEmail, затем в Битриксе.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.crypto import get_random_string

from core.models import UserProfile

from .models import B24UserEmail


def _bitrix_email(b24_id: int) -> str:
    """E-mail сотрудника из Битрикса (когда нет ни в профиле, ни в B24UserEmail)."""
    try:
        from bitrix.client import BitrixClient, get_active_portal, get_users_by_ids

        portal = get_active_portal()
        if not portal:
            return ""
        users = get_users_by_ids(BitrixClient(portal), [int(b24_id)])
        if users:
            u = users[0]
            return (u.get("EMAIL") or u.get("WORK_EMAIL") or "").strip()
    except Exception:
        pass
    return ""


def _resolve_email(participant) -> str:
    """E-mail участника: явный → профиль → B24UserEmail → Битрикс."""
    if participant.email:
        return participant.email.strip()
    if participant.b24_user_id:
        prof = UserProfile.objects.filter(bitrix_id=participant.b24_user_id).first()
        if prof and prof.email:
            return prof.email.strip()
        link = B24UserEmail.objects.filter(
            b24_user_id=participant.b24_user_id
        ).first()
        if link and link.email:
            return link.email.strip()
        return _bitrix_email(participant.b24_user_id)
    return ""


def _resolve_b24_id(participant) -> int | None:
    """b24-id участника: явный (внутренний) → по email через B24UserEmail (внешний)."""
    if participant.b24_user_id:
        return participant.b24_user_id
    if participant.email:
        link = B24UserEmail.objects.filter(
            email__iexact=participant.email.strip()
        ).first()
        if link:
            return link.b24_user_id
    return None


def _bitrix_notify(b24_id: int, message: str) -> None:
    try:
        from bitrix.client import BitrixClient, get_active_portal, notify_user

        portal = get_active_portal()
        if not portal:
            return
        notify_user(BitrixClient(portal), int(b24_id), message)
    except Exception:
        pass


def _approve_url(participant, base_url: str) -> str:
    if not participant.external_token:
        participant.external_token = get_random_string(24)
        participant.save(update_fields=["external_token"])
    path = reverse("external_approve", args=[participant.external_token])
    return base_url.rstrip("/") + path


def notify_participant(agreement, participant, base_url: str) -> None:
    """Шлёт участнику письмо со ссылкой + Битрикс-колокольчик (если он в Б24)."""
    approve_url = _approve_url(participant, base_url)

    subject = f"Согласование #{agreement.id}: {agreement.title}"
    lines = [
        "Вам отправлен документ на согласование.",
        "",
        f"Название: {agreement.title}",
    ]
    if agreement.description:
        lines.append(f"Описание: {agreement.description}")
    if agreement.amount is not None:
        lines.append(f"Сумма: {agreement.amount}")
    if agreement.crm_link:
        lines.append(f"CRM: {agreement.crm_link}")
    lines += ["", f"Перейти к согласованию: {approve_url}"]
    body = "\n".join(lines)

    email = _resolve_email(participant)
    if email:
        try:
            send_mail(
                subject, body,
                getattr(settings, "DEFAULT_FROM_EMAIL", None),
                [email], fail_silently=True,
            )
        except Exception:
            pass

    b24_id = _resolve_b24_id(participant)
    if b24_id:
        _bitrix_notify(b24_id, f"{subject}\n{approve_url}")
