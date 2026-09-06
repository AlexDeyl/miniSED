"""
API авторизации MiniSED.

Два способа входа в ОДИН аккаунт (UserProfile):
  1) email + пароль (login);
  2) через Битрикс24 — по связке bitrix_id/email резолвится тот же профиль.
"""

from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse
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
        # Показывать ли раздел «Заявки для исполнения» (комплименты).
        "is_compliment_executor": _is_compliment_executor(profile.bitrix_id),
        # Показывать ли раздел «Работа ИТ» (исполнение заявок на ЭЦП).
        "is_it_specialist": _is_it_specialist(profile.bitrix_id),
    }


def _is_it_specialist(b24_id) -> bool:
    """Назначен ли человек ИТ-специалистом (на объект или без привязки)."""
    if not b24_id:
        return False
    from requests_reg import constants as R
    from requests_reg.models import RoleAssignment

    return RoleAssignment.objects.filter(
        role_code=R.ROLE_IT_SPECIALIST, user_b24_id=b24_id, is_active=True
    ).exists()


def _is_compliment_executor(b24_id) -> bool:
    """Назначен ли человек исполнителем хотя бы одной категории комплиментов."""
    if not b24_id:
        return False
    from compliments import constants as K
    from requests_reg.models import RoleAssignment

    executor_roles = {plan["executor"] for plan in K.CATEGORY_ROUTES.values()}
    return RoleAssignment.objects.filter(
        role_code__in=executor_roles, user_b24_id=b24_id, is_active=True
    ).exists()


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


# ---------------------------------------------------------------------------
#  Вход через Битрикс24 = тот же аккаунт (связка bitrix_id / email)
# ---------------------------------------------------------------------------
def resolve_or_provision_profile(bitrix_id, email, fio="") -> UserProfile:
    """
    Находит профиль по bitrix_id, иначе по email (и до-связывает bitrix_id).
    Если профиля нет — создаёт (первый вход через Битрикс провижнит аккаунт).
    Гарантирует наличие django-User, чтобы можно было выдать токен.
    """
    email = (email or "").strip().lower()
    profile = None
    if bitrix_id:
        profile = UserProfile.objects.filter(bitrix_id=bitrix_id).first()
    if profile is None and email:
        profile = UserProfile.objects.filter(email__iexact=email).first()
        if profile and bitrix_id and not profile.bitrix_id:
            profile.bitrix_id = bitrix_id
            profile.save(update_fields=["bitrix_id"])
    if profile is None:
        profile = UserProfile.objects.create(
            fio=fio or (f"USER #{bitrix_id}" if bitrix_id else email),
            bitrix_id=bitrix_id or None,
            email=email,
        )

    if profile.auth_user is None:
        username = email or (f"b24_{bitrix_id}" if bitrix_id else f"profile_{profile.id}")
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": email}
        )
        if created:
            user.set_unusable_password()  # входит только через Битрикс, пока не задан пароль
            user.save()
        profile.auth_user = user
        profile.save(update_fields=["auth_user"])
    return profile


def _bitrix_user_info(access_token, domain):
    """Возвращает (bitrix_id, email, fio) из user.current."""
    resp = requests.get(
        f"https://{domain}/rest/user.current",
        params={"auth": access_token}, timeout=15,
    )
    u = resp.json().get("result") or {}
    bid = u.get("ID")
    bid = int(bid) if bid else None
    email = u.get("EMAIL") or u.get("WORK_EMAIL") or ""
    fio = " ".join(filter(None, [u.get("LAST_NAME"), u.get("NAME"), u.get("SECOND_NAME")]))
    return bid, email, fio


def _issue_for_bitrix(access_token, domain):
    """access_token+domain → (profile, token) того же аккаунта."""
    bid, email, fio = _bitrix_user_info(access_token, domain)
    if not bid:
        return None, None
    profile = resolve_or_provision_profile(bid, email, fio)
    token, _ = Token.objects.get_or_create(user=profile.auth_user)
    return profile, token


@api_view(["POST"])
@permission_classes([AllowAny])
def bitrix_login(request):
    """
    Вход через Битрикс24 (из iframe: BX24.getAuth → access_token+domain;
    либо OAuth-код). Возвращает токен MiniSED того же аккаунта.
    """
    access_token = (request.data.get("access_token") or "").strip()
    domain = (request.data.get("domain") or "").strip()
    code = (request.data.get("code") or "").strip()

    if code and not access_token:
        try:
            d = requests.get(
                settings.BITRIX_OAUTH_TOKEN_URL,
                params={
                    "grant_type": "authorization_code",
                    "client_id": settings.BITRIX_CLIENT_ID,
                    "client_secret": settings.BITRIX_CLIENT_SECRET,
                    "code": code,
                },
                timeout=15,
            ).json()
            access_token = d.get("access_token")
            domain = domain or d.get("domain")
        except requests.RequestException:
            return Response({"detail": "Не удалось обменять код Битрикс24."}, status=502)

    if not access_token or not domain:
        return Response({"detail": "Нужны access_token и domain."}, status=400)

    try:
        profile, token = _issue_for_bitrix(access_token, domain)
    except requests.RequestException:
        return Response({"detail": "Битрикс24 недоступен."}, status=502)
    if profile is None:
        return Response({"detail": "Не удалось определить пользователя Битрикс24."}, status=400)

    data = profile_payload(profile, profile.auth_user)
    data["token"] = token.key
    return Response(data)


def bitrix_start(request):
    """Старт OAuth-входа через Битрикс24 (для домена, вне iframe)."""
    next_url = request.GET.get("next") or getattr(settings, "FRONTEND_LOGIN_URL", "/")
    request.session["bx_login_next"] = next_url
    redirect_uri = request.build_absolute_uri(reverse("auth_bitrix_callback"))
    params = {
        "client_id": settings.BITRIX_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }
    return redirect(f"{settings.BITRIX_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


def bitrix_callback(request):
    """OAuth-callback: обмен кода → токен MiniSED → редирект на фронт с токеном."""
    next_url = request.session.pop("bx_login_next", None) or getattr(
        settings, "FRONTEND_LOGIN_URL", "/"
    )
    code = request.GET.get("code")
    if not code:
        return redirect(next_url)

    redirect_uri = request.build_absolute_uri(reverse("auth_bitrix_callback"))
    try:
        d = requests.post(
            settings.BITRIX_OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.BITRIX_CLIENT_ID,
                "client_secret": settings.BITRIX_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        ).json()
        access_token = d.get("access_token")
        domain = d.get("domain")
        profile, token = _issue_for_bitrix(access_token, domain)
    except Exception as e:
        print("[Bitrix login] callback error:", e)
        profile, token = None, None

    if token is None:
        sep = "&" if "?" in next_url else "?"
        return redirect(f"{next_url}{sep}bitrix_error=1")

    sep = "&" if "?" in next_url else "?"
    return redirect(f"{next_url}{sep}bitrix_token={token.key}")
