from django.contrib import admin
from .models import Agreement, AgreementDocument, Participant, B24UserEmail


class AgreementDocumentInline(admin.TabularInline):
    model = AgreementDocument
    extra = 0


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "author_b24_id", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "description")
    inlines = [AgreementDocumentInline, ParticipantInline]


@admin.register(B24UserEmail)
class B24UserEmailAdmin(admin.ModelAdmin):
    list_display = ("b24_user_id", "email")
    search_fields = ("b24_user_id", "email")
    ordering = ("b24_user_id", "email")


admin.site.register(Participant)
admin.site.register(AgreementDocument)
