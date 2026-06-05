"""
Создаёт 30 демо-аккаунтов (10 организаторов, 10 пилотов, 10 команд) и наполняет их данными.
Запускать один раз на сервере после настройки проекта.
Повторный запуск безопасен — пропускает уже существующих пользователей.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from datetime import timedelta


DEMO_PASSWORD = 'DemoGripline2026!'
SLOT_COUNT = 10


class Command(BaseCommand):
    help = 'Создать демо-аккаунты для организаторов, пилотов и команд'

    def handle(self, *args, **options):
        self._create_organizer_slots()
        self._create_pilot_slots()
        self._create_team_slots()
        self.stdout.write(self.style.SUCCESS('Демо-аккаунты созданы.'))

    def _get_or_create_user(self, email, first_name, last_name):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'username': email,
                'first_name': first_name,
                'last_name': last_name,
                'is_active': True,
            }
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self.stdout.write(f'  Создан пользователь {email}')
        return user, created

    def _create_organizer_slots(self):
        from demo.models import DemoSlot
        from organizers.models import OrganizerProfile, Championship, Stage
        from website.models import RaceClass, Track

        self.stdout.write('Организаторы...')

        race_classes = list(RaceClass.objects.all()[:3])
        track = Track.objects.filter(live=True).first()

        for i in range(1, SLOT_COUNT + 1):
            email = f'demo_org_{i}@email.ru'
            user, created = self._get_or_create_user(email, f'Демо{i}', 'Организатор')

            slot, _ = DemoSlot.objects.get_or_create(
                slot_type='organizer',
                slot_number=i,
                defaults={'user': user},
            )

            profile, _ = OrganizerProfile.objects.get_or_create(user=user)

            if created or not Championship.objects.filter(organizer=profile, is_demo=True).exists():
                self._create_demo_championships(profile, track, race_classes, i)

    def _create_demo_championships(self, profile, track, race_classes, slot_num):
        from organizers.models import Championship, Stage

        now = timezone.now()

        for c in range(1, 3):
            slug_base = f'demo-org-{slot_num}-champ-{c}'
            slug = slug_base
            counter = 1
            from organizers.models import Championship as C
            while C.objects.filter(slug=slug).exists():
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

    def _create_pilot_slots(self):
        from demo.models import DemoSlot
        from accounts.models import UserProfile

        self.stdout.write('Пилоты...')

        for i in range(1, SLOT_COUNT + 1):
            email = f'demo_pilot_{i}@email.ru'
            user, created = self._get_or_create_user(email, f'Демо{i}', 'Пилот')

            DemoSlot.objects.get_or_create(
                slot_type='pilot',
                slot_number=i,
                defaults={'user': user},
            )

            UserProfile.objects.get_or_create(
                user=user,
                defaults={'email_verified': True, 'city': 'Москва'},
            )

    def _create_team_slots(self):
        from demo.models import DemoSlot
        from teams.models import TeamManager
        from website.models import Team
        from accounts.models import UserProfile

        self.stdout.write('Команды...')

        for i in range(1, SLOT_COUNT + 1):
            email = f'demo_team_{i}@email.ru'
            user, created = self._get_or_create_user(email, f'Демо{i}', 'Команда')

            DemoSlot.objects.get_or_create(
                slot_type='team',
                slot_number=i,
                defaults={'user': user},
            )

            UserProfile.objects.get_or_create(
                user=user,
                defaults={'email_verified': True},
            )

            team_slug = f'demo-team-{i}'
            team, _ = Team.objects.get_or_create(
                slug=team_slug,
                defaults={
                    'name': f'Демо Команда {i}',
                    'manager_name': f'Демо Менеджер {i}',
                },
            )

            TeamManager.objects.get_or_create(
                user=user,
                team=team,
                defaults={'role': 'captain', 'is_active': True},
            )
