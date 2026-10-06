"""Анонимизация обращений старше срока хранения + чистка черновиков. Запуск по cron раз в сутки."""
import asyncio
import logging

from asgiref.sync import sync_to_async

from django.core.management.base import BaseCommand

from website.feedback import service
from website.models import FeedbackBotSettings

logger = logging.getLogger('feedback')


async def _refresh_cards(feedbacks):
    from website.feedback.channels.telegram import TelegramAdapter, build_bot
    cfg = await sync_to_async(FeedbackBotSettings.get)()
    token = cfg.get_token()
    if not token or not cfg.admin_chat_id:
        return 0
    bot = build_bot(token, cfg.proxy_url())
    adapter = TelegramAdapter(bot)
    done = 0
    try:
        for fb in feedbacks:
            try:
                await adapter.update_admin_card(fb)
                done += 1
            except Exception:
                logger.warning('Карточка №%s не перерисована', fb.pk)
    finally:
        await bot.session.close()
    return done


class Command(BaseCommand):
    help = 'Анонимизирует обращения старше срока хранения и чистит просроченные черновики.'

    def add_arguments(self, parser):
        parser.add_argument('--no-cards', action='store_true', help='Не перерисовывать карточки в админ-чате.')

    def handle(self, *args, **options):
        from website.dashboard.jobs import record_job
        with record_job('feedback_cleanup') as info:
            affected, drafts, users = service.cleanup_expired()
            summary = f'Анонимизировано обращений: {len(affected)}; черновиков удалено: {drafts}; пользователей удалено: {users}.'
            self.stdout.write(summary)
            info['message'] = f'обращений: {len(affected)}, черновиков: {drafts}'
            if affected and not options['no_cards']:
                refreshed = asyncio.run(_refresh_cards(affected))
                self.stdout.write(f'Карточек перерисовано: {refreshed}.')
