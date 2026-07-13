from django.db import migrations

from core.constants import ALL_PERMISSIONS, ALL_ROLES


def seed(apps, schema_editor):
    Permission = apps.get_model("core", "Permission")
    Role = apps.get_model("core", "Role")

    for code, name, category in ALL_PERMISSIONS:
        Permission.objects.update_or_create(
            code=code, defaults={"name": name, "category": category}
        )

    for code, (name, kind, perm_codes) in ALL_ROLES.items():
        role, _ = Role.objects.update_or_create(
            code=code, defaults={"name": name, "kind": kind}
        )
        perms = Permission.objects.filter(code__in=perm_codes)
        role.permissions.set(perms)


def unseed(apps, schema_editor):
    Permission = apps.get_model("core", "Permission")
    Role = apps.get_model("core", "Role")
    Role.objects.filter(code__in=ALL_ROLES.keys()).delete()
    Permission.objects.filter(
        code__in=[c for c, _, _ in ALL_PERMISSIONS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
