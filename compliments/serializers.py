from rest_framework import serializers

from approvalflow.serializers import ApprovalDetailSerializer
from documents.serializers import linked_documents

from . import constants, services
from .models import Compliment


class ComplimentListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="status_label", read_only=True)
    category_display = serializers.CharField(source="category_label", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True, default=None)
    restaurant_name = serializers.CharField(source="restaurant.name", read_only=True, default=None)

    class Meta:
        model = Compliment
        fields = [
            "id", "number", "title", "category", "category_display",
            "company", "event_at", "facility", "facility_name",
            "restaurant", "restaurant_name",
            "status", "status_display", "initiator_b24_id", "executor_b24_id",
            "created_at",
        ]


class ComplimentDetailSerializer(ComplimentListSerializer):
    approval = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    class Meta(ComplimentListSerializer.Meta):
        fields = ComplimentListSerializer.Meta.fields + [
            "category_details", "guest_name", "description", "department",
            "organization", "needs_ceo", "data",
            "taken_at", "executed_at", "execution_comment",
            "updated_at", "approval", "documents",
        ]

    def get_approval(self, obj):
        approval = services.get_approval(obj)
        return ApprovalDetailSerializer(approval).data if approval else None

    def get_documents(self, obj):
        return linked_documents(obj)


class ComplimentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Compliment
        fields = [
            "title", "category", "category_details", "company", "guest_name",
            "event_at", "facility", "organization", "restaurant", "description",
            "department", "needs_ceo", "executor_b24_id", "data",
        ]

    def validate_title(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите наименование заявки.")
        return value

    def validate_company(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите компанию — получателя комплимента.")
        return value

    def validate(self, attrs):
        """Ресторан обязателен для ресторанной категории и только для неё —
        от него зависит исполнитель. Сменили категорию или ресторан —
        сбрасываем закреплённого исполнителя: при отправке он подберётся
        заново по новому ресторану."""
        inst = self.instance
        category = attrs.get("category", inst.category if inst else None)
        restaurant = attrs.get("restaurant", inst.restaurant if inst else None)
        if category == constants.CATEGORY_RESTAURANT:
            if restaurant is None:
                raise serializers.ValidationError({"restaurant": "Выберите ресторан."})
            if not restaurant.is_active and (inst is None or inst.restaurant_id != restaurant.id):
                raise serializers.ValidationError({"restaurant": "Ресторан недоступен для выбора."})
        else:
            attrs["restaurant"] = None
        new_restaurant_id = attrs["restaurant"].id if attrs.get("restaurant") else None
        if inst is not None and "executor_b24_id" not in attrs and (
            category != inst.category
            or ("restaurant" in attrs and new_restaurant_id != inst.restaurant_id)
        ):
            attrs["executor_b24_id"] = None
        return attrs
