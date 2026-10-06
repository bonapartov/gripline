"""
Источники обращений для deep links с сайта: этап, пилот, трасса.

Формат start-параметра: <code>_<kind>_<id>, например err_s_142 (код категории,
вид объекта s/p/t, первичный ключ). Реестр расширяемый — новый вид
объекта = одна запись в RESOLVERS.

«Этап» — это EventPage (заезд одного класса на этапе — именно на её
странице таблица результатов), не StagePage (хаб этапа без результатов).
"""
import re
from dataclasses import dataclass
from typing import Callable, Optional

from django.conf import settings

START_PARAM_RE = re.compile(r'^([A-Za-z0-9]+)(?:_([a-z])_(\d+))?$')


@dataclass
class ResolvedSource:
    kind: str       # Feedback.SOURCE_*
    id: int
    title: str
    url: str


def _abs(path):
    return f'{settings.BASE_URL.rstrip("/")}{path}'


def _resolve_stage(pk):
    from website.models import EventPage
    page = EventPage.objects.filter(pk=pk, live=True).first()
    if not page:
        return None
    return ResolvedSource('stage', pk, page.admin_title or page.title, _abs(page.url or '/'))


def _resolve_pilot(pk):
    from website.models import Driver
    obj = Driver.objects.filter(pk=pk).first()
    return ResolvedSource('pilot', pk, obj.full_name, _abs(obj.get_absolute_url())) if obj else None


def _resolve_track(pk):
    from website.models import Track
    obj = Track.objects.filter(pk=pk).first()
    return ResolvedSource('track', pk, str(obj), _abs(obj.get_absolute_url())) if obj else None


# буква в ссылке -> (значение Feedback.source_kind, резолвер)
RESOLVERS: dict[str, tuple[str, Callable[[int], Optional[ResolvedSource]]]] = {
    's': ('stage', _resolve_stage),
    'p': ('pilot', _resolve_pilot),
    't': ('track', _resolve_track),
}
KIND_TO_LETTER = {kind: letter for letter, (kind, _) in RESOLVERS.items()}


def parse_start_param(param):
    """'err_s_142' -> ('err', 'stage', 142); 'err' -> ('err', None, None)
    (страница без объекта, например рейтинг); мусор -> None."""
    m = START_PARAM_RE.match((param or '').strip())
    if not m:
        return None
    code, letter, pk = m.groups()
    if letter is None:
        return code, None, None
    if letter not in RESOLVERS:
        return None
    return code, RESOLVERS[letter][0], int(pk)


def resolve(kind, pk):
    """Название и URL объекта или None, если объекта нет."""
    letter = KIND_TO_LETTER.get(kind)
    if not letter or not pk:
        return None
    return RESOLVERS[letter][1](pk)


def build_deep_link(bot_username, category_code, kind_letter, pk):
    return f'https://t.me/{bot_username}?start={category_code}_{kind_letter}_{pk}'
