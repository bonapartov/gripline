"""Публичная точка входа в бота обратной связи: /feedback/.

Статичная ссылка для мест, где нельзя подставить юзернейм из настроек (HTML
футера, лежащий в БД сниппета, письма, соцсети): адрес бота живёт в админке и
при смене не требует правки каждого места. ?c=<код категории> открывает сразу её.
"""
import re

from django.http import HttpResponseRedirect
from django.views.decorators.http import require_GET
from wagtailcache.cache import nocache_page

CODE_RE = re.compile(r'^[A-Za-z0-9]{1,10}$')


@nocache_page  # редирект зависит от настроек бота: не кэшировать
@require_GET
def feedback_redirect(request):
    from website.models import FeedbackBotSettings
    cfg = FeedbackBotSettings.get()
    username = cfg.bot_username.strip().lstrip('@')
    if not cfg.is_enabled or not username:
        return HttpResponseRedirect('/')
    url = f'https://t.me/{username}'
    code = request.GET.get('c', '')
    if CODE_RE.match(code):
        url += f'?start={code}'
    return HttpResponseRedirect(url)
