from django.db import migrations


def populate_b24useremail(apps, schema_editor):
    B24Identity = apps.get_model("approvals", "B24Identity")
    B24UserEmail = apps.get_model("approvals", "B24UserEmail")
    for identity in B24Identity.objects.all():
        if identity.email:
            B24UserEmail.objects.get_or_create(
                b24_user_id=identity.b24_user_id,
                email=identity.email.strip().lower(),
            )


class Migration(migrations.Migration):

    dependencies = [
        ("approvals", "0010_b24useremail"),
    ]

    operations = [
        migrations.RunPython(populate_b24useremail, migrations.RunPython.noop),
    ]
