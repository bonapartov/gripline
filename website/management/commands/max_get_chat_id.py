# -*- coding: utf-8 -*-
"""
Одноразовая bootstrap-команда: ловит chat_id канала MAX.
Запуск: python manage.py max_get_chat_id [--minutes 10]

У MAX нет способа получить chat_id канала списком (GET /chats снят с
поддержки с июня 2026) — единственный способ узнать его — поймать событие
bot_added через long-polling GET /updates в момент, когда администратор
добавляет бота в канал. Эта команда не пишет в БД — только печатает
найденный chat_id, дальше его нужно вручную внести в Wagtail Admin →
Соцсети → MAX → Настройки.
"""
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Ловит chat_id канала MAX через long-polling GET /updates. Запускать "
        "сразу после того, как бот добавлен администратором в целевой канал."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes', type=int, default=10,
            help='Сколько суммарно ждать событие bot_added, прежде чем сдаться',
        )

    def handle(self, *args, **options):
        token = settings.MAX_ANNOUNCE_BOT_TOKEN
        if not token:
            raise CommandError("MAX_ANNOUNCE_BOT_TOKEN не задан в .env")

        base_url = settings.MAX_API_BASE_URL
        headers = {"Authorization": token}
        deadline = time.monotonic() + options['minutes'] * 60
        marker = None

        self.stdout.write(self.style.WARNING(
            "Жду событие bot_added... Если ещё не сделали — добавьте бота "
            "администратором в целевой канал MAX прямо сейчас."
        ))

        while time.monotonic() < deadline:
            params = {"timeout": 25}
            if marker is not None:
                params["marker"] = marker
            try:
                resp = requests.get(f"{base_url}/updates", headers=headers, params=params, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as e:
                self.stderr.write(self.style.ERROR(f"Ошибка запроса к MAX API: {e}"))
                time.sleep(3)
                continue

            data = resp.json()
            marker = data.get('marker', marker)
            updates = data.get('updates', data if isinstance(data, list) else [])

            for update in updates:
                self.stdout.write(str(update))
                # Фильтруем строго по update_type == 'bot_added' — иначе
                # можно случайно поймать chat_id личной переписки от события
                # 'bot_started' (кто-то просто открыл чат с ботом) вместо
                # chat_id канала. Событие канала дополнительно отличается
                # флагом is_channel=True и отрицательным chat_id.
                if update.get('update_type') != 'bot_added':
                    continue
                chat_id = self._find_chat_id(update)
                if chat_id is not None:
                    self.stdout.write(self.style.SUCCESS(
                        f"\nchat_id найден: {chat_id} — впишите его в "
                        "Wagtail Admin → Соцсети → MAX → Настройки"
                    ))
                    return

        self.stdout.write(self.style.WARNING(
            "Событие bot_added не поймано за отведённое время. Убедитесь, что "
            "бот действительно добавлен администратором именно сейчас (после "
            "запуска этой команды) в целевой канал MAX, и повторите попытку."
        ))

    def _find_chat_id(self, update):
        """Эвристический поиск chat_id в теле апдейта — точная схема ответа
        GET /updates не на 100% подтверждена документацией на момент
        написания, поэтому ищем ключ 'chat_id' на верхнем уровне и в
        возможном вложенном 'chat', а не полагаемся на конкретное имя
        update_type."""
        if not isinstance(update, dict):
            return None
        if 'chat_id' in update:
            return update['chat_id']
        chat = update.get('chat')
        if isinstance(chat, dict):
            return chat.get('chat_id', chat.get('id'))
        return None
