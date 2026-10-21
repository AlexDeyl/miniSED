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
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
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
            "has_password": bool(user and user.has_usable_password()),
        }
    auth_user = user or profile.auth_user
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
        # Задан ли пароль для входа по почте. Кто входил только через Битрикс,
        # пароля не имеет — ему подсказываем задать его на случай сбоя портала.
        "has_password": bool(auth_user and auth_user.has_usable_password()),
        # Показывать ли раздел «Заявки для исполнения» (комплименты).
        "is_compliment_executor": _is_compliment_executor(profile.bitrix_id),
        # Показывать ли раздел «Работа ИТ» (исполнение заявок на ЭЦП).
        "is_it_specialist": _is_it_specialist(profile.bitrix_id),
        # Показывать ли раздел «Работа службы безопасности» (проверка лиц):
        # сотрудник СБ или юрист, пока функции СБ переданы юротделу.
        "is_security": _is_security(profile.bitrix_id),
        # Показывать ли раздел «Заявки для отдела по работе с персоналом» (ДИ).
        "is_hr_staff": _is_hr_staff(profile.bitrix_id),
    }


def _is_hr_staff(b24_id) -> bool:
    from jobdesc import hr_staff

    return hr_staff.is_hr_staff(b24_id)


def _is_it_specialist(b24_id) -> bool:
    """Назначен ли человек ИТ-специалистом (на объект или без привязки)."""
    if not b24_id:
        return False
    from requests_reg import constants as R
    from requests_reg.models import RoleAssignment

    # Раздел «Работа ИТ» нужен и ИТ-специалисту (ЭЦП), и исполнителю МЧД
    # для СФР (отдел внедрения и разработки ПО).
    return RoleAssignment.objects.filter(
        role_code__in=[R.ROLE_IT_SPECIALIST, R.ROLE_SFR_EXECUTOR],
        user_b24_id=b24_id, is_active=True,
    ).exists()


def _is_security(b24_id) -> bool:
    from requests_reg import check

    return check.can_work_security(b24_id)


def _is_compliment_executor(b24_id) -> bool:
    """Назначен ли человек исполнителем хотя бы одной категории комплиментов
    либо ответственным за ресторан."""
    if not b24_id:
        return False
    from compliments import constants as K
    from compliments.models import Restaurant
    from requests_reg.models import RoleAssignment

    executor_roles = {plan["executor"] for plan in K.CATEGORY_ROUTES.values()}
    return RoleAssignment.objects.filter(
        role_code__in=executor_roles, user_b24_id=b24_id, is_active=True
    ).exists() or Restaurant.objects.filter(executor_b24_id=b24_id).exists()


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    if not email or not password:
        return Response({"detail": "Укажите email и пароль."}, status=400)

    user = authenticate(request, username=_username_for_email(email), password=password)
    if user is None:
        return Response({"detail": "Неверный email или пароль."}, status=401)
    if not user.is_active:
        return Response({"detail": "Пользователь отключён."}, status=403)

    profile = getattr(user, "minised_profile", None)
    token, _ = Token.objects.get_or_create(user=user)
    data = profile_payload(profile, user)
    data["token"] = token.key
    return Response(data)


def _username_for_email(email: str) -> str:
    """Логин учётки по рабочей почте.

    Обычно логин и есть почта. Но учётка, заведённая через Битрикс, могла
    получить логин b24_<id> (почта была занята или пуста) — тогда находим её
    через профиль, если почта однозначно принадлежит одному человеку."""
    exact = User.objects.filter(username__iexact=email).values_list("username", flat=True).first()
    if exact:
        return exact
    usernames = list(
        UserProfile.objects.filter(email__iexact=email, is_active=True, auth_user__isnull=False)
        .values_list("auth_user__username", flat=True)[:2]
    )
    return usernames[0] if len(usernames) == 1 else email


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
#  Пароль: смена (из приложения) и восстановление (по ссылке из письма)
# ---------------------------------------------------------------------------
# Пароль нужен на случай, когда Битрикс24 недоступен: тогда входят по почте.
# Общих паролей «по умолчанию» нет — каждый задаёт свой сам: в приложении
# («Сменить пароль») или по ссылке из письма («Забыли пароль?»).

RESET_EMAIL_COOLDOWN = 120  # сек — не чаще одного письма на адрес


def _check_new_password(user, new_password: str, new_password2: str) -> str | None:
    """Текст ошибки для нового пароля или None, если он годится."""
    if not new_password:
        return "Введите новый пароль."
    if new_password != new_password2:
        return "Пароли не совпадают."
    try:
        validate_password(new_password, user)
    except ValidationError as e:
        return " ".join(e.messages)
    return None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def password_change(request):
    """Смена пароля вошедшим пользователем.

    Кто ещё ни разу не задавал пароль (входил через Битрикс), задаёт его без
    текущего — личность уже подтверждена входом."""
    user = request.user
    if user.has_usable_password() and not user.check_password(
        request.data.get("old_password") or ""
    ):
        return Response({"detail": "Текущий пароль указан неверно."}, status=400)

    error = _check_new_password(
        user, request.data.get("new_password") or "", request.data.get("new_password2") or ""
    )
    if error:
        return Response({"detail": error}, status=400)

    user.set_password(request.data["new_password"])
    user.save(update_fields=["password"])
    return Response({"detail": "Пароль сохранён.", "has_password": True})


def _user_for_reset(email: str):
    """Учётка, которой принадлежит почта, — для письма о восстановлении.

    Сотрудник из справочника, ещё ни разу не входивший, учётки не имеет:
    заводим её (как при первом входе через Битрикс), чтобы задать пароль
    можно было и тогда, когда портал недоступен."""
    user = User.objects.filter(username=_username_for_email(email)).first()
    if user is not None:
        profile = getattr(user, "minised_profile", None)
        if not user.is_active or (profile is not None and not profile.is_active):
            return None
        return user

    profiles = list(UserProfile.objects.filter(email__iexact=email, is_active=True)[:2])
    if len(profiles) != 1:
        return None
    profile = resolve_or_provision_profile(profiles[0].bitrix_id, email, profiles[0].fio)
    return profile.auth_user


def _reset_link(user) -> str:
    """Ссылка на страницу нового пароля — прямо на MiniSED, а не в портал:
    восстановление нужно как раз тогда, когда Битрикс недоступен."""
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{base}/app/?to=/reset-password/{uid}/{token}"


@api_view(["POST"])
@permission_classes([AllowAny])
def password_reset(request):
    """Письмо со ссылкой на смену пароля.

    Ответ всегда одинаковый — по нему нельзя узнать, есть ли такой адрес
    в системе."""
    email = (request.data.get("email") or "").strip().lower()
    if not email:
        return Response({"detail": "Укажите email."}, status=400)

    answer = Response({
        "detail": "Если этот адрес есть в системе, на него отправлено письмо "
                  "со ссылкой для смены пароля.",
    })
    if not cache.add(f"pwd_reset:{email}", 1, RESET_EMAIL_COOLDOWN):
        return answer

    user = _user_for_reset(email)
    if user is None:
        return answer

    profile = getattr(user, "minised_profile", None)
    greeting = f"Здравствуйте, {profile.fio}!" if profile and profile.fio else "Здравствуйте!"
    hours = settings.PASSWORD_RESET_TIMEOUT // 3600
    body = (
        f"{greeting}\n\n"
        "Для вашей учётной записи МиниСЭД запрошена смена пароля.\n"
        "Чтобы задать новый пароль, перейдите по ссылке:\n\n"
        f"{_reset_link(user)}\n\n"
        f"Ссылка действует {hours} ч. и срабатывает один раз.\n"
        "Если вы не запрашивали смену пароля, просто проигнорируйте это письмо — "
        "текущий пароль останется прежним.\n\n"
        "Логин для входа — этот адрес почты."
    )
    try:
        send_mail(
            "МиниСЭД: смена пароля", body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None), [email],
        )
    except Exception as e:  # почта недоступна — ответ тот же, причина в логе
        print("[password reset] send error:", e)
    return answer


@api_view(["POST"])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    """Новый пароль по ссылке из письма. После смены сразу входим."""
    try:
        uid = force_str(urlsafe_base64_decode(request.data.get("uid") or ""))
        user = User.objects.get(pk=uid, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user is None or not default_token_generator.check_token(
        user, request.data.get("token") or ""
    ):
        return Response(
            {"detail": "Ссылка недействительна или устарела. Запросите новую."},
            status=400,
        )

    error = _check_new_password(
        user, request.data.get("new_password") or "", request.data.get("new_password2") or ""
    )
    if error:
        return Response({"detail": error}, status=400)

    user.set_password(request.data["new_password"])
    user.save(update_fields=["password"])

    profile = getattr(user, "minised_profile", None)
    token, _ = Token.objects.get_or_create(user=user)
    data = profile_payload(profile, user)
    data["token"] = token.key
    return Response(data)


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
        # Профиль с ДРУГИМ Битрикс ID — чужой: адрес перешёл к другой учётке
        # (личный ящик сотрудника отдали групповому аккаунту службы). Отдать
        # его значило бы впустить человека под чужим именем.
        if profile and bitrix_id and profile.bitrix_id and profile.bitrix_id != bitrix_id:
            profile = None
        elif profile and bitrix_id and not profile.bitrix_id:
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
        # Учётка с таким логином уже принадлежит другому профилю (тот же
        # перешедший адрес) — её не берём, иначе два человека делят один токен.
        if UserProfile.objects.filter(auth_user__username=username).exclude(pk=profile.pk).exists():
            username = f"b24_{bitrix_id}" if bitrix_id else f"profile_{profile.id}"
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
