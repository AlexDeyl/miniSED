from django.contrib import admin

from .models import HrStaff, JobDescription


@admin.register(JobDescription)
class JobDescriptionAdmin(admin.ModelAdmin):
    list_display = (
        "number", "position_name", "organization", "cfo",
        "status", "initiator_b24_id", "executor_b24_id",
    )
    list_filter = ("status", "organization", "cfo")
    search_fields = ("number", "position_name")
    readonly_fields = ("created_at", "updated_at", "taken_at", "executed_at", "received_at")


@admin.register(HrStaff)
class HrStaffAdmin(admin.ModelAdmin):
    list_display = ("fio", "b24_user_id", "position", "source", "is_active", "synced_at")
    list_filter = ("source", "is_active")
    list_editable = ("is_active",)
    search_fields = ("fio", "b24_user_id")
    readonly_fields = ("synced_at",)
