from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Пересчитывает PulseCache'

    def handle(self, *args, **options):
        from website.models import PulseCache
        self.stdout.write('Пересчёт PulseCache...')
        PulseCache.rebuild()
        self.stdout.write(self.style.SUCCESS('PulseCache успешно обновлён'))
