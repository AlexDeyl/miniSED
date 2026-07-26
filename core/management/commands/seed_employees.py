"""
Сид тестовых сотрудников MiniSED (матрица ролей доступа).

Запускается идемпотентно — можно прогонять сколько угодно раз, в том числе
при каждом деплое на боевой сервер (scripts/deploy.sh вызывает его после
`migrate`). Сопоставление идёт по bitrix_id (уникальное поле), поэтому
повторный запуск не плодит дубли, а лишь дополняет данные.

Роли и организации назначаются АДДИТИВНО (add, не set): если администратор
вручную выдал пользователю дополнительную роль, сид её не затрёт.

Источник данных — «Матрица ролей МиниСЭД». Сами данные содержат ПДн реальных
сотрудников, поэтому в репозиторий НЕ коммитятся: команда читает их из
внешнего JSON-файла (по умолчанию seed_data/employees.json, путь можно
переопределить переменной окружения SEED_EMPLOYEES_FILE). Файл доставляется
на сервер отдельно (см. seed_data/employees.example.json как образец формата).
Если файла нет — команда завершается без изменений (no-op), чтобы деплой в
средах без данных не падал.

    python manage.py seed_employees            # применить
    python manage.py seed_employees --dry-run  # показать, что будет сделано
"""

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Facility, Organization, Position, Role, UserProfile

# Путь к файлу с данными сотрудников (негитируемый, содержит ПДн).
DEFAULT_DATA_FILE = Path(settings.BASE_DIR) / "seed_data" / "employees.json"


def _load_employees():
    """Читает список сотрудников из JSON. Возвращает (records | None, path).

    None означает «файл не найден» — вызывающий код делает no-op.
    Каждая запись JSON: {bitrix_id, fio, email, position, organization, roles,
    access_all?}. access_all=true — доступ ко всем организациям и объектам.
    """
    path = Path(os.environ.get("SEED_EMPLOYEES_FILE", str(DEFAULT_DATA_FILE)))
    if not path.exists():
        return None, path
    # utf-8-sig — терпимо к возможному BOM при копировании файла на сервер.
    with path.open(encoding="utf-8-sig") as fh:
        raw = json.load(fh)
    records = [
        (
            r["bitrix_id"], r["fio"], r["email"],
            r["position"], r["organization"], r["roles"],
            r.get("access_all", False),
        )
        for r in raw
    ]
    return records, path


class Command(BaseCommand):
    help = "Идемпотентно создаёт/обновляет тестовых сотрудников из матрицы ролей."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ничего не записывать, только показать план.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        employees, path = _load_employees()
        if employees is None:
            self.stdout.write(
                self.style.WARNING(
                    f"Файл с данными сотрудников не найден ({path}) — "
                    f"пропускаю сид (no-op). Задайте SEED_EMPLOYEES_FILE или "
                    f"положите seed_data/employees.json."
                )
            )
            return

        with transaction.atomic():
            created = updated = 0

            # Кэш ролей по коду
            roles = {r.code: r for r in Role.objects.all()}

            for bitrix_id, fio, email, position_name, org_name, role_codes, access_all in employees:
                org, _ = Organization.objects.get_or_create(
                    short_name=org_name, defaults={"is_active": True}
                )
                position, _ = Position.objects.get_or_create(
                    name=position_name, defaults={"is_active": True}
                )

                user, was_created = UserProfile.objects.update_or_create(
                    bitrix_id=bitrix_id,
                    defaults={
                        "fio": fio,
                        "email": email,
                        "position": position,
                        "is_active": True,
                    },
                )

                # Аддитивно: роли и организации не затираем
                user.organizations.add(org)
                # access_all — доступ ко всем юрлицам и объектам (юротдел, отдел
                # продаж): такие сотрудники работают по всем организациям.
                # Требует, чтобы объекты уже были засеяны (seed_org_structure
                # выполняется раньше seed_employees в scripts/deploy.sh).
                if access_all:
                    user.organizations.add(*Organization.objects.all())
                    user.facilities.add(*Facility.objects.all())
                missing = [c for c in role_codes if c not in roles]
                if missing:
                    self.stderr.write(
                        f"  ! роли не найдены (прогоните migrate): {missing} — {fio}"
                    )
                user.roles.add(*[roles[c] for c in role_codes if c in roles])

                if was_created:
                    created += 1
                    tag = "СОЗДАН"
                else:
                    updated += 1
                    tag = "обновлён"
                self.stdout.write(
                    f"  [{tag}] {fio} (bitrix {bitrix_id}) "
                    f"-> {org_name}, роли: {', '.join(role_codes)}"
                )

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("\n--dry-run: изменения откачены."))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nГотово. Создано: {created}, обновлено: {updated}, всего: {len(employees)}."
            )
        )
