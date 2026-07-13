from django.contrib import admin

from .models import RegulatoryRequest


@admin.register(RegulatoryRequest)
class RegulatoryRequestAdmin(admin.ModelAdmin):
    list_display = (
        "number", "request_type", "status", "subject_name",
        "organization", "created_at",
    )
    list_filter = ("request_type", "status", "organization")
    search_fields = ("number", "subject_name", "position")
    readonly_fields = ("number", "created_at", "updated_at")
