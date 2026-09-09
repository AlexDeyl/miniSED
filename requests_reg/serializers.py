from datetime import date

from rest_framework import serializers

from approvalflow.serializers import ApprovalDetailSerializer
from documents.serializers import linked_documents

from . import constants, services, validators
from .models import RegulatoryRequest


def _parse_date(value):
    """ISO-строка → date или None (без падения на мусоре)."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class RegulatoryRequestListSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_request_type_display", read_only=True)
    status_display = serializers.CharField(source="status_label", read_only=True)
    organization_name = serializers.CharField(source="organization.short_name", read_only=True)

    class Meta:
        model = RegulatoryRequest
        fields = [
            "id", "number", "request_type", "type_display",
            "status", "status_display", "subject_name",
            "organization", "organization_name", "created_at",
        ]


def _card_ref(req) -> dict | None:
    """Короткая ссылка на карточку заявки — для связки отзыв ↔ доверенность."""
    if req is None:
        return None
    return {
        "id": req.id,
        "number": req.number,
        "request_type": req.request_type,
        "type_display": req.get_request_type_display(),
        "status": req.status,
        "status_display": req.status_label(),
        "subject_name": req.subject_name,
    }


class RegulatoryRequestDetailSerializer(RegulatoryRequestListSerializer):
    approval = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    delivery_method_display = serializers.CharField(
        source="get_delivery_method_display", read_only=True
    )
    # Отзываемая доверенность (у заявки на отзыв) и, наоборот, заявки на отзыв
    # этой доверенности — связка нужна в обе стороны: из отзыва юрист уходит в
    # доверенность, а открыв доверенность, сразу видит, что её отзывают.
    source_request_info = serializers.SerializerMethodField()
    revocations = serializers.SerializerMethodField()

    class Meta(RegulatoryRequestListSerializer.Meta):
        fields = RegulatoryRequestListSerializer.Meta.fields + [
            "facility", "cfo", "initiator_b24_id", "subject_b24_id",
            "position", "department", "basis", "valid_from", "valid_until",
            "comment", "data", "delivery_method", "delivery_method_display",
            "delivery_comment", "executed_at", "received_at",
            "external_1c_id", "external_diadoc_id",
            "source_request", "source_request_info", "revocations",
            "updated_at", "approval", "documents",
        ]

    def get_source_request_info(self, obj):
        return _card_ref(obj.source_request)

    def get_revocations(self, obj):
        return [_card_ref(r) for r in obj.revocations.all().order_by("-id")]

    def get_approval(self, obj):
        approval = services.get_approval(obj)
        return ApprovalDetailSerializer(approval).data if approval else None

    def get_documents(self, obj):
        return linked_documents(obj)


class RegulatoryRequestWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryRequest
        fields = [
            "request_type", "organization", "facility", "cfo",
            "subject_name", "subject_b24_id", "position", "department",
            "basis", "valid_from", "valid_until", "comment", "data",
            "source_request",
        ]

    def validate_request_type(self, value):
        if value not in constants.REQUEST_TYPES:
            raise serializers.ValidationError("Неизвестный тип заявки.")
        return value

    def validate_source_request(self, value):
        """Отзывать можно только выданную доверенность или МЧД.

        Ссылка на ЭЦП или на другой отзыв — почти наверняка промах в выборе,
        и юрист получил бы заявку «отозвать заявку об отзыве»."""
        if value is None:
            return value
        if value.request_type not in constants.REVOCABLE_TYPES:
            raise serializers.ValidationError(
                "Отозвать можно только доверенность или МЧД."
            )
        return value

    def validate(self, attrs):
        # Серверная страховка правил анкеты (фронт проверяет то же самое).
        data = attrs.get("data")

        # Привязка к отзываемой доверенности имеет смысл только у отзыва:
        # у доверенности это поле осталось бы висеть непонятной ссылкой.
        rtype = attrs.get("request_type") or getattr(self.instance, "request_type", None)
        if attrs.get("source_request") and rtype != constants.TYPE_REVOKE:
            raise serializers.ValidationError(
                {"detail": "Привязать отзываемую доверенность можно только к заявке на отзыв."}
            )

        # МЧД: ИНН и СНИЛС не обязательны (на Госуслугах их не требуют), но
        # заполненные — проверяем по контрольным разрядам. Только когда анкету
        # присылают: PATCH одного поля не должен спотыкаться.
        if isinstance(data, dict) and validators.is_machine_readable(rtype, data):
            err = validators.mchd_rep_error(data)
            if err:
                raise serializers.ValidationError({"detail": err})

        if isinstance(data, dict) and data.get("term_type") == "period":
            f = _parse_date(data.get("term_from"))
            t = _parse_date(data.get("term_to"))
            if f and t:
                if t <= f:
                    raise serializers.ValidationError(
                        {"detail": "Дата окончания срока должна быть позже даты начала."}
                    )
                try:
                    max_t = f.replace(year=f.year + 3)
                except ValueError:  # 29 февраля → 28-е
                    max_t = f.replace(year=f.year + 3, day=28)
                if t > max_t:
                    raise serializers.ValidationError(
                        {"detail": "Срок доверенности не может превышать 3 года."}
                    )
        return attrs
