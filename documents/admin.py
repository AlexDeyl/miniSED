from django.contrib import admin

from .models import Document, DocumentVersion


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    readonly_fields = ("version_number", "uploaded_at", "checksum", "file_size")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "document_type", "is_confidential", "deleted_at")
    list_filter = ("is_confidential", "document_type")
    search_fields = ("title",)
    inlines = [DocumentVersionInline]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "is_current", "uploaded_at")
    list_filter = ("is_current",)
