"""
Логика заявок на комплименты: согласование на движке approvalflow + фаза
исполнения (взять в работу → исполнена).

Статусы согласования двигает только маршрут; исполнитель их не меняет —
у него есть «взять в работу» и «исполнена» (решение заказчика).
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from approvalflow import services as flow
from approvalflow.models import Approval, ApprovalParticipant
from core.services import log_action

from . import constants, routing
from .models import Compliment


class ComplimentError(Exception):
    pass


def _notify(event: str, compliment: Compliment) -> None:
    """Уведомление после commit (best-effort, не ломает флоу)."""
    def run():
        try:
            from . import notifications

            getattr(notifications, event)(compliment)
        except Exception as e:  # pragma: no cover
            print("[compliments notify] error:", e)

    transaction.on_commit(run)


def create_compliment(**fields) -> Compliment:
    # Подразделение инициатора — снимок из профиля, если не указано вручную.
    if not fields.get("department") and fields.get("initiator_b24_id"):
        from core.models import UserProfile

        profile = (
            UserProfile.objects
            .filter(bitrix_id=fields["initiator_b24_id"])
            .select_related("department")
            .first()
        )
        if profile and profile.department:
            fields["department"] = profile.department.name

    compliment = Compliment.objects.create(**fields)
    compliment.number = f"{constants.NUMBER_PREFIX}-{compliment.pk:06d}"
    compliment.save(update_fields=["number"])
    return compliment


def get_approval(compliment: Compliment) -> Approval | None:
    ct = ContentType.objects.get_for_model(Compliment)
    return (
        Approval.objects.filter(content_type=ct, object_id=compliment.pk)
        .order_by("-id")
        .first()
    )


def build_route(compliment: Compliment) -> list[dict]:
    return routing.build_route(compliment)


def _set(compliment: Compliment, status: str, **fields) -> None:
    compliment.status = status
    for k, v in fields.items():
        setattr(compliment, k, v)
    compliment.save(update_fields=["status", "updated_at", *fields.keys()])


def _sync_status(compliment: Compliment) -> None:
    approval = get_approval(compliment)
    if approval is None:
        return
    if approval.status == Approval.STATUS_IN_PROGRESS:
        _set(compliment, constants.STATUS_ON_APPROVAL)
    elif approval.status == Approval.STATUS_REJECTED:
        _set(compliment, constants.STATUS_REJECTED)
        _notify("notify_initiator_result", compliment)
    elif approval.status == Approval.STATUS_RETURNED:
        _set(compliment, constants.STATUS_RETURNED)
        _notify("notify_initiator_result", compliment)
    elif approval.status == Approval.STATUS_COMPLETED:
        if compliment.status in (
            constants.STATUS_ON_APPROVAL,
            constants.STATUS_DRAFT,
            constants.STATUS_RETURNED,
        ):
            _set(compliment, constants.STATUS_APPROVED)
            log_action("compliment_approved", target=compliment)
            _notify("notify_initiator_result", compliment)
            # согласована → попадает в раздел «Заявки для исполнения»
            _notify("notify_executor", compliment)


@transaction.atomic
def submit(compliment: Compliment, participants: list[dict], *, actor_b24_id=None) -> Approval:
    """Отправка на согласование (последовательный маршрут).

    Исполнителя в участники НЕ добавляем: исполнение — не решение, оно живёт
    отдельной фазой на самой заявке."""
    if compliment.status not in (
        constants.STATUS_DRAFT,
        constants.STATUS_RETURNED,
        constants.STATUS_REJECTED,
    ):
        raise ComplimentError("Отправить можно черновик, возвращённую или отклонённую заявку.")
    if not participants:
        raise ComplimentError("Маршрут пуст — добавьте согласующих.")

    # Исполнитель: если инициатор не выбрал — берём по роли категории.
    if not compliment.executor_b24_id:
        _, b24_id = routing.default_executor(compliment)
        if b24_id:
            compliment.executor_b24_id = b24_id
            compliment.save(update_fields=["executor_b24_id"])

    approval = get_approval(compliment)
    if approval is None:
        approval = Approval.objects.create(
            approval_type="compliment",
            title=f"Комплимент — {compliment.title}".strip(" —"),
            flow_type=Approval.FLOW_SEQUENTIAL,
            initiator_b24_id=compliment.initiator_b24_id,
            linked_object=compliment,
        )
        flow.submit(approval, participants)
    else:
        flow.start_new_round(approval, participants)

    _sync_status(compliment)
    _notify("notify_current_approver", compliment)
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


@transaction.atomic
def decide(compliment: Compliment, participant_id, decision, comment="", *,
           actor_b24_id=None) -> ApprovalParticipant:
    approval = get_approval(compliment)
    if approval is None:
        raise ComplimentError("Заявка не отправлена на согласование.")
    try:
        participant = ApprovalParticipant.objects.get(
            id=participant_id, round__approval=approval
        )
    except ApprovalParticipant.DoesNotExist:
        raise ComplimentError("Участник не найден.")

    if (
        actor_b24_id is not None
        and participant.type == ApprovalParticipant.TYPE_INTERNAL
        and participant.b24_user_id
        and actor_b24_id != participant.b24_user_id
    ):
        raise ComplimentError("Вы не являетесь этим согласующим.")

    flow.decide(participant, decision, comment)
    _sync_status(compliment)
    _notify("notify_current_approver", compliment)
    return participant


@transaction.atomic
def return_for_revision(compliment: Compliment, *, by_b24_id=None, comment="") -> None:
    approval = get_approval(compliment)
    if approval is None:
        raise ComplimentError("Заявка не на согласовании.")
    flow.return_for_revision(approval, by_b24_id=by_b24_id, comment=comment)
    _sync_status(compliment)


@transaction.atomic
def cancel(compliment: Compliment, *, by_b24_id=None) -> None:
    if compliment.status not in constants.CANCELABLE_STATUSES:
        raise ComplimentError("Отменить можно только заявку до согласования.")
    approval = get_approval(compliment)
    if approval is not None and approval.status == Approval.STATUS_IN_PROGRESS:
        try:
            flow.cancel(approval)
        except Exception:
            pass
    _set(compliment, constants.STATUS_CANCELED)
    log_action("compliment_canceled", target=compliment)


# --- фаза исполнения --------------------------------------------------------
@transaction.atomic
def take_in_work(compliment: Compliment, *, executor_b24_id: int) -> None:
    if compliment.status != constants.STATUS_APPROVED:
        raise ComplimentError("Взять в работу можно только согласованную заявку.")
    _set(
        compliment, constants.STATUS_IN_WORK,
        executor_b24_id=executor_b24_id, taken_at=timezone.now(),
    )
    log_action("compliment_taken", target=compliment)
    _notify("notify_initiator_execution", compliment)


@transaction.atomic
def execute(compliment: Compliment, *, executor_b24_id: int, comment: str = "") -> None:
    """Отметить исполненной. Файл-подтверждение НЕ обязателен (решение заказчика)."""
    if compliment.status not in (constants.STATUS_APPROVED, constants.STATUS_IN_WORK):
        raise ComplimentError("Исполнить можно согласованную заявку или заявку в работе.")
    _set(
        compliment, constants.STATUS_EXECUTED,
        executor_b24_id=executor_b24_id or compliment.executor_b24_id,
        executed_at=timezone.now(),
        execution_comment=comment,
    )
    log_action("compliment_executed", target=compliment)
    _notify("notify_initiator_execution", compliment)
