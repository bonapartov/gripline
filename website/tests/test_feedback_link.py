"""Виджет «Обратная связь» на сайте и редирект /feedback/."""
import pytest
from django.conf import settings
from django.core.cache import cache
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.models import Locale, Page, Site
from django.template import Context, Template

from website.models import (
    Driver, FeedbackBotSettings, FeedbackCategory, FeedbackStep, Track,
)


@pytest.fixture
def site(db):
    # --no-migrations → стартового дерева Wagtail нет; страницы сайта читают LayoutSettings Site
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    root = Page.add_root(title='Root', slug='root')
    return Site.objects.create(hostname='testserver', root_page=root, is_default_site=True)


def render(**ctx):
    return Template('{% load feedback_tags %}{% feedback_widget %}').render(Context(ctx))


@pytest.fixture(autouse=True)
def clear_cache():
    cache.delete('feedback_widget_config_v2')
    yield
    cache.delete('feedback_widget_config_v2')


@pytest.fixture
def ready(db):
    cfg = FeedbackBotSettings.get()
    cfg.is_enabled, cfg.bot_username = True, 'gripline_support_bot'
    cfg.save()
    err = FeedbackCategory.objects.create(slug='e', title='Ошибка в данных', emoji='🐞', deep_link_code='err',
                                          sort_order=1, widget_hint='Неточность на странице')
    FeedbackStep.objects.create(category=err, key='where', prompt_text='Где?', skip_if_source_set=True)
    idea = FeedbackCategory.objects.create(slug='i', title='Предложение', deep_link_code='idea', sort_order=2)
    FeedbackStep.objects.create(category=idea, key='text', prompt_text='Что?')
    return err, idea


def test_items_come_from_admin_categories_in_order(ready):
    html = render()
    assert html.index('Ошибка в данных') < html.index('Предложение')
    assert 'Неточность на странице' in html
    assert 'start=err"' in html and 'start=idea"' in html


def test_context_only_for_categories_with_source_step(ready):
    d = Driver.objects.create(first_name='Иван', last_name='Иванов')
    html = render(driver=d)
    assert f'start=err_p_{d.pk}' in html          # у категории есть шаг skip_if_source_set
    assert 'start=idea"' in html                    # у «Предложения» контекст не нужен


def test_track_context(ready):
    t = Track.objects.create(name='Пластунка')
    assert f'start=err_t_{t.pk}' in render(track=t)


def test_inactive_category_and_missing_code_hidden(ready):
    FeedbackCategory.objects.filter(slug='i').update(is_active=False)
    FeedbackCategory.objects.create(slug='n', title='Без кода', deep_link_code='')
    html = render()
    assert 'Предложение' not in html and 'Без кода' not in html


def test_hidden_when_bot_disabled_or_no_username_or_no_items(ready):
    FeedbackBotSettings.objects.update(is_enabled=False)
    assert 'glFeedback' not in render()
    cache.delete('feedback_widget_config_v2')
    FeedbackBotSettings.objects.update(is_enabled=True, bot_username='')
    assert 'glFeedback' not in render()
    cache.delete('feedback_widget_config_v2')
    FeedbackBotSettings.objects.update(bot_username='gripline_support_bot')
    FeedbackCategory.objects.update(is_active=False)
    assert 'glFeedback' not in render()


def test_widget_on_site_pages_but_not_in_balance_app(client, ready, site):
    assert 'id="glFeedback"' in client.get('/legal/data-request/').content.decode()
    assert 'glFeedback' not in client.get('/balance/').content.decode()


def test_redirect_to_bot(client, ready):
    r = client.get('/feedback/')
    assert r.status_code == 302 and r.url == 'https://t.me/gripline_support_bot'
    assert client.get('/feedback/?c=idea').url == 'https://t.me/gripline_support_bot?start=idea'


def test_redirect_ignores_bad_code(client, ready):
    assert client.get('/feedback/?c=bad code&x=1').url == 'https://t.me/gripline_support_bot'
    assert client.get('/feedback/?c=' + 'a' * 40).url == 'https://t.me/gripline_support_bot'


def test_redirect_home_when_disabled(client, ready):
    FeedbackBotSettings.objects.update(is_enabled=False)
    assert client.get('/feedback/').url == '/'


def test_driver_page_has_widget_with_pilot_context_and_cookie_banner(client, ready, site):
    """Страница пилота переопределяет custom_scripts — без {{ block.super }} терялись
    и виджет, и плашка cookie (а с ней Метрика после согласия)."""
    d = Driver.objects.create(first_name='Иван', last_name='Иванов')
    html = client.get(d.get_absolute_url()).content.decode()
    assert 'id="glFeedback"' in html and f'start=err_p_{d.pk}' in html
    assert 'cookie-consent.js' in html
