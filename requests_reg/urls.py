from rest_framework.routers import DefaultRouter

from .views import RegulatoryRequestViewSet

app_name = "requests_reg"

router = DefaultRouter()
router.register("requests", RegulatoryRequestViewSet, basename="request")

urlpatterns = router.urls
