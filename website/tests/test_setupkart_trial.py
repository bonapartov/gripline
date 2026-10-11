"""Пробный период устройства (11.10.2026): начало хранится на сайте по хэшу ANDROID_ID — переустановка,
«Очистить данные» и перевод часов на телефоне не дают новый пробный период."""
import datetime

import pytest
from django.core.cache import cache
from django.utils import timezone

from website.models import AppProSettings, AppTrialDevice

URL = '/api/setupkart/trial/'
DEV = 'a' * 64


@pytest.fixture(autouse=True)
def env(db):
    cache.clear()
    yield
    cache.clear()


def post(client, **body):
    data = {'device': DEV, 'client_id': 'install-1', 'app_version': '1.0.0+3000', **body}
    return client.post(URL, data, content_type='application/json')


def iso(dt):
    return datetime.datetime.fromisoformat(dt)


def test_first_contact_starts_trial_and_returns_server_time(client):
    pro = AppProSettings.get()
    pro.trial_days = 30
    pro.save()
    before = timezone.now()
    r = post(client).json()
    started, ends, now = iso(r['trial_started_at']), iso(r['trial_ends_at']), iso(r['server_now'])
    assert before <= started <= now
    assert ends - started == datetime.timedelta(days=30)
    d = AppTrialDevice.objects.get()
    assert (d.client_id, d.installs, d.app_version) == ('install-1', 1, '1.0.0+3000')


def test_reinstall_keeps_trial_start_and_counts_installs(client):
    first = post(client).json()['trial_started_at']
    AppTrialDevice.objects.update(first_seen_at=timezone.now() - datetime.timedelta(days=40))
    r = post(client, client_id='install-2', local_first_launch=timezone.now().isoformat()).json()
    assert iso(r['trial_started_at']) < iso(first), 'новая установка с «первым запуском сегодня» не сдвигает начало'
    assert iso(r['trial_ends_at']) < timezone.now(), 'пробный период уже закончился'
    assert AppTrialDevice.objects.get().installs == 2
    post(client, client_id='install-2')
    assert AppTrialDevice.objects.get().installs == 2, 'та же установка — не новая'


def test_earlier_local_first_launch_is_accepted_later_is_not(client):
    early = timezone.now() - datetime.timedelta(days=20)
    r = post(client, local_first_launch=early.isoformat()).json()
    assert abs(iso(r['trial_started_at']) - early) < datetime.timedelta(seconds=1), \
        'установка до появления проверки — пробный период не начинается заново'
    r = post(client, local_first_launch=timezone.now().isoformat()).json()
    assert abs(iso(r['trial_started_at']) - early) < datetime.timedelta(seconds=1)


@pytest.mark.parametrize('bad', ['2020-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00', 'вчера'])
def test_implausible_local_first_launch_ignored(client, bad):
    before = timezone.now()
    r = post(client, local_first_launch=bad).json()
    assert iso(r['trial_started_at']) >= before


def test_trial_not_before_paid_version_enabled(client):
    post(client)
    AppTrialDevice.objects.update(first_seen_at=timezone.now() - datetime.timedelta(days=100))
    pro = AppProSettings.get()
    pro.enabled = True
    pro.save()
    assert pro.enabled_at is not None
    r = post(client).json()
    assert iso(r['trial_started_at']) == pro.enabled_at, 'поставившие до включения Pro получают полный пробный период'
    enabled_at = pro.enabled_at
    pro.enabled = False
    pro.save()
    pro.enabled = True
    pro.save()
    assert AppProSettings.get().enabled_at == enabled_at, 'повторное включение не перезапускает пробный период'
    assert AppProSettings.get().payload()['trial_not_before'] == enabled_at.isoformat()


def test_admin_override(client):
    post(client)
    until = timezone.now() + datetime.timedelta(days=90)
    AppTrialDevice.objects.update(trial_ends_override=until)
    assert iso(post(client).json()['trial_ends_at']) == until


@pytest.mark.parametrize('device', ['', 'xyz', 'A' * 63, 'g' * 64])
def test_invalid_device(client, device):
    assert post(client, device=device).status_code == 400
    assert not AppTrialDevice.objects.exists()


def test_rate_limited_per_device(client):
    for _ in range(30):
        assert post(client).status_code == 200
    assert post(client).status_code == 429


def test_config_carries_offline_grace(client):
    pro = AppProSettings.get()
    pro.offline_grace_days = 5
    pro.save()
    p = client.get('/api/setupkart/config/').json()['pro']
    assert (p['offline_grace_days'], p['trial_not_before']) == (5, None)


def test_cleanup_removes_devices_silent_longer_than_retention(client):
    from django.core.management import call_command
    from website.models import ScheduledJobRun
    pro = AppProSettings.get()
    pro.trial_retention_months = 24
    pro.save()
    post(client)
    post(client, device='b' * 64)
    AppTrialDevice.objects.filter(device_hash='b' * 64).update(
        last_seen_at=timezone.now() - datetime.timedelta(days=30 * 24 + 1))
    call_command('setupkart_trial_cleanup', '--dry-run')
    assert AppTrialDevice.objects.count() == 2
    call_command('setupkart_trial_cleanup')
    assert list(AppTrialDevice.objects.values_list('device_hash', flat=True)) == [DEV]
    assert ScheduledJobRun.objects.get(name='setupkart_trial_cleanup').last_success_at is not None


def test_config_privacy_notice(client, settings):
    from website.models import AppSyncSettings
    settings.BASE_URL = 'https://gripline.ru'
    assert client.get('/api/setupkart/config/').json()['privacy_notice'] is None
    s = AppSyncSettings.get()
    s.privacy_notice_date = datetime.date(2026, 10, 11)
    s.privacy_notice = 'Добавлен учёт пробного периода.'
    s.save()
    assert client.get('/api/setupkart/config/').json()['privacy_notice'] == {
        'date': '2026-10-11', 'text': 'Добавлен учёт пробного периода.',
        'url': 'https://gripline.ru/legal/setupkart-privacy/'}


def test_setupkart_privacy_mentions_device_hash():
    """Политика должна описывать то, что приложение реально отправляет (п. 9.1)."""
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / 'legal_pages' / 'setupkart_privacy.html').read_text()
    assert 'ANDROID_ID' in html and 'Отправить журнал' in html and '24 месяца' in html
    assert AppProSettings._meta.get_field('trial_retention_months').default == 24, 'срок в политике — 24 месяца'
