from rest_framework import serializers

from approvalflow.serializers import ApprovalDetailSerializer

from . import constants, services
from .models import RegulatoryRequest


def _documents(obj):
    out = []
    for d in obj.documents.filter(deleted_at__isnull=True):
        cur = d.current_version
        out.append({
            "id": d.id,
            "title": d.title,
            "current_version_number": cur.version_number if cur else None,
            "download_url": (
                f"/api/documents/{d.id}/versions/{cur.id}/download/" if cur else None
            ),
        })
    return out


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
        return _documents(obj)


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
