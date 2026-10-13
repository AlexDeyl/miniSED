from rest_framework import serializers

from approvalflow.serializers import ApprovalDetailSerializer
from documents.serializers import linked_documents

from . import services
from .models import JobDescription


class JobDescListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="status_label", read_only=True)
    organization_name = serializers.CharField(source="organization.short_name", read_only=True)
    cfo_name = serializers.CharField(source="cfo.name", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True, default=None)

    class Meta:
        model = JobDescription
        fields = [
            "id", "number", "position_name",
            "organization", "organization_name", "cfo", "cfo_name",
            "facility", "facility_name", "is_nonstandard",
            "status", "status_display", "initiator_b24_id", "executor_b24_id",
            "created_at",
        ]


class JobDescDetailSerializer(JobDescListSerializer):
    approval = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    transfer_display = serializers.CharField(source="transfer_label", read_only=True)

    class Meta(JobDescListSerializer.Meta):
        fields = JobDescListSerializer.Meta.fields + [
            "description", "data",
            "taken_at", "executed_at", "transfer_method", "transfer_display",
            "execution_comment", "received_at",
            "updated_at", "approval", "documents",
        ]

    def get_approval(self, obj):
        approval = services.get_approval(obj)
        return ApprovalDetailSerializer(approval).data if approval else None

    def get_documents(self, obj):
        return linked_documents(obj)


class JobDescWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobDescription
        fields = ["position_name", "organization", "facility", "cfo", "is_nonstandard", "description"]

    def validate_position_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите должность.")
        return value

    def validate(self, attrs):
        """ЦФО — общий (без юрлица) либо того же юрлица, что и заявка."""
        inst = self.instance
        org = attrs.get("organization", inst.organization if inst else None)
        cfo = attrs.get("cfo", inst.cfo if inst else None)
        if cfo is not None and cfo.organization_id and org is not None and cfo.organization_id != org.id:
            raise serializers.ValidationError({"cfo": "ЦФО относится к другой организации."})
        return attrs
