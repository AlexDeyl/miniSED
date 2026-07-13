from django.contrib import admin

from .models import (
    CFO,
    AuditLog,
    Counterparty,
    Department,
    ExternalLink,
    Facility,
    IntegrationEvent,
    Organization,
    Permission,
    Position,
    Role,
    UserProfile,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("short_name", "inn", "kpp", "is_active")
    list_filter = ("is_active",)
    search_fields = ("short_name", "full_name", "inn")


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "ops_director", "is_active")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "address")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "parent", "is_active")
    list_filter = ("is_active", "organization")
    search_fields = ("name",)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)


@admin.register(CFO)
class CFOAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "head", "is_active")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "code")


@admin.register(Counterparty)
class CounterpartyAdmin(admin.ModelAdmin):
    list_display = ("name", "inn", "kpp", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "inn")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category")
    list_filter = ("category",)
    search_fields = ("code", "name")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind")
    list_filter = ("kind",)
    search_fields = ("name", "code")
    filter_horizontal = ("permissions",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("fio", "email", "bitrix_id", "position", "is_active")
    list_filter = ("is_active", "roles", "organizations")
    search_fields = ("fio", "email", "bitrix_id")
    filter_horizontal = ("roles", "organizations", "facilities")


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "entity_type", "external_id", "title", "last_sync_at")
    list_filter = ("source", "entity_type")
    search_fields = ("external_id", "title")


@admin.register(IntegrationEvent)
class IntegrationEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "status", "target_system", "retry_count", "created_at")
    list_filter = ("status", "event_type", "target_system")
    search_fields = ("event_type",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "actor_repr", "object_repr", "ip", "created_at")
    list_filter = ("action",)
    search_fields = ("actor_repr", "object_repr", "action")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
