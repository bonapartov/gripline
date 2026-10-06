"""Проверки «здоровья» системы для главной страницы админки и утренней сводки.

Каждая проверка — (название, level, текст); level: ok | warn | fail | unknown.
Сетевые пробы (FastAPI, прокси) короткие и выключены в DEBUG (локально этих
сервисов нет, и они всегда «падали» бы)."""
import glob
import os
import shutil
import socket
from datetime import datetime, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from .jobs import human_age, job_checks

LEVEL_ORDER = {'ok': 0, 'unknown': 1, 'warn': 2, 'fail': 3}
LEVEL_ICON = {'ok': '✅', 'unknown': '⚪', 'warn': '⚠️', 'fail': '🔴'}
PROBE_TIMEOUT = 0.7
BOT_HEARTBEAT_OK_SEC = 90
BACKUP_WARN_DAYS = 8     # cron делает бэкап раз в неделю
BACKUP_FAIL_DAYS = 15
DISK_WARN, DISK_FAIL = 85, 95


def check_bot(now):
    from website.models import FeedbackBotSettings
    cfg = FeedbackBotSettings.get()
    if not cfg.is_enabled:
        return ('Бот обратной связи', 'unknown', 'выключен в настройках')
    if cfg.heartbeat_at is None:
        return ('Бот обратной связи', 'fail', 'ещё ни разу не выходил на связь')
    age = now - cfg.heartbeat_at
    if age.total_seconds() > BOT_HEARTBEAT_OK_SEC:
        return ('Бот обратной связи', 'fail', f'молчит: последний ответ {human_age(age)}')
    return ('Бот обратной связи', 'ok', 'работает')


def check_backup(now):
    folder = getattr(settings, 'BACKUP_DIR', '/backups')
    files = glob.glob(os.path.join(folder, '*.sql*'))
    if not files:
        return ('Бэкап БД', 'unknown', 'папка с бэкапами не найдена или пуста')
    newest = max(files, key=os.path.getmtime)
    age = now - datetime.fromtimestamp(os.path.getmtime(newest), tz=timezone.get_current_timezone())
    if age > timedelta(days=BACKUP_FAIL_DAYS):
        level = 'fail'
    elif age > timedelta(days=BACKUP_WARN_DAYS):
        level = 'warn'
    else:
        level = 'ok'
    return ('Бэкап БД', level, f'{human_age(age)} ({os.path.basename(newest)})')


def check_disk():
    try:
        usage = shutil.disk_usage('/')
    except OSError:
        return ('Диск', 'unknown', 'нет данных')
    percent = round(usage.used * 100 / usage.total)
    level = 'fail' if percent >= DISK_FAIL else 'warn' if percent >= DISK_WARN else 'ok'
    return ('Диск', level, f'занято {percent}%, свободно {usage.free // 2**30} ГБ')


def check_mail():
    from website.models import MailSettings
    if MailSettings.get().enabled:
        return ('Исходящая почта', 'ok', 'включена')
    return ('Исходящая почта', 'warn', 'отправка писем выключена (кил-свитч)')


def _tcp_ok(host, port):
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def check_fastapi():
    return ('Мобильный API (FastAPI)',) + (
        ('ok', 'отвечает') if _tcp_ok('127.0.0.1', 8001) else ('fail', 'не отвечает на порту 8001'))


def check_proxy():
    from website.models import FeedbackBotSettings, VpnSettings
    if not FeedbackBotSettings.get().use_vpn:
        return ('Прокси для Telegram', 'unknown', 'не используется')
    url = VpnSettings.get().effective_url()
    parsed = urlparse(url or '')
    if not parsed.hostname or not parsed.port:
        return ('Прокси для Telegram', 'warn', 'адрес прокси не задан')
    if _tcp_ok(parsed.hostname, parsed.port):
        return ('Прокси для Telegram', 'ok', f'{parsed.hostname}:{parsed.port} доступен')
    return ('Прокси для Telegram', 'fail', f'{parsed.hostname}:{parsed.port} не отвечает')


def collect_health(now=None, probe=None):
    now = now or timezone.now()
    probe = (not settings.DEBUG) if probe is None else probe
    checks = [check_bot(now), check_backup(now), check_disk(), check_mail()]
    if probe:
        checks += [check_fastapi(), check_proxy()]
    checks += job_checks(now)
    return [{'name': n, 'level': lvl, 'text': text, 'icon': LEVEL_ICON[lvl]} for n, lvl, text in checks]


def worst_level(checks):
    return max((c['level'] for c in checks), key=LEVEL_ORDER.get, default='ok')
