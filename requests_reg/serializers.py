from datetime import date

from rest_framework import serializers

from approvalflow.serializers import ApprovalDetailSerializer
from documents.serializers import linked_documents

from . import constants, services
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


class RegulatoryRequestDetailSerializer(RegulatoryRequestListSerializer):
    approval = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    delivery_method_display = serializers.CharField(
        source="get_delivery_method_display", read_only=True
    )

    class Meta(RegulatoryRequestListSerializer.Meta):
        fields = RegulatoryRequestListSerializer.Meta.fields + [
            "facility", "cfo", "initiator_b24_id", "subject_b24_id",
            "position", "department", "basis", "valid_from", "valid_until",
            "comment", "data", "delivery_method", "delivery_method_display",
            "delivery_comment", "executed_at", "received_at",
            "external_1c_id", "external_diadoc_id",
            "updated_at", "approval", "documents",
        ]

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
        ]

    def validate_request_type(self, value):
        if value not in constants.REQUEST_TYPES:
            raise serializers.ValidationError("Неизвестный тип заявки.")
        return value

    def validate(self, attrs):
        # Серверная страховка правила «доверенность не более 3 лет».
        data = attrs.get("data")
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
