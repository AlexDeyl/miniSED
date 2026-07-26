"""
Сид оргструктуры MiniSED: организации, объекты (отели), ЦФО.

Идемпотентен — можно прогонять при каждом деплое (scripts/deploy.sh вызывает
после seed_employees). Организации сопоставляются по short_name, объекты и ЦФО —
по паре (название, организация), поэтому повторный запуск не плодит дубли.

Данные содержат внутреннюю оргструктуру и ФИО руководителей ЦФО (ПДн), поэтому
в репозиторий НЕ коммитятся: команда читает их из внешнего JSON
(по умолчанию seed_data/org_structure.json, путь переопределяется переменной
окружения SEED_ORG_STRUCTURE_FILE). Образец формата — seed_data/org_structure.example.json.
Если файла нет — команда завершается без изменений (no-op).

    python manage.py seed_org_structure            # применить
    python manage.py seed_org_structure --dry-run  # показать план
"""

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import CFO, Facility, Organization
from requests_reg.models import RoleAssignment

DEFAULT_DATA_FILE = Path(settings.BASE_DIR) / "seed_data" / "org_structure.json"


class Command(BaseCommand):
    help = "Идемпотентно создаёт организации, объекты и ЦФО из JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ничего не записывать, только показать план.",
        )

    def handle(self, *args, **options):
        path = Path(
            os.environ.get("SEED_ORG_STRUCTURE_FILE", str(DEFAULT_DATA_FILE))
        )
        if not path.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Файл оргструктуры не найден ({path}) — пропускаю (no-op). "
                    f"Задайте SEED_ORG_STRUCTURE_FILE или положите "
                    f"seed_data/org_structure.json."
                )
            )
            return

        with path.open(encoding="utf-8-sig") as fh:
            data = json.load(fh)

        dry_run = options["dry_run"]
        orgs_n = fac_n = cfo_n = ra_n = 0

        with transaction.atomic():
            # --- Организации ---
            for name in data.get("organizations", []):
                org, created = Organization.objects.get_or_create(
                    short_name=name, defaults={"is_active": True}
                )
                orgs_n += 1
                self.stdout.write(
                    f"  [организация {'СОЗДАНА' if created else 'есть'}] {name}"
                )

            # --- Объекты / отели ---
            for f in data.get("facilities", []):
                org = Organization.objects.filter(
                    short_name=f["organization"]
                ).first()
                if org is None:
                    self.stderr.write(
                        f"  ! организация не найдена для объекта "
                        f"{f['name']!r}: {f['organization']!r} — пропуск"
                    )
                    continue
                _, created = Facility.objects.update_or_create(
                    name=f["name"],
                    organization=org,
                    defaults={
                        "address": f.get("address", ""),
                        "is_active": True,
                    },
                )
                fac_n += 1
                self.stdout.write(
                    f"  [объект {'СОЗДАН' if created else 'обновлён'}] "
                    f"{f['name']} → {org.short_name}"
                )

            # --- ЦФО ---
            for c in data.get("cfos", []):
                org = Organization.objects.filter(
                    short_name=c["organization"]
                ).first()
                if org is None:
                    self.stderr.write(
                        f"  ! организация не найдена для ЦФО "
                        f"{c['name']!r}: {c['organization']!r} — пропуск"
                    )
                    continue
                _, created = CFO.objects.update_or_create(
                    name=c["name"],
                    organization=org,
                    defaults={
                        "code": c.get("code", ""),
                        "category": c.get("category", ""),
                        "head": c.get("head", ""),
                        "is_active": True,
                    },
                )
                cfo_n += 1
                self.stdout.write(
                    f"  [ЦФО {'СОЗДАН' if created else 'обновлён'}] "
                    f"{c['name']} → {org.short_name}"
                    + (f", рук.: {c['head']}" if c.get("head") else "")
                )

            # --- Матрица исполнителей маршрутных ролей (RoleAssignment) ---
            # Контекст задаётся полями organization/cfo/facility (по названию);
            # без них — глобальное назначение. resolve_role в requests_reg берёт
            # самое специфичное (ЦФО → объект → организация → глобально).
            for ra in data.get("role_assignments", []):
                cfo = org = fac = None
                if ra.get("cfo"):
                    cfo = CFO.objects.filter(name=ra["cfo"]).first()
                    if cfo is None:
                        self.stderr.write(
                            f"  ! ЦФО не найден для роли {ra['role_code']!r}: "
                            f"{ra['cfo']!r} — пропуск"
                        )
                        continue
                if ra.get("organization"):
                    org = Organization.objects.filter(
                        short_name=ra["organization"]
                    ).first()
                if ra.get("facility"):
                    fac = Facility.objects.filter(name=ra["facility"]).first()

                _, created = RoleAssignment.objects.update_or_create(
                    role_code=ra["role_code"],
                    organization=org,
                    cfo=cfo,
                    facility=fac,
                    defaults={
                        "user_b24_id": ra["user_b24_id"],
                        "user_name": ra.get("user_name", ""),
                        "is_active": True,
                    },
                )
                ra_n += 1
                ctx = (
                    f"ЦФО {cfo.name}" if cfo else
                    f"объект {fac.name}" if fac else
                    f"орг {org.short_name}" if org else "глобально"
                )
                self.stdout.write(
                    f"  [роль {'СОЗДАНА' if created else 'обновлена'}] "
                    f"{ra['role_code']} @ {ctx} → {ra.get('user_name', ra['user_b24_id'])}"
                )

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("\n--dry-run: изменения откачены.")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nГотово. Организаций: {orgs_n}, объектов: {fac_n}, "
                f"ЦФО: {cfo_n}, назначений ролей: {ra_n}."
            )
        )
