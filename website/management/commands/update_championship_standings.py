from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Пересчитывает и кэширует турнирные таблицы чемпионатов '
        '(ChampionshipPage.standings_cache). Запускать вручную после ввода '
        'новых результатов — как update_ratings.'
    )

    def handle(self, *args, **options):
        from website.models import ChampionshipPage

        updated = 0
        for champ in ChampionshipPage.objects.all():
            years = champ.get_years()
            cache = {}
            for cache_key, year in [('__all__', None)] + [(str(y), y) for y in years]:
                champions_by_class = champ._compute_champions_by_class(year)
                cache[cache_key] = {
                    str(class_id): {
                        'name': data['name'],
                        'champions': [
                            {
                                'position': c['position'],
                                'driver_id': c['driver'].id,
                                'points': c['points'],
                                'starts': c['starts'],
                            }
                            for c in data['champions']
                        ],
                    }
                    for class_id, data in champions_by_class.items()
                }
            champ.standings_cache = cache
            champ.save()
            updated += 1

        self.stdout.write(self.style.SUCCESS(f'Обновлено чемпионатов: {updated}'))
