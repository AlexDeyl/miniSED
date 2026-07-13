from django import forms
from django.contrib import admin
from django.contrib.auth.models import User

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


class UserProfileAdminForm(forms.ModelForm):
    """Позволяет админу завести вход (email+пароль) прямо в карточке профиля."""

    password = forms.CharField(
        label="Пароль для входа",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Задать/сменить пароль. Логин = email. Оставьте пустым, чтобы не менять.",
    )

    class Meta:
        model = UserProfile
        fields = "__all__"

    def save(self, commit=True):
        profile = super().save(commit=False)
        email = (profile.email or "").strip().lower()
        pwd = self.cleaned_data.get("password")

        if email:
            user = profile.auth_user
            if user is None:
                user, _ = User.objects.get_or_create(
                    username=email, defaults={"email": email}
                )
                profile.auth_user = user
            # синхронизируем email/username и активность
            if user.username != email:
                user.username = email
            user.email = email
            user.is_active = profile.is_active
            if pwd:
                user.set_password(pwd)
            user.save()

        if commit:
            profile.save()
            self.save_m2m()
        return profile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    form = UserProfileAdminForm
    list_display = ("fio", "email", "bitrix_id", "position", "has_login", "is_active")
    list_filter = ("is_active", "roles", "organizations")
    search_fields = ("fio", "email", "bitrix_id")
    filter_horizontal = ("roles", "organizations", "facilities")

    @admin.display(boolean=True, description="Вход")
    def has_login(self, obj):
        return obj.auth_user_id is not None


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
