"""Виджет «Обратная связь» — плавающая кнопка и окно со ссылками в бота.

{% feedback_widget %} подключён в базовом шаблоне сайта (templates/coderedcms/pages/base.html).
Пункты окна — активные категории из админки («Обратная связь» → «Категории и шаги»)
с кодом deep link; порядок, названия и подсказки правятся там же. Контекст страницы
(этап/пилот/трасса) подставляется только в категории, у которых есть шаг с
«пропускать, если обращение пришло по ссылке с объектом» (по умолчанию — «Ошибка в данных»).

Не выводится, если бот выключен, не задан юзернейм или нет подходящих категорий.
"""
from django import template
from django.core.cache import cache

from website.feedback import sources

register = template.Library()

CACHE_KEY = 'feedback_widget_config_v2'
CACHE_TTL = 60  # сек; страницы дополнительно кэширует wagtailcache — после правок нужен clear_wagtail_cache


def _config():
    """{'username': str, 'items': [...]} или None, если виджет показывать нельзя."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached or None
    from website.models import FeedbackBotSettings, FeedbackCategory, FeedbackStep
    cfg = FeedbackBotSettings.get()
    value = {}
    if cfg.is_enabled and cfg.bot_username.strip():
        with_context = set(
            FeedbackStep.objects.filter(skip_if_source_set=True).values_list('category_id', flat=True)
        )
        items = [
            {
                'code': c.deep_link_code,
                'title': c.title,
                'emoji': c.emoji,
                'hint': c.widget_hint,
                'context': c.pk in with_context,
            }
            for c in FeedbackCategory.objects.filter(is_active=True).exclude(deep_link_code='')
        ]
        if items:
            value = {'username': cfg.bot_username.strip().lstrip('@'), 'items': items}
    cache.set(CACHE_KEY, value, CACHE_TTL)
    return value or None


def _page_object(context):
    """(вид источника, pk объекта) для текущей страницы или (None, None).

    Вьюха без Wagtail-страницы может явно задать источник в контексте:
    feedback_source=('rating', <pk>) — так страница рейтинга передаёт выбранный класс."""
    from website.models import ChampionshipPage, Driver, EventPage, StagePage, Track
    explicit = context.get('feedback_source')
    if explicit and explicit[0] in sources.KIND_TO_LETTER and explicit[1]:
        return explicit
    page = context.get('page') or context.get('self')
    for model, kind in ((EventPage, 'stage'), (StagePage, 'hub'), (ChampionshipPage, 'champ')):
        if isinstance(page, model):
            return kind, page.pk
    for key, kind, model in (('driver', 'pilot', Driver), ('track', 'track', Track)):
        obj = context.get(key)
        if isinstance(obj, model):
            return kind, obj.pk
    return None, None


@register.inclusion_tag('includes/feedback_widget.html', takes_context=True)
def feedback_widget(context):
    cfg = _config()
    if not cfg:
        return {'items': []}
    kind, pk = _page_object(context)
    letter = sources.KIND_TO_LETTER.get(kind) if kind else None
    items = []
    for it in cfg['items']:
        template = ''
        if letter and it['context']:
            url = sources.build_deep_link(cfg['username'], it['code'], letter, pk)
            if kind == 'rating':
                # класс переключается на странице без перезагрузки — JS виджета подставит актуальный
                template = sources.build_deep_link(cfg['username'], it['code'], letter, '{id}')
        else:
            url = f'https://t.me/{cfg["username"]}?start={it["code"]}'
        items.append({**it, 'url': url, 'template': template})
    return {'items': items}
