"""
Read-only API справочников ядра.

Пока только чтение (создание/редактирование — через админку). Позже,
на этапе авторизации, добавится проверка прав manage_directories и CRUD.
"""

from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from .models import CFO, Counterparty, Department, Facility, Organization, Role
from .serializers import (
    CFOSerializer,
    CounterpartySerializer,
    DepartmentSerializer,
    FacilitySerializer,
    OrganizationSerializer,
    RoleSerializer,
)


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
