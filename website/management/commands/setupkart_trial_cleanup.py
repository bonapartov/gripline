"""Удаляет записи пробного периода устройств, которые не выходили на связь дольше срока из «Pro-версии»
(политика конфиденциальности приложения, п. 7.2). Cron раз в сутки."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Удалить устройства пробного периода, давно не выходившие на связь'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Только посчитать, ничего не удалять')

    def handle(self, *args, dry_run=False, **options):
        from website.dashboard.jobs import record_job
        from website.models import AppProSettings, AppTrialDevice

        months = AppProSettings.get().trial_retention_months
        old = AppTrialDevice.objects.filter(last_seen_at__lt=timezone.now() - timedelta(days=30 * months))
        if dry_run:
            self.stdout.write(f'Удалилось бы: {old.count()}')
            return
        with record_job('setupkart_trial_cleanup') as info:
            deleted, _ = old.delete()
            info['message'] = f'удалено {deleted}'
            self.stdout.write(f'Удалено устройств: {deleted}')
