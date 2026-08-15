"""
Бланк «Заявка на предоставление комплимента» (PDF) — по форме из ТЗ.

По требованию ТЗ итог процесса — заявка отдельным документом вместе с листом
согласования, поэтому лист подшивается сюда же (approvalflow.sheet.build_story),
без склейки файлов и лишних зависимостей.
"""

from __future__ import annotations

import io

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from approvalflow.sheet import _ensure_font, build_story

from . import constants


def _fmt_dt(dt) -> str:
    return timezone.localtime(dt).strftime("%d.%m.%Y %H:%M") if dt else "—"


def _fmt_date(dt) -> str:
    return timezone.localtime(dt).strftime("%d.%m.%Y") if dt else "—"


def _initiator_name(compliment) -> str:
    from core.models import UserProfile

    profile = UserProfile.objects.filter(bitrix_id=compliment.initiator_b24_id).first()
    return profile.fio if profile and profile.fio else f"ID Б24 {compliment.initiator_b24_id or '—'}"


def render_pdf(compliment, *, approval=None) -> bytes:
    """Бланк заявки; если передан approval — следом лист согласования."""
    font = _ensure_font()
    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName=font, fontSize=10, leading=13)
    bold_c = ParagraphStyle("bold_c", parent=base, fontSize=12, alignment=1)
    label = ParagraphStyle("label", parent=base, textColor=colors.HexColor("#5a6675"))
    section = ParagraphStyle("section", parent=base, fontSize=11, alignment=1)

    grid = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9aa4b0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])

    story = [
        Paragraph("Заявка на предоставление комплимента", bold_c),
        Spacer(1, 8),
    ]

    head = Table(
        [[Paragraph(f"<b>Дата составления:</b> {_fmt_date(compliment.created_at)}", base),
          Paragraph(f"<b>Номер:</b> {compliment.number}", base)]],
        colWidths=[None, 55 * mm],
    )
    head.setStyle(grid)
    story += [head, Spacer(1, 2)]

    guest = Table(
        [[Paragraph(f"<b>Ф.И.О. гостя:</b> {compliment.guest_name or '—'}", base),
          Paragraph(f"<b>Дополнительная информация:</b><br/>{compliment.description or '—'}", base)],
         [Paragraph(f"<b>Компания:</b> {compliment.company}", base), ""]],
        colWidths=[None, 80 * mm],
    )
    guest.setStyle(grid)
    story += [guest, Spacer(1, 2)]

    when = Table(
        [[Paragraph(f"<b>Дата и время:</b> {_fmt_dt(compliment.event_at)}", base),
          Paragraph(f"<b>Отель:</b> {compliment.facility.name if compliment.facility_id else '—'}", base)]],
        colWidths=[None, 80 * mm],
    )
    when.setStyle(grid)
    story += [when, Spacer(1, 2)]

    category = Table(
        [[Paragraph("Категория", section)],
         [Paragraph(
             f"{compliment.category_label}"
             + (f"<br/>{compliment.category_details}" if compliment.category_details else ""),
             base,
         )]],
    )
    category.setStyle(grid)
    story += [category, Spacer(1, 10)]

    story.append(Paragraph(f"Подразделение: {compliment.department or '—'}", base))
    story.append(Paragraph(f"Ф.И.О.: {_initiator_name(compliment)}", base))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Статус: {compliment.status_label}", label))

    if approval is not None:
        story.append(PageBreak())
        story += build_story(approval, role_names=constants.ROLE_NAMES)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Заявка на комплимент {compliment.number}",
    )
    doc.build(story)
    return buffer.getvalue()
