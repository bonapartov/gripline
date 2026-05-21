"""
Создаёт тестовых пользователей и команду для ручного тестирования.
Запуск: python3 manage.py create_test_users
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Создаёт тестового пилота и тестовую команду'

    def handle(self, *args, **options):
        self._create_pilot()
        self._create_team()

    def _create_pilot(self):
        email = 'test_pilot@gripline.test'
        password = 'TestPilot123!'

        user, created = User.objects.get_or_create(
            username='test_pilot',
            defaults={
                'email': email,
                'first_name': 'Тест_имя',
                'last_name': 'Тест_фамилия',
                'is_active': True,
            }
        )
        if created:
            user.set_password(password)
            user.save()

        from accounts.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.email_verified = True
        profile.save()

        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Пилот создан:\n'
                f'  Email:    {email}\n'
                f'  Пароль:   {password}\n'
                f'  Имя:      Тест_имя Тест_фамилия\n'
            ))
        else:
            profile.email_verified = True
            profile.save()
            self.stdout.write(self.style.WARNING(
                f'  Пилот test_pilot уже существует — email_verified = True проставлен'
            ))

    def _create_team(self):
        from website.models import Team

        if Team.objects.filter(name='тест команда').exists():
            self.stdout.write(self.style.WARNING('  Команда «тест команда» уже существует'))
            return

        team = Team(name='тест команда')
        try:
            revision = team.save_revision()
            revision.publish()
            self.stdout.write(self.style.SUCCESS('✓ Команда «тест команда» создана (опубликована)'))
        except Exception:
            team.save()
            self.stdout.write(self.style.SUCCESS('✓ Команда «тест команда» создана'))
