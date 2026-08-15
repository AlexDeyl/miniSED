from django.contrib import admin

from .models import Compliment


@admin.register(Compliment)
class ComplimentAdmin(admin.ModelAdmin):
    list_display = (
        "number", "title", "category", "company", "event_at",
        "status", "initiator_b24_id", "executor_b24_id",
    )
    list_filter = ("status", "category", "facility")
    search_fields = ("number", "title", "company", "guest_name")
    readonly_fields = ("created_at", "updated_at", "taken_at", "executed_at")
