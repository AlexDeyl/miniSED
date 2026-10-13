"""
Подтягивает сотрудников отдела по работе с персоналом из Битрикс24 в
jobdesc.HrStaff. Безопасно гонять по cron раз в сутки: ручные записи не
трогает, ушедших из отдела (по данным портала) снимает.

    python manage.py sync_hr_staff
"""

from django.core.management.base import BaseCommand, CommandError

from jobdesc import hr_staff


class Command(BaseCommand):
    help = "Синхронизирует сотрудников отдела по работе с персоналом из Битрикс24."

    def handle(self, *args, **options):
        try:
            result = hr_staff.sync()
        except hr_staff.HrSyncError as e:
            raise CommandError(str(e))
        self.stdout.write(f"Отделы: {', '.join(result['departments'])}")
        for s in hr_staff.staff_options():
            self.stdout.write(f"  {s['bitrix_id']}: {s['fio']} — {s['position']}")
        self.stdout.write(self.style.SUCCESS(
            f"Готово. В отделе: {result['total']}, добавлено: {result['added']}, "
            f"снято: {result['removed']}."
        ))
