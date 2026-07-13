from django.db import migrations

from requests_reg.constants import POWER_TEMPLATES


def seed(apps, schema_editor):
    PowerTemplate = apps.get_model("requests_reg", "PowerTemplate")
    for code, name, powers in POWER_TEMPLATES:
        PowerTemplate.objects.update_or_create(
            code=code, defaults={"name": name, "powers": powers}
        )


def unseed(apps, schema_editor):
    PowerTemplate = apps.get_model("requests_reg", "PowerTemplate")
    PowerTemplate.objects.filter(code__in=[c for c, _, _ in POWER_TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("requests_reg", "0003_powertemplate"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
