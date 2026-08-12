# -*- coding: utf-8 -*-
"""
Одноразовая bootstrap-команда: резолвит screen_name сообщества VK в
числовой group_id.
Запуск: python manage.py vk_get_group_id --screen-name gripline

В отличие от MAX (нужен long-polling GET /updates), у VK это простой
публичный метод utils.resolveScreenName — не нужно ждать никаких событий.
Команда не пишет в БД — только печатает, дальше group_id нужно вручную
внести в Wagtail Admin → Соцсети → VK → Настройки.
"""
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from website.vk import VK_API_BASE_URL


class Command(BaseCommand):
    help = "Резолвит screen_name сообщества VK (из URL vk.ru/<screen_name>) в числовой group_id."

    def add_arguments(self, parser):
        parser.add_argument(
            '--screen-name', type=str, required=True,
            help='Например: gripline (из https://vk.ru/gripline)',
        )

    def handle(self, *args, **options):
        token = settings.VK_ANNOUNCE_ACCESS_TOKEN
        if not token:
            raise CommandError("VK_ANNOUNCE_ACCESS_TOKEN не задан в .env")

        resp = requests.post(
            f"{VK_API_BASE_URL}/utils.resolveScreenName",
            data={
                'screen_name': options['screen_name'],
                'access_token': token,
                'v': settings.VK_API_VERSION,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if 'error' in data:
            error = data['error']
            raise CommandError(f"VK API error: code={error.get('error_code')} msg={error.get('error_msg')}")

        result = data.get('response')
        if not result or result.get('type') != 'group':
            self.stdout.write(self.style.ERROR(
                f"Не удалось распознать '{options['screen_name']}' как сообщество. Ответ VK: {result}"
            ))
            return

        group_id = result['object_id']
        self.stdout.write(self.style.SUCCESS(
            f"group_id найден: {group_id} — впишите его в Wagtail Admin → Соцсети → VK → Настройки"
        ))
