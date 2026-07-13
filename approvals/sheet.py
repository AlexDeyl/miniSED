"""
Лист согласования для старого движка (Agreement) — PDF с выгрузкой (ТЗ п.7.7).

Собирается из данных согласования: участники, их решения, история (DecisionLog),
документы, итоговый статус. Шрифт-хелпер переиспользуем из approvalflow.sheet.
"""

from __future__ import annotations

import io
import os

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from approvalflow.sheet import _ensure_font
from .models import Agreement, Participant

STATUS_RU = {
    Agreement.STATUS_DRAFT: "Черновик",
    Agreement.STATUS_IN_PROGRESS: "В работе",
    Agreement.STATUS_COMPLETED: "Согласован",
    Agreement.STATUS_REJECTED: "Отклонён",
    Agreement.STATUS_CANCELED: "Отменено",
}
DEC_RU = {
    Participant.STATUS_WAITING: "Ожидает",
    Participant.STATUS_APPROVED: "Согласовано",
    Participant.STATUS_REJECTED: "Отклонено",
}


def _fmt(dt) -> str:
    if not dt:
        return "—"
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M")


def _name_maps(agreement: Agreement):
    """
    Карты «ID Б24 → ФИО» и «email → ФИО» из профилей пользователей
    (UserProfile связывает почту и Bitrix ID). Один запрос на каждую карту.
    """
    from core.models import UserProfile

    parts = list(agreement.participants.all())
    bids = {p.b24_user_id for p in parts if p.b24_user_id}
    if agreement.author_b24_id:
        bids.add(agreement.author_b24_id)
    emails = {p.email.strip().lower() for p in parts if p.email}

    by_bid = {
        u.bitrix_id: u.fio
        for u in UserProfile.objects.filter(bitrix_id__in=bids)
        if u.fio
    }
    by_email = {
        u.email.strip().lower(): u.fio
        for u in UserProfile.objects.filter(email__in=emails)
        if u.fio
    }
    return by_bid, by_email


def _pname(p: Participant, by_bid: dict, by_email: dict) -> str:
    """Имя согласующего: ФИО из профиля, иначе — фолбэк на ID/email."""
    if p.type == Participant.TYPE_INTERNAL and p.b24_user_id:
        return by_bid.get(p.b24_user_id) or f"USER #{p.b24_user_id}"
    if p.email:
        return by_email.get(p.email.strip().lower()) or p.email
    return p.name or "участник"


def _initiator_name(agreement: Agreement, by_bid: dict) -> str:
    if agreement.author_b24_id and agreement.author_b24_id in by_bid:
        return by_bid[agreement.author_b24_id]
    return f"ID Б24 {agreement.author_b24_id}"


def render_pdf(agreement: Agreement) -> bytes:
    font = _ensure_font()
    by_bid, by_email = _name_maps(agreement)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Лист согласования #{agreement.id}",
    )
    styles = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=styles["Normal"], fontName=font, fontSize=9, leading=12)
    label = ParagraphStyle("l", parent=base, textColor=colors.HexColor("#5a6675"))
    h1 = ParagraphStyle("h1", parent=base, fontSize=15, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=base, fontSize=11, spaceBefore=10, spaceAfter=4)

    story = []
    story.append(Paragraph("Лист согласования", h1))
    story.append(Paragraph(f"№ {agreement.id} · {agreement.title}", label))
    story.append(Spacer(1, 6))

    head = Table(
        [[Paragraph(k, label), Paragraph(v, base)] for k, v in [
            ("Инициатор", _initiator_name(agreement, by_bid)),
            ("Тип", "Параллельное" if agreement.flow_type == Agreement.FLOW_PARALLEL else "Последовательное"),
            ("Сумма", str(agreement.amount) if agreement.amount is not None else "—"),
            ("Дедлайн", str(agreement.deadline) if agreement.deadline else "—"),
            ("Создано", _fmt(agreement.created_at)),
            ("Итоговый статус", STATUS_RU.get(agreement.status, agreement.status)),
        ]],
        colWidths=[45 * mm, None],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(head)

    # Участники и решения
    story.append(Paragraph("Согласующие", h2))
    data = [["Согласующий", "Решение", "Дата", "Комментарий"]]
    for p in agreement.participants.all().order_by("round_number", "order_index"):
        data.append([
            Paragraph(_pname(p, by_bid, by_email), base),
            Paragraph(DEC_RU.get(p.status, p.status), base),
            Paragraph(_fmt(p.decided_at), base),
            Paragraph(p.comment or "—", base),
        ])
    table = Table(data, colWidths=[45 * mm, 28 * mm, 32 * mm, None])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c6ced9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)

    # История решений
    logs = agreement.decision_logs.all().order_by("decided_at")
    if logs:
        story.append(Paragraph("История согласования", h2))
        for log in logs:
            story.append(Paragraph(
                f"{_pname(log.participant, by_bid, by_email)} — {DEC_RU.get(log.status, log.status)} · {_fmt(log.decided_at)}"
                + (f" · {log.comment}" if log.comment else ""),
                base,
            ))

    # Документы
    docs = [d for d in agreement.documents.all() if (d.file or d.url)]
    if docs:
        story.append(Paragraph("Документы", h2))
        for d in docs:
            name = os.path.basename(d.file.name) if d.file else d.url
            story.append(Paragraph(f"• {name}", base))

    story.append(Spacer(1, 10))
    story.append(Paragraph(f"Сформировано: {_fmt(timezone.now())}", label))

    doc.build(story)
    return buffer.getvalue()
