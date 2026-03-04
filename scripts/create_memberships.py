# scripts/create_memberships.py
from website.models import Team, Driver, TeamMembership
from django.utils import timezone

def run():
    print("Создаем членства для существующих пилотов...")

    for team in Team.objects.all():
        # Находим всех пилотов, которые есть в результатах этой команды
        drivers = Driver.objects.filter(raceresult__team=team).distinct()

        count = 0
        for driver in drivers:
            # Создаем активное членство, если его нет
            membership, created = TeamMembership.objects.get_or_create(
                driver=driver,
                team=team,
                defaults={
                    'joined_at': timezone.now().date(),
                    'is_active': True
                }
            )
            if created:
                count += 1

        print(f"Команда {team.name}: добавлено {count} пилотов")

    print("Готово!")

if __name__ == "__main__":
    run()
