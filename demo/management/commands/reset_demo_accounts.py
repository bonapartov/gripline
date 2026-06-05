"""
Сброс демо-аккаунтов в исходное состояние.
Запускать ежедневно через cron:
  0 3 * * * cd /www/wwwroot/gripline.ru && venv/bin/python manage.py reset_demo_accounts
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Сбросить демо-аккаунты в исходное состояние'

    def handle(self, *args, **options):
        self._release_slots()
        self._reset_organizer_data()
        self._reset_pilot_data()
        self._reset_team_data()
        self.stdout.write(self.style.SUCCESS('Демо-данные сброшены.'))

    def _release_slots(self):
        from demo.models import DemoSlot
        count = DemoSlot.objects.filter(is_occupied=True).update(
            is_occupied=False, occupied_until=None
        )
        self.stdout.write(f'  Освобождено слотов: {count}')

    def _reset_organizer_data(self):
        from demo.models import DemoSlot
        from organizers.models import Championship, Stage
        from applications.models import Application

        slots = DemoSlot.objects.filter(slot_type='organizer').select_related('user')
        for slot in slots:
            profile = getattr(slot.user, 'organizer_profile', None)
            if not profile:
                continue

            # Удаляем все демо-чемпионаты и пересоздаём через setup_demo_accounts логику
            Championship.objects.filter(organizer=profile, is_demo=True).delete()

        # Пересоздаём через ту же логику что и setup
        from django.core.management import call_command
        # Вызываем только часть с организаторами
        cmd = _SetupOrganizersOnly()
        cmd.stdout = self.stdout
        cmd.style = self.style
        cmd._create_organizer_slots()
        self.stdout.write('  Данные организаторов восстановлены.')

    def _reset_pilot_data(self):
        from demo.models import DemoSlot
        from applications.models import Application

        slots = DemoSlot.objects.filter(slot_type='pilot').select_related('user')
        count = 0
        for slot in slots:
            n = Application.objects.filter(submitted_by=slot.user).delete()[0]
            count += n
        self.stdout.write(f'  Удалено заявок пилотов: {count}')

    def _reset_team_data(self):
        from demo.models import DemoSlot
        from applications.models import Application

        slots = DemoSlot.objects.filter(slot_type='team').select_related('user')
        count = 0
        for slot in slots:
            from teams.models import TeamManager
            for tm in TeamManager.objects.filter(user=slot.user):
                n = Application.objects.filter(submitted_by=slot.user).delete()[0]
                count += n
        self.stdout.write(f'  Удалено заявок команд: {count}')


class _SetupOrganizersOnly:
    """Вспомогательный класс — только создание чемпионатов организаторов."""

    def _create_organizer_slots(self):
        from demo.models import DemoSlot
        from organizers.models import OrganizerProfile, Championship
        from website.models import RaceClass, Track

        race_classes = list(RaceClass.objects.all()[:3])
        track = Track.objects.filter(live=True).first()

        for i in range(1, 11):
            email = f'demo_org_{i}@email.ru'
            from django.contrib.auth.models import User
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                continue

            try:
                profile = user.organizer_profile
            except OrganizerProfile.DoesNotExist:
                continue

            self._create_demo_championships(profile, track, race_classes, i)

    def _create_demo_championships(self, profile, track, race_classes, slot_num):
        from organizers.models import Championship, Stage
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()

        for c in range(1, 3):
            slug_base = f'demo-org-{slot_num}-champ-{c}'
            slug = slug_base
            counter = 1
            while Championship.objects.filter(slug=slug).exists():
                slug = f'{slug_base}-{counter}'
                counter += 1

            champ = Championship.objects.create(
                organizer=profile,
                title=f'Демо Чемпионат {c} (Орг {slot_num})',
                slug=slug,
                is_published=False,
                is_active=True,
                is_demo=True,
                registration_mode='per_stage',
                tyre_mode='all',
            )
            if race_classes:
                champ.race_classes.set(race_classes)

            for s in range(1, 4):
                start = now + timedelta(days=30 * s)
                Stage.objects.create(
                    championship=champ,
                    title=f'Этап {s}',
                    start_date=start,
                    end_date=start + timedelta(days=1),
                    track=track,
                    entry_fee=2500,
                    is_published=False,
                    registration_enabled=True,
                )
