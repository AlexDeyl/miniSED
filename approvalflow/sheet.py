"""
Формирование листа согласования в PDF (ТЗ п.7.7).

Лист — самостоятельный документ системы: номер, тип, объект, инициатор,
даты, все круги, решения согласующих с должностями/датами/комментариями,
итог. В будущем может уходить в 1С или прикладываться к документу в Диадоке.

Кириллица требует Unicode-TTF: ищем системный шрифт (Windows/Linux),
с запасным вариантом Helvetica (латиница).
"""

from __future__ import annotations

import io
import os

from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import Approval, ApprovalParticipant, ApprovalSheet

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]
_FONT_NAME = "SheetFont"
_font_ready = False


def _ensure_font() -> str:
    """Регистрирует Unicode-шрифт для кириллицы; иначе — Helvetica."""
    global _font_ready
    if _font_ready:
        return _FONT_NAME
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(_FONT_NAME, path))
                _font_ready = True
                return _FONT_NAME
            except Exception:
                continue
    return "Helvetica"


_DECISION_RU = {
    ApprovalParticipant.DECISION_WAITING: "Ожидает",
    ApprovalParticipant.DECISION_APPROVED: "Согласовано",
    ApprovalParticipant.DECISION_REJECTED: "Отклонено",
}


def _fmt(dt) -> str:
    if not dt:
        return "—"
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M")


def _name_maps(approval: Approval):
    """Карты b24_id→ФИО, b24_id→должность и email→ФИО из профилей."""
    from core.models import UserProfile

    bids, emails = set(), set()
    for rnd in approval.rounds.all():
        for p in rnd.participants.all():
            if p.b24_user_id:
                bids.add(p.b24_user_id)
            if p.email:
                emails.add(p.email.strip().lower())
    if approval.initiator_b24_id:
        bids.add(approval.initiator_b24_id)
    profiles = list(
        UserProfile.objects.filter(bitrix_id__in=bids).select_related("position")
    )
    by_bid = {u.bitrix_id: u.fio for u in profiles if u.fio}
    pos_by_bid = {u.bitrix_id: (u.position.name if u.position else "") for u in profiles}
    by_email = {
        u.email.strip().lower(): u.fio
        for u in UserProfile.objects.filter(email__in=emails) if u.fio
    }
    return by_bid, by_email, pos_by_bid


def _who(p: ApprovalParticipant, by_bid: dict, by_email: dict) -> str:
    """Кто согласующий. Групповой юрэтап без решения — «Юридический отдел»;
    после решения показываем конкретного юриста (в participant.b24_user_id
    записан тот, кто согласовал)."""
    if p.type == ApprovalParticipant.TYPE_INTERNAL:
        if p.role == "legal_dept" and not p.b24_user_id:
            return "Юридический отдел"
        if p.b24_user_id:
            return by_bid.get(p.b24_user_id) or f"USER #{p.b24_user_id}"
        return "—"
    return by_email.get((p.email or "").strip().lower()) or p.email or p.name or "участник"


def _pos(p: ApprovalParticipant, pos_by_bid: dict) -> str:
    if p.type == ApprovalParticipant.TYPE_INTERNAL and p.b24_user_id:
        return pos_by_bid.get(p.b24_user_id, "")
    return ""


def render_pdf(approval: Approval, *, role_names: dict | None = None) -> bytes:
    role_names = role_names or {}
    font = _ensure_font()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Лист согласования #{approval.pk}",
    )

    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName=font, fontSize=9, leading=12)
    h1 = ParagraphStyle("h1", parent=base, fontSize=15, spaceAfter=6)
    label = ParagraphStyle("label", parent=base, textColor=colors.HexColor("#5a6675"))

    by_bid, by_email, pos_by_bid = _name_maps(approval)

    story = []
    story.append(Paragraph("Лист согласования", h1))
    story.append(Paragraph(
        f"№ {approval.pk} · тип: {approval.approval_type} · "
        f"статус: {approval.get_status_display()}", label,
    ))
    story.append(Spacer(1, 6))

    # Шапка
    head_rows = [
        ["Название", approval.title or "—"],
        ["Инициатор", by_bid.get(approval.initiator_b24_id) or f"ID Б24 {approval.initiator_b24_id or '—'}"],
        ["Тип согласования", approval.get_flow_type_display()],
        ["Создано", _fmt(approval.created_at)],
        ["Отправлено", _fmt(approval.submitted_at)],
        ["Завершено", _fmt(approval.completed_at)],
    ]
    head = Table(
        [[Paragraph(k, label), Paragraph(v, base)] for k, v in head_rows],
        colWidths=[45 * mm, None],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(head)
    story.append(Spacer(1, 10))

    # Круги
    for rnd in approval.rounds.all():
        story.append(Paragraph(
            f"Круг {rnd.round_number} — {rnd.get_result_display()}"
            + (f" · завершён {_fmt(rnd.completed_at)}" if rnd.completed_at else ""),
            ParagraphStyle("rh", parent=base, fontSize=11, spaceBefore=6, spaceAfter=4),
        ))
        data = [["Согласующий", "Должность", "Роль", "Решение", "Дата", "Комментарий"]]
        for p in rnd.participants.all():
            data.append([
                Paragraph(_who(p, by_bid, by_email), base),
                Paragraph(_pos(p, pos_by_bid) or "—", base),
                Paragraph(role_names.get(p.role, p.role) or "—", base),
                Paragraph(_DECISION_RU.get(p.decision, p.decision), base),
                Paragraph(_fmt(p.decided_at), base),
                Paragraph(p.decision_comment or "—", base),
            ])
        table = Table(data, colWidths=[34 * mm, 28 * mm, 28 * mm, 20 * mm, 24 * mm, None])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c6ced9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)
        if rnd.comment:
            story.append(Paragraph(f"Комментарий круга: {rnd.comment}", label))
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Итоговый статус: {approval.get_status_display()}",
        ParagraphStyle("total", parent=base, fontSize=11),
    ))
    story.append(Paragraph(f"Сформировано: {_fmt(timezone.now())}", label))

    doc.build(story)
    return buffer.getvalue()


def generate_sheet(
    approval: Approval, *, generated_by_b24_id: int | None = None
) -> ApprovalSheet:
    """Формирует PDF-лист и сохраняет как ApprovalSheet."""
    pdf_bytes = render_pdf(approval)
    sheet = ApprovalSheet(
        approval=approval,
        format=ApprovalSheet.FORMAT_PDF,
        generated_by_b24_id=generated_by_b24_id,
    )
    sheet.generated_file.save(
        f"approval_{approval.pk}_{timezone.now():%Y%m%d_%H%M%S}.pdf",
        ContentFile(pdf_bytes),
        save=True,
    )
    return sheet
