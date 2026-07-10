from django.contrib import admin

from .models import BitrixApiLog, BitrixPortal, BitrixToken


@admin.register(BitrixPortal)
class BitrixPortalAdmin(admin.ModelAdmin):
    list_display = ("id", "domain", "member_id", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("domain", "member_id")


@admin.register(BitrixToken)
class BitrixTokenAdmin(admin.ModelAdmin):
    list_display = ("portal", "expires_at", "updated_at")
    # Токены не показываем целиком в списке — только служебные поля.
    readonly_fields = ("updated_at",)


@admin.register(BitrixApiLog)
class BitrixApiLogAdmin(admin.ModelAdmin):
    list_display = ("id", "portal", "method", "ok", "status_code", "created_at")
    list_filter = ("ok", "method")
    search_fields = ("method", "error")
    readonly_fields = ("portal", "method", "ok", "status_code", "error", "created_at")
