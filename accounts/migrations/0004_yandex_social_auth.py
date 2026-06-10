from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_pilotdocument'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='YandexSocialAuth',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('yandex_uid', models.CharField(max_length=64, unique=True)),
                ('yandex_login', models.CharField(max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='yandex_auth',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Яндекс аккаунт',
                'verbose_name_plural': 'Яндекс аккаунты',
            },
        ),
        migrations.CreateModel(
            name='SocialAuthSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('yandex_enabled', models.BooleanField(default=False, verbose_name='Вход через Яндекс')),
                ('yandex_client_id', models.CharField(blank=True, max_length=200, verbose_name='Client ID')),
                ('yandex_client_secret', models.CharField(blank=True, max_length=200, verbose_name='Client Secret')),
            ],
            options={
                'verbose_name': 'Авторизация на сайте',
                'bases': ('wagtail.contrib.settings.models.BaseGenericSetting',),
            },
            bases=('wagtail.contrib.settings.models.BaseGenericSetting',),
        ),
    ]
