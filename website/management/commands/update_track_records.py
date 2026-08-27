from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Пересчитывает и записывает в БД рекорды трасс по классам '
        '(Track.records_cache). Запускать вручную после ввода новых '
        'результатов — как update_ratings.'
    )

    def handle(self, *args, **options):
        from website.models import Track
        from website.views import _compute_all_track_records

        all_records = _compute_all_track_records()

        updated = 0
        for track in Track.objects.all():
            track.records_cache = all_records.get(track.id, {})
            track.save()
            updated += 1

        self.stdout.write(self.style.SUCCESS(f'Обновлено трасс: {updated}'))
