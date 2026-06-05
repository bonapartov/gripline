"""
Создаёт 30 демо-аккаунтов (10 организаторов, 10 пилотов, 10 команд) и наполняет их данными.
Запускать один раз на сервере после настройки проекта.
Повторный запуск безопасен — пропускает уже существующих пользователей.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


DEMO_PASSWORD = 'DemoGripline2026!'
SLOT_COUNT = 10

STAFF_ROLES = [
    ('Демо Механик', 'Старший механик'),
    ('Демо Телеметрист', 'Телеметрист'),
    ('Демо Менеджер', 'Командный менеджер'),
]


class Command(BaseCommand):
    help = 'Создать демо-аккаунты для организаторов, пилотов и команд'

    def handle(self, *args, **options):
        self._create_organizer_slots()
        pilot_drivers = self._create_pilot_slots()
        self._create_team_slots(pilot_drivers)
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

    # ------------------------------------------------------------------
    # Организаторы
    # ------------------------------------------------------------------

    def _create_organizer_slots(self):
        from demo.models import DemoSlot
        from organizers.models import OrganizerProfile, Championship
        from website.models import RaceClass, Track

        self.stdout.write('Организаторы...')

        race_classes = list(RaceClass.objects.all()[:3])
        track = Track.objects.filter(live=True).first()

        for i in range(1, SLOT_COUNT + 1):
            email = f'demo_org_{i}@email.ru'
            user, created = self._get_or_create_user(email, f'Демо{i}', 'Организатор')

            DemoSlot.objects.get_or_create(
                slot_type='organizer', slot_number=i, defaults={'user': user},
            )

            profile, _ = OrganizerProfile.objects.get_or_create(user=user)

            if created or not Championship.objects.filter(organizer=profile, is_demo=True).exists():
                self._create_demo_championships(profile, track, race_classes, i)

    def _create_demo_championships(self, profile, track, race_classes, slot_num):
        from organizers.models import Championship, Stage

        now = timezone.now()
        for c in range(1, 3):
            slug = self._unique_slug(f'demo-org-{slot_num}-champ-{c}')
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

    def _unique_slug(self, base):
        from organizers.models import Championship
        slug = base
        counter = 1
        while Championship.objects.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
        return slug

    # ------------------------------------------------------------------
    # Пилоты
    # ------------------------------------------------------------------

    def _create_pilot_slots(self):
        from demo.models import DemoSlot
        from accounts.models import UserProfile, DriverClaim
        from website.models import Driver, RaceClass

        self.stdout.write('Пилоты...')
        race_classes = list(RaceClass.objects.all())
        drivers = []

        for i in range(1, SLOT_COUNT + 1):
            email = f'demo_pilot_{i}@email.ru'
            user, created = self._get_or_create_user(email, f'Пилот{i}', 'Демо')

            DemoSlot.objects.get_or_create(
                slot_type='pilot', slot_number=i, defaults={'user': user},
            )

            UserProfile.objects.get_or_create(
                user=user,
                defaults={'email_verified': True, 'city': 'Москва'},
            )

            # Driver + DriverClaim
            driver = self._get_or_create_driver(f'Пилот{i}', 'Демо', i)
            drivers.append(driver)

            if not DriverClaim.objects.filter(user=user, status='approved').exists():
                DriverClaim.objects.create(
                    user=user,
                    driver=driver,
                    requested_first_name=f'Пилот{i}',
                    requested_last_name='Демо',
                    status='approved',
                )

        return drivers

    def _get_or_create_driver(self, first_name, last_name, num):
        from website.models import Driver
        slug_base = f'demo-pilot-{num}'
        slug = slug_base
        counter = 1
        while Driver.objects.filter(slug=slug).exists():
            existing = Driver.objects.filter(slug=slug).first()
            if existing.first_name == first_name and existing.last_name == last_name:
                return existing
            slug = f'{slug_base}-{counter}'
            counter += 1

        driver = Driver(
            first_name=first_name,
            last_name=last_name,
            slug=slug,
            live=True,
        )
        driver.save()
        return driver

    # ------------------------------------------------------------------
    # Команды
    # ------------------------------------------------------------------

    def _create_team_slots(self, pilot_drivers):
        from demo.models import DemoSlot
        from teams.models import TeamManager
        from website.models import Team, TeamMembership, TeamStaff, TeamStaffMembership, RaceClass
        from accounts.models import UserProfile

        self.stdout.write('Команды...')
        race_classes = list(RaceClass.objects.all())

        for i in range(1, SLOT_COUNT + 1):
            email = f'demo_team_{i}@email.ru'
            user, created = self._get_or_create_user(email, f'Команда{i}', 'Демо')

            DemoSlot.objects.get_or_create(
                slot_type='team', slot_number=i, defaults={'user': user},
            )

            UserProfile.objects.get_or_create(
                user=user, defaults={'email_verified': True},
            )

            team = self._get_or_create_team(i)

            TeamManager.objects.get_or_create(
                user=user, team=team,
                defaults={'role': 'captain', 'is_active': True},
            )

            # Добавляем 4 пилота из демо-пилотов (с разными классами)
            if pilot_drivers:
                selected = pilot_drivers[(i - 1) * 4 % len(pilot_drivers):(i - 1) * 4 % len(pilot_drivers) + 4]
                if len(selected) < 4:
                    selected = (pilot_drivers * 2)[:(4)]
                for driver in selected:
                    TeamMembership.objects.get_or_create(
                        driver=driver, team=team,
                        defaults={'is_active': True},
                    )

            # Сотрудники команды
            if not TeamStaffMembership.objects.filter(team=team).exists():
                for staff_name, position in STAFF_ROLES:
                    slug = f'demo-team-{i}-{position.lower().replace(" ", "-")[:20]}'
                    counter = 1
                    while TeamStaff.objects.filter(slug=slug).exists():
                        slug = f'demo-team-{i}-{position.lower().replace(" ", "-")[:15]}-{counter}'
                        counter += 1
                    staff = TeamStaff(
                        first_name=staff_name,
                        last_name=f'Команды {i}',
                        slug=slug,
                        position=position,
                        live=True,
                    )
                    staff.save()
                    TeamStaffMembership.objects.get_or_create(
                        staff=staff, team=team, defaults={'is_active': True},
                    )

    def _get_or_create_team(self, num):
        from website.models import Team
        slug = f'demo-team-{num}'
        team, created = Team.objects.get_or_create(
            slug=slug,
            defaults={'name': f'Демо Команда {num}', 'manager_name': f'Демо Менеджер {num}'},
        )
        if created:
            team.live = True
            team.save()
        return team
