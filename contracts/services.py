"""
Логика согласования договоров.

Один этап — согласование через движок approvalflow (последовательный маршрут).
Маршрут строится по правилам (routing.build_route); ручной выбор согласующего
для нераспознанных ролей фиксируется в аудите. Юр-исполнения (как у заявок на
доверенность) здесь нет — договор проходит маршрут и становится «Согласован».
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from approvalflow import services as flow
from approvalflow.models import Approval, ApprovalParticipant
from core.auth import is_lawyer
from core.services import log_action

from . import constants, routing
from .models import Contract


class ContractError(Exception):
    pass


def _notify(event: str, contract: Contract) -> None:
    """Уведомление после commit (best-effort, не ломает флоу)."""
    def run():
        try:
            from . import notifications

            getattr(notifications, event)(contract)
        except Exception as e:  # pragma: no cover
            print("[contracts notify] error:", e)

    transaction.on_commit(run)


def create_contract(*, organization, **fields) -> Contract:
    contract = Contract.objects.create(organization=organization, **fields)
    contract.number = f"{constants.NUMBER_PREFIX}-{contract.pk:06d}"
    contract.save(update_fields=["number"])
    return contract


def get_approval(contract: Contract) -> Approval | None:
    ct = ContentType.objects.get_for_model(Contract)
    return (
        Approval.objects.filter(content_type=ct, object_id=contract.pk)
        .order_by("-id")
        .first()
    )


def build_route(contract: Contract) -> list[dict]:
    """Предпросмотр маршрута (для инициатора до отправки)."""
    return routing.build_route(contract)


def _set(contract: Contract, status: str) -> None:
    contract.status = status
    contract.save(update_fields=["status", "updated_at"])


def _sync_status(contract: Contract) -> None:
    approval = get_approval(contract)
    if approval is None:
        return
    if approval.status == Approval.STATUS_IN_PROGRESS:
        _set(contract, constants.STATUS_ON_APPROVAL)
    elif approval.status == Approval.STATUS_REJECTED:
        _set(contract, constants.STATUS_REJECTED)
        _notify("notify_initiator_result", contract)  # инициатору — отклонён
    elif approval.status == Approval.STATUS_RETURNED:
        _set(contract, constants.STATUS_RETURNED)
        _notify("notify_initiator_result", contract)  # инициатору — возвращён
    elif approval.status == Approval.STATUS_COMPLETED:
        if contract.status in (
            constants.STATUS_ON_APPROVAL,
            constants.STATUS_DRAFT,
            constants.STATUS_RETURNED,
        ):
            _set(contract, constants.STATUS_APPROVED)
            log_action("contract_approved", target=contract)
            _notify("notify_initiator_result", contract)  # инициатору — согласован


@transaction.atomic
def submit(contract: Contract, participants: list[dict], *, flow_type=None,
           actor_b24_id=None) -> Approval:
    """Отправляет договор на согласование (последовательный маршрут).

    Допускается перезапуск после возврата/отклонения (новый круг)."""
    if contract.status not in (
        constants.STATUS_DRAFT,
        constants.STATUS_RETURNED,
        constants.STATUS_REJECTED,
    ):
        raise ContractError("Отправить можно черновик, возвращённый или отклонённый договор.")
    if not participants:
        raise ContractError("Маршрут пуст — добавьте согласующих.")

    # зафиксировать ручной выбор для слотов, которые система не разрешила
    manual_roles = {s["role_code"] for s in routing.build_route(contract) if s["needs_manual"]}
    for p in participants:
        if p.get("role") in manual_roles:
            log_action(
                "contract_manual_approver_selected", target=contract,
                new_value={"role": p.get("role"), "b24_user_id": p.get("b24_user_id")},
            )

    approval = get_approval(contract)
    if approval is None:
        approval = Approval.objects.create(
            approval_type="contract",
            title=f"Договор — {contract.title}".strip(" —"),
            # Согласование договоров — СТРОГО последовательное (по одному, в
            # порядке маршрута). Параллельный режим здесь не используется.
            flow_type=Approval.FLOW_SEQUENTIAL,
            initiator_b24_id=contract.initiator_b24_id,
            linked_object=contract,
        )
        flow.submit(approval, participants)
    else:
        flow.start_new_round(approval, participants)

    _sync_status(contract)
    _notify("notify_current_approver", contract)  # тому, чья очередь
    return approval


def current_pending_participant(approval: Approval | None) -> ApprovalParticipant | None:
    """Первый ожидающий участник текущего круга (последовательный маршрут)."""
    if approval is None or approval.status != Approval.STATUS_IN_PROGRESS:
        return None
    round = flow.get_current_round(approval)
    if round is None:
        return None
    return (
        round.participants.filter(decision=ApprovalParticipant.DECISION_WAITING)
        .order_by("order")
        .first()
    )


def is_group_legal(participant: ApprovalParticipant) -> bool:
    return participant.role == constants.roles.ROLE_LEGAL_DEPT and participant.b24_user_id is None


@transaction.atomic
def decide(contract: Contract, participant_id, decision, comment="", *,
           actor_b24_id=None) -> ApprovalParticipant:
    approval = get_approval(contract)
    if approval is None:
        raise ContractError("Договор не отправлен на согласование.")
    try:
        participant = ApprovalParticipant.objects.get(
            id=participant_id, round__approval=approval
        )
    except ApprovalParticipant.DoesNotExist:
        raise ContractError("Участник не найден.")

    # Авторизация решающего.
    if is_group_legal(participant):
        # Групповой юр-этап: согласовать может любой юрист; фиксируем, кто именно.
        if not is_lawyer(actor_b24_id):
            raise ContractError("Согласовать этап юротдела может только сотрудник юридического отдела.")
        participant.b24_user_id = actor_b24_id
        participant.save(update_fields=["b24_user_id"])
    elif (
        actor_b24_id is not None
        and participant.type == ApprovalParticipant.TYPE_INTERNAL
        and participant.b24_user_id
        and actor_b24_id != participant.b24_user_id
    ):
        raise ContractError("Вы не являетесь этим согласующим.")

    flow.decide(participant, decision, comment)
    _sync_status(contract)
    # если ещё на согласовании — уведомить следующего согласующего
    _notify("notify_current_approver", contract)
    return participant


@transaction.atomic
def return_for_revision(contract: Contract, *, by_b24_id=None, comment="") -> None:
    approval = get_approval(contract)
    if approval is None:
        raise ContractError("Договор не на согласовании.")
    flow.return_for_revision(approval, by_b24_id=by_b24_id, comment=comment)
    _sync_status(contract)


@transaction.atomic
def cancel(contract: Contract, *, by_b24_id=None) -> None:
    if contract.status not in constants.CANCELABLE_STATUSES:
        raise ContractError("Этот договор уже нельзя отменить.")
    approval = get_approval(contract)
    if approval is not None and approval.status == Approval.STATUS_IN_PROGRESS:
        try:
            flow.cancel(approval)
        except Exception:
            pass
    _set(contract, constants.STATUS_CANCELED)
    log_action("contract_canceled", target=contract)
