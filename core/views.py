"""
Read-only API справочников ядра.

Пока только чтение (создание/редактирование — через админку). Позже,
на этапе авторизации, добавится проверка прав manage_directories и CRUD.
"""

from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .auth import get_current_b24_id
from . import services
from .models import (
    CFO,
    Counterparty,
    Department,
    Facility,
    Organization,
    Role,
    UserProfile,
)
from .serializers import (
    CFOSerializer,
    CounterpartySerializer,
    DepartmentSerializer,
    FacilitySerializer,
    OrganizationSerializer,
    RoleSerializer,
    UserProfileMiniSerializer,
)


@api_view(["POST"])
@permission_classes([AllowAny])
def mark_seen(request):
    """
    Отметить карточку просмотренной текущим пользователем.
    Тело: {"linked_type": "app_label.model", "linked_id": <id>}.
    Универсально — используется всеми модулями для счётчиков непросмотренного.
    """
    b24_id = get_current_b24_id(request)
    if not b24_id:
        return Response({"detail": "Требуется авторизация."}, status=401)
    linked_type = request.data.get("linked_type") or ""
    linked_id = request.data.get("linked_id")
    try:
        app_label, model = linked_type.split(".")
        ct = ContentType.objects.get(app_label=app_label, model=model)
    except (ValueError, ContentType.DoesNotExist):
        return Response({"detail": "Неизвестный тип объекта."}, status=400)
    obj = ct.model_class().objects.filter(pk=linked_id).first()
    if obj is None:
        return Response({"detail": "Объект не найден."}, status=404)
    services.mark_seen(b24_id, obj)
    return Response({"ok": True})


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Organization.objects.filter(is_active=True)
    serializer_class = OrganizationSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class FacilityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FacilitySerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = Facility.objects.filter(is_active=True).select_related("organization")
        org = self.request.query_params.get("organization")
        if org:
            qs = qs.filter(organization_id=org)
        return qs


class DepartmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Department.objects.filter(is_active=True)
    serializer_class = DepartmentSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class CFOViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CFO.objects.filter(is_active=True)
    serializer_class = CFOSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class CounterpartyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CounterpartySerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = Counterparty.objects.filter(is_active=True)
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Role.objects.prefetch_related("permissions").all()
    serializer_class = RoleSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class UserProfileViewSet(viewsets.ReadOnlyModelViewSet):
    """Справочник сотрудников для выбора согласующих по ФИО.

    Только активные и с bitrix_id (движок согласований адресует по нему).
    Поиск по ФИО через ?q=.
    """

    serializer_class = UserProfileMiniSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = (
            UserProfile.objects.filter(is_active=True, bitrix_id__isnull=False)
            .select_related("position")
            .order_by("fio")
        )
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(fio__icontains=q)
        return qs
