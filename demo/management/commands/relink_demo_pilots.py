"""
Восстанавливает привязку демо-пилотов к карточкам Driver.

Зачем: карточки «ПилотN Демо» (slug demo-pilot-N) на проде когда-то удалили, а FK
DriverClaim.driver / UserProfile.driver — SET_NULL, поэтому заявки остались без пилота, и
демо-команда в окне «Пригласить пилота» видела пустой список (teams/views.py: для demo_team_*
список = Driver по подтверждённым заявкам demo_pilot_*).

Идемпотентна, ничего кроме этой привязки не трогает (в отличие от setup_demo_accounts, который
создаёт пользователей/команды и на проде без нужды запускать не стоит). Карточки в публичные
списки не попадают — см. website/services/demo.py.

Запуск:  python manage.py relink_demo_pilots
"""
from django.core.management.base import BaseCommand

SLOT_COUNT = 10


class Command(BaseCommand):
    help = 'Пересоздаёт карточки демо-пилотов и привязывает к ним заявки/профили (идемпотентно)'

    def handle(self, *args, **options):
        from accounts.models import DriverClaim, UserProfile
        from django.contrib.auth.models import User
        from demo.management.commands.setup_demo_accounts import Command as SetupCommand

        helper = SetupCommand()
        fixed = 0
        for i in range(1, SLOT_COUNT + 1):
            user = User.objects.filter(email=f'demo_pilot_{i}@email.ru').first()
            if not user:
                self.stdout.write(self.style.WARNING(f'demo_pilot_{i}: пользователя нет — пропускаю'))
                continue
            claim = DriverClaim.objects.filter(user=user, status='approved').first()
            profile = UserProfile.objects.filter(user=user).first()
            if claim and claim.driver_id and (not profile or profile.driver_id):
                continue
            driver = (claim.driver if claim and claim.driver_id else None) \
                or helper._get_or_create_driver(f'Пилот{i}', 'Демо', i)
            if claim and not claim.driver_id:
                claim.driver = driver
                claim.save()
            elif not claim:
                DriverClaim.objects.create(
                    user=user, driver=driver, status='approved',
                    requested_first_name=f'Пилот{i}', requested_last_name='Демо',
                )
            if profile and not profile.driver_id:
                profile.driver = driver
                profile.save()
            fixed += 1
            self.stdout.write(self.style.SUCCESS(f'demo_pilot_{i}: привязан к {driver.slug}'))
        self.stdout.write(f'Готово, исправлено: {fixed}')
