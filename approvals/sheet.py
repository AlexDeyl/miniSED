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


def _versioned_documents(agreement: Agreement) -> list[dict]:
    """Версионируемые документы согласования (documents app) с историей версий."""
    from django.contrib.contenttypes.models import ContentType
    from documents.models import Document

    ct = ContentType.objects.get_for_model(Agreement)
    docs = Document.objects.filter(
        content_type=ct, object_id=agreement.pk, deleted_at__isnull=True
    ).prefetch_related("versions")
    out = []
    for d in docs:
        versions = [
            {
                "num": v.version_number,
                "at": v.uploaded_at,
                "by": v.uploaded_by_b24_id,
                "comment": v.change_comment,
                "is_current": v.is_current,
            }
            for v in d.versions.all().order_by("version_number")
        ]
        out.append({
            "title": d.title,
            "current": d.current_version.version_number if d.current_version else None,
            "versions": versions,
        })
    return out


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
    h3 = ParagraphStyle("h3", parent=base, fontSize=9.5, spaceBefore=6, spaceAfter=3,
                        textColor=colors.HexColor("#0b7f5f"))

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

    # Согласующие — с разбивкой по кругам (ТЗ п.7.4)
    story.append(Paragraph("Ход согласования по кругам", h2))
    parts = list(agreement.participants.all().order_by("round_number", "order_index"))
    rounds: dict[int, list] = {}
    for p in parts:
        rounds.setdefault(p.round_number, []).append(p)

    def _round_result(members: list) -> str:
        if any(m.status == Participant.STATUS_REJECTED for m in members):
            return "отклонён"
        if all(m.status == Participant.STATUS_APPROVED for m in members):
            return "согласован"
        return "в процессе"

    for rn in sorted(rounds):
        members = rounds[rn]
        suffix = " · текущий" if rn == agreement.current_round else ""
        story.append(Paragraph(
            f"Круг {rn} — {_round_result(members)}{suffix}", h3,
        ))
        data = [["Согласующий", "Решение", "Дата", "Комментарий"]]
        for p in members:
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

    # Документы и их версии (изменения документа, ТЗ п.7.1-7.3)
    vdocs = _versioned_documents(agreement)
    if vdocs:
        # доузнаём ФИО тех, кто загружал версии, но не значится в участниках
        missing = {v["by"] for d in vdocs for v in d["versions"] if v["by"] and v["by"] not in by_bid}
        if missing:
            from core.models import UserProfile
            for u in UserProfile.objects.filter(bitrix_id__in=missing):
                if u.fio:
                    by_bid[u.bitrix_id] = u.fio
        story.append(Paragraph("Документы и версии", h2))
        for d in vdocs:
            cur = f" · актуальная v{d['current']}" if d["current"] else ""
            story.append(Paragraph(f"{d['title']}{cur}", h3))
            vdata = [["Версия", "Дата", "Загрузил", "Изменения"]]
            for v in d["versions"]:
                who = by_bid.get(v["by"]) or (f"USER #{v['by']}" if v["by"] else "—")
                vdata.append([
                    Paragraph(f"v{v['num']}" + (" ✓" if v["is_current"] else ""), base),
                    Paragraph(_fmt(v["at"]), base),
                    Paragraph(who, base),
                    Paragraph(v["comment"] or "—", base),
                ])
            vtable = Table(vdata, colWidths=[20 * mm, 32 * mm, 40 * mm, None])
            vtable.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c6ced9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(vtable)

    # Прочие вложения (без версий)
    attachments = [d for d in agreement.documents.all() if (d.file or d.url)]
    if attachments:
        story.append(Paragraph("Прочие вложения", h2))
        for d in attachments:
            name = os.path.basename(d.file.name) if d.file else d.url
            story.append(Paragraph(f"• {name}", base))

    story.append(Spacer(1, 10))
    story.append(Paragraph(f"Сформировано: {_fmt(timezone.now())}", label))

    doc.build(story)
    return buffer.getvalue()
