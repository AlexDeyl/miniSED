# Категория ЦФО «СПиР» (служба приёма и размещения): по ней в маршрут
# доверенности подключается операционный директор.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_permission_view_all'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cfo',
            name='category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('sales', 'Отдел продаж'),
                    ('revenue', 'Управление доходами'),
                    ('marketing', 'Маркетинг'),
                    ('booking', 'Бронирование'),
                    ('accounting', 'Бухгалтерия'),
                    ('hr_kdp', 'КДП'),
                    ('hr_recruit', 'Подбор / адаптация'),
                    ('hr_training', 'Обучение'),
                    ('reception', 'СПиР (служба приёма и размещения)'),
                    ('its_it', 'ИТС / ИТ'),
                    ('sgh', 'СГХ'),
                    ('territory', 'Содержание территории'),
                    ('warehouse', 'Склад'),
                    ('restaurant', 'Ресторанная служба'),
                    ('other', 'Прочее'),
                ],
                max_length=32,
                verbose_name='Категория',
            ),
        ),
    ]
