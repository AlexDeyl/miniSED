"""
Уведомления по флоу заявок на согласование ДИ.

Каналы (Битрикс-«колокольчик» + e-mail, best-effort) — общий плумбинг из
requests_reg.notifications, не дублируем.

События:
  - согласующему, когда до него дошла очередь (юр-этап — всем юристам);
  - инициатору при смене статуса согласования (утверждена / отклонена / возвращена);
  - отделу по работе с персоналом — утверждённая заявка ждёт в его разделе;
  - инициатору — заявку взяли в работу, она на подписании или исполнена;
  - исполнителю — инициатор подтвердил получение, заявка закрыта.
"""

from __future__ import annotations

from approvalflow import services as flow
from approvalflow.models import ApprovalParticipant
from core.links import app_link, jobdesc_route
from requests_reg import notifications as rn

from . import hr_staff


def _details(jd) -> list[str]:
    lines = [
        f"Должность: {jd.position_name}",
        f"Организация: {jd.organization.short_name}",
        f"ЦФО: {jd.cfo.name}",
    ]
    if jd.facility_id:
        lines.append(f"Объект: {jd.facility.name}")
    if jd.is_nonstandard:
        lines.append("Нестандартная форма / изменены шаблонные условия")
    if jd.description:
        lines.append(f"Комментарий: {jd.description}")
    return lines


def _card_link(jd) -> str:
    return app_link(jobdesc_route(jd.id))


def notify_current_approver(jd):
    """Тому, чья сейчас очередь согласовать (юр-этап — всем юристам)."""
    from . import services

    p = services.current_pending_participant(services.get_approval(jd))
    if p is None:
        return
    note = flow.opening_note(p)
    if services.is_group_legal(p):
        b24, emails = rn._recipients(rn.lawyer_b24_ids())
        head = "Требуется согласование юридического отдела по должностной инструкции."
        subject = f"ДИ {jd.number}: требуется юротдел"
    elif p.type == ApprovalParticipant.TYPE_INTERNAL and p.b24_user_id:
        b24, emails = rn._recipients([p.b24_user_id])
        head = "Требуется ваше согласование должностной инструкции."
        subject = f"ДИ {jd.number}: требуется согласование"
    else:
        return
    lines = [head, "", *_details(jd)]
    if note:
        lines += ["", note]
    rn._dispatch(b24, emails, subject, "\n".join(lines), link=_card_link(jd))


def notify_initiator_result(jd):
    if not jd.initiator_b24_id:
        return
    b24, emails = rn._recipients([jd.initiator_b24_id])
    st = jd.status_label
    body = f"Статус заявки на согласование ДИ изменился: {st}.\n\n" + "\n".join(_details(jd))
    rn._dispatch(b24, emails, f"ДИ {jd.number}: {st}", body,
                 link=_card_link(jd), link_text="Открыть заявку")


def notify_hr_queue(jd):
    """Отделу по работе с персоналом — утверждённая заявка ждёт исполнения."""
    ids = sorted(hr_staff.staff_ids())
    if not ids:
        return
    b24, emails = rn._recipients(ids)
    body = (
        "Должностная инструкция утверждена и ждёт исполнения в разделе "
        "«Заявки для отдела по работе с персоналом».\n\n" + "\n".join(_details(jd))
    )
    rn._dispatch(b24, emails, f"ДИ {jd.number}: к исполнению", body,
                 link=_card_link(jd), link_text="Открыть заявку")


def notify_initiator_execution(jd):
    """Инициатору — заявку взяли в работу / она на подписании / исполнена."""
    if not jd.initiator_b24_id:
        return
    b24, emails = rn._recipients([jd.initiator_b24_id])
    st = jd.status_label
    lines = [f"Заявка на согласование ДИ: {st}.", ""]
    if jd.status == "executed":
        lines.append(f"Способ передачи: {jd.transfer_label}")
        if jd.execution_comment:
            lines.append(f"Комментарий отдела персонала: {jd.execution_comment}")
        lines += ["Откройте заявку и нажмите «Получил / ознакомился».", ""]
    lines += _details(jd)
    rn._dispatch(b24, emails, f"ДИ {jd.number}: {st}", "\n".join(lines),
                 link=_card_link(jd), link_text="Открыть заявку")


def notify_executor_closed(jd):
    """Исполнителю — инициатор подтвердил получение, заявка закрыта."""
    if not jd.executor_b24_id:
        return
    b24, emails = rn._recipients([jd.executor_b24_id])
    body = "Инициатор подтвердил получение ДИ, заявка закрыта.\n\n" + "\n".join(_details(jd))
    rn._dispatch(b24, emails, f"ДИ {jd.number}: закрыта", body,
                 link=_card_link(jd), link_text="Открыть заявку")
