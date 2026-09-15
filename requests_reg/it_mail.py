"""
Письмо ИТ-отделу объекта по согласованной заявке на ЭЦП.

Колокольчик и короткое письмо ИТ-специалисту (notifications.notify_it_queue)
зовут человека в приложение. Здесь другое: ИТ-отдел объекта получает на свой
ящик комплект, с которым можно работать не заходя в MiniSED — все данные
заявления в тексте письма, оно же PDF-вложением, файлы, приложенные
инициатором, и лист согласования.

Адресат — почта ИТ-отдела ОБЪЕКТА заявки (Facility.it_email): заявка отеля
Введенский уходит в ИТ Введенского. Если у объекта адрес не заполнен (или
объект в заявке не указан) — settings.IT_DEPT_FALLBACK_EMAIL, иначе письмо
ушло бы в никуда.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from core.links import app_link, request_route

from . import constants as C

SUBJECT_MARK = "Заявка на создание ЭЦП"

_SPLIT_RE = re.compile(r"[,;\s]+")


# --- адресаты ----------------------------------------------------------------
def _split_emails(raw: str) -> list[str]:
    return [e for e in _SPLIT_RE.split((raw or "").strip()) if "@" in e]


def recipients(request) -> list[str]:
    """Почты ИТ-отдела объекта; фолбэк — общий адрес из настроек."""
    raw = getattr(request.facility, "it_email", "") if request.facility_id else ""
    emails = _split_emails(raw)
    if not emails:
        emails = _split_emails(getattr(settings, "IT_DEPT_FALLBACK_EMAIL", ""))
    # порядок сохраняем (кому адресовано в первую очередь), дубли убираем
    seen, out = set(), []
    for e in emails:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# --- текст письма ------------------------------------------------------------
def _date(v) -> str:
    """ГГГГ-ММ-ДД из HTML-инпута → ДД.ММ.ГГГГ."""
    if not v:
        return "—"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(v))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(v)


def _one(choices, code) -> str:
    return C.label(choices, code) if code else "—"


def _many(choices, codes) -> str:
    names = C.labels(choices, codes)
    return "; ".join(names) if names else "—"


def _initiator(request) -> str:
    from core.models import UserProfile

    if request.initiator_b24_id:
        p = UserProfile.objects.filter(bitrix_id=request.initiator_b24_id).first()
        if p and p.fio:
            pos = p.position.name if p.position_id else ""
            contacts = " · ".join(filter(None, [p.email, p.phone]))
            return " · ".join(filter(None, [f"{pos} {p.fio}".strip(), contacts]))
    return f"ID Б24 {request.initiator_b24_id or '—'}"


def _section(title: str, rows) -> list[str]:
    """Секция «ключ: значение». Пустые печатаем прочерком: в письме должно быть
    видно, что поле не заполнено, а не что его потеряли по дороге."""
    out = [title, "-" * len(title)]
    for k, v in rows:
        out.append(f"{k}: {v if v not in (None, '') else '—'}")
    out.append("")
    return out


def _route_lines(request) -> list[str]:
    """Кто и когда согласовал — то же, что в листе согласования, коротко."""
    from approvalflow.sheet import _DECISION_RU, _name_maps, _who

    from . import services

    approval = services.get_approval(request)
    if approval is None:
        return ["Согласование: заявка передана без круга согласования.", ""]
    by_bid, by_email, _pos = _name_maps(approval)
    title = "Лист согласования"
    lines = [title, "-" * len(title)]
    for rnd in approval.rounds.all():
        for p in rnd.participants.all():
            when = (
                timezone.localtime(p.decided_at).strftime("%d.%m.%Y %H:%M")
                if p.decided_at else "—"
            )
            role = C.ROLE_NAMES.get(p.role, p.role or "")
            comment = f" · {p.decision_comment}" if p.decision_comment else ""
            lines.append(
                f"- {_who(p, by_bid, by_email)}"
                + (f" ({role})" if role else "")
                + f" — {_DECISION_RU.get(p.decision, p.decision)}, {when}{comment}"
            )
    lines.append("")
    return lines


def build_subject(request) -> str:
    parts = [SUBJECT_MARK, request.number or f"#{request.pk}"]
    if request.facility_id:
        parts.append(request.facility.name)
    if request.subject_name:
        parts.append(request.subject_name)
    return " — ".join(parts)


def build_body(request) -> str:
    data = request.data or {}
    rep = data.get("rep", {}) or {}
    legal = data.get("rep_legal", {}) or {}

    lines = [
        SUBJECT_MARK.upper(),
        "",
        "Заявка согласована и передана ИТ-отделу на исполнение.",
        "Во вложении: заявление (PDF), лист согласования (PDF) и файлы, "
        "приложенные инициатором.",
        "",
    ]
    lines += _section("Заявка", [
        ("Номер", request.number),
        ("Дата подачи", timezone.localtime(request.created_at).strftime("%d.%m.%Y %H:%M")),
        ("Организация", request.organization.short_name if request.organization_id else ""),
        ("Объект", request.facility.name if request.facility_id else ""),
        ("ЦФО", request.cfo.name if request.cfo_id else ""),
        ("Инициатор", _initiator(request)),
        ("Тип ЭЦП", data.get("ecp_type")),
        ("Планируемая дата получения", _date(data.get("planned_date"))),
        ("Срочность", _one(C.ANKETA_URGENCY, data.get("urgency"))),
    ])
    lines += _section("Сотрудник, на которого оформляется ЭЦП", [
        ("ФИО", " ".join(filter(None, [
            rep.get("last_name"), rep.get("first_name"), rep.get("middle_name"),
        ])) or request.subject_name),
        ("Дата рождения", _date(rep.get("birth_date"))),
        ("Должность", rep.get("position") or request.position),
        ("Подразделение", request.department),
        ("Статус", _one(C.ANKETA_REP_STATUS, rep.get("status"))),
        ("ИНН", rep.get("inn")),
        ("СНИЛС", rep.get("snils")),
        ("Телефон", rep.get("phone")),
        ("Email", rep.get("email")),
        ("Паспорт (серия, №)", rep.get("passport")),
        ("Код подразделения", rep.get("passport_department_code")),
        ("Кем и когда выдан", " · ".join(filter(None, [
            rep.get("passport_issued_by"), _date(rep.get("passport_issue_date")),
        ]))),
        ("Адрес регистрации", rep.get("reg_address")),
    ])
    if any(legal.values()):
        lines += _section("Юридическое лицо представителя", [
            ("Наименование", legal.get("name")),
            ("ОГРН / ИНН / КПП", " / ".join(filter(None, [
                legal.get("ogrn"), legal.get("inn"), legal.get("kpp"),
            ]))),
            ("Юридический адрес", legal.get("address")),
            ("Действует от имени юр.лица", legal.get("acting_person")),
        ])
    lines += _section("Дополнительные сведения", [
        ("Основание оформления", request.basis),
        ("Приложения к заявке", _many(C.ANKETA_ECP_ATTACHMENTS, data.get("attachments"))),
        ("Способ получения ЭЦП", _one(C.ANKETA_ECP_RECEIVE, data.get("receive"))),
        ("Комментарий инициатора", request.comment),
    ])
    lines += _route_lines(request)

    link = app_link(request_route(request.id))
    if link:
        lines += [f"Карточка заявки в MiniSED: {link}", ""]
    return "\n".join(lines)


# --- вложения ----------------------------------------------------------------
def _sheet_pdf(request):
    """Лист согласования PDF. None, если круга не было или сборка не удалась:
    письмо с заявлением важнее листа."""
    from approvalflow import sheet as flow_sheet

    from . import services

    approval = services.get_approval(request)
    if approval is None:
        return None
    try:
        return flow_sheet.render_pdf(approval, role_names=C.ROLE_NAMES)
    except Exception as e:  # pragma: no cover
        print("[it_mail] sheet error:", e)
        return None


def _doc_attachments(request):
    """(имя, байты, mime) по живым документам заявки: заявление-анкета и файлы
    инициатора. Анкету ставим первой — это главный документ письма."""
    docs = list(
        request.documents.filter(deleted_at__isnull=True).select_related("current_version")
    )
    docs.sort(key=lambda d: (d.document_type != "anketa", d.id))
    out = []
    for doc in docs:
        ver = doc.current_version
        if ver is None or not ver.file:
            continue
        try:
            ver.file.open("rb")
            content = ver.file.read()
            ver.file.close()
        except Exception as e:  # файл мог не доехать при переносе — письмо не роняем
            print("[it_mail] file error:", doc.id, e)
            continue
        name = ver.original_filename or ver.file.name.rsplit("/", 1)[-1]
        out.append((name, content, ver.mime_type or "application/octet-stream"))
    return out


def build_attachments(request):
    """(вложения, имена тех, что не влезли в лимит размера письма)."""
    limit = int(getattr(settings, "IT_MAIL_MAX_ATTACH_MB", 20)) * 1024 * 1024
    items = _doc_attachments(request)
    sheet = _sheet_pdf(request)
    if sheet:
        items.append((
            f"Лист_согласования_{request.number or request.pk}.pdf",
            sheet, "application/pdf",
        ))
    attached, skipped, total = [], [], 0
    for name, content, mime in items:
        if total + len(content) > limit:
            skipped.append(name)
            continue
        total += len(content)
        attached.append((name, content, mime))
    return attached, skipped


# --- отправка ----------------------------------------------------------------
def send_to_it_department(request) -> bool:
    """Шлёт письмо; False, если адресата нет или отправка не удалась."""
    to = recipients(request)
    if not to:
        print("[it_mail] нет адреса ИТ-отдела для заявки", request.number)
        return False

    body = build_body(request)
    attached, skipped = build_attachments(request)
    if skipped:
        body += (
            "\nНе вложены из-за размера письма (скачайте в карточке заявки): "
            + ", ".join(skipped) + "\n"
        )

    msg = EmailMessage(
        subject=build_subject(request), body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None), to=to,
    )
    for name, content, mime in attached:
        msg.attach(name, content, mime)
    try:
        msg.send(fail_silently=False)
    except Exception as e:
        print("[it_mail] send error:", e)
        return False
    return True
