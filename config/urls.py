from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from approvals.views import (
    AgreementViewSet,
    ApprovalTemplateViewSet,
    simple_create_agreement,
    app_view,
    external_approve_view,
    register_b24_identity,
    bitrix_auth_start,
    bitrix_auth_callback,
)

router = DefaultRouter()
router.register("agreements", AgreementViewSet, basename="agreement")
router.register("templates", ApprovalTemplateViewSet, basename="template")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("app/", app_view, name="app"),
    path("app", app_view, name="app_no_slash"),
    path(
        "external/approve/<str:token>/", external_approve_view,
        name="external_approve"
    ),
    path(
        "api/agreements/create_simple/",
        simple_create_agreement,
        name="simple_create_agreement",
    ),
    path(
        "api/b24/register_identity/",
        register_b24_identity,
        name="register_b24_identity",
    ),
    path("create/simple/", simple_create_agreement,
         name="simple_create_agreement"),
    path("auth/bitrix/start/", bitrix_auth_start, name="bitrix_auth_start"),
    path("auth/bitrix/callback/", bitrix_auth_callback,
         name="bitrix_auth_callback"),
    path("api/", include(router.urls)),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
