"""Утренняя сводка в админ-чат Telegram.

Содержит только счётчики и статусы — персональных данных нет (группа — не лучшее
место для контактов заявителей). Время отправки — FeedbackBotSettings.digest_time
(по Москве); cron вызывает `daily_digest` каждые 10 минут, команда сама решает, пора ли.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from website.feedback import notify
from . import data, health

DIGEST_WINDOW = timedelta(hours=24)


def digest_due(cfg, now=None):
    """Пора ли отправлять: включено, время наступило, сегодня ещё не отправляли."""
    now = timezone.localtime(now or timezone.now())
    return bool(
        cfg.digest_enabled
        and cfg.digest_last_sent_on != now.date()
        and now.time() >= cfg.digest_time
    )


def build_digest(now=None):
    now = now or timezone.now()
    local = timezone.localtime(now)
    base = settings.BASE_URL.rstrip('/')
    checks = health.collect_health(now)
    problems = [c for c in checks if c['level'] in ('warn', 'fail')]
    attention = [a for a in data.attention_items(now) if a['count'] and a['digest']]
    news = [n for n in data.news_since(now - DIGEST_WINDOW) if n['count']]
    rating = data.rating_block(now)

    lines = [f'☀️ <b>Gripline — сводка на {local:%d.%m.%Y}</b>']
    if problems:
        lines += ['', '<b>Система</b>']
        lines += [f'{c["icon"]} {c["name"]}: {c["text"]}' for c in problems]
    lines += ['', '<b>Требует внимания</b>']
    if attention:
        for a in attention:
            note = f' ({a["note"]})' if a['note'] else ''
            icon = '🔴' if a['level'] == 'fail' else '•'
            lines.append(f'{icon} {a["label"]}: {a["count"]}{note}')
    else:
        lines.append('Очередей нет ✅')
    lines += ['', '<b>За сутки</b>']
    lines.append(' · '.join(f'{n["label"].lower()}: {n["count"]}' for n in news) if news else 'Тихо, новых событий нет.')
    if rating['needs_update']:
        lines += ['', f'📊 Пора пересчитать рейтинг: добавлено результатов — {rating["added"]}']
    if rating['events_without_results_count']:
        lines.append(f'Заездов без результатов (60 дней): {rating["events_without_results_count"]}')
    if not problems:
        lines += ['', 'Система: всё в порядке ✅']
    lines += ['', f'<a href="{base}/admin/">Открыть админку</a>']
    return '\n'.join(lines)


def send_digest(now=None):
    """True — сводка ушла в чат. Исключения не глотаем: команда пометит запуск сбоем."""
    return notify.send_admin_chat_message(build_digest(now))
