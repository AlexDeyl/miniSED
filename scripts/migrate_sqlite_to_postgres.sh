#!/usr/bin/env bash
# =============================================================================
# MiniSED — миграция данных с SQLite на PostgreSQL БЕЗ потери данных.
#
# Запускается ОДИН РАЗ на сервере при переходе на PostgreSQL.
# Логика: выгружаем данные из текущей SQLite (dumpdata), затем заливаем
# их в свежую PostgreSQL (loaddata). dumpdata/loaddata не зависят от движка БД.
#
# ВАЖНО: выполнять пошагово и осознанно. Перед стартом убедитесь, что есть
# резервная копия db.sqlite3.
#
# Предварительно (вне этого скрипта), от имени администратора БД:
#   sudo -u postgres psql -c "CREATE USER minised WITH PASSWORD '...';"
#   sudo -u postgres psql -c "CREATE DATABASE minised OWNER minised;"
#
# Использование:
#   export PROJECT_PATH=~/minised/miniSED
#   bash scripts/migrate_sqlite_to_postgres.sh
# =============================================================================

set -Eeuo pipefail

PROJECT_PATH="${PROJECT_PATH:?Не задана переменная PROJECT_PATH}"
DUMP_FILE="${DUMP_FILE:-/tmp/minised_data_$(date +%Y%m%d_%H%M%S).json}"

cd "$PROJECT_PATH"
# shellcheck disable=SC1091
source venv/bin/activate

echo "=============================================================="
echo "[migrate] Шаг 1/4: резервная копия SQLite"
echo "=============================================================="
if [ -f "db.sqlite3" ]; then
    cp db.sqlite3 "/tmp/db.sqlite3.backup.$(date +%Y%m%d_%H%M%S)"
    echo "[migrate]   Бэкап db.sqlite3 сделан в /tmp"
else
    echo "[migrate]   ВНИМАНИЕ: db.sqlite3 не найден в $PROJECT_PATH"
fi

echo "=============================================================="
echo "[migrate] Шаг 2/4: выгрузка данных из SQLite → $DUMP_FILE"
echo "=============================================================="
# Принудительно читаем из SQLite (на случай, если .env уже переключён).
# Исключаем служебные таблицы, которые создаются заново миграциями и
# ломают loaddata дублями (contenttypes, permissions, сессии, логи админки).
DB_ENGINE=sqlite python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes \
    --exclude auth.permission \
    --exclude admin.logentry \
    --exclude sessions.session \
    --indent 2 \
    --output "$DUMP_FILE"
echo "[migrate]   Данные выгружены."

echo "=============================================================="
echo "[migrate] Шаг 3/4: создание схемы в PostgreSQL (migrate)"
echo "=============================================================="
echo "[migrate]   Проверьте, что в .env: DB_ENGINE=postgres и заданы DB_*"
DB_ENGINE=postgres python manage.py migrate --noinput

echo "=============================================================="
echo "[migrate] Шаг 4/4: загрузка данных в PostgreSQL (loaddata)"
echo "=============================================================="
DB_ENGINE=postgres python manage.py loaddata "$DUMP_FILE"

echo "=============================================================="
echo "[migrate] Готово. Данные перенесены в PostgreSQL."
echo "[migrate] Дамп сохранён: $DUMP_FILE"
echo "[migrate] Дальше: убедитесь, что systemd-сервис читает .env с"
echo "[migrate] DB_ENGINE=postgres, и перезапустите сервис."
echo "=============================================================="
