"""
Определение текущего пользователя.

Два режима (параллельно):
  1) Вход в MiniSED по email+пароль → токен → request.user (Django User),
     связанный с UserProfile. Личность = UserProfile.bitrix_id.
  2) Запуск из Битрикс24 → заголовок X-B24-User (переходный режим).
"""

from __future__ import annotations


def get_current_profile(request):
    """UserProfile авторизованного пользователя MiniSED (или None)."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return getattr(user, "minised_profile", None)
    return None


def get_current_b24_id(request) -> int | None:
    # 1) авторизованный пользователь MiniSED
    profile = get_current_profile(request)
    if profile is not None and profile.bitrix_id:
        return profile.bitrix_id

    # 2) режим Битрикс24 — заголовок X-B24-User
    header = request.META.get("HTTP_X_B24_USER")
    if header:
        try:
            return int(header)
        except (TypeError, ValueError):
            pass

    session_id = request.session.get("b24_user_id") if hasattr(request, "session") else None
    if session_id:
        try:
            return int(session_id)
        except (TypeError, ValueError):
            pass

    return None


def is_lawyer(b24_id) -> bool:
    """Есть ли у сотрудника (по bitrix_id) право юриста (legal_manage).

    Так определяется член юротдела: для гейтинга раздела «Заявки для юристов»
    и группового согласования юрэтапа (любой юрист может согласовать)."""
    if not b24_id:
        return False
    from .models import UserProfile

    profile = UserProfile.objects.filter(bitrix_id=b24_id, is_active=True).first()
    return bool(profile and profile.has_perm("legal_manage"))


def lawyer_b24_ids() -> list[int]:
    """b24-id всех активных сотрудников с правом юриста (legal_manage).

    Состав юротдела как множество: на нём строятся групповые юр-этапы,
    уведомления юристам и общая видимость юр-дел внутри отдела."""
    from .models import UserProfile

    return list(
        UserProfile.objects.filter(
            is_active=True,
            bitrix_id__isnull=False,
            roles__permissions__code="legal_manage",
        )
        .values_list("bitrix_id", flat=True)
        .distinct()
    )
