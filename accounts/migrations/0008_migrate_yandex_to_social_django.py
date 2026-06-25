"""
Data migration: copy YandexSocialAuth records to social_django.UserSocialAuth.
Run AFTER: python manage.py migrate social_django
"""
from django.db import migrations


def migrate_yandex_auth(apps, schema_editor):
    YandexSocialAuth = apps.get_model('accounts', 'YandexSocialAuth')
    UserSocialAuth = apps.get_model('social_django', 'UserSocialAuth')

    for ya in YandexSocialAuth.objects.select_related('user').all():
        UserSocialAuth.objects.get_or_create(
            provider='yandex-oauth2',
            uid=ya.yandex_uid,
            defaults={
                'user': ya.user,
                'extra_data': {'login': ya.yandex_login},
            },
        )


def reverse_migrate(apps, schema_editor):
    UserSocialAuth = apps.get_model('social_django', 'UserSocialAuth')
    UserSocialAuth.objects.filter(provider='yandex-oauth2').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_socialauthsettings_simplify'),
        ('social_django', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(migrate_yandex_auth, reverse_migrate),
    ]
