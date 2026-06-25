from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0010_organizersettings_payments_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='championship',
            name='is_demo',
            field=models.BooleanField(
                default=False,
                verbose_name='Демо-мероприятие',
                help_text='Не публикуется на сайте и не попадает в рейтинг',
            ),
        ),
    ]
