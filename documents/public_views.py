"""
Просмотр документа по токен-ссылке — для участника, который согласует из письма.

Зачем. Участник получает письмо со ссылкой на страницу согласования и должен
видеть то, что подписывает. Раньше файл на этой странице отдавался обычным
API документов, а он требует заголовок X-B24-User: браузер, открывший ссылку
из почты, его не шлёт, поэтому вместо документа приходил отказ — и решение
принималось вслепую либо человек шёл искать карточку в приложении руками.
Вход в приложение в соседней вкладке не помогал: личность передаётся
заголовком, а не cookie, и обычный переход по ссылке его не несёт.

Безопасность. Доступ даёт тот же одноразовый токен участника, которым он и
согласует, — то есть чтение здесь строго СЛАБЕЕ того, что ссылка уже
позволяет (принять решение за подписью). Сверх этого:
  * документ обязан принадлежать ИМЕННО той карточке, к которой выдан токен, —
    перебор чужих id по этой ссылке ничего не даёт;
  * удалённые (soft delete) документы не отдаются;
  * файл отдаётся инлайн и только на чтение, ничего не меняя.

Иначе говоря, ссылка из письма открывает ровно один комплект документов —
свой, — и живёт ровно столько, сколько сама страница согласования.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.http import FileResponse, Http404

from .models import Document


def _card_by_token(token: str):
    """Карточка, к которой выдан токен: заявка, договор, комплимент или
    согласование старого движка. None — токен не найден."""
    if not token:
        return None

    from approvalflow.models import ApprovalParticipant

    participant = (
        ApprovalParticipant.objects.select_related("round__approval")
        .filter(external_token=token)
        .first()
    )
    if participant is not None:
        return participant.round.approval.linked_object

    # Старый движок согласований — свои участники со своими токенами.
    from approvals.models import Participant

    legacy = (
        Participant.objects.select_related("agreement").filter(external_token=token).first()
    )
    return legacy.agreement if legacy is not None else None


def _file_response(file, filename: str):
    """Инлайн: PDF и картинки открываются прямо в браузере, а не скачиваются —
    человеку нужно ПОСМОТРЕТЬ документ, а не забрать его."""
    return FileResponse(file.open("rb"), as_attachment=False, filename=filename)


def external_document(request, token, doc_id):
    """Актуальная версия документа карточки (приложение documents)."""
    card = _card_by_token(token)
    if card is None:
        raise Http404()

    doc = Document.objects.filter(
        id=doc_id,
        deleted_at__isnull=True,
        content_type=ContentType.objects.get_for_model(card.__class__),
        object_id=card.pk,
    ).first()
    if doc is None or doc.current_version is None or not doc.current_version.file:
        raise Http404()

    version = doc.current_version
    return _file_response(
        version.file, version.original_filename or f"document_{doc.id}.bin"
    )


def external_agreement_file(request, token, doc_id):
    """Файл согласования старого движка (approvals.AgreementDocument).

    У него нет версий и он лежит в media; отдаём его так же по токену, чтобы
    страница согласования не зависела от того, открыт ли media наружу."""
    from approvals.models import Agreement, AgreementDocument

    card = _card_by_token(token)
    if not isinstance(card, Agreement):
        raise Http404()

    doc = AgreementDocument.objects.filter(id=doc_id, agreement=card).first()
    if doc is None or not doc.file:
        raise Http404()

    return _file_response(doc.file, doc.file.name.rsplit("/", 1)[-1])
