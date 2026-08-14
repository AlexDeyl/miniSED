from rest_framework import serializers

from . import editing
from .models import Document, DocumentVersion


class DocumentVersionSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = DocumentVersion
        fields = [
            "id", "version_number", "original_filename", "uploaded_by_b24_id",
            "uploaded_at", "change_comment", "is_current", "file_size",
            "mime_type", "checksum", "download_url",
        ]

    def get_download_url(self, obj):
        return f"/api/documents/{obj.document_id}/versions/{obj.id}/download/"


class DocumentSerializer(serializers.ModelSerializer):
    versions = DocumentVersionSerializer(many=True, read_only=True)
    current_version_number = serializers.IntegerField(
        source="current_version.version_number", read_only=True, default=None
    )
    # Показывать ли кнопку «Редактировать онлайн» (актуальная версия + фича включена).
    can_edit_online = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id", "title", "document_type", "is_confidential",
            "created_by_b24_id", "created_at", "deleted_at",
            "current_version", "current_version_number", "versions",
            "can_edit_online",
        ]

    def get_can_edit_online(self, obj) -> bool:
        return editing.is_editable(obj.current_version)


def linked_documents(obj) -> list[dict]:
    """Документы карточки (договора, заявки…) со всеми версиями.

    Общий вид для всех модулей: версии + can_edit_online из DocumentSerializer
    плюс download_url актуальной версии — по нему качают «текущий» файл."""
    out = []
    for d in obj.documents.filter(deleted_at__isnull=True).prefetch_related("versions"):
        data = DocumentSerializer(d).data
        cur = d.current_version
        data["download_url"] = (
            f"/api/documents/{d.id}/versions/{cur.id}/download/" if cur else None
        )
        out.append(data)
    return out
