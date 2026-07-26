#!/usr/bin/env bash
# =============================================================================
# Mini-СЭД — скрипт деплоя на продакшн-сервер
#
# Использование (вручную с сервера):
#   export PROJECT_PATH=~/minised/miniSED
#   export BRANCH=main
#   export DJANGO_SERVICE_NAME=microSED
#   export NGINX_SERVICE_NAME=nginx
#   bash scripts/deploy.sh
#
# При запуске через GitHub Actions переменные передаются автоматически.
# =============================================================================

set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Переменные (обязательные помечены :?)
# ---------------------------------------------------------------------------
PROJECT_PATH="${PROJECT_PATH:?Не задана переменная PROJECT_PATH}"
BRANCH="${BRANCH:-main}"
DJANGO_SERVICE_NAME="${DJANGO_SERVICE_NAME:?Не задана переменная DJANGO_SERVICE_NAME}"
NGINX_SERVICE_NAME="${NGINX_SERVICE_NAME:-nginx}"

# ---------------------------------------------------------------------------
# sudo — нужен только для не-root пользователя
# ---------------------------------------------------------------------------
if [ "$(id -u)" = "0" ]; then
    SUDO=""
else
    SUDO="sudo"
fi

# ---------------------------------------------------------------------------
# Защита от одновременного деплоя (flock)
# ---------------------------------------------------------------------------
LOCK_FILE="/tmp/minised_deploy.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[deploy] Другой деплой уже выполняется. Попробуйте позже."
    exit 1
fi

# ---------------------------------------------------------------------------
# Функция вывода ошибки и последних логов при падении
# ---------------------------------------------------------------------------
on_error() {
    local exit_code=$?
    echo ""
    echo "[deploy] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "[deploy] ДЕПЛОЙ ЗАВЕРШИЛСЯ С ОШИБКОЙ (код: $exit_code)"
    echo "[deploy] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
    echo "[deploy] Последние логи сервиса $DJANGO_SERVICE_NAME:"
    $SUDO journalctl -u "$DJANGO_SERVICE_NAME" -n 30 --no-pager || true
    exit $exit_code
}
trap on_error ERR

# ---------------------------------------------------------------------------
echo "========================================================"
echo "[deploy] Начало деплоя: $(date '+%Y-%m-%d %H:%M:%S')"
echo "[deploy] Проект:  $PROJECT_PATH"
echo "[deploy] Ветка:   $BRANCH"
echo "[deploy] Сервис:  $DJANGO_SERVICE_NAME"
echo "========================================================"

# --- 1. Переходим в папку проекта ---
echo ""
echo "[deploy] 1/8  Переходим в $PROJECT_PATH ..."
cd "$PROJECT_PATH"

# --- 2. Проверяем git ---
if [ ! -d ".git" ]; then
    echo "[deploy] ОШИБКА: $PROJECT_PATH не является git-репозиторием"
    exit 1
fi

# --- 3. Резервная копия БД (SQLite) ---
if [ -f "db.sqlite3" ]; then
    BACKUP_FILE="/tmp/db.sqlite3.backup.$(date +%Y%m%d_%H%M%S)"
    cp db.sqlite3 "$BACKUP_FILE"
    echo "[deploy]       Резервная копия БД → $BACKUP_FILE"
fi

# --- 4. Получаем и применяем обновления из git ---
echo ""
echo "[deploy] 2/8  git fetch origin ..."
git fetch origin

echo "[deploy]      Состояние ветки до pull:"
git status -sb

echo "[deploy] 3/8  git pull origin $BRANCH ..."
git pull origin "$BRANCH"

echo "[deploy]      Текущий коммит: $(git log -1 --oneline)"

# --- 5. Активируем виртуальное окружение ---
echo ""
echo "[deploy] 4/8  Активируем venv ..."
# shellcheck disable=SC1091
source venv/bin/activate

# --- 6. Зависимости ---
echo ""
echo "[deploy] 5/8  pip install -r requirements.txt ..."
pip install -r requirements.txt --quiet

# --- 7. Django: миграции и статика ---
echo ""
echo "[deploy] 6/8  python manage.py migrate --noinput ..."
python manage.py migrate --noinput

echo "[deploy]      python manage.py seed_employees (идемпотентно) ..."
python manage.py seed_employees

echo "[deploy]      python manage.py collectstatic --noinput ..."
python manage.py collectstatic --noinput --clear

# --- 8. Перезапускаем Django-сервис ---
echo ""
echo "[deploy] 7/8  Перезапускаем $DJANGO_SERVICE_NAME ..."
$SUDO systemctl restart "$DJANGO_SERVICE_NAME"
sleep 3
$SUDO systemctl status "$DJANGO_SERVICE_NAME" --no-pager -l

# --- 9. Nginx ---
echo ""
echo "[deploy] 8/8  Проверяем nginx и перезагружаем ..."
$SUDO nginx -t
$SUDO systemctl reload "$NGINX_SERVICE_NAME"

# --- 10. Опциональный health-check ---
if [ -n "${HEALTH_CHECK_URL:-}" ]; then
    echo ""
    echo "[deploy]      Health-check: $HEALTH_CHECK_URL ..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_CHECK_URL" || true)
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
        echo "[deploy]      Health-check OK (HTTP $HTTP_CODE)"
    else
        echo "[deploy]      Health-check вернул HTTP $HTTP_CODE — проверьте сервис вручную"
    fi
fi

echo ""
echo "========================================================"
echo "[deploy] Деплой завершён успешно: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"
