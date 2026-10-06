"""Статистика обращений (website/feedback/stats.py + страница в админке)."""
from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse
from django.utils import timezone

from website.feedback import service, stats
from website.models import Feedback, FeedbackCategory, FeedbackMessage, FeedbackUser


@pytest.fixture(autouse=True)
def private_media(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / 'private'


@pytest.fixture
def cats(db):
    return (
        FeedbackCategory.objects.create(slug='e', title='Ошибка в данных', emoji='🐞', deep_link_code='err'),
        FeedbackCategory.objects.create(slug='i', title='Предложение', emoji='💡', deep_link_code='idea'),
    )


@pytest.fixture
def user(db):
    return FeedbackUser.objects.create(channel='telegram', external_user_id='1', username='u')


def make(category, user, ago_hours=1, **kw):
    fb = Feedback.objects.create(category=category, user=user, **kw)
    Feedback.objects.filter(pk=fb.pk).update(created_at=timezone.now() - timedelta(hours=ago_hours))
    fb.refresh_from_db()
    return fb


def test_human_duration():
    assert stats.human_duration(None) == '—'
    assert stats.human_duration(timedelta(minutes=12)) == '12 мин'
    assert stats.human_duration(timedelta(hours=2, minutes=15)) == '2 ч 15 мин'
    assert stats.human_duration(timedelta(days=3, hours=4)) == '3 дн 4 ч'


def test_parse_period():
    assert stats.parse_period('7') == 7 and stats.parse_period('0') == 0
    assert stats.parse_period('13') == stats.DEFAULT_PERIOD
    assert stats.parse_period('abc') == stats.DEFAULT_PERIOD and stats.parse_period(None) == stats.DEFAULT_PERIOD


def test_empty_database_does_not_crash(db):
    s = stats.compute_stats(30)
    assert s['total'] == 0 and s['categories'] == [] and s['daily_peak'] == 0
    assert s['median_first_reply'] == '—' and len(s['daily']) == 30


def test_counts_by_status_category_and_period(cats, user):
    e, i = cats
    make(e, user, status='new')
    make(e, user, status='in_work')
    make(i, user, status='done', closed_at=timezone.now())
    make(i, user, ago_hours=24 * 60)  # старше 30 дней
    s = stats.compute_stats(30)
    assert (s['total'], s['new'], s['in_work'], s['done']) == (3, 1, 1, 1)
    assert s['open_now'] == 3  # new + in_work + старое new без закрытия — открытые считаются по всей базе
    by_cat = {c['title']: c for c in s['categories']}
    assert by_cat['🐞 Ошибка в данных']['count'] == 2 and by_cat['🐞 Ошибка в данных']['share'] == 67
    assert stats.compute_stats(0)['total'] == 4 and stats.compute_stats(7)['total'] == 3


def test_open_now_ignores_period(cats, user):
    make(cats[0], user, ago_hours=24 * 100, status='in_work')
    s = stats.compute_stats(7)
    assert s['total'] == 0 and s['open_now'] == 1


def test_response_times(cats, user):
    fb = make(cats[0], user, ago_hours=5)
    msg = FeedbackMessage.objects.create(feedback=fb, direction='out', text='ответ')
    FeedbackMessage.objects.filter(pk=msg.pk).update(created_at=fb.created_at + timedelta(hours=2))
    Feedback.objects.filter(pk=fb.pk).update(closed_at=fb.created_at + timedelta(hours=4), status='done')
    s = stats.compute_stats(30)
    assert s['median_first_reply'] == '2 ч 0 мин' and s['replied_count'] == 1
    assert s['median_to_close'] == '4 ч 0 мин'


def test_unanswered_lists_only_old_open_without_reply(cats, user):
    old = make(cats[0], user, ago_hours=72, status='new')
    answered = make(cats[0], user, ago_hours=72, status='in_work')
    FeedbackMessage.objects.create(feedback=answered, direction='out', text='x')
    make(cats[0], user, ago_hours=1, status='new')                 # свежее
    make(cats[0], user, ago_hours=72, status='done')               # закрытое
    assert [u['id'] for u in stats.compute_stats(30)['unanswered']] == [old.pk]


def test_daily_chart_fills_empty_days_and_scales(cats, user):
    make(cats[0], user, ago_hours=1)
    make(cats[0], user, ago_hours=2)
    s = stats.compute_stats(7)
    assert len(s['daily']) == 7 and s['daily_peak'] >= 1
    assert max(d['height'] for d in s['daily']) == 100
    assert sum(d['count'] for d in s['daily']) == 2
    assert s['last_day'] == s['daily'][-1]['date']


def test_top_sources_resolved_and_deleted_page_marked(cats, user, monkeypatch):
    monkeypatch.setattr(stats.sources, 'resolve',
                        lambda kind, pk: stats.sources.ResolvedSource(kind, pk, 'Этап 5', 'https://x/5/') if pk == 5 else None)
    for _ in range(3):
        make(cats[0], user, source_kind='stage', source_id=5)
    make(cats[0], user, source_kind='pilot', source_id=99)
    make(cats[0], user)  # без источника — в топ не попадает
    top = stats.compute_stats(30)['top_sources']
    assert top[0] == {'count': 3, 'title': 'Этап 5', 'url': 'https://x/5/'}
    assert 'страница удалена' in top[1]['title']
    kinds = {k['label']: k['count'] for k in stats.compute_stats(30)['kinds']}
    assert kinds['Без привязки к странице'] == 1 and kinds['Этап (класс)'] == 3


def test_anonymized_feedback_still_counted(cats, user):
    fb = make(cats[0], user)
    service.anonymize_feedback(fb)
    s = stats.compute_stats(30)
    assert s['total'] == 1 and s['anonymized'] == 1 and s['authors'] == 0


# ---- страница ----

def test_stats_page_renders_with_data(client, cats, user):
    old = make(cats[0], user, ago_hours=72, status='new', source_kind='stage', source_id=1)
    client.force_login(User.objects.create_superuser('root', 'r@example.com', 'pw'))
    html = client.get(reverse('feedback_stats')).content.decode()
    assert 'Статистика обращений' in html and 'Ошибка в данных' in html
    assert f'№{old.pk}' in html and 'Без ответа дольше 48' in html
    assert client.get(reverse('feedback_stats') + '?days=0').status_code == 200
    assert client.get(reverse('feedback_stats') + '?days=bogus').status_code == 200


def test_stats_page_empty_state(client, db):
    client.force_login(User.objects.create_superuser('root', 'r@example.com', 'pw'))
    html = client.get(reverse('feedback_stats')).content.decode()
    assert 'За этот период обращений не было' in html


def test_stats_page_requires_view_permission(client, db):
    plain = User.objects.create_user('plain', password='pw')
    plain.user_permissions.add(Permission.objects.get(codename='access_admin'))
    client.force_login(plain)
    assert client.get(reverse('feedback_stats')).status_code == 403
    plain.user_permissions.add(Permission.objects.get(codename='view_feedback'))
    client = type(client)()
    client.force_login(User.objects.get(pk=plain.pk))
    assert client.get(reverse('feedback_stats')).status_code == 200


def test_menu_item_in_feedback_group(client, db):
    client.force_login(User.objects.create_superuser('root', 'r@example.com', 'pw'))
    html = client.get('/admin/website/feedback/').content.decode()
    # меню Wagtail отдаёт пункты JSON-ом с экранированием кириллицы — ищем ссылку, не подпись
    assert reverse('feedback_stats') in html
