"""
Уведомления по флоу заявок на комплименты.

Каналы (Битрикс-«колокольчик» + e-mail, best-effort) — общий плумбинг из
requests_reg.notifications, не дублируем.

События:
  - согласующему, когда до него дошла очередь;
  - инициатору при смене статуса (согласована / отклонена / возвращена);
  - исполнителю, когда заявка согласована и попала в раздел исполнения;
  - инициатору, когда исполнитель взял заявку в работу или исполнил её.
"""

from __future__ import annotations

from approvalflow import services as flow
from approvalflow.models import ApprovalParticipant
from requests_reg import notifications as rn
from requests_reg.models import RoleAssignment

from . import routing


def _details(compliment) -> list[str]:
    lines = [
        f"Заявка: {compliment.title}",
        f"Категория: {compliment.category_label}",
        f"Компания: {compliment.company}",
    ]
    if compliment.guest_name:
        lines.append(f"Гость: {compliment.guest_name}")
    if compliment.event_at:
        lines.append(f"Дата и время: {compliment.event_at:%d.%m.%Y %H:%M}")
    if compliment.facility_id:
        lines.append(f"Отель: {compliment.facility.name}")
    if compliment.category_details:
        lines.append(f"Что предоставляем: {compliment.category_details}")
    if compliment.description:
        lines.append(f"Описание: {compliment.description}")
    return lines


def notify_current_approver(compliment):
    """Тому, чья сейчас очередь согласовать."""
    from . import services

    p = services.current_pending_participant(services.get_approval(compliment))
    if p is None or p.type != ApprovalParticipant.TYPE_INTERNAL or not p.b24_user_id:
        return
    b24, emails = rn._recipients([p.b24_user_id])
    lines = ["Требуется ваше согласование заявки на комплимент.", "", *_details(compliment)]
    note = flow.opening_note(p)  # пояснение инициатора к этому кругу
    if note:
        lines += ["", note]
    rn._dispatch(b24, emails, f"Комплимент {compliment.number}: требуется согласование",
                 "\n".join(lines))


def notify_initiator_result(compliment):
    """Инициатору — статус заявки изменился."""
    if not compliment.initiator_b24_id:
        return
    b24, emails = rn._recipients([compliment.initiator_b24_id])
    st = compliment.status_label
    body = f"Статус заявки на комплимент изменился: {st}.\n\n" + "\n".join(_details(compliment))
    rn._dispatch(b24, emails, f"Комплимент {compliment.number}: {st}", body)


def _executor_ids(compliment) -> list[int]:
    """Кому исполнять: назначенному лично либо всем на роли исполнителя."""
    if compliment.executor_b24_id:
        return [compliment.executor_b24_id]
    role_code = routing.executor_role(compliment)
    if not role_code:
        return []
    return list(
        RoleAssignment.objects
        .filter(role_code=role_code, is_active=True)
        .values_list("user_b24_id", flat=True)
    )


def notify_executor(compliment):
    """Исполнителю — заявка согласована и ждёт в разделе «Заявки для исполнения»."""
    ids = _executor_ids(compliment)
    if not ids:
        return
    b24, emails = rn._recipients(ids)
    body = (
        "Заявка на комплимент согласована и ждёт исполнения.\n\n"
        + "\n".join(_details(compliment))
    )
    rn._dispatch(b24, emails, f"Комплимент {compliment.number}: к исполнению", body)


def notify_initiator_execution(compliment):
    """Инициатору — исполнитель взял заявку в работу либо исполнил её."""
    if not compliment.initiator_b24_id:
        return
    b24, emails = rn._recipients([compliment.initiator_b24_id])
    st = compliment.status_label
    lines = [f"Заявка на комплимент: {st}.", ""]
    if compliment.execution_comment:
        lines.append(f"Комментарий исполнителя: {compliment.execution_comment}")
    lines += _details(compliment)
    rn._dispatch(b24, emails, f"Комплимент {compliment.number}: {st}", "\n".join(lines))
