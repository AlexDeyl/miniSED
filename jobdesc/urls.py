from rest_framework.routers import DefaultRouter

from .views import JobDescViewSet

app_name = "jobdesc"

router = DefaultRouter()
router.register("jobdesc", JobDescViewSet, basename="jobdesc")

urlpatterns = router.urls
