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

from core.formatting import money
from core.links import agreement_route, app_link
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


def _bitrix_b24_by_email(email: str) -> int | None:
    """Ищет сотрудника Битрикса по email (user.get). Найденное кэшируем в B24UserEmail."""
    try:
        from bitrix.client import BitrixClient, get_active_portal

        portal = get_active_portal()
        if not portal:
            return None
        res = BitrixClient(portal).call("user.get", {"EMAIL": email})
        if isinstance(res, list) and res:
            b24 = int(res[0].get("ID"))
            try:
                B24UserEmail.objects.get_or_create(
                    b24_user_id=b24, email=email.strip().lower()
                )
            except Exception:
                pass
            return b24
    except Exception:
        pass
    return None


def _resolve_b24_id(participant) -> int | None:
    """b24-id участника: явный (внутренний) → B24UserEmail → Битрикс по email (внешний)."""
    if participant.b24_user_id:
        return participant.b24_user_id
    if participant.email:
        link = B24UserEmail.objects.filter(
            email__iexact=participant.email.strip()
        ).first()
        if link:
            return link.b24_user_id
        return _bitrix_b24_by_email(participant.email.strip())
    return None


def _bitrix_notify(b24_id: int, message: str, *, link: str = "",
                   link_text: str = "Перейти к согласованию") -> None:
    try:
        from bitrix.client import BitrixClient, get_active_portal, notify_user

        portal = get_active_portal()
        if not portal:
            return
        notify_user(BitrixClient(portal), int(b24_id), message,
                    link=link, link_text=link_text)
    except Exception:
        pass


def _card_link(agreement) -> str:
    """Ссылка на карточку согласования в приложении."""
    return app_link(agreement_route(agreement.id))


def _person_name(b24_id) -> str:
    """ФИО сотрудника: профиль → Битрикс. Пусто, если не нашли — строку с
    «USER #123» в уведомление лучше не класть."""
    if not b24_id:
        return ""
    prof = UserProfile.objects.filter(bitrix_id=b24_id).first()
    if prof and prof.fio:
        return prof.fio
    try:
        from bitrix.client import BitrixClient, get_active_portal, get_users_by_ids

        portal = get_active_portal()
        if not portal:
            return ""
        users = get_users_by_ids(BitrixClient(portal), [int(b24_id)])
        if users:
            u = users[0]
            return " ".join(
                x for x in (u.get("LAST_NAME"), u.get("NAME"), u.get("SECOND_NAME")) if x
            ).strip()
    except Exception:
        pass
    return ""


def _details(agreement, round_number=None) -> list[str]:
    """Наполнение уведомления — то же, что в письме: суть документа без
    перехода в карточку. Без CRM-ссылки: в письме она строкой, в колокольчике
    прячется за подписью (BB-код), поэтому её добавляют вызывающие."""
    lines = [f"Название: {agreement.title}"]
    author = _person_name(agreement.author_b24_id)
    if author:
        lines.append(f"Инициатор: {author}")
    if agreement.description:
        lines.append(f"Описание: {agreement.description}")
    if agreement.amount is not None:
        lines.append(f"Сумма: {money(agreement.amount)}")
    if agreement.deadline:
        lines.append(f"Срок: {agreement.deadline:%d.%m.%Y}")
    if round_number and round_number > 1:
        lines.append(f"Круг согласования: {round_number}")
    return lines


def _approve_url(participant, base_url: str) -> str:
    if not participant.external_token:
        participant.external_token = get_random_string(24)
        participant.save(update_fields=["external_token"])
    path = reverse("external_approve", args=[participant.external_token])
    return base_url.rstrip("/") + path


def _round_note(agreement, round_number: int) -> str:
    """Комментарий инициатора к этому кругу (пусто, если его нет).

    Согласующий должен видеть, что изменилось после доработки, прямо в письме —
    не только в карточке."""
    from .models import RoundNote

    note = (
        RoundNote.objects.filter(agreement=agreement, round_number=round_number)
        .order_by("-id")
        .first()
    )
    if not note or not note.comment.strip():
        return ""
    prefix = (
        "Комментарий инициатора при повторном направлении"
        if round_number > 1
        else "Комментарий инициатора"
    )
    return f"{prefix}: {note.comment.strip()}"


def notify_participant(agreement, participant, base_url: str) -> None:
    """Шлёт участнику письмо со ссылкой + Битрикс-колокольчик (если он в Б24)."""
    approve_url = _approve_url(participant, base_url)

    subject = f"Согласование #{agreement.id}: {agreement.title}"
    details = _details(agreement, participant.round_number)
    note = _round_note(agreement, participant.round_number)

    lines = ["Вам отправлен документ на согласование.", "", *details]
    if agreement.crm_link:
        lines.append(f"CRM: {agreement.crm_link}")
    if note:
        lines += ["", note]
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
        # Колокольчик получает то же наполнение, что и письмо (раньше уходил
        # один заголовок). Отличия: ссылки прячем за подписями BB-кодом, а
        # токен-ссылку на одноклик-согласование не даём — в приложении человек
        # и так авторизован, решение принимается в карточке.
        bell = [f"[B]{agreement.title}[/B]", *details[1:]]
        if note:
            bell += ["", note]
        if agreement.crm_link:
            bell += ["", f"[URL={agreement.crm_link}]Сделка в CRM[/URL]"]
        _bitrix_notify(
            b24_id, "\n".join(bell), link=_card_link(agreement) or approve_url,
        )


def _resolve_email_by_b24(b24_id: int) -> str:
    """E-mail сотрудника по b24-id: профиль → B24UserEmail → Битрикс."""
    prof = UserProfile.objects.filter(bitrix_id=b24_id).first()
    if prof and prof.email:
        return prof.email.strip()
    link = B24UserEmail.objects.filter(b24_user_id=b24_id).first()
    if link and link.email:
        return link.email.strip()
    return _bitrix_email(b24_id)


def notify_author_result(agreement, *, approved: bool, by_name: str = "", comment: str = "") -> None:
    """Инициатору (автору) — итог согласования: согласовано или отклонено.

    Почта + Битрикс-колокольчик, best-effort."""
    b24 = agreement.author_b24_id
    if not b24:
        return

    details = _details(agreement, agreement.current_round)
    if approved:
        subject = f"Согласовано #{agreement.id}: {agreement.title}"
        head = "Ваш документ согласован."
    else:
        who = f" ({by_name})" if by_name else ""
        subject = f"Отклонено #{agreement.id}: {agreement.title}"
        head = f"Ваш документ отклонён{who}."

    lines = [head, "", *details]
    if not approved and comment:
        lines.append(f"Причина: {comment}")
    if agreement.crm_link:
        lines.append(f"CRM: {agreement.crm_link}")
    body = "\n".join(lines)

    email = _resolve_email_by_b24(b24)
    if email:
        try:
            send_mail(subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", None),
                      [email], fail_silently=True)
        except Exception:
            pass

    # Колокольчик — то же наполнение, что в письме; CRM прячем за подписью.
    bell = [f"[B]{head}[/B]", "", *details]
    if not approved and comment:
        bell.append(f"Причина: {comment}")
    if agreement.crm_link:
        bell += ["", f"[URL={agreement.crm_link}]Сделка в CRM[/URL]"]
    _bitrix_notify(b24, "\n".join(bell), link=_card_link(agreement),
                   link_text="Открыть согласование")
