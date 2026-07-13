from rest_framework.routers import DefaultRouter

from .views import ApprovalViewSet

app_name = "approvalflow"

router = DefaultRouter()
router.register("approvals", ApprovalViewSet, basename="approval")

urlpatterns = router.urls
