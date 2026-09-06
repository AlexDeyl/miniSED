"""
Публичная страница согласования регламентной заявки по токен-ссылке.

По ссылке из письма участник (внешний ИЛИ внутренний) открывает страницу и
принимает решение — без входа в Битрикс. Решение проводится через
services.decide (actor_b24_id=None → проверку личности обычного слота не
навязываем; групповой юрэтап по токену не согласуется — только сотрудником
юротдела в приложении).
"""

from __future__ import annotations

from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from approvalflow.models import ApprovalParticipant

from . import services
from .models import RegulatoryRequest


def _resolve(token):
    participant = (
        ApprovalParticipant.objects.select_related("round__approval")
        .filter(external_token=token)
        .first()
    )
    if participant is None:
        return None, None
    approval = participant.round.approval
    req = approval.linked_object
    if not isinstance(req, RegulatoryRequest):
        req = None
    return participant, req


def _documents(participant, card):
    """Документы карточки для внешней страницы — со ссылкой по токену."""
    if card is None:
        return []
    docs = []
    for d in card.documents.filter(deleted_at__isnull=True):
        if d.current_version and d.current_version.file:
            docs.append({
                "url": f"/external/doc/{participant.external_token}/{d.id}/",
                "name": d.title or d.current_version.original_filename or "Документ",
            })
    return docs


def _ctx(request, participant, req, **extra):
    ctx = {
        "participant": participant,
        "req": req,
        # Файл лежит на ВЕРСИИ документа, а не на самом документе: раньше тут
        # проверялось несуществующее поле Document.file, и список документов на
        # внешней странице всегда оказывался пустым — участник согласовывал
        # вслепую. Ссылка ведёт на просмотр по токену (documents.public_views).
        "documents": _documents(participant, req),
        "already_decided": participant.decision != ApprovalParticipant.DECISION_WAITING,
    }
    ctx.update(extra)
    return ctx


@csrf_exempt
def reg_external_approve(request, token):
    participant, req = _resolve(token)
    if participant is None or req is None:
        return render(request, "requests_reg/external_not_found.html", status=404)

    if request.method == "POST":
        if participant.decision != ApprovalParticipant.DECISION_WAITING:
            return render(request, "requests_reg/external_result.html",
                          _ctx(request, participant, req))
        decision = request.POST.get("decision")
        comment = (request.POST.get("comment") or "").strip()
        if decision not in ("approve", "reject"):
            return render(request, "requests_reg/external_approve.html",
                          _ctx(request, participant, req,
                               error="Выберите решение."))
        if decision == "reject" and not comment:
            return render(request, "requests_reg/external_approve.html",
                          _ctx(request, participant, req,
                               error="При отклонении комментарий обязателен.",
                               comment_value=comment))
        try:
            services.decide(req, participant.id, decision, comment)
        except Exception as e:
            return render(request, "requests_reg/external_approve.html",
                          _ctx(request, participant, req, error=str(e),
                               comment_value=comment))
        participant.refresh_from_db()
        req.refresh_from_db()
        return render(request, "requests_reg/external_result.html",
                      _ctx(request, participant, req))

    return render(request, "requests_reg/external_approve.html",
                  _ctx(request, participant, req))
