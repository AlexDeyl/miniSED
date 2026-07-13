"""
Генерация заполненного PDF-заявления на оформление доверенности/МЧД (ТЗ).

Это тот самый документ, который в заполненном виде получают юристы. Данные
берутся из анкеты (RegulatoryRequest.data), выбранные полномочия — из матрицы
шаблонов (PowerTemplate). Верстка повторяет структуру бумажной формы.
"""

from __future__ import annotations

import io

from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from approvalflow.sheet import _ensure_font
from . import constants as C
from .models import PowerTemplate


import re


def _fmt_date(v) -> str:
    """ГГГГ-ММ-ДД (из HTML-инпутов) → ДД.ММ.ГГГГ."""
    if not v:
        return "__.__.____"
    s = str(v)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return s


# ■/□ надёжно есть в системных шрифтах (в отличие от ☑, который в Arial нет).
def _checks(choices, selected: list[str]) -> str:
    """Список опций с отметкой выбранных (жирным)."""
    selected = set(selected or [])
    parts = []
    for code, name in choices:
        if code in selected:
            parts.append(f"■ <b>{name}</b>")
        else:
            parts.append(f"□ {name}")
    return "<br/>".join(parts)


def _one(choices, code: str) -> str:
    return _checks(choices, [code] if code else [])


def _initiator_name(request) -> str:
    """ФИО инициатора из профиля (заводится админом); иначе — ID Б24."""
    from core.models import UserProfile

    if request.initiator_b24_id:
        p = UserProfile.objects.filter(bitrix_id=request.initiator_b24_id).first()
        if p and p.fio:
            return p.fio
    return f"ID Б24 {request.initiator_b24_id or '—'}"


def render_pdf(request) -> bytes:
    font = _ensure_font()
    data = request.data or {}
    rep = data.get("rep", {}) or {}
    legal = data.get("rep_legal", {}) or {}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Заявление {request.number}",
    )
    styles = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=styles["Normal"], fontName=font, fontSize=9, leading=12)
    label = ParagraphStyle("l", parent=base, textColor=colors.HexColor("#5a6675"))
    h1 = ParagraphStyle("h1", parent=base, fontSize=14, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base, fontSize=11, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#0b7f5f"))

    def kv_table(rows):
        t = Table(
            [[Paragraph(k, label), Paragraph(v, base)] for k, v in rows],
            colWidths=[55 * mm, None],
        )
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#eeeeee")),
        ]))
        return t

    story = []
    story.append(Paragraph("ЗАЯВКА на оформление доверенности", h1))
    story.append(Paragraph(
        f"№ {request.number} · подана {request.created_at:%d.%m.%Y} · "
        f"{request.organization.short_name}", label,
    ))
    story.append(Spacer(1, 6))

    # Шапка
    story.append(kv_table([
        ("Тип доверенности", _one(C.ANKETA_POA_TYPES, data.get("poa_type"))),
        ("Планируемая дата получения", _fmt_date(data.get("planned_date"))),
        ("Срочность", _one(C.ANKETA_URGENCY, data.get("urgency"))),
    ]))

    # Раздел 1
    story.append(Paragraph("Раздел 1. Сведения о представителе", h2))
    story.append(kv_table([
        ("ФИО", " ".join(filter(None, [rep.get("last_name"), rep.get("first_name"), rep.get("middle_name")])) or request.subject_name or "—"),
        ("Дата рождения", _fmt_date(rep.get("birth_date"))),
        ("Статус", _one(C.ANKETA_REP_STATUS, rep.get("status"))),
        ("Должность", rep.get("position") or request.position or "—"),
        ("Телефон", rep.get("phone") or "—"),
        ("Email", rep.get("email") or "—"),
        ("Паспорт (серия, №)", rep.get("passport") or "—"),
        ("Кем и когда выдан", " · ".join(filter(None, [rep.get("passport_issued_by"), rep.get("passport_issue_date")])) or "—"),
        ("Адрес регистрации", rep.get("reg_address") or "—"),
    ]))
    if any(legal.values()):
        story.append(kv_table([
            ("Юр. лицо (наименование)", legal.get("name") or "—"),
            ("ОГРН / ИНН / КПП", " / ".join(filter(None, [legal.get("ogrn"), legal.get("inn"), legal.get("kpp")])) or "—"),
            ("Юридический адрес", legal.get("address") or "—"),
            ("Действует от имени юр.лица", legal.get("acting_person") or "—"),
        ]))

    # Раздел 2
    story.append(Paragraph("Раздел 2. Полномочия и цель выдачи", h2))
    story.append(kv_table([
        ("Куда направляется представитель", data.get("target_org") or "—"),
        ("Перечень полномочий", _checks(C.ANKETA_POWERS, data.get("powers"))),
    ]))
    if data.get("powers_other"):
        story.append(Paragraph(f"Иные полномочия: {data['powers_other']}", base))

    codes = data.get("power_templates") or []
    if codes:
        tpls = PowerTemplate.objects.filter(code__in=codes)
        story.append(Paragraph("Шаблоны полномочий (матрица):", label))
        for t in tpls:
            story.append(Paragraph(f"<b>{t.code} — {t.name}</b>: {t.powers}", base))
            story.append(Spacer(1, 2))

    term = data.get("term_type")
    term_str = C.label(C.ANKETA_TERM, term)
    if term == "period":
        term_str += f": с {_fmt_date(data.get('term_from'))} по {_fmt_date(data.get('term_to'))}"
    story.append(kv_table([
        ("Право передоверия", _one(C.ANKETA_PEREDOVERIE, data.get("peredoverie"))),
        ("Срок действия", term_str),
    ]))

    # Раздел 3
    story.append(Paragraph("Раздел 3. Дополнительные сведения", h2))
    story.append(kv_table([
        ("Форма доверенности", _one(C.ANKETA_FORMS, data.get("form"))),
        ("Приложения к заявке", _checks(C.ANKETA_ATTACHMENTS, data.get("attachments"))),
        ("Способ получения готовой", _one(C.ANKETA_RECEIVE, data.get("receive"))),
    ]))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"Инициатор: {_initiator_name(request)} · "
        f"Сформировано: {timezone.localtime(timezone.now()):%d.%m.%Y %H:%M}", label,
    ))

    doc.build(story)
    return buffer.getvalue()


def generate_and_attach(request):
    """
    Формирует PDF-заявление и прикрепляет его к заявке как документ
    (актуальная версия). Так юристы всегда видят заполненную анкету в PDF.
    """
    from documents import services as docsvc
    from documents.models import Document

    pdf = render_pdf(request)
    doc = (
        request.documents.filter(document_type="anketa", deleted_at__isnull=True).first()
    )
    if doc is None:
        doc = docsvc.create_document(
            title="Заявление (анкета)", document_type="anketa",
            linked_object=request, created_by_b24_id=request.initiator_b24_id,
        )
    docsvc.add_version(
        doc, ContentFile(pdf, name=f"anketa_{request.number}.pdf"),
        uploaded_by_b24_id=request.initiator_b24_id, change_comment="Автоформирование анкеты",
    )
    return doc
