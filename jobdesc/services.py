"""
Логика заявок на согласование ДИ: согласование на движке approvalflow +
исполнение отделом по работе с персоналом (взять в работу → на подписании →
исполнена → инициатор «Получил / ознакомился» → закрыта).
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from approvalflow import services as flow
from approvalflow.models import Approval, ApprovalParticipant
from core.auth import is_lawyer
from core.services import log_action

from . import constants, routing
from .models import JobDescription

# Пометка на этапе, который закрылся сам: инициатор — он же первый согласующий.
AUTO_APPROVE_COMMENT = "Согласовано инициатором при отправке"


class JobDescError(Exception):
    pass


def _notify(event: str, jd: JobDescription) -> None:
    """Уведомление после commit (best-effort, не ломает флоу)."""
    def run():
        try:
            from . import notifications

            getattr(notifications, event)(jd)
        except Exception as e:  # pragma: no cover
            print("[jobdesc notify] error:", e)

    transaction.on_commit(run)


def create_jobdesc(**fields) -> JobDescription:
    jd = JobDescription.objects.create(**fields)
    jd.number = f"{constants.NUMBER_PREFIX}-{jd.pk:06d}"
    jd.save(update_fields=["number"])
    return jd


def get_approval(jd: JobDescription) -> Approval | None:
    ct = ContentType.objects.get_for_model(JobDescription)
    return (
        Approval.objects.filter(content_type=ct, object_id=jd.pk)
        .order_by("-id")
        .first()
    )


def build_route(jd: JobDescription) -> list[dict]:
    return routing.build_route(jd)


def _set(jd: JobDescription, status: str, **fields) -> None:
    jd.status = status
    for k, v in fields.items():
        setattr(jd, k, v)
    jd.save(update_fields=["status", "updated_at", *fields.keys()])


def _sync_status(jd: JobDescription) -> None:
    approval = get_approval(jd)
    if approval is None:
        return
    if approval.status == Approval.STATUS_IN_PROGRESS:
        _set(jd, constants.STATUS_ON_APPROVAL)
    elif approval.status == Approval.STATUS_REJECTED:
        _set(jd, constants.STATUS_REJECTED)
        _notify("notify_initiator_result", jd)
    elif approval.status == Approval.STATUS_RETURNED:
        _set(jd, constants.STATUS_RETURNED)
        _notify("notify_initiator_result", jd)
    elif approval.status == Approval.STATUS_COMPLETED:
        if jd.status in (
            constants.STATUS_ON_APPROVAL, constants.STATUS_DRAFT, constants.STATUS_RETURNED,
        ):
            # Утверждённая заявка не уходит письмом, а сразу попадает в раздел
            # «Заявки для отдела по работе с персоналом» (требование ТЗ).
            _set(jd, constants.STATUS_TO_HR)
            log_action("jobdesc_approved", target=jd)
            _notify("notify_initiator_result", jd)
            _notify("notify_hr_queue", jd)


def _dedup(participants: list[dict]) -> list[dict]:
    """Один человек — один этап (первый по порядку); групповой юр-этап не трогаем."""
    seen: set[int] = set()
    out = []
    for p in participants:
        uid = p.get("b24_user_id")
        if uid:
            if uid in seen:
                continue
            seen.add(uid)
        out.append(p)
    for i, p in enumerate(out):
        p["order"] = i
    return out


def _log_route_overrides(jd: JobDescription, participants: list[dict], *,
                         actor_b24_id=None) -> None:
    """Ручной выбор и замена согласующих — в историю заявки (требование ТЗ)."""
    auto = {s["role_code"]: s for s in routing.build_route(jd)}
    for p in participants:
        slot = auto.get(p.get("role"))
        if slot is None or slot.get("group"):
            continue
        if not slot["resolved"]:
            log_action(
                "jobdesc_manual_approver_selected", target=jd,
                new_value={"role": p.get("role"), "b24_user_id": p.get("b24_user_id")},
            )
        elif slot["b24_user_id"] != p.get("b24_user_id"):
            log_action(
                "jobdesc_approver_replaced", target=jd,
                old_value={"role": p.get("role"), "b24_user_id": slot["b24_user_id"]},
                new_value={"b24_user_id": p.get("b24_user_id"), "by_b24_id": actor_b24_id},
            )


def _auto_approve_initiator(jd: JobDescription, approval: Approval) -> None:
    """Инициатор стоит первым в маршруте — его этап закрывается при отправке,
    чтобы не нажимать «Согласовать» за самого себя (решение заказчика)."""
    round = flow.get_current_round(approval)
    first = round.participants.order_by("order").first() if round else None
    if (
        first is None
        or first.type != ApprovalParticipant.TYPE_INTERNAL
        or not jd.initiator_b24_id
        or first.b24_user_id != jd.initiator_b24_id
    ):
        return
    flow.decide(first, "approve", AUTO_APPROVE_COMMENT)
    log_action(
        "jobdesc_initiator_auto_approved", target=jd,
        new_value={"round": round.round_number, "role": first.role},
    )


@transaction.atomic
def submit(jd: JobDescription, participants: list[dict], *, actor_b24_id=None,
           comment: str = "") -> Approval:
    """Отправка на согласование (новый круг после доработки — тем же вызовом)."""
    if jd.status not in constants.EDITABLE_STATUSES:
        raise JobDescError("Отправить можно черновик, возвращённую или отклонённую заявку.")
    # Пустые этапы «при наличии» фронт не шлёт; на всякий случай отсеиваем и
    # здесь — кроме группового юр-этапа, у которого человека нет по замыслу.
    participants = _dedup([
        p for p in participants
        if p.get("b24_user_id") or p.get("role") == constants.ROLE_LEGAL_DEPT
    ])
    if not participants:
        raise JobDescError("Маршрут пуст — добавьте согласующих.")

    _log_route_overrides(jd, participants, actor_b24_id=actor_b24_id)

    approval = get_approval(jd)
    if approval is None:
        approval = Approval.objects.create(
            approval_type="jobdesc",
            title=f"ДИ — {jd.position_name}".strip(" —"),
            flow_type=Approval.FLOW_SEQUENTIAL,
            initiator_b24_id=jd.initiator_b24_id,
            linked_object=jd,
        )
        flow.submit(approval, participants, comment=comment)
    else:
        flow.start_new_round(approval, participants, comment=comment)

    _auto_approve_initiator(jd, approval)
    _sync_status(jd)
    _notify("notify_current_approver", jd)
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
    return participant.role == constants.ROLE_LEGAL_DEPT and participant.b24_user_id is None


@transaction.atomic
def decide(jd: JobDescription, participant_id, decision, comment="", *,
           actor_b24_id=None, admin_b24_id=None) -> ApprovalParticipant:
    approval = get_approval(jd)
    if approval is None:
        raise JobDescError("Заявка не отправлена на согласование.")
    try:
        participant = ApprovalParticipant.objects.get(id=participant_id, round__approval=approval)
    except ApprovalParticipant.DoesNotExist:
        raise JobDescError("Участник не найден.")

    if is_group_legal(participant):
        # Юр-этап группой: согласует любой юрист, фиксируем — кто именно.
        if admin_b24_id is None:
            if not is_lawyer(actor_b24_id):
                raise JobDescError(
                    "Согласовать этап юротдела может только сотрудник юридического отдела."
                )
            participant.b24_user_id = actor_b24_id
            participant.save(update_fields=["b24_user_id"])
    elif (
        admin_b24_id is None
        and actor_b24_id is not None
        and participant.type == ApprovalParticipant.TYPE_INTERNAL
        and participant.b24_user_id
        and actor_b24_id != participant.b24_user_id
    ):
        raise JobDescError("Вы не являетесь этим согласующим.")

    try:
        flow.decide(participant, decision, comment, admin_b24_id=admin_b24_id)
    except flow.ApprovalError as e:
        raise JobDescError(str(e)) from e
    _sync_status(jd)
    _notify("notify_current_approver", jd)
    return participant


@transaction.atomic
def return_for_revision(jd: JobDescription, *, by_b24_id=None, comment="") -> None:
    approval = get_approval(jd)
    if approval is None:
        raise JobDescError("Заявка не на согласовании.")
    try:
        flow.return_for_revision(approval, by_b24_id=by_b24_id, comment=comment)
    except flow.ApprovalError as e:
        raise JobDescError(str(e)) from e
    _sync_status(jd)


@transaction.atomic
def cancel(jd: JobDescription, *, by_b24_id=None) -> None:
    if jd.status not in constants.CANCELABLE_STATUSES:
        raise JobDescError("Отменить можно только заявку до утверждения.")
    approval = get_approval(jd)
    if approval is not None and approval.status == Approval.STATUS_IN_PROGRESS:
        flow.cancel(approval)
    _set(jd, constants.STATUS_CANCELED)
    log_action("jobdesc_canceled", target=jd, new_value={"by_b24_id": by_b24_id})


# --- исполнение отделом по работе с персоналом ----------------------------
@transaction.atomic
def take_in_work(jd: JobDescription, *, executor_b24_id: int) -> None:
    if jd.status != constants.STATUS_TO_HR:
        raise JobDescError("Взять в работу можно заявку, переданную в отдел персонала.")
    _set(jd, constants.STATUS_HR_WORK, executor_b24_id=executor_b24_id, taken_at=timezone.now())
    log_action("jobdesc_taken", target=jd, new_value={"by_b24_id": executor_b24_id})
    _notify("notify_initiator_execution", jd)


@transaction.atomic
def set_status(jd: JobDescription, status: str, *, by_b24_id: int) -> None:
    """Ручная смена статуса исполнения: «В работе» ⇄ «На подписании»."""
    if status not in constants.HR_MANUAL_STATUSES:
        raise JobDescError("Недопустимый статус.")
    if jd.status not in constants.HR_MANUAL_STATUSES:
        raise JobDescError("Сначала возьмите заявку в работу.")
    if jd.status == status:
        return
    old = jd.status
    _set(jd, status, executor_b24_id=jd.executor_b24_id or by_b24_id)
    log_action(
        "jobdesc_status_changed", target=jd,
        old_value={"status": old}, new_value={"status": status, "by_b24_id": by_b24_id},
    )
    _notify("notify_initiator_execution", jd)


def has_final_document(jd: JobDescription) -> bool:
    return jd.documents.filter(
        document_type=constants.DOC_TYPE_FINAL, deleted_at__isnull=True
    ).exists()


@transaction.atomic
def execute(jd: JobDescription, *, executor_b24_id: int, transfer_method: str,
            comment: str = "") -> None:
    """«Исполнена» — только с прикреплённой готовой ДИ и способом передачи (ТЗ)."""
    if jd.status not in (constants.STATUS_TO_HR, *constants.HR_MANUAL_STATUSES):
        raise JobDescError("Исполнить можно заявку, которая находится у отдела персонала.")
    if transfer_method not in dict(constants.TRANSFER_CHOICES):
        raise JobDescError("Укажите способ передачи ДИ.")
    if not has_final_document(jd):
        raise JobDescError("Прикрепите файл или скан готовой ДИ.")
    _set(
        jd, constants.STATUS_EXECUTED,
        executor_b24_id=jd.executor_b24_id or executor_b24_id,
        taken_at=jd.taken_at or timezone.now(),
        executed_at=timezone.now(),
        transfer_method=transfer_method,
        execution_comment=comment,
    )
    log_action(
        "jobdesc_executed", target=jd,
        new_value={"by_b24_id": executor_b24_id, "transfer_method": transfer_method},
    )
    _notify("notify_initiator_execution", jd)


@transaction.atomic
def acknowledge(jd: JobDescription, *, by_b24_id: int) -> None:
    """Инициатор: «Получил / ознакомился» → «Закрыта»."""
    if jd.status != constants.STATUS_EXECUTED:
        raise JobDescError("Подтвердить получение можно только исполненную заявку.")
    _set(jd, constants.STATUS_CLOSED, received_at=timezone.now())
    log_action("jobdesc_received", target=jd, new_value={"by_b24_id": by_b24_id})
    _notify("notify_executor_closed", jd)
