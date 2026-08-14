"""
Публичная страница согласования договора по токен-ссылке (без авторизации),
как у обычных согласований/заявок. По ссылке из письма согласующий открывает
страницу и принимает решение. Групповой юр-этап по токену не согласуется —
только сотрудником юротдела в приложении.
"""

from __future__ import annotations

from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from approvalflow.models import ApprovalParticipant

from . import services
from .models import Contract


def _resolve(token):
    participant = (
        ApprovalParticipant.objects.select_related("round__approval")
        .filter(external_token=token)
        .first()
    )
    if participant is None:
        return None, None
    obj = participant.round.approval.linked_object
    contract = obj if isinstance(obj, Contract) else None
    return participant, contract


def _ctx(request, participant, contract, **extra):
    docs = []
    if contract:
        for d in contract.documents.filter(deleted_at__isnull=True):
            cur = d.current_version
            if cur:
                docs.append({
                    "url": f"/api/documents/{d.id}/versions/{cur.id}/download/",
                    "name": d.title,
                })
    ctx = {
        "participant": participant,
        "contract": contract,
        "documents": docs,
        "already_decided": participant.decision != ApprovalParticipant.DECISION_WAITING,
    }
    ctx.update(extra)
    return ctx


@csrf_exempt
def contract_external_approve(request, token):
    participant, contract = _resolve(token)
    if participant is None or contract is None:
        return render(request, "contracts/external_not_found.html", status=404)
    # Групповой юр-этап по токену не согласуется — только юрист в приложении.
    if services.is_group_legal(participant):
        return render(request, "contracts/external_not_found.html", status=404)

    if request.method == "POST":
        if participant.decision != ApprovalParticipant.DECISION_WAITING:
            return render(request, "contracts/external_result.html",
                          _ctx(request, participant, contract))
        decision = request.POST.get("decision")
        comment = (request.POST.get("comment") or "").strip()
        if decision not in ("approve", "reject"):
            return render(request, "contracts/external_approve.html",
                          _ctx(request, participant, contract, error="Выберите решение."))
        if decision == "reject" and not comment:
            return render(request, "contracts/external_approve.html",
                          _ctx(request, participant, contract,
                               error="При отклонении комментарий обязателен.",
                               comment_value=comment))
        try:
            services.decide(contract, participant.id, decision, comment)
        except Exception as e:
            return render(request, "contracts/external_approve.html",
                          _ctx(request, participant, contract, error=str(e),
                               comment_value=comment))
        participant.refresh_from_db()
        contract.refresh_from_db()
        return render(request, "contracts/external_result.html",
                      _ctx(request, participant, contract))

    return render(request, "contracts/external_approve.html",
                  _ctx(request, participant, contract))
