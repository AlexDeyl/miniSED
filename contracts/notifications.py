"""
Уведомления по флоу договоров.

Каналы и плумбинг (Битрикс-«колокольчик» + e-mail, best-effort) — ОБЩИЕ,
переиспользуем из requests_reg.notifications, не дублируем.

Письма богатые (название, ЮО, ЦФО, сумма, признаки, комментарий, CRM) и содержат
ссылку-токен на страницу согласования БЕЗ авторизации (contract_external_approve),
как у обычных согласований/заявок.

События:
  - согласующему, когда до него дошла очередь (юр-этап → всем юристам);
  - инициатору, когда статус договора изменился (согласован / отклонён / возвращён).
"""

from __future__ import annotations

from django.conf import settings
from django.urls import reverse
from django.utils.crypto import get_random_string

from approvalflow import services as flow
from approvalflow.models import ApprovalParticipant
from core.links import app_link, contract_route
from requests_reg import notifications as rn


def _card_link(contract) -> str:
    """Ссылка на карточку договора в приложении (для колокольчика и письма)."""
    return app_link(contract_route(contract.id))


def _label(contract) -> str:
    return f"{contract.number} · {contract.title}".strip(" ·")


def _details(contract) -> list[str]:
    lines = [f"Название: {contract.title}"]
    if contract.organization_id:
        lines.append(f"Юрлицо: {contract.organization.short_name}")
    if contract.cfo_id:
        lines.append(f"ЦФО: {contract.cfo.name}")
    if contract.amount is not None:
        lines.append(f"Сумма: {contract.amount}")
    flags = []
    if contract.is_nonstandard:
        flags.append("нестандартный")
    if contract.has_disagreement_protocol:
        flags.append("с протоколом разногласий")
    if flags:
        lines.append("Признаки: " + ", ".join(flags))
    if contract.comment:
        lines.append(f"Комментарий: {contract.comment}")
    if contract.crm_link:
        lines.append(f"CRM: {contract.crm_link}")
    return lines


def _approve_url(participant) -> str:
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if not base or participant is None:
        return ""
    if not participant.external_token:
        participant.external_token = get_random_string(24)
        participant.save(update_fields=["external_token"])
    return base + reverse("contract_external_approve", args=[participant.external_token])


def notify_current_approver(contract):
    """Тому, чья сейчас очередь согласовать (юр-этап — всем юристам)."""
    from . import services

    p = services.current_pending_participant(services.get_approval(contract))
    if p is None:
        return

    # что инициатор написал, направляя этот круг (например после доработки)
    note = flow.opening_note(p)
    if services.is_group_legal(p):
        # Групповой юр-этап: согласует любой юрист в приложении — без токен-ссылки.
        b24, emails = rn._recipients(rn.lawyer_b24_ids())
        lines = ["Требуется согласование юридического отдела.", "", *_details(contract)]
        if note:
            lines += ["", note]
        rn._dispatch(b24, emails, f"Договор {contract.number}: требуется юротдел",
                     "\n".join(lines), link=_card_link(contract))
        return

    approve_url = _approve_url(p)
    lines = ["Требуется ваше согласование договора.", "", *_details(contract)]
    if note:
        lines += ["", note]
    if approve_url:
        lines += ["", f"Перейти к согласованию: {approve_url}"]
    body = "\n".join(lines)
    subject = f"Согласование договора {contract.number}: {contract.title}"

    if p.type == ApprovalParticipant.TYPE_INTERNAL and p.b24_user_id:
        b24, emails = rn._recipients([p.b24_user_id])
        rn._dispatch(b24, emails, subject, body, link=_card_link(contract))
    elif p.email:
        bid = rn._b24_by_email(p.email)
        rn._dispatch([bid] if bid else [], [p.email], subject, body,
                     link=_card_link(contract))


def notify_initiator_result(contract):
    """Инициатору — статус договора изменился (согласован/отклонён/возвращён)."""
    if not contract.initiator_b24_id:
        return
    b24, emails = rn._recipients([contract.initiator_b24_id])
    st = contract.status_label
    body = f"Статус договора изменился: {st}.\n\n" + "\n".join(_details(contract))
    rn._dispatch(b24, emails, f"Договор {contract.number}: {st}", body,
                 link=_card_link(contract), link_text="Открыть договор")
