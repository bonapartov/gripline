"""Меры по итогам security-ревью регистраций/заявок (07.10.2026)."""
import re

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.http import HttpResponse
from django.template import Context, Template

from accounts.models import DriverClaim
from teams.models import TeamClaim
from website.models import Driver, Team


@pytest.fixture(autouse=True)
def _env(db, settings):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    cache.clear()


def render(value):
    return Template('{% load website_tags %}{{ v|safe_html }}').render(Context({'v': value}))


# ---------- XSS в пользовательских описаниях ----------

@pytest.mark.parametrize('payload', [
    '<script>alert(1)</script>', '<img src=x onerror=alert(1)>', '<a href="javascript:alert(1)">x</a>',
    '<svg onload=alert(1)>', '<iframe src="//evil"></iframe>',
])
def test_safe_html_strips_dangerous_markup(payload):
    out = render(payload).lower()
    assert 'script' not in out and 'onerror' not in out and 'javascript:' not in out
    assert 'onload' not in out and 'iframe' not in out


def test_safe_html_keeps_simple_formatting_and_links():
    out = render('<p>Привет, <b>мир</b></p><a href="https://gripline.ru/x">ссылка</a>')
    assert '<b>мир</b>' in out and 'href="https://gripline.ru/x"' in out and 'noopener' in out


def test_safe_html_empty_values_stay_falsy_for_default():
    assert render(None) == '' and render('') == ''
    out = Template('{% load website_tags %}{{ v|safe_html|default:"заглушка" }}').render(Context({'v': None}))
    assert out == 'заглушка'


def test_user_editable_texts_never_use_plain_safe_filter():
    """Страницу целиком не отрендерить без Site Wagtail — проверяем сами шаблоны."""
    import glob
    offenders = []
    for path in glob.glob('website/templates/coderedcms/snippets/*_page.html'):
        for n, line in enumerate(open(path, encoding='utf-8'), 1):
            if re.search(r'\.(description|biography)\|safe(?!_html)', line):
                offenders.append(f'{path}:{n}')
    assert offenders == []


# ---------- rate limit регистраций ----------

PILOT = {'email': 'p{n}@example.ru', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
         'first_name': 'Иван', 'last_name': 'Смирнов', 'city': ''}


def test_pilot_registration_is_rate_limited_per_ip_on_post_only(client):
    for n in range(20):
        r = client.post('/accounts/register/', {**PILOT, 'email': f'p{n}@example.ru'})
        assert r.status_code == 302
    assert client.post('/accounts/register/', {**PILOT, 'email': 'p99@example.ru'}).status_code == 429
    assert not User.objects.filter(email='p99@example.ru').exists()


def test_viewing_register_page_does_not_spend_the_limit(client, monkeypatch):
    monkeypatch.setattr('accounts.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    for _ in range(30):
        assert client.get('/accounts/register/').status_code == 200


# ---------- дубли заявок и валидация выбора ----------

def test_team_verify_link_opened_repeatedly_creates_one_claim(client):
    client.post('/teams/register/', {'email': 'boss@example.ru', 'team_name': 'Kart Lab',
                                     'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123'})
    link = re.search(r'/teams/verify-email/[^\s"<]+', mail.outbox[0].body).group(0)
    for _ in range(4):
        client.get(link)
    assert TeamClaim.objects.count() == 1


def test_team_verify_link_in_fresh_session_does_not_duplicate(client):
    from django.test import Client
    client.post('/teams/register/', {'email': 'boss@example.ru', 'team_name': 'Kart Lab',
                                     'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123'})
    link = re.search(r'/teams/verify-email/[^\s"<]+', mail.outbox[0].body).group(0)
    client.get(link)
    # вторая сессия без team_requested_name — заявки не создаёт
    Client().get(link)
    assert TeamClaim.objects.count() == 1


def test_select_driver_rejects_id_not_in_found_list(client):
    client.post('/accounts/register/', {**PILOT, 'email': 'a@example.ru'})
    stranger = Driver.objects.create(first_name='Чужой', last_name='Пилот', slug='chuzhoy')
    Driver.objects.create(first_name='Иван', last_name='Смирнов', slug='ivan-smirnov')
    # повторная регистрация другого пользователя с совпадением — чтобы был found_drivers в сессии
    client.logout()
    client.post('/accounts/register/', {**PILOT, 'email': 'b@example.ru'})
    r = client.post('/accounts/select-driver/', {'driver_id': stranger.pk})
    assert r.status_code == 302 and DriverClaim.objects.filter(driver=stranger).count() == 0
    assert client.post('/accounts/select-driver/', {'driver_id': '999999'}).status_code == 302


def test_select_team_rejects_id_not_in_found_list(client):
    user = User.objects.create_user('u', 'u@example.ru', 'x')
    mine, stranger = Team.objects.create(name='Mine'), Team.objects.create(name='Stranger')
    s = client.session
    s.update({'found_teams': [{'id': mine.pk, 'name': 'Mine'}], 'user_id': user.pk, 'requested_team_name': 'Mine'})
    s.save()
    r = client.post('/teams/select-team/', {'team_id': stranger.pk})
    assert r.status_code == 302 and TeamClaim.objects.count() == 0


# ---------- 500 и утечки ----------

def test_team_slug_collision_gets_suffix():
    a, b = Team.objects.create(name='Kart Lab'), Team.objects.create(name='Kart Lab')
    assert a.slug == 'kart-lab' and b.slug == 'kart-lab-2'


def test_register_mail_failure_does_not_leak_exception_text(client, monkeypatch):
    def boom(*a, **kw):
        raise OSError('smtp.secret.internal:587 refused')
    monkeypatch.setattr('teams.views.send_team_verification_email', boom)
    captured = {}
    monkeypatch.setattr('teams.views.render', lambda request, template, ctx=None, **kw: HttpResponse(template))
    from django.contrib.messages import get_messages
    r = client.post('/teams/register/', {'email': 'boss@example.ru', 'team_name': 'X',
                                         'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123'})
    texts = [str(m) for m in get_messages(r.wsgi_request)]
    assert texts and all('secret.internal' not in t for t in texts)
    assert not User.objects.filter(email='boss@example.ru').exists()


def test_resend_verification_template_is_valid_utf8():
    raw = open('accounts/templates/accounts/verification_resend.html', 'rb').read()
    assert 'Отправить письмо' in raw.decode('utf-8')
