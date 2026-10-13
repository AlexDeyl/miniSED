"""
Внести в реестр доверенности и МЧД, взятые в работу до появления реестра.

Номер им НЕ присваивается: в жизни такие доверенности уже выданы под своими
номерами, и выдумать за юриста номер значит испортить реестр. Графа «№»
остаётся пустой — юрист вписывает фактический номер. Повторный запуск
безопасен: заявки, уже внесённые в реестр, пропускаются.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from requests_reg import constants as C
from requests_reg import registry
from requests_reg.models import PoaRegistryEntry, RegulatoryRequest

TAKEN = [
    C.STATUS_LEGAL_WORK, C.STATUS_SIGNING, C.STATUS_DEV_WORK,
    C.STATUS_EXECUTED, C.STATUS_CLOSED,
]


class Command(BaseCommand):
    help = "Внести в реестр доверенности/МЧД, взятые в работу до появления реестра (без номера)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Только показать, что будет внесено.")

    @transaction.atomic
    def handle(self, *args, dry_run=False, **opts):
        qs = (
            RegulatoryRequest.objects
            .filter(request_type__in=[C.TYPE_POA, C.TYPE_MCHD], status__in=TAKEN,
                    registry_entry__isnull=True)
            .select_related("organization")
            .order_by("id")
        )
        created = 0
        for req in qs:
            when = req.executed_at or req.taken_at
            revoke = (
                req.revocations.filter(status__in=[C.STATUS_EXECUTED, C.STATUS_CLOSED])
                .order_by("executed_at").first()
            )
            self.stdout.write(f"{req.number} {req.subject_name} — {req.organization.short_name}")
            if dry_run:
                continue
            PoaRegistryEntry.objects.create(
                request=req,
                issue_date=timezone.localdate(when) if when else None,
                revoked_at=(
                    registry._parse_date((revoke.data or {}).get("revoke_date"))
                    or (timezone.localdate(revoke.executed_at) if revoke.executed_at else None)
                ) if revoke else None,
                **registry.defaults_from_request(req),
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(
            f"{'Нашлось' if dry_run else 'Внесено'}: {qs.count() if dry_run else created}"
        ))
