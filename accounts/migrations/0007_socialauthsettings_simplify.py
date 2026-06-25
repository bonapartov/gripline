from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_userprofile_birth_date_public'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialauthsettings',
            name='vk_enabled',
            field=models.BooleanField(default=False, verbose_name='Вход через ВКонтакте'),
        ),
        migrations.AddField(
            model_name='socialauthsettings',
            name='google_enabled',
            field=models.BooleanField(default=False, verbose_name='Вход через Google'),
        ),
        migrations.AlterField(
            model_name='socialauthsettings',
            name='yandex_client_id',
            field=models.CharField(blank=True, max_length=200, verbose_name='Яндекс Client ID'),
        ),
        migrations.AlterField(
            model_name='socialauthsettings',
            name='yandex_client_secret',
            field=models.CharField(blank=True, max_length=200, verbose_name='Яндекс Client Secret'),
        ),
    ]
