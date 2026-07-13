"""
Логика движка согласований: круги, решения, возвраты, повторная отправка,
правка маршрута. Вся бизнес-логика здесь, модели остаются «тонкими».

Спецификация участника (participant spec) — dict:
  {
    "type": "internal" | "external",
    "b24_user_id": int | None,
    "email": str,
    "name": str,
    "role": str,          # процессная роль (код)
    "order": int,
    "is_required": bool,
  }
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import Approval, ApprovalParticipant, ApprovalRound, ApprovalRouteChangeLog


class ApprovalError(Exception):
    """Нарушение правил процесса согласования."""


def _add_participants(round: ApprovalRound, participants: list[dict]) -> None:
    for idx, spec in enumerate(participants):
        ApprovalParticipant.objects.create(
            round=round,
            type=spec.get("type", ApprovalParticipant.TYPE_INTERNAL),
            b24_user_id=spec.get("b24_user_id"),
            email=spec.get("email", ""),
            name=spec.get("name", ""),
            role=spec.get("role", ""),
            order=spec.get("order", idx),
            is_required=spec.get("is_required", True),
        )


def _open_round(approval: Approval, participants: list[dict]) -> ApprovalRound:
    if not participants:
        raise ApprovalError("Нельзя открыть круг без участников.")
    number = approval.current_round + 1
    round = ApprovalRound.objects.create(approval=approval, round_number=number)
    _add_participants(round, participants)
    approval.current_round = number
    approval.status = Approval.STATUS_IN_PROGRESS
    if approval.submitted_at is None:
        approval.submitted_at = timezone.now()
    approval.completed_at = None
    approval.save(
        update_fields=["current_round", "status", "submitted_at", "completed_at"]
    )
    return round


def get_current_round(approval: Approval) -> ApprovalRound | None:
    return approval.rounds.filter(round_number=approval.current_round).first()


@transaction.atomic
def submit(approval: Approval, participants: list[dict]) -> ApprovalRound:
    """Первичная отправка на согласование: открывает круг №1."""
    if approval.current_round != 0:
        raise ApprovalError("Согласование уже отправлено; используйте start_new_round.")
    return _open_round(approval, participants)


@transaction.atomic
def start_new_round(
    approval: Approval, participants: list[dict], *, reason: str = ""
) -> ApprovalRound:
    """
    Повторная отправка после доработки (ТЗ п.7.5): новый круг со связью с
    предыдущими (по round_number). История прошлых кругов не затирается.
    """
    if approval.status not in (Approval.STATUS_RETURNED, Approval.STATUS_REJECTED):
        raise ApprovalError(
            "Новый круг можно открыть только после возврата или отклонения."
        )
    return _open_round(approval, participants)


def _is_turn(round: ApprovalRound, participant: ApprovalParticipant) -> bool:
    """Для последовательного флоу — очередь ли этого участника."""
    if round.approval.flow_type == Approval.FLOW_PARALLEL:
        return participant.decision == ApprovalParticipant.DECISION_WAITING
    if participant.decision != ApprovalParticipant.DECISION_WAITING:
        return False
    return not round.participants.filter(
        order__lt=participant.order, decision=ApprovalParticipant.DECISION_WAITING
    ).exists()


def _recompute(round: ApprovalRound) -> None:
    approval = round.approval
    parts = round.participants.all()
    now = timezone.now()

    if parts.filter(decision=ApprovalParticipant.DECISION_REJECTED).exists():
        round.result = ApprovalRound.RESULT_REJECTED
        round.completed_at = now
        round.save(update_fields=["result", "completed_at"])
        approval.status = Approval.STATUS_REJECTED
        approval.save(update_fields=["status"])
    elif not parts.filter(decision=ApprovalParticipant.DECISION_WAITING).exists():
        round.result = ApprovalRound.RESULT_APPROVED
        round.completed_at = now
        round.save(update_fields=["result", "completed_at"])
        approval.status = Approval.STATUS_COMPLETED
        approval.completed_at = now
        approval.save(update_fields=["status", "completed_at"])


@transaction.atomic
def decide(
    participant: ApprovalParticipant, decision: str, comment: str = ""
) -> ApprovalParticipant:
    """
    Решение участника: approve | reject.
    Проверяет очередь (для последовательного) и статус.
    """
    round = participant.round
    approval = round.approval

    if approval.status not in (Approval.STATUS_IN_PROGRESS,):
        raise ApprovalError("Согласование не в статусе «на согласовании».")
    if participant.decision != ApprovalParticipant.DECISION_WAITING:
        raise ApprovalError("Вы уже приняли решение.")
    if not _is_turn(round, participant):
        raise ApprovalError("Сейчас очередь других участников выше по списку.")
    if decision == "reject" and not comment.strip():
        raise ApprovalError("При отклонении комментарий обязателен.")

    if decision == "approve":
        participant.decision = ApprovalParticipant.DECISION_APPROVED
    elif decision == "reject":
        participant.decision = ApprovalParticipant.DECISION_REJECTED
    else:
        raise ApprovalError("Недопустимое решение.")

    participant.decision_comment = comment.strip()
    participant.decided_at = timezone.now()
    participant.save(update_fields=["decision", "decision_comment", "decided_at"])

    _recompute(round)
    return participant


@transaction.atomic
def return_for_revision(
    approval: Approval, *, by_b24_id: int | None = None, comment: str = ""
) -> ApprovalRound:
    """Вернуть текущий круг на доработку инициатору (ТЗ п.7.5)."""
    round = get_current_round(approval)
    if round is None or approval.status != Approval.STATUS_IN_PROGRESS:
        raise ApprovalError("Возврат доступен только для активного круга.")
    round.result = ApprovalRound.RESULT_RETURNED
    round.completed_at = timezone.now()
    round.comment = comment
    round.save(update_fields=["result", "completed_at", "comment"])
    approval.status = Approval.STATUS_RETURNED
    approval.save(update_fields=["status"])
    return round


def route_snapshot(round: ApprovalRound) -> list[dict]:
    """Сериализует маршрут круга для журнала изменений."""
    return [
        {
            "type": p.type,
            "b24_user_id": p.b24_user_id,
            "email": p.email,
            "role": p.role,
            "order": p.order,
            "is_required": p.is_required,
        }
        for p in round.participants.all()
    ]


@transaction.atomic
def change_route(
    approval: Approval,
    participants: list[dict],
    *,
    by_b24_id: int | None = None,
    reason: str = "",
) -> ApprovalRouteChangeLog:
    """
    Изменение маршрута текущего круга с логированием (ТЗ п.7.6).
    Разрешено, пока по кругу ещё никто не принял решение.
    """
    round = get_current_round(approval)
    if round is None:
        raise ApprovalError("Нет активного круга для изменения маршрута.")
    if round.participants.exclude(
        decision=ApprovalParticipant.DECISION_WAITING
    ).exists():
        raise ApprovalError(
            "Маршрут нельзя менять после того, как приняты решения."
        )

    old = route_snapshot(round)
    round.participants.all().delete()
    _add_participants(round, participants)
    new = route_snapshot(round)

    return ApprovalRouteChangeLog.objects.create(
        approval=approval,
        changed_by_b24_id=by_b24_id,
        old_route_snapshot=old,
        new_route_snapshot=new,
        reason=reason,
    )


@transaction.atomic
def cancel(approval: Approval) -> None:
    if approval.status in (Approval.STATUS_COMPLETED, Approval.STATUS_CLOSED):
        raise ApprovalError("Нельзя отменить завершённое согласование.")
    approval.status = Approval.STATUS_CANCELED
    approval.save(update_fields=["status"])
