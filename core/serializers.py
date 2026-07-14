from rest_framework import serializers

from .models import (
    CFO,
    Counterparty,
    Department,
    Facility,
    Organization,
    Role,
    UserProfile,
)


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "short_name", "full_name", "inn", "kpp", "is_active"]


class FacilitySerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(
        source="organization.short_name", read_only=True
    )

    class Meta:
        model = Facility
        fields = [
            "id", "name", "organization", "organization_name",
            "address", "ops_director", "is_active",
        ]


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "organization", "parent", "is_active"]


class CFOSerializer(serializers.ModelSerializer):
    class Meta:
        model = CFO
        fields = ["id", "name", "code", "organization", "head", "is_active"]


class CounterpartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Counterparty
        fields = ["id", "name", "inn", "kpp", "ogrn", "is_active"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(
        slug_field="code", many=True, read_only=True
    )

    class Meta:
        model = Role
        fields = ["id", "code", "name", "kind", "permissions"]


class UserProfileMiniSerializer(serializers.ModelSerializer):
    """Краткий справочник сотрудников для выбора согласующих по ФИО."""

    position_name = serializers.CharField(source="position.name", read_only=True)

    class Meta:
        model = UserProfile
        fields = ["id", "fio", "bitrix_id", "position_name"]
