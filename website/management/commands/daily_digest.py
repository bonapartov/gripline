"""Утренняя сводка в Telegram. Cron раз в 10 минут:
  */10 * * * * cd /www/wwwroot/gripline.ru && venv/bin/python manage.py daily_digest >> /var/log/gripline-digest.log 2>&1
Команда сама проверяет время из настроек бота («Утренняя сводка») и не шлёт дважды в день."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from website.dashboard import digest
from website.dashboard.jobs import record_job
from website.models import FeedbackBotSettings


class Command(BaseCommand):
    help = 'Отправляет утреннюю сводку в админ-чат бота, если пришло время из настроек.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Отправить сейчас, независимо от времени и от того, что уже отправлено.')
        parser.add_argument('--dry-run', action='store_true', help='Только вывести текст сводки, ничего не отправляя.')

    def handle(self, *args, **options):
        if options['dry_run']:
            self.stdout.write(digest.build_digest())
            return
        with record_job('daily_digest') as info:
            cfg = FeedbackBotSettings.get()
            if not options['force'] and not digest.digest_due(cfg):
                info['message'] = 'не время или уже отправлена'
                return
            if not digest.send_digest():
                raise CommandError('Сводка не отправлена: проверьте токен, ID админ-чата и доступ к Telegram.')
            cfg.digest_last_sent_on = timezone.localdate()
            cfg.save(update_fields=['digest_last_sent_on'])
            info['message'] = 'сводка отправлена'
            self.stdout.write(self.style.SUCCESS('Сводка отправлена.'))
