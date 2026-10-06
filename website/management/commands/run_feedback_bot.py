"""Запуск Telegram-бота обратной связи (long polling). Под systemd, Restart=always."""
import asyncio
import logging

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Запускает Telegram-бота обратной связи (настройки — в админке: Бот обратной связи).'

    def handle(self, *args, **options):
        from website.feedback.telegram_bot import run_forever
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
        try:
            asyncio.run(run_forever())
        except KeyboardInterrupt:
            pass
