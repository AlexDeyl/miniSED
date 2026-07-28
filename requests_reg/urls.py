from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import RegulatoryRequestViewSet, address_suggest, fms_unit

app_name = "requests_reg"

router = DefaultRouter()
router.register("requests", RegulatoryRequestViewSet, basename="request")

urlpatterns = [
    path("fms-unit/", fms_unit, name="fms_unit"),
    path("address-suggest/", address_suggest, name="address_suggest"),
    *router.urls,
]
