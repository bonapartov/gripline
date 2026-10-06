"""Главная страница админки (website/dashboard/) и утренняя сводка."""
import datetime
import os
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import DriverClaim
from website.dashboard import data, digest, health, jobs
from website.feedback import notify
from website.models import (
    DataRequest, Feedback, FeedbackBotSettings, FeedbackCategory, FeedbackMessage,
    ScheduledJobRun, UpdateLog,
)


@pytest.fixture(autouse=True)
def fernet(settings):
    settings.FEEDBACK_FERNET_KEY = 'cmV6b2x2ZXpvbHZlenJlem9sdmV6b2x2ZXpvbHZlenI='


@pytest.fixture
def site(db):
    # --no-migrations → стартового дерева Wagtail нет; главная админки читает Site/корень
    from django.conf import settings as dj_settings
    from wagtail.coreutils import get_supported_content_language_variant
    from wagtail.models import Locale, Page, Site
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(dj_settings.LANGUAGE_CODE))
    root = Page.add_root(title='Root', slug='root')
    return Site.objects.create(hostname='testserver', root_page=root, is_default_site=True)


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser('root', 'r@example.com', 'pw')


# ---------- задачи ----------

def test_record_job_success_and_failure(db):
    with jobs.record_job('feedback_cleanup') as info:
        info['message'] = 'ок'
    run = ScheduledJobRun.objects.get(name='feedback_cleanup')
    assert run.last_success_at and run.last_message == 'ок'
    with pytest.raises(ValueError):
        with jobs.record_job('feedback_cleanup'):
            raise ValueError('бум')
    run.refresh_from_db()
    assert run.last_failure_at and 'бум' in run.last_message and run.last_success_at


def test_job_checks_levels(db):
    now = timezone.now()
    by_label = lambda: {label: (lvl, text) for label, lvl, text in jobs.job_checks(now)}
    assert by_label()['Очистка обращений бота (ПД)'][0] == 'unknown'          # ещё не запускалась — нейтрально
    ScheduledJobRun.objects.create(name='feedback_cleanup', last_success_at=now - timedelta(hours=2))
    assert by_label()['Очистка обращений бота (ПД)'][0] == 'ok'
    ScheduledJobRun.objects.filter(name='feedback_cleanup').update(last_success_at=now - timedelta(hours=40))
    assert by_label()['Очистка обращений бота (ПД)'][0] == 'fail'               # молчит дольше 36 ч
    ScheduledJobRun.objects.create(name='daily_digest', last_failure_at=now, last_message='boom')
    assert by_label()['Проверка утренней сводки'][0] == 'fail'                  # ни разу не удавалась
    ScheduledJobRun.objects.filter(name='daily_digest').update(last_success_at=now - timedelta(minutes=5))
    assert by_label()['Проверка утренней сводки'][0] == 'warn'                  # недавний сбой после успеха


# ---------- здоровье ----------

def test_backup_check(tmp_path, settings):
    settings.BACKUP_DIR = str(tmp_path)
    now = timezone.now()
    assert health.check_backup(now)[1] == 'unknown'
    f = tmp_path / 'gripline_20261004.sql'
    f.write_text('x')
    assert health.check_backup(now)[1] == 'ok'
    old = (now - timedelta(days=10)).timestamp()
    os.utime(f, (old, old))
    assert health.check_backup(now)[1] == 'warn'
    older = (now - timedelta(days=20)).timestamp()
    os.utime(f, (older, older))
    assert health.check_backup(now)[1] == 'fail'


def test_bot_check(db):
    now = timezone.now()
    cfg = FeedbackBotSettings.get()
    assert health.check_bot(now)[1] == 'unknown'          # выключен
    cfg.is_enabled = True
    cfg.save()
    assert health.check_bot(now)[1] == 'fail'             # ни разу не выходил
    FeedbackBotSettings.objects.update(heartbeat_at=now - timedelta(seconds=10))
    assert health.check_bot(now)[1] == 'ok'
    FeedbackBotSettings.objects.update(heartbeat_at=now - timedelta(minutes=10))
    assert health.check_bot(now)[1] == 'fail'


def test_disk_check_levels(monkeypatch):
    import collections
    usage = collections.namedtuple('u', 'total used free')
    for used, level in ((50, 'ok'), (90, 'warn'), (97, 'fail')):
        monkeypatch.setattr(health.shutil, 'disk_usage', lambda p, u=used: usage(100 * 2**30, u * 2**30, (100 - u) * 2**30))
        assert health.check_disk()[1] == level


def test_collect_health_skips_network_probes_by_default_in_debug(db, settings):
    settings.DEBUG = True
    names = [c['name'] for c in health.collect_health()]
    assert 'Мобильный API (FastAPI)' not in names and 'Бэкап БД' in names
    assert health.worst_level([{'level': 'ok'}, {'level': 'fail'}, {'level': 'warn'}]) == 'fail'


# ---------- очереди ----------

def test_attention_counts_and_levels(db, admin_user):
    now = timezone.now()
    DriverClaim.objects.create(user=admin_user, requested_first_name='И', requested_last_name='И')
    DriverClaim.objects.create(user=admin_user, requested_first_name='П', requested_last_name='П', status='approved')
    DataRequest.objects.create(request_type='deletion', contact='a@b.c', text='x' * 12, is_confirmed=True)
    late = DataRequest.objects.create(request_type='deletion', contact='a@b.c', text='x' * 12, is_confirmed=True)
    DataRequest.objects.filter(pk=late.pk).update(due_date=timezone.localdate() - timedelta(days=1))
    cat = FeedbackCategory.objects.create(slug='c', title='C')
    fresh = Feedback.objects.create(category=cat)
    stale = Feedback.objects.create(category=cat)
    Feedback.objects.filter(pk=stale.pk).update(created_at=now - timedelta(hours=72))
    answered = Feedback.objects.create(category=cat, status='in_work')
    Feedback.objects.filter(pk=answered.pk).update(created_at=now - timedelta(hours=72))
    FeedbackMessage.objects.create(feedback=answered, direction='out', text='x')

    items = {i['label']: i for i in data.attention_items(now)}
    assert items['Заявки на привязку пилота']['count'] == 1 and items['Заявки на привязку пилота']['level'] == 'warn'
    pd = items['Обращения по персональным данным']
    assert pd['count'] == 2 and pd['level'] == 'fail' and 'просрочено: 1' in pd['note']
    bot = items['Новые обращения бота']
    assert bot['count'] == 2 and bot['level'] == 'fail' and 'без ответа' in bot['note']  # 2 новых; 1 висит > 48 ч
    assert items['Заявки на управление командой']['level'] == 'ok'
    assert items['Неопубликованные страницы']['digest'] is False


# ---------- что нового / окно визита ----------

def test_news_since_counts_only_new(db, admin_user):
    now = timezone.now()
    old = User.objects.create_user('old', password='x')
    User.objects.filter(pk=old.pk).update(date_joined=now - timedelta(days=10))
    counts = {n['label']: n['count'] for n in data.news_since(now - timedelta(days=1))}
    assert counts['Новых регистраций'] == 1          # только admin_user, не old
    assert data.news_since(now - timedelta(days=30))[0]['count'] == 2


def test_visit_window_moves_only_on_new_visit(admin_user):
    t0 = timezone.now()
    first = data.touch_visit(admin_user, t0)
    assert first == t0 - data.FIRST_VISIT_WINDOW                       # первый заход — неделя назад
    assert data.touch_visit(admin_user, t0 + timedelta(minutes=10)) == first   # обновление страницы окно не двигает
    assert data.touch_visit(admin_user, t0 + timedelta(minutes=20)) == first
    later = t0 + timedelta(hours=5)
    since = data.touch_visit(admin_user, later)                         # пауза > 30 мин — новый визит
    assert since == t0 + timedelta(minutes=20)                          # окно начинается с последнего просмотра
    assert data.touch_visit(admin_user, later + timedelta(minutes=5)) == since


def test_window_start_periods():
    now = timezone.now()
    visit = now - timedelta(days=3)
    assert data.window_start('visit', visit, now) == visit
    assert data.window_start('day', visit, now) == now - timedelta(hours=24)
    assert data.window_start('week', visit, now) == now - timedelta(days=7)
    assert data.window_start('bogus', visit, now) == visit


# ---------- рейтинг ----------

def test_update_log_remembers_results_count(db):
    log = UpdateLog.objects.create(status='success')
    assert log.race_results_count == 0
    block = data.rating_block()
    assert block['added'] == 0 and block['needs_update'] is False and block['last_at']


def test_rating_block_without_any_update_and_old_log(db):
    assert data.rating_block()['last_at'] is None
    UpdateLog.objects.bulk_create([UpdateLog(status='success')])      # старая запись без отметки (в обход save)
    assert data.rating_block()['added'] is None


def test_site_summary_shape(db):
    labels = [s['label'] for s in data.site_summary()]
    assert labels == ['Пилотов', 'Команд', 'Результатов', 'Пользователей', 'Опубликованных страниц']


# ---------- страница ----------

def test_admin_home_renders_dashboard(client, admin_user, site):
    client.force_login(admin_user)
    html = client.get('/admin/').content.decode()
    for heading in ('Требует внимания', 'Что нового', 'Состояние системы', 'Рейтинг и результаты', 'Сайт в цифрах'):
        assert heading in html
    assert 'Вся статистика обращений' in html                      # суперпользователь видит блок обращений
    assert client.get('/admin/?dash=week').status_code == 200
    assert client.get('/admin/?dash=мусор').status_code == 200


def test_feedback_block_hidden_without_permission(client, db, site):
    editor = User.objects.create_user('ed', password='pw')
    editor.user_permissions.add(Permission.objects.get(codename='access_admin'))
    client.force_login(editor)
    html = client.get('/admin/').content.decode()
    assert 'Состояние системы' in html and 'Вся статистика обращений' not in html


# ---------- сводка ----------

def test_digest_due_logic(db):
    cfg = FeedbackBotSettings.get()
    cfg.digest_time = datetime.time(9, 0)
    tz = timezone.get_current_timezone()
    day = datetime.date(2026, 10, 7)
    at = lambda h, m=0: datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
    assert digest.digest_due(cfg, at(8, 59)) is False             # рано
    assert digest.digest_due(cfg, at(9, 0)) is True
    assert digest.digest_due(cfg, at(15)) is True                  # пропустили окно — всё равно отправим
    cfg.digest_last_sent_on = day
    assert digest.digest_due(cfg, at(15)) is False                 # сегодня уже была
    cfg.digest_last_sent_on = day - timedelta(days=1)
    assert digest.digest_due(cfg, at(9, 10)) is True
    cfg.digest_enabled = False
    assert digest.digest_due(cfg, at(15)) is False


def test_digest_text_has_numbers_not_personal_data(db, admin_user):
    DataRequest.objects.create(request_type='deletion', contact='secret@example.com', text='паспорт 1234 5678', is_confirmed=True)
    cat = FeedbackCategory.objects.create(slug='c', title='C')
    Feedback.objects.create(category=cat, answers={'text': 'очень личное'})
    text = digest.build_digest()
    assert 'Обращения по персональным данным: 1' in text and 'Новые обращения бота: 1' in text
    assert 'secret@example.com' not in text and 'паспорт' not in text and 'очень личное' not in text
    assert '<a href=' in text and '/admin/' in text
    assert 'Неопубликованные страницы' not in text                  # не срочно — в сводку не идёт


def test_digest_quiet_day_message(db):
    text = digest.build_digest()
    assert 'Очередей нет' in text or 'Требует внимания' in text


def _configure_bot(monkeypatch):
    cfg = FeedbackBotSettings.get()
    cfg.set_token('123456789:AAFabcdefghijklmnopqrstuvwxyz0123')
    cfg.admin_chat_id = -1001
    cfg.save()
    sent = []
    monkeypatch.setattr(notify.tg_sync, 'api_call', lambda token, method, proxy=None, payload=None, timeout=0: sent.append(payload) or {})
    return sent


def test_command_sends_once_per_day_and_records_job(db, monkeypatch):
    sent = _configure_bot(monkeypatch)
    FeedbackBotSettings.objects.update(digest_time=datetime.time(0, 0))       # время уже наступило
    call_command('daily_digest', stdout=StringIO())
    assert len(sent) == 1 and sent[0]['chat_id'] == -1001 and sent[0]['parse_mode'] == 'HTML'
    assert FeedbackBotSettings.get().digest_last_sent_on == timezone.localdate()
    call_command('daily_digest', stdout=StringIO())                          # cron через 10 минут
    assert len(sent) == 1
    assert ScheduledJobRun.objects.get(name='daily_digest').last_success_at


def test_command_not_due_does_nothing(db, monkeypatch):
    sent = _configure_bot(monkeypatch)
    FeedbackBotSettings.objects.update(digest_time=datetime.time(23, 59), digest_enabled=False)
    call_command('daily_digest', stdout=StringIO())
    assert not sent


def test_command_force_and_dry_run(db, monkeypatch):
    sent = _configure_bot(monkeypatch)
    FeedbackBotSettings.objects.update(digest_time=datetime.time(23, 59))
    out = StringIO()
    call_command('daily_digest', '--dry-run', stdout=out)
    assert 'Gripline — сводка' in out.getvalue() and not sent
    call_command('daily_digest', '--force', stdout=StringIO())
    assert len(sent) == 1


def test_command_failure_is_recorded(db, monkeypatch):
    FeedbackBotSettings.get()                                                 # строки настроек в пустой БД ещё нет
    FeedbackBotSettings.objects.update(digest_time=datetime.time(0, 0))      # время наступило, а бот не настроен — отправить нечем
    with pytest.raises(CommandError):
        call_command('daily_digest', stdout=StringIO())
    run = ScheduledJobRun.objects.get(name='daily_digest')
    assert run.last_failure_at and FeedbackBotSettings.get().digest_last_sent_on is None


def test_other_cron_commands_record_runs(db):
    call_command('feedback_cleanup', '--no-cards', stdout=StringIO())
    assert ScheduledJobRun.objects.get(name='feedback_cleanup').last_success_at


def test_digest_now_button_endpoint(client, admin_user, monkeypatch):
    from django.urls import reverse
    sent = _configure_bot(monkeypatch)
    client.force_login(admin_user)
    data_ = client.post(reverse('feedback_bot_digest_now')).json()
    assert data_['ok'] and len(sent) == 1
    page = client.get(f'/admin/website/feedbackbotsettings/edit/{FeedbackBotSettings.get().pk}/').content.decode()
    assert 'Отправить сводку сейчас' in page and 'digest_time' in page
