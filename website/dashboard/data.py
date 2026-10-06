"""Данные для главной страницы админки и утренней сводки.

Только счётчики и ссылки — без персональных данных (в сводке они уходят в
групповой чат Telegram)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Exists, OuterRef
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

PERIODS = [('visit', 'С прошлого визита'), ('day', '24 часа'), ('week', '7 дней')]
VISIT_GAP = timedelta(minutes=30)   # пауза, после которой заход считается новым визитом
FIRST_VISIT_WINDOW = timedelta(days=7)
UNANSWERED_HOURS = 48
RESULTS_ABSENT_DAYS = 60            # «этап без результатов» — только недавние, иначе шум от архива


def _url(name, query=''):
    try:
        return reverse(name) + query
    except NoReverseMatch:
        return ''


# ---------- окно «с прошлого визита» ----------

def touch_visit(user, now=None):
    """Возвращает начало окна «с прошлого визита» и фиксирует текущий заход.
    Повторные обновления страницы в течение 30 минут окно не сдвигают."""
    from website.models import AdminDashboardVisit
    now = now or timezone.now()
    visit = AdminDashboardVisit.objects.filter(user=user).first()
    if visit is None:
        AdminDashboardVisit.objects.create(user=user, last_seen=now, since=now - FIRST_VISIT_WINDOW)
        return now - FIRST_VISIT_WINDOW
    if now - visit.last_seen > VISIT_GAP:
        visit.since = visit.last_seen
    visit.last_seen = now
    visit.save(update_fields=['since', 'last_seen'])
    return visit.since


def window_start(period, visit_since, now=None):
    now = now or timezone.now()
    if period == 'day':
        return now - timedelta(hours=24)
    if period == 'week':
        return now - timedelta(days=7)
    return visit_since


# ---------- 1. Требует внимания ----------

def attention_items(now=None):
    """Очереди, которые ждут действия. level: fail (просрочено) | warn (ждёт) | ok (пусто)."""
    from accounts.models import DriverClaim
    from applications.models import Application
    from teams.models import TeamClaim
    from wagtail.models import Page
    from website.models import DataRequest, Feedback
    from website.feedback.stats import OPEN_STATUSES

    now = now or timezone.now()
    today = timezone.localdate(now)
    items = []

    def add(label, count, url, note='', level=None, digest=True):
        items.append({
            'label': label, 'count': count, 'url': url, 'note': note,
            'level': level or ('warn' if count else 'ok'),
            'digest': digest,  # входит ли в утреннюю сводку (черновики — нет: не срочно)
        })

    add('Заявки на привязку пилота', DriverClaim.objects.filter(status='pending').count(),
        _url('accounts_driverclaim_modeladmin_index'))
    add('Заявки на управление командой', TeamClaim.objects.filter(status='pending').count(),
        _url('admin:teams_teamclaim_changelist', '?status__exact=pending'))
    add('Заявки на участие в этапах', Application.objects.filter(status='submitted').count(),
        _url('admin:applications_application_changelist', '?status__exact=submitted'))

    pd_open = DataRequest.objects.filter(status__in=('new', 'in_progress'))
    pd_count = pd_open.count()
    overdue = pd_open.filter(due_date__lt=today).count()
    nearest = pd_open.exclude(due_date__lt=today).order_by('due_date').values_list('due_date', flat=True).first()
    note = f'просрочено: {overdue}' if overdue else (f'ближайший срок: {nearest:%d.%m.%Y}' if nearest else '')
    add('Обращения по персональным данным', pd_count, _url('website_datarequest_modeladmin_index'), note,
        level='fail' if overdue else None)

    fb_new = Feedback.objects.filter(status=Feedback.STATUS_NEW).count()
    stale = (Feedback.objects.filter(status__in=OPEN_STATUSES, created_at__lte=now - timedelta(hours=UNANSWERED_HOURS))
             .exclude(messages__direction='out').count())
    add('Новые обращения бота', fb_new, _url('website_feedback_modeladmin_index'),
        f'без ответа > {UNANSWERED_HOURS} ч: {stale}' if stale else '', level='fail' if stale else None)

    drafts = Page.objects.filter(live=False).exclude(depth__lte=1).count()
    add('Неопубликованные страницы', drafts, _url('wagtailadmin_explore_root'), level='warn' if drafts else 'ok', digest=False)
    return items


# ---------- 2. Что нового ----------

def news_since(since):
    from accounts.models import DriverClaim
    from applications.models import Application
    from teams.models import TeamClaim
    from wagtail.models import Page
    from website.models import DataRequest, Feedback

    rows = [
        ('Новых регистраций', User.objects.filter(date_joined__gte=since).count()),
        ('Заявок на привязку пилота', DriverClaim.objects.filter(created_at__gte=since).count()),
        ('Заявок на управление командой', TeamClaim.objects.filter(created_at__gte=since).count()),
        ('Заявок на участие в этапах', Application.objects.filter(created_at__gte=since).exclude(status='draft').count()),
        ('Обращений бота', Feedback.objects.filter(created_at__gte=since).count()),
        ('Обращений по ПД', DataRequest.objects.filter(created_at__gte=since).count()),
        ('Опубликовано страниц', Page.objects.filter(first_published_at__gte=since).count()),
    ]
    return [{'label': label, 'count': count} for label, count in rows]


# ---------- 4. Рейтинг ----------

def rating_block(now=None):
    from wagtail.models import Page
    from website.models import EventPage, RaceResult, UpdateLog

    now = now or timezone.now()
    last = UpdateLog.objects.filter(status='success').first()
    results_now = RaceResult.objects.count()
    added = None
    if last is not None and last.race_results_count is not None:
        added = max(0, results_now - last.race_results_count)

    since = now - timedelta(days=RESULTS_ABSENT_DAYS)
    from website.models import RaceResult as RR
    without_results = (
        EventPage.objects.live()
        .filter(occurrences__start__lt=now, occurrences__start__gte=since)
        .annotate(has_results=Exists(RR.objects.filter(group__page=OuterRef('pk'))))
        .filter(has_results=False).distinct().order_by('-occurrences__start')
    )
    events = []
    for p in without_results[:5]:
        parent = p.get_parent()
        events.append({
            'title': f'{parent.title} → {p.title}' if parent else p.title,
            'url': reverse('wagtailadmin_pages:edit', args=[p.pk]),
        })
    return {
        'last_at': last.updated_at if last else None,
        'added': added,
        'needs_update': bool(added),
        'url': _url('analytics_dashboard'),
        'events_without_results': events,
        'events_without_results_count': without_results.count(),
    }


# ---------- 5. Сводка по сайту ----------

def site_summary():
    from wagtail.models import Page
    from website.models import Driver, RaceResult, Team

    return [
        {'label': 'Пилотов', 'count': Driver.objects.count()},
        {'label': 'Команд', 'count': Team.objects.count()},
        {'label': 'Результатов', 'count': RaceResult.objects.count()},
        {'label': 'Пользователей', 'count': User.objects.count()},
        {'label': 'Опубликованных страниц', 'count': Page.objects.live().exclude(depth__lte=1).count()},
    ]
