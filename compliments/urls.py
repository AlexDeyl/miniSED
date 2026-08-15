from rest_framework.routers import DefaultRouter

from .views import ComplimentViewSet

app_name = "compliments"

router = DefaultRouter()
router.register("compliments", ComplimentViewSet, basename="compliment")

urlpatterns = router.urls
