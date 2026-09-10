"""
Лимиты и rate limiting серверных эндпоинтов /balance/ — Блок 3 ТЗ «Сервис
расчёта развесовки карта», раздел 12 «Защита и ограничения доступа». Сам
расчёт клиентский (balance-calculator.js), под лимит попадают только
серверные операции: сохранение/копирование/шеринг/архивация сетапа,
создание карта/записи ростера.

Захардкоженные константы, не настройка в админке — по образцу
TITLES_MAX/TRACK_RECORDS_MAX в website/services/mediakit.py: недостижимо
для живого пользователя, тривиально поднять числом при необходимости, не
то, что стоит выносить в БД без явного запроса.

Rate limiting — свой декоратор на django.core.cache, не сторонняя
библиотека (в проекте нет ни одной — ни django-ratelimit, ни аналогов).
mysite/settings/prod.py держит FileBasedCache — общий для всех воркеров
бэкенд, тот же cache.get/cache.set уже используется в
website/weather_utils.py для похожей задачи.
"""
import logging
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse

logger = logging.getLogger("balance.ratelimit")

MAX_KARTS_PER_OWNER = 50
MAX_SETUPS_PER_KART = 500
MAX_BALLASTS_PER_SETUP = 30


def client_ip(request):
    """X-Forwarded-For (первый хоп в цепочке) с фолбэком на REMOTE_ADDR.
    Проверено на проде (Этап 7 плана Блока 3, аудит) — nginx location / уже
    выставляет `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`
    (/etc/nginx/sites-available/gripline), /balance/ отдельного location не
    имеет и falls through в этот же блок — заголовок долетает как есть."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def balance_ratelimit(key, limit, window_seconds):
    """Декоратор: не более `limit` вызовов за `window_seconds` секунд с
    одного IP на этот `key`. Превышение — HTTP 429 + запись в лог для
    ручного разбора всплесков (ТЗ §12 «Логирование аномалий»)."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            ip = client_ip(request)
            cache_key = f"balance:rl:{key}:{ip}"
            count = cache.get(cache_key)
            if count is None:
                cache.set(cache_key, 1, timeout=window_seconds)
            elif count >= limit:
                logger.warning(
                    "balance rate limit exceeded: key=%s ip=%s count=%s", key, ip, count,
                )
                return HttpResponse("Слишком много запросов, попробуйте позже.", status=429)
            else:
                try:
                    cache.incr(cache_key)
                except ValueError:
                    # Ключ протух между get и incr (гонка на границе окна) —
                    # не блокировать пользователя из-за этого, начать заново.
                    cache.set(cache_key, 1, timeout=window_seconds)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
