"""
Логика регламентных заявок. Согласование делегируется движку approvalflow,
поэтому здесь только специфика заявок: создание, номер, синхронизация статуса
и жизненный цикл выпуска (в работе → выпущена/оформлена → закрыта).
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from approvalflow import services as flow
from approvalflow.models import Approval

from . import constants
from .models import RegulatoryRequest


class RequestError(Exception):
    pass


def create_request(*, request_type: str, organization, **fields) -> RegulatoryRequest:
    if request_type not in constants.REQUEST_TYPES:
        raise RequestError(f"Неизвестный тип заявки: {request_type}")
    req = RegulatoryRequest.objects.create(
        request_type=request_type, organization=organization, **fields
    )
    # номер вида ЭЦП-000123
    req.number = f"{constants.number_prefix(request_type)}-{req.pk:06d}"
    req.save(update_fields=["number"])
    return req


def get_approval(request: RegulatoryRequest) -> Approval | None:
    ct = ContentType.objects.get_for_model(RegulatoryRequest)
    return (
        Approval.objects.filter(content_type=ct, object_id=request.pk)
        .order_by("-id")
        .first()
    )


def _sync_status(request: RegulatoryRequest) -> None:
    """Отражает статус связанного согласования в статусе заявки."""
    approval = get_approval(request)
    if approval is None:
        return
    mapping = {
        Approval.STATUS_IN_PROGRESS: constants.STATUS_ON_APPROVAL,
        Approval.STATUS_COMPLETED: constants.STATUS_APPROVED,
        Approval.STATUS_REJECTED: constants.STATUS_REJECTED,
        Approval.STATUS_RETURNED: constants.STATUS_RETURNED,
    }
    new_status = mapping.get(approval.status)
    if new_status and request.status != new_status:
        request.status = new_status
        request.save(update_fields=["status", "updated_at"])


@transaction.atomic
def submit(request: RegulatoryRequest, participants: list[dict], *, flow_type=None):
    """Отправляет заявку на согласование: создаёт Approval и открывает круг №1."""
    if request.status not in (constants.STATUS_DRAFT, constants.STATUS_RETURNED):
        raise RequestError("Отправить можно только черновик или возвращённую заявку.")

    approval = get_approval(request)
    if approval is None:
        approval = Approval.objects.create(
            approval_type=f"reg_{request.request_type}",
            title=f"{request.get_request_type_display()} — {request.subject_name}".strip(" —"),
            flow_type=flow_type or Approval.FLOW_SEQUENTIAL,
            initiator_b24_id=request.initiator_b24_id,
            linked_object=request,
        )
        flow.submit(approval, participants)
    else:
        flow.start_new_round(approval, participants)

    _sync_status(request)
    return approval


@transaction.atomic
def decide(request: RegulatoryRequest, participant_id, decision, comment=""):
    approval = get_approval(request)
    if approval is None:
        raise RequestError("Заявка не отправлена на согласование.")
    from approvalflow.models import ApprovalParticipant

    try:
        participant = ApprovalParticipant.objects.get(
            id=participant_id, round__approval=approval
        )
    except ApprovalParticipant.DoesNotExist:
        raise RequestError("Участник не найден.")
    flow.decide(participant, decision, comment)
    _sync_status(request)
    return participant


@transaction.atomic
def return_for_revision(request: RegulatoryRequest, *, by_b24_id=None, comment=""):
    approval = get_approval(request)
    if approval is None:
        raise RequestError("Заявка не на согласовании.")
    flow.return_for_revision(approval, by_b24_id=by_b24_id, comment=comment)
    _sync_status(request)


# --- жизненный цикл выпуска (после согласования) ---
def _set_status(request, status):
    request.status = status
    request.save(update_fields=["status", "updated_at"])


def mark_in_work(request: RegulatoryRequest):
    if request.status != constants.STATUS_APPROVED:
        raise RequestError("В работу можно взять только согласованную заявку.")
    _set_status(request, constants.STATUS_IN_WORK)


def mark_issued(request: RegulatoryRequest):
    if request.status not in (constants.STATUS_APPROVED, constants.STATUS_IN_WORK):
        raise RequestError("Выпустить можно согласованную заявку или заявку в работе.")
    _set_status(request, constants.STATUS_ISSUED)


def close(request: RegulatoryRequest):
    if request.status == constants.STATUS_CLOSED:
        raise RequestError("Заявка уже закрыта.")
    _set_status(request, constants.STATUS_CLOSED)
