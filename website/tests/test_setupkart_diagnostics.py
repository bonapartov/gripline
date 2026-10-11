"""Журнал приложения из «Настроек» → AppDiagnosticReport + уведомление в админ-чат (11.10.2026)."""
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from website.feedback import notify
from website.models import AppDiagnosticReport

URL = '/api/setupkart/diagnostics/'


@pytest.fixture(autouse=True)
def env(db, settings, monkeypatch):
    cache.clear()
    settings.BASE_URL = 'https://gripline.ru'
    sent = []
    monkeypatch.setattr(notify, 'notify_admin_chat', lambda text, label: sent.append(text))
    yield sent
    cache.clear()


def post(client, **body):
    data = {'client_id': 'install-1', 'log': 'tracks: local=8 server=10', 'app_version': '1.0.0+2001',
            'device_info': 'Android 14', 'comment': 'трасс меньше', **body}
    return client.post(URL, data, content_type='application/json')


def test_report_saved_and_admin_notified(client, env, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = post(client)
    assert resp.status_code == 201
    r = AppDiagnosticReport.objects.get(pk=resp.json()['number'])
    assert (r.client_id, r.comment, r.log) == ('install-1', 'трасс меньше', 'tracks: local=8 server=10')
    assert len(env) == 1 and f'№{r.pk}' in env[0] and 'install-1' not in env[0]


@pytest.mark.parametrize('body', [{'client_id': ''}, {'log': '  '}, {'log': 'x' * 200_001}])
def test_validation(client, body):
    assert post(client, **body).status_code == 400
    assert not AppDiagnosticReport.objects.exists()


def test_rate_limit_per_install(client):
    codes = [post(client).status_code for _ in range(6)]
    assert codes[:5] == [201] * 5 and codes[5] == 429


def test_admin_pages(client):
    r = AppDiagnosticReport.objects.create(client_id='c', log='<b>строка</b>', app_version='1')
    admin = get_user_model().objects.create_superuser('adm', 'a@a.ru', 'x')
    client.force_login(admin)
    assert client.get('/admin/setupkart/diagnostics/').status_code == 200
    page = client.get(f'/admin/setupkart/diagnostics/{r.pk}/')
    assert page.status_code == 200 and '&lt;b&gt;строка' in page.content.decode()
    r.refresh_from_db()
    assert r.is_read
    client.post(f'/admin/setupkart/diagnostics/{r.pk}/', {'action': 'delete'})
    assert not AppDiagnosticReport.objects.exists()
