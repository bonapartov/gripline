"""Проверки «здоровья» системы для главной страницы админки и утренней сводки.

Каждая проверка — (название, level, текст); level: ok | warn | fail | unknown.
Сетевая проба прокси короткая и выключена в DEBUG (локально прокси нет,
и она всегда «падала» бы)."""
import glob
import os
import shutil
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .jobs import human_age, job_checks

LEVEL_ORDER = {'ok': 0, 'unknown': 1, 'warn': 2, 'fail': 3}
LEVEL_ICON = {'ok': '✅', 'unknown': '⚪', 'warn': '⚠️', 'fail': '🔴'}
HTTP_PROBE_TIMEOUT = 5
PROXY_CACHE_KEY = 'dashboard:telegram_proxy'
PROXY_CACHE_SEC = 60
# Заведомо неверный токен: Telegram отвечает 401 и JSON с полем ok.
# Этого достаточно, чтобы отличить живой Bot API от мёртвого туннеля,
# не используя реальный токен бота.
TELEGRAM_PROBE_URL = 'https://api.telegram.org/bot0:0/getMe'
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


def _telegram_via_proxy(proxy_url):
    """End-to-end проба Bot API через прокси: (ok, задержка в секундах | None)."""
    import requests

    started = time.monotonic()
    try:
        response = requests.get(
            TELEGRAM_PROBE_URL,
            proxies={'http': proxy_url, 'https': proxy_url},
            timeout=HTTP_PROBE_TIMEOUT,
        )
        payload = response.json()
    except (requests.RequestException, ValueError):
        return False, None
    if not isinstance(payload, dict) or 'ok' not in payload:
        return False, None
    return True, time.monotonic() - started


def check_proxy():
    from website.models import FeedbackBotSettings, VpnSettings
    if not FeedbackBotSettings.get().use_vpn:
        return ('Прокси для Telegram', 'unknown', 'не используется')
    url = VpnSettings.get().effective_url()
    parsed = urlparse(url or '')
    if not parsed.hostname or not parsed.port:
        return ('Прокси для Telegram', 'warn', 'адрес прокси не задан')

    cached = cache.get(PROXY_CACHE_KEY)
    if cached is None:
        ok, latency = _telegram_via_proxy(url)
        cache.set(PROXY_CACHE_KEY, (ok, latency), PROXY_CACHE_SEC)
    else:
        ok, latency = cached

    where = f'{parsed.hostname}:{parsed.port}'
    if not ok:
        return ('Прокси для Telegram', 'fail', f'{where}: Bot API не отвечает через прокси')
    if latency is None:
        return ('Прокси для Telegram', 'ok', f'{where}: Bot API отвечает')
    return ('Прокси для Telegram', 'ok', f'{where}: Bot API отвечает за {latency:.2f} с')


def collect_health(now=None, probe=None):
    now = now or timezone.now()
    probe = (not settings.DEBUG) if probe is None else probe
    checks = [check_bot(now), check_backup(now), check_disk(), check_mail()]
    if probe:
        checks += [check_proxy()]
    checks += job_checks(now)
    return [{'name': n, 'level': lvl, 'text': text, 'icon': LEVEL_ICON[lvl]} for n, lvl, text in checks]


def worst_level(checks):
    return max((c['level'] for c in checks), key=LEVEL_ORDER.get, default='ok')
