"""
API авторизации MiniSED (email + пароль → токен).
"""

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import UserProfile


def profile_payload(profile: UserProfile | None, user=None) -> dict:
    if profile is None:
        return {
            "authenticated": True,
            "profile": None,
            "email": getattr(user, "email", "") or getattr(user, "username", ""),
        }
    role_codes = list(profile.roles.values_list("code", flat=True))
    perm_codes = list(
        profile.roles.filter(permissions__isnull=False)
        .values_list("permissions__code", flat=True)
        .distinct()
    )
    return {
        "authenticated": True,
        "id": profile.id,
        "fio": profile.fio,
        "email": profile.email,
        "bitrix_id": profile.bitrix_id,
        "is_active": profile.is_active,
        "roles": role_codes,
        "permissions": perm_codes,
        "organizations": list(profile.organizations.values_list("id", flat=True)),
    }


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    if not email or not password:
        return Response({"detail": "Укажите email и пароль."}, status=400)

    user = authenticate(request, username=email, password=password)
    if user is None:
        return Response({"detail": "Неверный email или пароль."}, status=401)
    if not user.is_active:
        return Response({"detail": "Пользователь отключён."}, status=403)

    profile = getattr(user, "minised_profile", None)
    token, _ = Token.objects.get_or_create(user=user)
    data = profile_payload(profile, user)
    data["token"] = token.key
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    profile = getattr(request.user, "minised_profile", None)
    return Response(profile_payload(profile, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
