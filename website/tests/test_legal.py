"""Правовые страницы и форма обращения по ПД (/legal/*)."""
from datetime import date

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.conf import settings
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.models import Locale, Page, Site

from website.models import DataRequest, WebPage, add_working_days

URL = '/legal/data-request/'
VALID = {
    'request_type': 'deletion',
    'page_url': 'https://gripline.ru/drivers/ivan-ivanov/',
    'contact': '@ivan',
    'text': 'Прошу удалить мои фотографии и данные профиля.',
    'confirm': 'on',
    'website': '',
}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


@pytest.fixture
def site(db):
    # --no-migrations → стартового дерева Wagtail нет; страницы сайта (web_page.html)
    # читают LayoutSettings текущего Site, поэтому создаём корень и сайт сами.
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    root = Page.add_root(title='Root', slug='root')
    return Site.objects.create(hostname='testserver', root_page=root, is_default_site=True)


@pytest.mark.django_db
@pytest.mark.usefixtures('site')
class TestDataRequestForm:
    def test_get_renders_form(self, client):
        r = client.get(URL)
        assert r.status_code == 200
        assert 'Обращение по персональным данным' in r.content.decode()
        assert 'name="confirm"' in r.content.decode()

    def test_prefill_from_query(self, client):
        r = client.get(URL + '?url=https://gripline.ru/drivers/x/&type=correction')
        html = r.content.decode()
        assert 'value="https://gripline.ru/drivers/x/"' in html
        assert 'value="correction" selected' in html

    def test_valid_post_saves_and_shows_confirmation_once(self, client):
        r = client.post(URL, VALID)
        assert r.status_code == 302
        obj = DataRequest.objects.get()
        assert obj.request_type == 'deletion' and obj.status == 'new' and obj.is_confirmed
        assert obj.due_date and obj.due_date.weekday() < 5
        page = client.get(URL).content.decode()
        assert 'Обращение принято' in page and f'№{obj.pk}' in page
        # «спасибо» показывается один раз — повторный заход снова отдаёт форму
        assert 'name="confirm"' in client.get(URL).content.decode()

    def test_admin_gets_email(self, client):
        client.post(URL, VALID)
        assert len(mail.outbox) == 1
        assert 'Обращение по персональным данным' in mail.outbox[0].subject

    def test_confirm_required(self, client):
        data = {**VALID}
        data.pop('confirm')
        r = client.post(URL, data)
        assert r.status_code == 200
        assert not DataRequest.objects.exists()
        assert 'Нужно подтвердить' in r.content.decode()

    def test_short_text_and_empty_contact_rejected(self, client):
        r = client.post(URL, {**VALID, 'text': 'мало', 'contact': ' '})
        assert r.status_code == 200
        assert not DataRequest.objects.exists()

    def test_unknown_type_rejected(self, client):
        client.post(URL, {**VALID, 'request_type': 'hack'})
        assert not DataRequest.objects.exists()

    def test_honeypot_silently_dropped(self, client):
        r = client.post(URL, {**VALID, 'website': 'http://spam'})
        assert r.status_code == 302
        assert not DataRequest.objects.exists()
        assert len(mail.outbox) == 0

    def test_rate_limit(self, client):
        for _ in range(5):
            assert client.post(URL, VALID).status_code == 302
        assert client.post(URL, VALID).status_code == 429
        assert DataRequest.objects.count() == 5

    def test_email_failure_does_not_lose_request(self, client, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError('smtp down')
        monkeypatch.setattr('website.legal_views.send_templated_mail', boom)
        assert client.post(URL, VALID).status_code == 302
        assert DataRequest.objects.count() == 1


class TestWorkingDays:
    def test_skips_weekends(self):
        assert add_working_days(date(2026, 10, 2), 1) == date(2026, 10, 5)    # пт → пн
        assert add_working_days(date(2026, 10, 5), 10) == date(2026, 10, 19)  # пн → через 2 недели

    def test_zero_days(self):
        assert add_working_days(date(2026, 10, 3), 0) == date(2026, 10, 3)


@pytest.mark.django_db
@pytest.mark.usefixtures('site')
class TestCreateLegalPages:
    def run(self, **kw):
        call_command('create_legal_pages', operator='Иванов Иван Иванович', tg='@oper', **kw)

    def test_creates_drafts_then_publishes_without_duplicates(self):
        self.run()
        slugs = set(WebPage.objects.filter(slug__in=['legal', 'privacy', 'terms']).values_list('slug', flat=True))
        assert slugs == {'legal', 'privacy', 'terms'}
        assert not WebPage.objects.get(slug='privacy').live
        self.run(publish=True)
        assert WebPage.objects.filter(slug='privacy').count() == 1
        privacy = WebPage.objects.get(slug='privacy')
        assert privacy.live and privacy.url_path.endswith('/legal/privacy/')

    def test_placeholders_replaced(self):
        self.run(publish=True)
        for slug in ('privacy', 'terms'):
            html = str(WebPage.objects.get(slug=slug).body[0].value)
            assert 'Иванов Иван Иванович' in html and '@oper' in html
            assert '{{' not in html


@pytest.mark.django_db
@pytest.mark.usefixtures('site')
class TestPrivacyRedirectAndBalanceSection:
    def test_old_url_redirects_permanently(self, client):
        call_command('create_legal_pages', operator='Иван', tg='@t', publish=True)
        r = client.get('/privacy-policy/')
        assert r.status_code == 301 and r['Location'].endswith('/legal/privacy/')

    def test_rerun_keeps_single_redirect(self):
        from wagtail.contrib.redirects.models import Redirect
        for _ in range(2):
            call_command('create_legal_pages', operator='Иван', tg='@t', publish=True)
        assert Redirect.objects.count() == 1

    def test_policy_contains_balance_section(self):
        call_command('create_legal_pages', operator='Иван', tg='@t', publish=True)
        html = str(WebPage.objects.get(slug='privacy').body[0].value)
        assert '11. Сервис расчёта развесовки карта' in html
        assert 'Дата рождения не запрашивается' in html or 'дата рождения не запрашивается' in html.lower()


@pytest.mark.django_db
@pytest.mark.usefixtures('site')
class TestCookieConsent:
    def test_cookie_policy_page_created_with_settings_button(self):
        call_command('create_legal_pages', operator='Иван', tg='@t', publish=True)
        page = WebPage.objects.get(slug='cookies')
        html = str(page.body[0].value)
        assert page.live and page.url_path.endswith('/legal/cookies/')
        assert 'data-cookie-switch' in html and 'id="settings"' in html and 'Вебвизор' in html and '{{' not in html

    def test_privacy_links_to_cookie_policy(self):
        call_command('create_legal_pages', operator='Иван', tg='@t', publish=True)
        assert 'href="/legal/cookies/"' in str(WebPage.objects.get(slug='privacy').body[0].value)

    def test_site_pages_do_not_load_metrika_unconditionally(self, client):
        html = client.get('/legal/data-request/').content.decode()
        assert 'cookie-consent.js' in html and 'data-ym-counter' in html
        assert 'mc.yandex.ru/metrika' not in html       # сам тег — только из cookie-consent.js
        assert 'mc.yandex.ru/watch' not in html         # noscript-пиксель убран
        assert 'gl_cookies_accepted' not in html        # старая плашка без выбора убрана

    def test_footer_has_cookie_links(self, client):
        html = client.get('/legal/data-request/').content.decode()
        assert 'href="/legal/cookies/#settings"' in html


@pytest.mark.django_db
@pytest.mark.usefixtures('site')
class TestAdminEditableFooter:
    def _footer_html(self, client):
        return client.get('/legal/data-request/').content.decode()

    def test_default_footer_when_no_snippet(self, client):
        html = self._footer_html(client)
        assert '<div class="gl-footer__grid">' in html and 'href="/legal/privacy/"' in html

    def test_seed_makes_footer_editable_and_it_is_rendered_from_snippet(self, client, site):
        from coderedcms.models import Footer
        call_command('seed_footer')
        footer = Footer.objects.get(name='футер')
        assert 'gl-footer__grid' in str(footer.content[0].value)
        # правка в «админке» (в сниппете) сразу меняет футер сайта
        footer.content = [('html', '<div class="gl-footer__main">МОЙ-ФУТЕР-123</div>')]
        footer.save()
        html = self._footer_html(client)
        assert 'МОЙ-ФУТЕР-123' in html
        assert '<div class="gl-footer__grid">' not in html   # встроенный запасной не дублируется

    def test_seed_does_not_overwrite_without_force(self):
        from coderedcms.models import Footer
        call_command('seed_footer')
        footer = Footer.objects.get(name='футер')
        footer.content = [('html', '<p>правка админа</p>')]
        footer.save()
        call_command('seed_footer')
        assert 'правка админа' in str(Footer.objects.get(name='футер').content[0].value)
        call_command('seed_footer', force=True)
        assert 'gl-footer__grid' in str(Footer.objects.get(name='футер').content[0].value)
