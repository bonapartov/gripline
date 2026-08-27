from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = (
        'Полное обновление аналитики после ввода новых результатов: '
        'рейтинги + турнирные таблицы + рекорды трасс. Обёртка над '
        'update_ratings, update_championship_standings и update_track_records — '
        'запускается кнопкой «Запустить обновление» в /admin/analytics/.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--entity', type=str, default='all')
        parser.add_argument('--model', type=str, default='all')

    def handle(self, *args, **options):
        self.stdout.write('=== Рейтинги (update_ratings) ===')
        call_command('update_ratings', entity=options['entity'], model=options['model'])

        self.stdout.write('=== Турнирные таблицы (update_championship_standings) ===')
        call_command('update_championship_standings')

        self.stdout.write('=== Рекорды трасс (update_track_records) ===')
        call_command('update_track_records')

        self.stdout.write(self.style.SUCCESS('=== Обновление аналитики завершено ==='))
