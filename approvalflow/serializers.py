from rest_framework import serializers

from .models import (
    Approval,
    ApprovalParticipant,
    ApprovalRound,
    ApprovalRouteChangeLog,
    ApprovalSheet,
)


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalParticipant
        fields = [
            "id", "type", "b24_user_id", "email", "name", "role",
            "order", "is_required", "decision", "decision_comment", "decided_at",
        ]


class RoundSerializer(serializers.ModelSerializer):
    participants = ParticipantSerializer(many=True, read_only=True)

    class Meta:
        model = ApprovalRound
        fields = [
            "id", "round_number", "result", "comment",
            "started_at", "completed_at", "participants",
        ]


class SheetSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalSheet
        fields = ["id", "format", "generated_at", "generated_by_b24_id", "file_url"]

    def get_file_url(self, obj):
        return f"/api/approvalflow/approvals/{obj.approval_id}/sheet/{obj.id}/download/"


class RouteChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalRouteChangeLog
        fields = [
            "id", "changed_by_b24_id", "changed_at",
            "old_route_snapshot", "new_route_snapshot", "reason",
        ]


class ApprovalListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Approval
        fields = [
            "id", "approval_type", "title", "flow_type", "status",
            "status_display", "current_round", "initiator_b24_id", "created_at",
        ]


class ApprovalDetailSerializer(ApprovalListSerializer):
    rounds = RoundSerializer(many=True, read_only=True)
    sheets = SheetSerializer(many=True, read_only=True)
    route_changes = RouteChangeSerializer(many=True, read_only=True)
    linked_type = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    class Meta(ApprovalListSerializer.Meta):
        fields = ApprovalListSerializer.Meta.fields + [
            "submitted_at", "completed_at", "object_id",
            "linked_type", "rounds", "sheets", "route_changes", "documents",
        ]

    def get_linked_type(self, obj):
        return obj.content_type.model if obj.content_type_id else None

    def get_documents(self, obj):
        # несколько документов, привязанных к согласованию (ТЗ п.7.1)
        from django.contrib.contenttypes.models import ContentType
        from documents import editing
        from documents.models import Document

        ct = ContentType.objects.get_for_model(obj.__class__)
        docs = Document.objects.filter(
            content_type=ct, object_id=obj.pk, deleted_at__isnull=True
        ).select_related("current_version")
        out = []
        for d in docs:
            cur = d.current_version
            out.append({
                "id": d.id,
                "title": d.title,
                "current_version_number": cur.version_number if cur else None,
                "download_url": (
                    f"/api/documents/{d.id}/versions/{cur.id}/download/" if cur else None
                ),
                # можно ли редактировать онлайн (фича включена + подходящий формат)
                "can_edit_online": editing.is_editable(cur),
            })
        return out


class ApprovalCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Approval
        fields = ["id", "approval_type", "title", "flow_type"]
