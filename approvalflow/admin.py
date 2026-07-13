from django.contrib import admin

from .models import (
    Approval,
    ApprovalParticipant,
    ApprovalRound,
    ApprovalRouteChangeLog,
    ApprovalSheet,
)


class ApprovalParticipantInline(admin.TabularInline):
    model = ApprovalParticipant
    extra = 0


class ApprovalRoundInline(admin.TabularInline):
    model = ApprovalRound
    extra = 0
    readonly_fields = ("round_number", "result", "started_at", "completed_at")
    show_change_link = True


@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "approval_type", "status", "current_round",
        "initiator_b24_id", "created_at",
    )
    list_filter = ("status", "approval_type", "flow_type")
    search_fields = ("title",)
    inlines = [ApprovalRoundInline]


@admin.register(ApprovalRound)
class ApprovalRoundAdmin(admin.ModelAdmin):
    list_display = ("id", "approval", "round_number", "result", "completed_at")
    list_filter = ("result",)
    inlines = [ApprovalParticipantInline]


@admin.register(ApprovalRouteChangeLog)
class ApprovalRouteChangeLogAdmin(admin.ModelAdmin):
    list_display = ("id", "approval", "changed_by_b24_id", "changed_at", "reason")
    readonly_fields = [f.name for f in ApprovalRouteChangeLog._meta.fields]


@admin.register(ApprovalSheet)
class ApprovalSheetAdmin(admin.ModelAdmin):
    list_display = ("id", "approval", "format", "generated_by_b24_id", "generated_at")
