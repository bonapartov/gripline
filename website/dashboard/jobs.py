"""
Регулярные (cron) задачи: реестр ожидаемых и отметка о запуске.

Дашборд админки по этим отметкам видит, что задача не молчит. Бэкап БД (shell-cron
вне Django) проверяется отдельно — по возрасту файла (health.check_backup).
"""
from contextlib import contextmanager
from datetime import timedelta

from django.utils import timezone

HOUR = 3600
# имя -> (подпись, через сколько секунд без успешного запуска считаем сбоем)
JOBS = {
    'feedback_cleanup': ('Очистка обращений бота (ПД)', 36 * HOUR),
    'reset_demo_accounts': ('Сброс демо-аккаунтов', 36 * HOUR),
    # cron раз в 10 минут: если молчит больше часа — cron или команда сломаны
    'daily_digest': ('Проверка утренней сводки', 1 * HOUR),
}


@contextmanager
def record_job(name):
    """with record_job('имя') as info: ...; info['message'] = '…' — итог для дашборда.
    Исключение фиксируется как сбой и пробрасывается дальше."""
    from website.models import ScheduledJobRun
    info = {'message': ''}
    try:
        yield info
    except Exception as exc:
        ScheduledJobRun.objects.update_or_create(name=name, defaults={
            'last_failure_at': timezone.now(), 'last_message': f'{type(exc).__name__}: {exc}'[:255],
        })
        raise
    else:
        ScheduledJobRun.objects.update_or_create(name=name, defaults={
            'last_success_at': timezone.now(), 'last_message': (info.get('message') or '')[:255],
        })


def human_age(delta):
    seconds = int(delta.total_seconds())
    if seconds < 90:
        return 'только что'
    minutes = seconds // 60
    if minutes < 90:
        return f'{minutes} мин назад'
    hours = minutes // 60
    if hours < 48:
        return f'{hours} ч назад'
    return f'{hours // 24} дн назад'


def job_checks(now=None):
    """[(подпись, level, текст)] по реестру JOBS. Ни разу не запускавшаяся — нейтрально
    (unknown): сразу после деплоя это нормально, а не сбой."""
    from website.models import ScheduledJobRun
    now = now or timezone.now()
    runs = {r.name: r for r in ScheduledJobRun.objects.filter(name__in=JOBS)}
    result = []
    for name, (label, max_age) in JOBS.items():
        run = runs.get(name)
        if run is None or run.last_success_at is None:
            failed = run is not None and run.last_failure_at is not None
            result.append((label, 'fail' if failed else 'unknown',
                           f'сбой: {run.last_message}' if failed else 'ещё не запускалась'))
            continue
        age = now - run.last_success_at
        if age > timedelta(seconds=max_age):
            result.append((label, 'fail', f'не запускалась {human_age(age)}'))
        elif run.last_failure_at and run.last_failure_at > run.last_success_at:
            result.append((label, 'warn', f'последний запуск со сбоем: {run.last_message}'))
        else:
            result.append((label, 'ok', human_age(age) + (f' · {run.last_message}' if run.last_message else '')))
    return result
