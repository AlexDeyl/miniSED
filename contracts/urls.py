from rest_framework.routers import DefaultRouter

from .views import ContractViewSet

app_name = "contracts"

router = DefaultRouter()
router.register("contracts", ContractViewSet, basename="contract")

urlpatterns = router.urls
