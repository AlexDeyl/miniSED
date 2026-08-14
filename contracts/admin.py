from django.contrib import admin

from .models import Contract


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "id", "number", "title", "organization", "cfo",
        "amount", "is_nonstandard", "has_disagreement_protocol", "status",
    )
    list_filter = ("status", "is_nonstandard", "has_disagreement_protocol")
    search_fields = ("number", "title")
    readonly_fields = ("number", "created_at", "updated_at")
