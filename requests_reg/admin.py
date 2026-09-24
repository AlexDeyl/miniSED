from django.contrib import admin

from .models import PowerTemplate, RegulatoryRequest, RoleAssignment, SecurityDelegation


@admin.register(PowerTemplate)
class PowerTemplateAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "powers")


@admin.register(RegulatoryRequest)
class RegulatoryRequestAdmin(admin.ModelAdmin):
    list_display = (
        "number", "request_type", "status", "subject_name",
        "organization", "created_at",
    )
    list_filter = ("request_type", "status", "organization")
    search_fields = ("number", "subject_name", "position")
    readonly_fields = (
        "number", "created_at", "updated_at", "taken_at", "executed_at", "received_at",
    )


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("role_code", "user_b24_id", "user_name", "organization", "cfo", "facility", "is_active")
    list_filter = ("role_code", "is_active", "organization")
    search_fields = ("user_name", "user_b24_id")


@admin.register(SecurityDelegation)
class SecurityDelegationAdmin(admin.ModelAdmin):
    list_display = ("started_at", "started_by_b24_id", "ended_at", "ended_by_b24_id", "comment")
    readonly_fields = ("started_at",)
