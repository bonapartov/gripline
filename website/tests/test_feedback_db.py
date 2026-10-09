"""Бот переживает перезапуск PostgreSQL (09.10.2026): соединение, закрытое со стороны сервера,
не ломает следующие обращения к БД."""
import asyncio

import pytest
from django.db import connection

from website.feedback.db import run_sync
from website.models import FeedbackBotSettings


@pytest.mark.django_db(transaction=True)
def test_run_sync_reconnects_after_server_closed_connection():
    async def scenario():
        await run_sync(lambda: FeedbackBotSettings.objects.filter(pk=1).count())
        # Сервер закрыл соединение (перезапуск PostgreSQL): Django об этом не знает.
        await run_sync(lambda: (connection.ensure_connection(), connection.connection.close()))
        return await run_sync(lambda: FeedbackBotSettings.objects.filter(pk=1).count())

    assert asyncio.run(scenario()) >= 0
