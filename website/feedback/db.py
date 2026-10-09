"""Обращение к БД из асинхронного кода бота (долгоживущий процесс).

Django открывает и закрывает соединение на каждый HTTP-запрос, а у бота запросов нет — без
`close_old_connections()` он держит одно соединение до перезапуска процесса. После перезапуска
PostgreSQL (09.10.2026: автоматические обновления Ubuntu в 06:42) каждое обращение падало с
«the connection is closed», heartbeat не писался, бот «молчал» до ручного перезапуска.
"""
from asgiref.sync import sync_to_async
from django.db import close_old_connections


def _fresh(func, args, kwargs):
    # Закрывает соединение, если оно устарело (CONN_MAX_AGE) или сломалось; следующий запрос откроет новое.
    close_old_connections()
    return func(*args, **kwargs)


def run_sync(func, *args, **kwargs):
    """Синхронная функция с ORM из async-кода — всегда на живом соединении с БД."""
    return sync_to_async(_fresh, thread_sensitive=True)(func, args, kwargs)
