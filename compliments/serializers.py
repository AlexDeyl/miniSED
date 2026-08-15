from rest_framework import serializers

from approvalflow.serializers import ApprovalDetailSerializer
from documents.serializers import linked_documents

from . import services
from .models import Compliment


class ComplimentListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="status_label", read_only=True)
    category_display = serializers.CharField(source="category_label", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True, default=None)

    class Meta:
        model = Compliment
        fields = [
            "id", "number", "title", "category", "category_display",
            "company", "event_at", "facility", "facility_name",
            "status", "status_display", "initiator_b24_id", "executor_b24_id",
            "created_at",
        ]


class ComplimentDetailSerializer(ComplimentListSerializer):
    approval = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    class Meta(ComplimentListSerializer.Meta):
        fields = ComplimentListSerializer.Meta.fields + [
            "category_details", "guest_name", "description", "department",
            "organization", "needs_ceo", "data",
            "taken_at", "executed_at", "execution_comment",
            "updated_at", "approval", "documents",
        ]

    def get_approval(self, obj):
        approval = services.get_approval(obj)
        return ApprovalDetailSerializer(approval).data if approval else None

    def get_documents(self, obj):
        return linked_documents(obj)


class ComplimentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Compliment
        fields = [
            "title", "category", "category_details", "company", "guest_name",
            "event_at", "facility", "organization", "description", "department",
            "needs_ceo", "executor_b24_id", "data",
        ]

    def validate_title(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите наименование заявки.")
        return value

    def validate_company(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите компанию — получателя комплимента.")
        return value
