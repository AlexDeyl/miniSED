from rest_framework.routers import DefaultRouter

from . import views

app_name = "core"

router = DefaultRouter()
router.register("organizations", views.OrganizationViewSet, basename="organization")
router.register("facilities", views.FacilityViewSet, basename="facility")
router.register("departments", views.DepartmentViewSet, basename="department")
router.register("cfos", views.CFOViewSet, basename="cfo")
router.register("counterparties", views.CounterpartyViewSet, basename="counterparty")
router.register("roles", views.RoleViewSet, basename="role")

urlpatterns = router.urls
