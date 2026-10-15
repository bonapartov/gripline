"""Напоминания пилотам об истечении документов из ЛК (applications/reminders.py).
Cron раз в сутки; проверять на проде только с --dry-run — без него письма уходят."""
from django.core.management.base import BaseCommand

from applications import reminders
from website.dashboard.jobs import record_job


class Command(BaseCommand):
    help = 'Отправляет напоминания о скором окончании срока документов в ЛК пилотов.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Только показать, кому пора напомнить.')

    def handle(self, *args, dry_run=False, **options):
        if dry_run:
            sent, failed, log = reminders.send_all(dry_run=True)
            for line in log:
                self.stdout.write(line)
            self.stdout.write(f"dry-run: к отправке {sum(line.startswith('документ') for line in log)}")
            return
        with record_job('send_document_reminders') as info:
            sent, failed, log = reminders.send_all()
            info['message'] = f'отправлено {sent}' + (f', не доставлено {failed}' if failed else '')
        self.stdout.write(info['message'])
