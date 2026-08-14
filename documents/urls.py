from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DocumentViewSet, ds_download, editor_callback

app_name = "documents"

router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="document")

# Эндпоинты сервер→сервер редактора идут ДО роутера и в обход DRF-гейта:
# сервер документов авторизуется токеном в URL, а не пользовательской сессией.
urlpatterns = [
    path(
        "documents/<int:pk>/versions/<int:version_id>/ds-download/",
        ds_download,
        name="ds_download",
    ),
    path(
        "documents/<int:pk>/editor-callback/",
        editor_callback,
        name="editor_callback",
    ),
] + router.urls
