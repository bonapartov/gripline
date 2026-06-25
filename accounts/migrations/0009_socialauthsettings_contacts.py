from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_migrate_yandex_to_social_django'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialauthsettings',
            name='contact_email',
            field=models.EmailField(
                blank=True,
                help_text='Email для связи с администратором (показывается пользователям)',
                verbose_name='Контактный email',
            ),
        ),
        migrations.AddField(
            model_name='socialauthsettings',
            name='telegram_contact',
            field=models.CharField(
                blank=True,
                help_text='Telegram-аккаунт или канал, например @gripline',
                max_length=100,
                verbose_name='Telegram администратора',
            ),
        ),
    ]
