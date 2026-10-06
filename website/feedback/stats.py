"""
Статистика обращений для админки («Обратная связь» → «Статистика»).

Считается на лету из БД, без отдельных таблиц и без персональных данных:
анонимизированные обращения (/forget, срок хранения) остаются в счётчиках —
у них сохраняются категория, статус и даты (см. service.anonymize_feedback).
Времена ответа считаются только по обращениям, у которых ещё есть сообщения
диалога: после анонимизации сообщения удаляются.
"""
import statistics
from datetime import timedelta

from django.db.models import Count, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from website.models import Feedback
from . import sources

PERIODS = [(7, '7 дней'), (30, '30 дней'), (90, '90 дней'), (365, 'Год'), (0, 'Всё время')]
DEFAULT_PERIOD = 30
CHART_MAX_DAYS = 90
UNANSWERED_AFTER = timedelta(hours=48)
TOP_SOURCES = 10
OPEN_STATUSES = (Feedback.STATUS_NEW, Feedback.STATUS_IN_WORK)

SOURCE_LABELS = dict(Feedback.SOURCE_CHOICES)


def human_duration(delta):
    """timedelta → «3 дн 4 ч», «2 ч 15 мин», «12 мин»; None → «—»."""
    if delta is None:
        return '—'
    minutes = int(delta.total_seconds() // 60)
    days, rest = divmod(minutes, 60 * 24)
    hours, mins = divmod(rest, 60)
    if days:
        return f'{days} дн {hours} ч'
    if hours:
        return f'{hours} ч {mins} мин'
    return f'{mins} мин'


def _median(values):
    return statistics.median(values) if values else None


def parse_period(raw):
    """GET-параметр ?days= → допустимое значение (0 = всё время)."""
    allowed = {days for days, _ in PERIODS}
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PERIOD
    return days if days in allowed else DEFAULT_PERIOD


def compute_stats(days=DEFAULT_PERIOD, now=None):
    now = now or timezone.now()
    qs = Feedback.objects.all()
    if days:
        qs = qs.filter(created_at__gte=now - timedelta(days=days))

    total = qs.count()
    by_status = {row['status']: row['n'] for row in qs.values('status').annotate(n=Count('id'))}

    categories = []
    for row in qs.values('category__title', 'category__emoji').annotate(
        n=Count('id'), open=Count('id', filter=Q(status__in=OPEN_STATUSES)),
    ).order_by('-n'):
        categories.append({
            'title': f'{row["category__emoji"]} {row["category__title"]}'.strip() if row['category__title'] else 'Без категории',
            'count': row['n'], 'open': row['open'],
            'share': round(row['n'] * 100 / total) if total else 0,
        })

    kinds = []
    for row in qs.values('source_kind').annotate(n=Count('id')).order_by('-n'):
        kinds.append({
            'label': SOURCE_LABELS.get(row['source_kind'], 'Без привязки к странице') if row['source_kind'] else 'Без привязки к странице',
            'count': row['n'],
        })

    top = []
    for row in (qs.exclude(source_kind='').exclude(source_id__isnull=True)
                .values('source_kind', 'source_id').annotate(n=Count('id')).order_by('-n', 'source_kind')[:TOP_SOURCES]):
        resolved = sources.resolve(row['source_kind'], row['source_id'])
        top.append({
            'count': row['n'],
            'title': resolved.title if resolved else f'{SOURCE_LABELS.get(row["source_kind"], "")} #{row["source_id"]} (страница удалена)',
            'url': resolved.url if resolved else '',
        })

    # --- динамика по дням: пустые дни тоже нужны, иначе график врёт ---
    span = min(days or CHART_MAX_DAYS, CHART_MAX_DAYS)
    today = timezone.localdate(now)
    first_day = today - timedelta(days=span - 1)
    per_day = {
        row['day']: row['n']
        for row in Feedback.objects.filter(created_at__date__gte=first_day)
        .annotate(day=TruncDate('created_at')).values('day').annotate(n=Count('id'))
    }
    daily = [{'date': first_day + timedelta(days=i), 'count': per_day.get(first_day + timedelta(days=i), 0)} for i in range(span)]
    peak = max((d['count'] for d in daily), default=0)
    for d in daily:
        d['height'] = round(d['count'] * 100 / peak) if peak else 0

    # --- скорость реакции ---
    first_reply = [
        row.first_reply - row.created_at
        for row in qs.filter(messages__direction='out').annotate(first_reply=Min('messages__created_at'))
    ]
    to_close = [row.closed_at - row.created_at for row in qs.filter(closed_at__isnull=False)]

    # --- что висит прямо сейчас (не зависит от периода) ---
    open_now = Feedback.objects.filter(status__in=OPEN_STATUSES)
    stale = list(
        open_now.filter(created_at__lte=now - UNANSWERED_AFTER)
        .exclude(messages__direction='out').select_related('category').order_by('created_at')[:10]
    )
    unanswered = [{
        'id': f.pk, 'category': f.category.title if f.category else '—',
        'age': human_duration(now - f.created_at), 'status': f.get_status_display(),
    } for f in stale]

    return {
        'days': days,
        'total': total,
        'new': by_status.get(Feedback.STATUS_NEW, 0),
        'in_work': by_status.get(Feedback.STATUS_IN_WORK, 0),
        'done': by_status.get(Feedback.STATUS_DONE, 0),
        'open_now': open_now.count(),
        'authors': qs.exclude(user=None).values('user').distinct().count(),
        'anonymized': qs.filter(anonymized_at__isnull=False).count(),
        'median_first_reply': human_duration(_median(first_reply)),
        'median_to_close': human_duration(_median(to_close)),
        'replied_count': len(first_reply),
        'categories': categories,
        'kinds': kinds,
        'top_sources': top,
        'daily': daily,
        'last_day': daily[-1]['date'] if daily else None,
        'daily_peak': peak,
        'unanswered': unanswered,
        'unanswered_hours': int(UNANSWERED_AFTER.total_seconds() // 3600),
    }
