"""Право сквозного просмотра (view_all) и выдача его системному администратору.

Точечная миграция, а не повторный прогон сида ролей: пересинхронизация всех
ролей из констант затёрла бы правки, сделанные руками в админке.
"""

from django.db import migrations

PERMISSION = ("view_all", "Просмотр всех документов и заявок", "system")
ROLE_CODE = "sys_admin"


def add_permission(apps, schema_editor):
    Permission = apps.get_model("core", "Permission")
    Role = apps.get_model("core", "Role")

    code, name, category = PERMISSION
    perm, _ = Permission.objects.update_or_create(
        code=code, defaults={"name": name, "category": category}
    )
    role = Role.objects.filter(code=ROLE_CODE).first()
    if role is not None:
        role.permissions.add(perm)


def remove_permission(apps, schema_editor):
    Permission = apps.get_model("core", "Permission")
    Permission.objects.filter(code=PERMISSION[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_seenmark"),
    ]

    operations = [
        migrations.RunPython(add_permission, remove_permission),
    ]
