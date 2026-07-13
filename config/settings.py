import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем переменные окружения из .env (если файл есть).
# На сервере переменные могут приходить из окружения systemd — тогда .env не нужен.
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Хелперы чтения окружения
# ---------------------------------------------------------------------------
def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Базовое
# ---------------------------------------------------------------------------
DEBUG = env_bool("DEBUG", default=False)

# В DEBUG допускаем небезопасный ключ по умолчанию — только для локальной разработки.
# В продакшене SECRET_KEY обязателен и должен приходить из окружения.
SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-dev-only-key-change-me"
    else:
        raise RuntimeError(
            "SECRET_KEY не задан. Задайте переменную окружения SECRET_KEY "
            "(см. .env.example)."
        )

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default="127.0.0.1,localhost")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
    "approvals",
    "bitrix",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Вместо XFrameOptionsMiddleware управляем встраиванием в iframe
    # через CSP frame-ancestors (позволяет точечно разрешить домены Битрикс24).
    "config.middleware.FrameAncestorsMiddleware",
]

# Клик-джекинг мы закрываем через CSP frame-ancestors (FrameAncestorsMiddleware),
# поэтому штатный X-Frame-Options-мидлвар намеренно не используем.
SILENCED_SYSTEM_CHECKS = ["security.W002"]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}


# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------
# DB_ENGINE:
#   "sqlite"   -> локальная разработка / промежуточный этап (по умолчанию)
#   "postgres" -> продакшн (требует DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT)
#
# Такой переключатель нужен для миграции сервера с SQLite на PostgreSQL
# без потери данных: сначала dumpdata на SQLite, затем loaddata на PostgreSQL.
DB_ENGINE = env("DB_ENGINE", "sqlite").strip().lower()

if DB_ENGINE in ("postgres", "postgresql"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "minised"),
            "USER": env("DB_USER", "minised"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ---------------------------------------------------------------------------
# Встраивание в iframe (Битрикс24) + доверенные источники
# ---------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Домены, которым разрешено встраивать MiniSED в iframe.
# По умолчанию — сам сайт и порталы Битрикс24.
FRAME_ANCESTORS = env_list(
    "FRAME_ANCESTORS",
    default="'self',https://*.bitrix24.ru,https://*.bitrix24.com",
)


# ---------------------------------------------------------------------------
# Безопасность (активируется в продакшене, DEBUG=False)
# ---------------------------------------------------------------------------
# Приложение работает и напрямую по HTTPS, и в iframe Битрикс24.
# Для кросс-доменного iframe cookie обязаны быть SameSite=None; Secure.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "None"
    CSRF_COOKIE_SAMESITE = "None"

    # Работаем за nginx: доверяем заголовку X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # Редиректом на HTTPS обычно занимается nginx; включается опционально.
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=False)

    # HSTS — включать только когда HTTPS точно работает на всех поддоменах.
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS")
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD")


LANGUAGE_CODE = "ru-ru"

TIME_ZONE = env("TIME_ZONE", "Europe/Moscow")

USE_I18N = True

USE_TZ = True


STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Почта
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", "smtp.yandex.ru")
EMAIL_PORT = int(env("EMAIL_PORT", "465"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)


# ---------------------------------------------------------------------------
# Интеграция с Битрикс24
# ---------------------------------------------------------------------------
BITRIX_CLIENT_ID = env("BITRIX_CLIENT_ID", "")
BITRIX_CLIENT_SECRET = env("BITRIX_CLIENT_SECRET", "")
BITRIX_OAUTH_AUTHORIZE_URL = env(
    "BITRIX_OAUTH_AUTHORIZE_URL", "https://oauth.bitrix.info/oauth/authorize"
)
BITRIX_OAUTH_TOKEN_URL = env(
    "BITRIX_OAUTH_TOKEN_URL", "https://oauth.bitrix.info/oauth/token"
)
BITRIX_OAUTH_REDIRECT_PATH = env("BITRIX_OAUTH_REDIRECT_PATH", "")
