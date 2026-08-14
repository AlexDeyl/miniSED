from rest_framework import serializers

from approvalflow.serializers import ApprovalDetailSerializer
from documents.serializers import linked_documents

from . import services
from .models import Contract


class ContractListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="status_label", read_only=True)
    organization_name = serializers.CharField(source="organization.short_name", read_only=True)
    cfo_name = serializers.CharField(source="cfo.name", read_only=True, default=None)

    class Meta:
        model = Contract
        fields = [
            "id", "number", "title", "amount",
            "status", "status_display",
            "organization", "organization_name", "cfo", "cfo_name",
            "created_at",
        ]


class ContractDetailSerializer(ContractListSerializer):
    approval = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    class Meta(ContractListSerializer.Meta):
        fields = ContractListSerializer.Meta.fields + [
            "is_nonstandard", "has_disagreement_protocol",
            "initiator_b24_id", "crm_link", "comment", "data",
            "updated_at", "approval", "documents",
        ]

    def get_approval(self, obj):
        approval = services.get_approval(obj)
        return ApprovalDetailSerializer(approval).data if approval else None

    def get_documents(self, obj):
        return linked_documents(obj)


class ContractWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = [
            "title", "organization", "cfo", "amount",
            "is_nonstandard", "has_disagreement_protocol",
            "crm_link", "comment", "data",
        ]

    def validate_title(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите название договора.")
        return value
