from django.urls import path

from . import views

app_name = "bitrix"

urlpatterns = [
    path("auth/", views.bitrix_auth, name="auth"),
    path("status/", views.bitrix_status, name="status"),
    path("deals/", views.deals_search, name="deals_search"),
    path("deals/<int:deal_id>/", views.deal_detail, name="deal_detail"),
    path("users/", views.users_search, name="users_search"),
    path("timeline/", views.timeline_comment, name="timeline_comment"),
]
