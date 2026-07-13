"""
Общий помощник определения текущего пользователя.

Переходный контракт (как в approvals): личность = b24_user_id, приходит
заголовком X-B24-User (из фронта) или из сессии после OAuth. На этапе
авторизации будет заменён на нормальную сессию/токен MiniSED — правки
локализуются здесь.
"""

from __future__ import annotations


def get_current_b24_id(request) -> int | None:
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
