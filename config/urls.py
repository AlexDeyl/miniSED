from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve
from rest_framework.routers import DefaultRouter
from core import auth_views
from requests_reg.public_views import reg_external_approve
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
    # Собранные ассеты SPA (frontend/dist/assets). В проде их отдаёт nginx,
    # но при открытии из Битрикса через Django нужен и этот маршрут.
    path(
        "assets/<path:path>",
        static_serve,
        {"document_root": settings.BASE_DIR / "frontend" / "dist" / "assets"},
        name="spa_assets",
    ),
    path(
        "external/approve/<str:token>/", external_approve_view,
        name="external_approve"
    ),
    path(
        "external/reg/approve/<str:token>/", reg_external_approve,
        name="reg_external_approve"
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
    path("api/auth/login/", auth_views.login, name="auth_login"),
    path("api/auth/me/", auth_views.me, name="auth_me"),
    path("api/auth/logout/", auth_views.logout, name="auth_logout"),
    path("api/auth/bitrix/", auth_views.bitrix_login, name="auth_bitrix_login"),
    path("api/auth/bitrix/start/", auth_views.bitrix_start, name="auth_bitrix_start"),
    path("api/auth/bitrix/callback/", auth_views.bitrix_callback, name="auth_bitrix_callback"),
    path("api/bitrix/", include("bitrix.urls")),
    path("api/core/", include("core.urls")),
    path("api/approvalflow/", include("approvalflow.urls")),
    path("api/reg/", include("requests_reg.urls")),
    path("api/", include("documents.urls")),
    path("api/", include(router.urls)),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
