"""Кнопка «Сообщить об ошибке» на сайте (шаблонный тег feedback_link)."""
import pytest
from django.core.cache import cache
from django.template import Context, Template

from website.models import FeedbackBotSettings, FeedbackCategory


class Obj:
    pk = 142


def render(src, **ctx):
    return Template('{% load feedback_tags %}' + src).render(Context(ctx)).strip()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.delete('feedback_link_config_v1')
    yield
    cache.delete('feedback_link_config_v1')


@pytest.fixture
def ready(db):
    cfg = FeedbackBotSettings.get()
    cfg.is_enabled, cfg.bot_username = True, 'gripline_support_bot'
    cfg.save()
    FeedbackCategory.objects.create(slug='e', title='Ошибка', deep_link_code='err')


def test_link_for_object(ready):
    out = render("{% feedback_link 'stage' obj %}", obj=Obj())
    assert 'https://t.me/gripline_support_bot?start=err_s_142' in out and 'Сообщить об ошибке' in out


def test_link_without_object(ready):
    assert 'start=err"' in render("{% feedback_link '' %}")


def test_hidden_when_bot_disabled(ready):
    FeedbackBotSettings.objects.update(is_enabled=False)
    assert render("{% feedback_link 'stage' obj %}", obj=Obj()) == ''


def test_hidden_without_username(ready):
    FeedbackBotSettings.objects.update(bot_username='')
    assert render("{% feedback_link 'stage' obj %}", obj=Obj()) == ''


def test_hidden_when_category_missing_or_inactive(ready):
    FeedbackCategory.objects.update(is_active=False)
    assert render("{% feedback_link 'pilot' obj %}", obj=Obj()) == ''
