"""
Онлайн-редактирование документов через сервер документов семейства
OnlyOffice / Р7-Офис (ТЗ п.7.2-7.3).

Слой намеренно провайдер-агностичный: у OnlyOffice и Р7-Офиса ОДИН контракт
(фронт монтирует `DocsAPI.DocEditor(config)`, сервер документов ходит к нам за
файлом и присылает результат в callback, всё подписано общим JWT HS256).
Выбор конкретного продукта — это лишь смена `DOCS_EDITOR_SERVER_URL` на деплое.

Ответственность модуля:
  * feature-gate (`is_enabled`, `is_editable`);
  * генерация `editor_key`, меняющегося при смене содержимого;
  * сборка и подпись конфига редактора для фронта;
  * выдача серверу документов защищённых токеном URL (скачать файл / callback);
  * приём callback и создание НОВОЙ версии через documents.services.

JWT реализован на stdlib (hmac/base64), чтобы дремлющая фича не тянула
рантайм-зависимость до включения. OnlyOffice/Р7 достаточно HS256.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlsplit

from django.conf import settings

from . import services
from .models import Document, DocumentVersion, EditSession

# Сопоставление расширения → тип редактора сервера документов.
_WORD_EXTS = {"doc", "docx", "docm", "dot", "dotx", "odt", "ott", "rtf", "txt", "fodt"}
_CELL_EXTS = {"xls", "xlsx", "xlsm", "ods", "ots", "csv", "fods"}
_SLIDE_EXTS = {"ppt", "pptx", "pptm", "odp", "otp", "fodp"}


# --------------------------------------------------------------------------- #
# Конфигурация / фиче-гейт
# --------------------------------------------------------------------------- #
def is_enabled() -> bool:
    """Фича включена и сервер документов сконфигурирован."""
    return bool(settings.DOCS_EDITOR_ENABLED and settings.DOCS_EDITOR_SERVER_URL)


def _jwt_secret() -> str:
    return settings.DOCS_EDITOR_JWT_SECRET or ""


def extension(name: str) -> str:
    _, ext = os.path.splitext(name or "")
    return ext.lstrip(".").lower()


def is_editable(version: DocumentVersion | None) -> bool:
    """Можно ли открыть эту версию в онлайн-редакторе."""
    if not is_enabled() or version is None or not version.file:
        return False
    ext = extension(version.original_filename or version.file.name)
    return ext in {e.lower() for e in settings.DOCS_EDITOR_EDITABLE_EXTS}


def document_type_for(ext: str) -> str:
    """Тип редактора для сервера документов: word | cell | slide."""
    if ext in _CELL_EXTS:
        return "cell"
    if ext in _SLIDE_EXTS:
        return "slide"
    return "word"


# --------------------------------------------------------------------------- #
# JWT HS256 (self-contained)
# --------------------------------------------------------------------------- #
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def jwt_encode(payload: dict) -> str:
    """Подписать payload секретом сервера документов (HS256)."""
    secret = _jwt_secret()
    header = {"alg": "HS256", "typ": "JWT"}
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode()),
        _b64url(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode("ascii")
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(sig))
    return ".".join(segments)


def jwt_decode(token: str) -> dict | None:
    """Проверить подпись и срок, вернуть payload либо None."""
    secret = _jwt_secret()
    try:
        header_seg, payload_seg, sig_seg = token.split(".")
    except (ValueError, AttributeError):
        return None
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig_seg)):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_seg))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = payload.get("exp")
    if exp is not None and time.time() > exp:
        return None
    return payload


# --------------------------------------------------------------------------- #
# Ключ документа
# --------------------------------------------------------------------------- #
def editor_key(version: DocumentVersion) -> str:
    """
    Уникальный ключ версии для сервера документов.

    ОБЯЗАН меняться при любой смене содержимого, иначе сервер документов отдаёт
    закэшированную копию. Привязка к checksum это гарантирует; длина ≤128 и
    только [A-Za-z0-9-] — как требует OnlyOffice/Р7.
    """
    stamp = (version.checksum or "")[:16] or str(int(version.uploaded_at.timestamp()))
    return f"doc{version.document_id}-v{version.version_number}-{stamp}"


# --------------------------------------------------------------------------- #
# URL для сервера документов (сервер→сервер, вне пользовательской сессии)
# --------------------------------------------------------------------------- #
def _callback_base() -> str:
    return settings.DOCS_EDITOR_CALLBACK_BASE_URL or ""


def internalize_ds_url(url: str) -> str:
    """
    Переписать URL, который сервер документов дал нам для скачивания результата,
    на ПРЯМОЙ адрес контейнера (DOCS_EDITOR_INTERNAL_URL).

    OnlyOffice строит ссылку из внешнего контекста запроса — напр.
    `https://devmsed.nordhotels.ru/ds/cache/…`. MiniSED на том же хосте резолвит
    домен в себя и упирается в self-signed TLS на :443 → requests падает на
    проверке сертификата. Контейнер доступен с хоста напрямую по http, поэтому
    берём путь (сняв внешний субпуть вроде `/ds`) и подставляем внутренний адрес.
    Подписанные параметры (md5/expires/shardkey) считаются по пути, а не по хосту,
    поэтому смена схемы/хоста их не ломает.

    Если DOCS_EDITOR_INTERNAL_URL не задан (напр., прод с валидным TLS) — URL
    остаётся как есть.
    """
    internal = (getattr(settings, "DOCS_EDITOR_INTERNAL_URL", "") or "").rstrip("/")
    if not internal:
        return url
    parts = urlsplit(url)
    path = parts.path
    subpath = urlsplit(settings.DOCS_EDITOR_SERVER_URL).path.rstrip("/")
    if subpath and (path == subpath or path.startswith(subpath + "/")):
        path = path[len(subpath):] or "/"
    return internal + path + (f"?{parts.query}" if parts.query else "")


def _download_url(version: DocumentVersion, *, ttl: int = 6 * 3600) -> str:
    token = jwt_encode({"typ": "dl", "vid": version.id, "exp": int(time.time()) + ttl})
    return (
        f"{_callback_base()}/api/documents/{version.document_id}"
        f"/versions/{version.id}/ds-download/?t={token}"
    )


def _callback_url(session: EditSession, *, ttl: int = 24 * 3600) -> str:
    token = jwt_encode(
        {"typ": "cb", "sid": session.id, "exp": int(time.time()) + ttl}
    )
    return (
        f"{_callback_base()}/api/documents/{session.document_id}"
        f"/editor-callback/?t={token}"
    )


# --------------------------------------------------------------------------- #
# Сессия + конфиг редактора
# --------------------------------------------------------------------------- #
def open_session(
    document: Document, *, b24_id: int | None
) -> EditSession:
    """
    Получить активную сессию для актуальной версии документа (или создать).

    Совместное редактирование: одна активная сессия на (документ, версия) —
    второй пользователь получает тот же editor_key и попадает в тот же сеанс.
    """
    version = document.current_version
    if version is None:
        raise ValueError("У документа нет версии для редактирования.")

    key = editor_key(version)
    session = (
        EditSession.objects.filter(
            document=document,
            base_version=version,
            editor_key=key,
            status__in=[EditSession.STATUS_ACTIVE, EditSession.STATUS_SAVING],
        )
        .order_by("-id")
        .first()
    )
    if session is None:
        session = EditSession.objects.create(
            document=document,
            base_version=version,
            editor_key=key,
            opened_by_b24_id=b24_id,
        )
    return session


def build_config(
    document: Document,
    *,
    b24_id: int | None,
    user_name: str = "",
    can_edit: bool = True,
    lang: str = "ru",
) -> dict:
    """
    Собрать конфиг для `DocsAPI.DocEditor` на фронте.

    Возвращает готовый объект (включая подписанный `token`, если задан секрет) и
    `serverUrl` — базу, с которой фронт грузит `api.js`. Всё, что фронту нужно
    знать о провайдере, приходит отсюда — Vue-компонент остаётся тонким.
    """
    version = document.current_version
    session = open_session(document, b24_id=b24_id)

    filename = version.original_filename or version.file.name
    ext = extension(filename)
    mode = "edit" if can_edit else "view"

    config = {
        "type": "desktop",
        "documentType": document_type_for(ext),
        "document": {
            "title": document.title or filename,
            "fileType": ext,
            "key": session.editor_key,
            "url": _download_url(version),
            "permissions": {
                "edit": can_edit,
                "download": True,
                "print": True,
            },
        },
        "editorConfig": {
            "mode": mode,
            "lang": lang,
            "callbackUrl": _callback_url(session),
            "user": {
                "id": str(b24_id or "anon"),
                "name": user_name or (f"Сотрудник {b24_id}" if b24_id else "Гость"),
            },
            "customization": {
                "forcesave": True,   # сохранять по кнопке, не только по закрытию
                "autosave": True,
            },
        },
    }
    if _jwt_secret():
        config["token"] = jwt_encode(config)

    return {
        "serverUrl": settings.DOCS_EDITOR_SERVER_URL,
        "provider": settings.DOCS_EDITOR_PROVIDER,
        "session_id": session.id,
        "config": config,
    }


# --------------------------------------------------------------------------- #
# Приём результата (callback от сервера документов)
# --------------------------------------------------------------------------- #
# Коды статусов OnlyOffice/Р7:
#   1 — редактируется; 2 — готов к сохранению; 3 — ошибка сохранения;
#   4 — закрыт без изменений; 6 — принудительное сохранение (forcesave);
#   7 — ошибка принудительного сохранения.
_STATUS_SAVE = (2, 6)
_STATUS_ERROR = (3, 7)
_STATUS_NOCHANGE = (4,)


def handle_callback(session: EditSession, payload: dict) -> dict:
    """
    Обработать один callback. Возвращает тело ответа серверу документов —
    он ждёт строго `{"error": 0}`, иначе считает доставку неуспешной и повторит.
    """
    status = payload.get("status")
    session.last_callback_status = status

    if status in _STATUS_SAVE:
        url = payload.get("url")
        if not url:
            session.status = EditSession.STATUS_ERROR
            session.error_detail = "callback без url при статусе сохранения"
            session.save(update_fields=["status", "error_detail", "last_callback_status"])
            return {"error": 1}
        try:
            version = _save_edited(session, url, payload)
        except Exception as exc:  # noqa: BLE001 — best-effort, детали в сессию
            session.status = EditSession.STATUS_ERROR
            session.error_detail = str(exc)[:2000]
            session.save(update_fields=["status", "error_detail", "last_callback_status"])
            return {"error": 1}
        session.saved_version = version
        # forcesave (6) не закрывает сеанс — пользователь ещё редактирует.
        session.status = (
            EditSession.STATUS_CLOSED if status == 2 else EditSession.STATUS_ACTIVE
        )
        if status == 2:
            from django.utils import timezone

            session.closed_at = timezone.now()
        session.save()
        return {"error": 0}

    if status in _STATUS_ERROR:
        session.status = EditSession.STATUS_ERROR
        session.error_detail = f"сервер документов вернул статус {status}"
        session.save(update_fields=["status", "error_detail", "last_callback_status"])
        return {"error": 0}

    if status in _STATUS_NOCHANGE:
        from django.utils import timezone

        session.status = EditSession.STATUS_CLOSED
        session.closed_at = timezone.now()
        session.save(update_fields=["status", "closed_at", "last_callback_status"])
        return {"error": 0}

    # status 1 (редактируется) и прочее — просто фиксируем.
    session.save(update_fields=["last_callback_status"])
    return {"error": 0}


def _save_edited(session: EditSession, url: str, payload: dict) -> DocumentVersion:
    """Скачать отредактированный файл у сервера документов и создать версию."""
    import requests
    from django.core.files.base import ContentFile

    session.status = EditSession.STATUS_SAVING
    session.save(update_fields=["status", "last_callback_status"])

    resp = requests.get(internalize_ds_url(url), timeout=60)
    resp.raise_for_status()

    base = session.base_version
    base_name = base.original_filename or base.file.name
    content = ContentFile(resp.content, name=base_name)

    editor_uid = None
    users = payload.get("users") or []
    if users:
        try:
            editor_uid = int(users[0])
        except (TypeError, ValueError):
            editor_uid = None

    return services.add_version(
        session.document,
        content,
        uploaded_by_b24_id=editor_uid or session.opened_by_b24_id,
        change_comment="Онлайн-редактирование",
    )
