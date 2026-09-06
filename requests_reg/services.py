"""
Логика регламентных заявок.

Двухэтапный процесс (доверенность/МЧД):
  1) Согласование — через движок approvalflow (последовательный маршрут).
  2) Исполнение юридическим отделом — взять в работу → на подписании →
     исполнена (файл + способ передачи) → инициатор подтверждает получение →
     закрыта.

Маршрут строится по правилам (routing.build_route); ручной выбор согласующего
фиксируется в аудите (core.log_action).
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from approvalflow import services as flow
from approvalflow.models import Approval, ApprovalParticipant
from core.auth import is_lawyer
from core.services import log_action

from . import constants, routing, validators
from .models import RegulatoryRequest


class RequestError(Exception):
    pass


def _notify(event: str, request: RegulatoryRequest) -> None:
    """Уведомление после commit (best-effort, не ломает флоу)."""
    def run():
        try:
            from . import notifications

            getattr(notifications, event)(request)
        except Exception as e:  # pragma: no cover
            print("[notify] error:", e)

    transaction.on_commit(run)


def create_request(*, request_type: str, organization, **fields) -> RegulatoryRequest:
    if request_type not in constants.REQUEST_TYPES:
        raise RequestError(f"Неизвестный тип заявки: {request_type}")
    req = RegulatoryRequest.objects.create(
        request_type=request_type, organization=organization, **fields
    )
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


def build_route(request: RegulatoryRequest) -> list[dict]:
    """Предпросмотр маршрута (для инициатора до отправки)."""
    return routing.build_route(request)


def _set(request, status, **extra):
    request.status = status
    fields = ["status", "updated_at", *extra.keys()]
    for k, v in extra.items():
        setattr(request, k, v)
    request.save(update_fields=fields)


def _sync_status(request: RegulatoryRequest) -> None:
    approval = get_approval(request)
    if approval is None:
        return
    if approval.status == Approval.STATUS_IN_PROGRESS:
        _set(request, constants.STATUS_ON_APPROVAL)
    elif approval.status == Approval.STATUS_REJECTED:
        _set(request, constants.STATUS_REJECTED)
        _notify("notify_initiator_status", request)  # инициатору — отклонена
    elif approval.status == Approval.STATUS_RETURNED:
        _set(request, constants.STATUS_RETURNED)
        _notify("notify_initiator_status", request)  # инициатору — возвращена
    elif approval.status == Approval.STATUS_COMPLETED:
        if request.status in (
            constants.STATUS_ON_APPROVAL,
            constants.STATUS_DRAFT,
            constants.STATUS_RETURNED,
        ):
            # финальное утверждение → согласована → автопередача юристам
            _set(request, constants.STATUS_APPROVED)
            _notify("notify_initiator_status", request)  # инициатору — согласована
            _set(request, constants.STATUS_TO_LEGAL)
            log_action("request_approved_to_legal", target=request)
            _notify("notify_legal_queue", request)  # юристам — новая на исполнение


@transaction.atomic
def submit(request: RegulatoryRequest, participants: list[dict], *, flow_type=None,
           actor_b24_id=None, comment: str = ""):
    """Отправляет заявку на согласование (последовательный маршрут по умолчанию).

    Допускается и перезапуск после отклонения (новый круг)."""
    if request.status not in (
        constants.STATUS_DRAFT,
        constants.STATUS_RETURNED,
        constants.STATUS_REJECTED,
    ):
        raise RequestError("Отправить можно черновик, возвращённую или отклонённую заявку.")
    if not participants:
        raise RequestError("Маршрут пуст — добавьте согласующих.")

    # МЧД без ИНН/СНИЛС представителя отправлять некуда: ФНС такую доверенность
    # не примет. Сериализатор ловит это при сохранении анкеты, но заявка могла
    # быть создана и другим путём — здесь последний рубеж перед маршрутом.
    # Заявки, поданные до введения требования, правило не задевает: анкету
    # поданной заявки не отредактировать, и они бы намертво застряли.
    if validators.is_machine_readable(
        request.request_type, request.data
    ) and validators.identifiers_required(request.created_at):
        err = validators.mchd_rep_error(request.data)
        if err:
            raise RequestError(err)

    # зафиксировать ручной выбор согласующих (слоты, которые система не разрешила)
    manual_roles = {s["role_code"] for s in routing.build_route(request) if s["needs_manual"]}
    for p in participants:
        if p.get("role") in manual_roles:
            log_action(
                "manual_approver_selected", target=request,
                new_value={"role": p.get("role"), "b24_user_id": p.get("b24_user_id")},
            )

    # Заполненное PDF-заявление прикрепляем к заявке (его получат юристы).
    if request.request_type in (constants.TYPE_POA, constants.TYPE_MCHD):
        try:
            from . import anketa_pdf

            anketa_pdf.generate_and_attach(request)
        except Exception as e:  # генерация PDF не должна блокировать отправку
            print("[anketa] generate error:", e)

    approval = get_approval(request)
    if approval is None:
        approval = Approval.objects.create(
            approval_type=f"reg_{request.request_type}",
            title=f"{request.get_request_type_display()} — {request.subject_name}".strip(" —"),
            flow_type=flow_type or Approval.FLOW_SEQUENTIAL,
            initiator_b24_id=request.initiator_b24_id,
            linked_object=request,
        )
        flow.submit(approval, participants, comment=comment)
    else:
        # Новый круг после доработки: пояснение инициатора, что изменилось,
        # остаётся на круге и попадает согласующим в историю и в письмо.
        flow.start_new_round(approval, participants, comment=comment)

    _sync_status(request)
    _notify("notify_current_approver", request)  # тому, чья очередь
    return approval


def current_pending_participant(approval: Approval | None) -> ApprovalParticipant | None:
    """Первый ожидающий участник текущего круга (по order) — чья очередь сейчас.

    Маршрут заявок последовательный, поэтому «чья очередь» = минимальный order
    среди ещё не принявших решение."""
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
def decide(request: RegulatoryRequest, participant_id, decision, comment="", *,
           actor_b24_id=None, admin_b24_id=None):
    approval = get_approval(request)
    if approval is None:
        raise RequestError("Заявка не отправлена на согласование.")
    try:
        participant = ApprovalParticipant.objects.get(
            id=participant_id, round__approval=approval
        )
    except ApprovalParticipant.DoesNotExist:
        raise RequestError("Участник не найден.")

    # Авторизация решающего. actor_b24_id из API всегда задан; при прямом
    # сервисном вызове (None) проверку личности обычного слота не навязываем.
    if is_group_legal(participant):
        # Групповой юрэтап: согласовать может любой юрист; фиксируем, кто именно.
        # Администратор в своём режиме закрывает и его — но себя в слот не
        # подставляет: этап так и остаётся юротдельским, просто с пометкой.
        if admin_b24_id is None:
            if not is_lawyer(actor_b24_id):
                raise RequestError("Согласовать этап юротдела может только сотрудник юридического отдела.")
            participant.b24_user_id = actor_b24_id
            participant.save(update_fields=["b24_user_id"])
    elif (
        admin_b24_id is None
        and actor_b24_id is not None
        and participant.type == ApprovalParticipant.TYPE_INTERNAL
        and participant.b24_user_id
        and actor_b24_id != participant.b24_user_id
    ):
        raise RequestError("Вы не являетесь этим согласующим.")

    flow.decide(participant, decision, comment, admin_b24_id=admin_b24_id)
    _sync_status(request)
    # если ещё на согласовании — уведомить следующего согласующего
    _notify("notify_current_approver", request)
    return participant


@transaction.atomic
def return_for_revision(request: RegulatoryRequest, *, by_b24_id=None, comment=""):
    approval = get_approval(request)
    if approval is None:
        raise RequestError("Заявка не на согласовании.")
    flow.return_for_revision(approval, by_b24_id=by_b24_id, comment=comment)
    _sync_status(request)


@transaction.atomic
def cancel(request: RegulatoryRequest, *, by_b24_id=None):
    """Отмена заявки инициатором (до передачи юристам)."""
    if request.status not in constants.CANCELABLE_STATUSES:
        raise RequestError("Эту заявку уже нельзя отменить.")
    approval = get_approval(request)
    if approval is not None and approval.status == Approval.STATUS_IN_PROGRESS:
        try:
            flow.cancel(approval)
        except Exception:
            pass
    _set(request, constants.STATUS_CANCELED)
    log_action("request_canceled", target=request)


# --- Исполнение юридическим отделом -----------------------------------------
def take_in_work(request: RegulatoryRequest):
    if request.status != constants.STATUS_TO_LEGAL:
        raise RequestError("Взять в работу можно только заявку, переданную юристам.")
    _set(request, constants.STATUS_LEGAL_WORK)


def to_signing(request: RegulatoryRequest):
    if request.status != constants.STATUS_LEGAL_WORK:
        raise RequestError("На подписание можно отправить заявку в работе у юристов.")
    _set(request, constants.STATUS_SIGNING)


def execute(request: RegulatoryRequest, *, delivery_method: str, delivery_comment: str = ""):
    """Отметить исполненной: обязателен прикреплённый файл и способ передачи."""
    if request.status not in (constants.STATUS_LEGAL_WORK, constants.STATUS_SIGNING):
        raise RequestError("Исполнить можно заявку в работе у юристов или на подписании.")
    if not delivery_method:
        raise RequestError("Укажите способ передачи документа.")
    # нужен реальный скан доверенности, а не автосформированная анкета
    if not request.documents.filter(deleted_at__isnull=True).exclude(
        document_type="anketa"
    ).exists():
        raise RequestError("Прикрепите файл/скан доверенности перед исполнением.")
    _set(
        request, constants.STATUS_EXECUTED,
        delivery_method=delivery_method,
        delivery_comment=delivery_comment,
        executed_at=timezone.now(),
    )
    log_action("request_executed", target=request,
               new_value={"delivery_method": delivery_method})
    _notify("notify_initiator_executed", request)  # инициатору — подтвердите получение


def confirm_receipt(request: RegulatoryRequest, *, by_b24_id=None):
    """Инициатор подтверждает получение → заявка закрывается."""
    if request.status != constants.STATUS_EXECUTED:
        raise RequestError("Подтвердить получение можно только исполненную заявку.")
    _set(request, constants.STATUS_CLOSED, received_at=timezone.now())
    log_action("request_received", target=request)
    _notify("notify_legal_closed", request)  # юристам — инициатор ознакомился
