from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0009_championship_registration_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizersettings',
            name='payments_enabled',
            field=models.BooleanField(
                default=False,
                verbose_name='Оплата включена',
                help_text='Показывать блоки оплаты, комиссий и финансов в ЛК организатора',
            ),
        ),
    ]
