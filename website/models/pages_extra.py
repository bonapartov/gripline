"""Страницы двигателей, обновлений, рейтинга, календаря и главная."""

from django.contrib.auth.models import User
from coderedcms.forms import CoderedFormField
from coderedcms.models import (
    CoderedArticleIndexPage, CoderedArticlePage, CoderedEmail,
    CoderedEventIndexPage, CoderedEventOccurrence, CoderedEventPage,
    CoderedFormPage, CoderedLocationIndexPage, CoderedLocationPage,
    CoderedWebPage)
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from modelcluster.models import ClusterableModel
from wagtail.api import APIField
from wagtail.snippets.models import register_snippet
from wagtail.admin.panels import FieldPanel, FieldRowPanel, HelpPanel, InlinePanel, MultiFieldPanel, ObjectList, Panel, TabbedInterface
from wagtail.admin.forms.pages import WagtailAdminPageForm
from wagtail.models import DraftStateMixin, RevisionMixin, PreviewableMixin, Orderable
from django.urls import reverse
from django.utils.text import slugify
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned, ValidationError
from unidecode import unidecode
import datetime
from wagtail.models import Page
from django.db.models import Count, Q
from django import forms
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.http import HttpResponse
from wagtail.fields import StreamField
from coderedcms.blocks import CONTENT_STREAMBLOCKS
from coderedcms.blocks.html_blocks import RichTextBlock as CrxRichTextBlock
from wagtailmarkdown.blocks import MarkdownBlock
from django.utils.html import format_html, format_html_join
from wagtailseo.models import SeoType

from .equipment import Engine
from .pages import (
    ArticlePage, ChampionshipPage, ColorSwatchWidget, EventPage,
    TechArticleIndexPage, TransliteratedSlugMixin,
)
from .pages_content import AnalyticsMetadata, AnalyticsSettings
from .people import Driver
from .racing import CompetitionType, RaceClass, RaceResult


class EngineIndexPage(TransliteratedSlugMixin, CoderedWebPage):
    """
    Страница со списком всех двигателей
    """
    class Meta:
        verbose_name = "Список двигателей"
        verbose_name_plural = "Списки двигателей"

    parent_page_types = ["website.WebPage", "website.SeasonArchivePage"]
    subpage_types = []  # Нельзя создавать дочерние страницы
    template = "coderedcms/pages/engine_index_page.html"

    def get_context(self, request):
        context = super().get_context(request)
        # Получаем все двигатели из сниппета Engine
        engines = Engine.objects.all().order_by('name')
        context['engines'] = engines
        return context


# ---------- ЛОГ ОБНОВЛЕНИЙ ----------

class UpdateLog(models.Model):
    """Лог обновлений рейтингов"""
    updated_at = models.DateTimeField("Дата обновления", auto_now_add=True)
    status = models.CharField("Статус", max_length=50, default="success")
    message = models.TextField("Сообщение", blank=True, null=True)
    # Сколько результатов было на момент пересчёта — дашборд админки считает по нему,
    # сколько добавлено с тех пор («пора пересчитать»). Заполняется в save(), поэтому
    # работает для любого места, создающего лог. У старых записей — NULL.
    race_results_count = models.PositiveIntegerField("Результатов на момент обновления", null=True, blank=True, editable=False)

    def save(self, *args, **kwargs):
        if self.race_results_count is None:
            self.race_results_count = RaceResult.objects.count()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Лог обновления"
        verbose_name_plural = "Логи обновлений"
        ordering = ['-updated_at']

    def __str__(self):
        return f"Обновление от {self.updated_at.strftime('%d.%m.%Y %H:%M')}"

class WeightsTablePage(TransliteratedSlugMixin, CoderedWebPage):
    """
    Страница для отображения таблицы весов контекстной модели
    """
    class Meta:
        verbose_name = "Таблица весов (динамическая)"

    parent_page_types = ["website.WebPage", "website.SeasonArchivePage"]
    subpage_types = []
    template = "coderedcms/snippets/weights_table.html"

class PulseIndexPage(TransliteratedSlugMixin, CoderedWebPage):
    """
    Главная страница Пульс - агрегатор чемпионатов с визуализацией по годам
    """
    class Meta:
        verbose_name = "Пульс картинга"
        verbose_name_plural = "Пульс картинга"

    parent_page_types = ["website.WebPage", "wagtailcore.Page"]
    subpage_types = []
    template = "coderedcms/pages/pulse_index_page.html"

    # Кастомные поля для настройки внешнего вида
    hero_title = models.CharField(
        "Заголовок шапки",
        max_length=255,
        default="Пульс картинга",
        blank=True,
    )

    hero_subtitle = models.TextField(
        "Подзаголовок",
        max_length=500,
        default="Итоги сезонов, чемпионы и трассы",
        blank=True,
    )

    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('hero_title'),
        FieldPanel('hero_subtitle'),
        # FieldPanel('competition_type'),  ← УДАЛИ ЭТУ СТРОКУ
    ]

    def get_context(self, request):
        context = super().get_context(request)
        from django.utils import timezone
        from .pages import ChampionshipPage, EventPage
        from .racing import CompetitionType, RaceClass, RaceResult

        # Получаем все чемпионаты
        championships = ChampionshipPage.objects.live().public().specific()

        # Получаем все доступные типы соревнований
        types = CompetitionType.objects.values_list('name', flat=True).distinct()

        # Получаем все доступные классы
        race_classes = RaceClass.objects.filter(
            raceclassresultgroup__isnull=False
        ).distinct().order_by('sort_order', 'name')

        # Получаем все доступные годы из этапов (через новую структуру)
        all_years = set()
        for champ in championships:
            all_years.update(champ.get_years())

        # Текущий год
        current_year = timezone.now().year

        # Этапы, у которых есть опубликованное событие с результатами — одним
        # запросом (путь родителя события = путь этапа), без обхода дерева.
        stage_paths_with_results = {
            path[:-Page.steplen] for path in
            RaceResult.objects.filter(group__page__live=True)
            .values_list('group__page__path', flat=True).distinct()
        }

        # Фильтруем годы: только текущий и прошедшие
        filtered_years = []
        for year in all_years:
            if year <= current_year:
                if year == current_year:
                    filtered_years.append(year)
                elif StagePage.objects.filter(
                    start_date__year=year, live=True, path__in=stage_paths_with_results,
                ).exists():
                    filtered_years.append(year)

        # Сортируем от большего к меньшему
        filtered_years = sorted(filtered_years, reverse=True)

        context['championships'] = championships
        context['available_types'] = list(types)

        context['available_classes'] = list(race_classes)
        context['available_years'] = filtered_years
        context['current_year'] = filtered_years[0] if filtered_years else current_year

        return context

class RatingInfoPage(TransliteratedSlugMixin, CoderedWebPage):
    """
    Страница с информацией о расчёте рейтингов
    """
    class Meta:
        verbose_name = "Как считается рейтинг"
        verbose_name_plural = "Как считается рейтинг"

    parent_page_types = ["website.WebPage"]
    subpage_types = []
    template = "coderedcms/pages/rating_info_page.html"

    def get_context(self, request):
        context = super().get_context(request)

        from .pages_content import AnalyticsMetadata
        from .people import Driver
        from .racing import RaceClass, RaceResult
        from django.db.models import Count
        import zoneinfo
        from datetime import datetime

        # Дата последнего обновления
        try:
            last_update_utc = AnalyticsMetadata.objects.get(key='last_updated').value
            moscow_tz = zoneinfo.ZoneInfo('Europe/Moscow')
            context['last_update'] = last_update_utc.astimezone(moscow_tz)
        except AnalyticsMetadata.DoesNotExist:
            last_race = RaceResult.objects.order_by('-group__page__occurrences__start').first()
            if last_race and last_race.group and last_race.group.page:
                occurrence = last_race.group.page.occurrences.first()
                context['last_update'] = occurrence.start if occurrence else datetime.now()
            else:
                context['last_update'] = None

        # Веса контекстной модели
        driver_with_weights = Driver.objects.exclude(context_weights={}).first()
        context['weights'] = driver_with_weights.context_weights if driver_with_weights else None

        # Статистика для страницы
        drivers = Driver.objects.exclude(rating_score__isnull=True)
        drivers_with_count = drivers.annotate(race_count=Count('raceresult'))

        context['total_drivers'] = drivers.count()
        context['total_races'] = RaceResult.objects.values('group__page').distinct().count()
        context['low_starts_count'] = drivers_with_count.filter(race_count__lt=3).count()
        context['reliable_count'] = drivers_with_count.filter(race_count__gte=10).count()
        context['active_classes_count'] = RaceClass.objects.filter(raceclassresultgroup__isnull=False).distinct().count()
        context['top_drivers'] = drivers.order_by('-rating_score')[:5]

        return context

class EventCalendarPage(TransliteratedSlugMixin, CoderedWebPage):
    """
    Страница календаря мероприятий с двумя режимами: сетка и календарь
    """
    class Meta:
        verbose_name = "Календарь мероприятий"
        verbose_name_plural = "Календари мероприятий"

    parent_page_types = ["website.WebPage"]  # Можно создать как дочернюю страницу
    subpage_types = []  # Нельзя создавать дочерние страницы
    template = "coderedcms/pages/event_calendar_page.html"

    # Поля для настройки внешнего вида
    hero_title = models.CharField(
        "Заголовок",
        max_length=255,
        default="Календарь мероприятий",
        blank=True,
    )

    hero_subtitle = models.TextField(
        "Подзаголовок",
        max_length=500,
        default="Все предстоящие этапы и соревнования",
        blank=True,
    )

    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('hero_title'),
        FieldPanel('hero_subtitle'),
    ]
    def get_context(self, request):
        context = super().get_context(request)
        from .pages import ChampionshipPage, EventPage
        from .racing import CompetitionType
        from django.utils import timezone
        from django.db.models import Q
        from datetime import timedelta

        # Получаем все типы соревнований для фильтров
        context['competition_types'] = CompetitionType.objects.all()

        # Получаем выбранный тип из GET-параметров
        selected_type = request.GET.get('type', '')
        context['selected_type'] = selected_type

        # Получаем режим отображения (grid/calendar)
        view_mode = request.GET.get('view', 'grid')
        context['view_mode'] = view_mode


        # Получаем ТЕКУЩУЮ дату по московскому времени
        today = timezone.localtime().date()

        # Получаем ВСЕ БУДУЩИЕ события (start > сегодня по Москве)
        # Уже закончившиеся и идущие сейчас не показываем
        all_events = EventPage.objects.live().filter(
            occurrences__start__date__gt=today
        ).distinct().select_related('track')

        # Фильтр по типу соревнований
        if selected_type:
            filtered_events = []
            for event in all_events:
                parent = event.get_parent().specific
                if hasattr(parent, 'championship_competition_types'):
                    if parent.championship_competition_types.filter(competition_type__code=selected_type).exists():
                        filtered_events.append(event)
            all_events = filtered_events
        else:
            all_events = list(all_events)

        # СОЗДАЕМ СПИСОК УНИКАЛЬНЫХ ЭТАПОВ
        unique_events = {}
        for event in all_events:
            # Получаем StagePage (родитель event)
            stage = event.get_parent().specific
            # Получаем ChampionshipPage (родитель StagePage)
            championship = stage.get_parent().specific if stage else None

            occurrence = event.occurrences.first()

            track_id = event.track.id if event.track else 'none'
            start_date_str = str(occurrence.start.date()) if occurrence and occurrence.start else 'no-date'

            stage_key = f"{event.title}_{start_date_str}_{track_id}"

            if stage_key not in unique_events:
                unique_events[stage_key] = {
                    'event': event,
                    'stage': stage,
                    'championship': championship,
                    'start_date': occurrence.start if occurrence else None,
                    'end_date': occurrence.end if occurrence else None,
                    'track': event.track,
                    'event_url': event.url,
                    'championship_url': championship.url if championship else None,
                    'track_url': event.track.get_absolute_url() if event.track else None,
                    'classes': []
                }

            for group in event.race_class_groups.all():
                class_name = group.race_class.name
                if class_name not in unique_events[stage_key]['classes']:
                    unique_events[stage_key]['classes'].append(class_name)

        # Бейджи классов на карточке события — в едином порядке классов
        # сайта, а не в порядке появления групп результатов.
        class_sort = RaceClass.sort_key_map()
        enriched_events = list(unique_events.values())
        for ed in enriched_events:
            ed['classes'].sort(key=lambda name: class_sort.get(name, 9999))
        enriched_events.sort(key=lambda x: x['start_date'] or x['event'].first_published_at)

        # Добавляем org_stage, фильтруем неопубликованные, добавляем цвет
        try:
            from organizers.models import Stage as OrgStage
            org_stages = {
                s.wagtail_page_id: s
                for s in OrgStage.objects.filter(wagtail_page__isnull=False)
                    .select_related('championship')
            }
            filtered = []
            filtered_event_ids = set()
            for ed in enriched_events:
                stage_page = ed.get('stage')
                org_s = org_stages.get(stage_page.pk) if stage_page else None
                # фильтр: скрываем если чемпионат или этап не опубликованы
                if org_s is not None:
                    if not org_s.is_published or not org_s.championship.is_published:
                        continue
                ed['org_stage'] = org_s if (org_s and org_s.registration_closed_reason() is None) else None
                if org_s:
                    ed['color'] = org_s.championship.color or '#ffc107'
                else:
                    stage_color = getattr(stage_page, 'calendar_color', '')
                    champ_color = getattr(ed.get('championship'), 'calendar_color', '')
                    ed['color'] = stage_color or champ_color or '#ffc107'
                filtered.append(ed)
                filtered_event_ids.add(ed['event'].id)
            enriched_events = filtered
            # Фильтруем unique_events для календарной сетки
            unique_events = {k: v for k, v in unique_events.items() if v['event'].id in filtered_event_ids}
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning('Calendar publish filter error: %s', e)

        context['enriched_events'] = enriched_events

        # ИНИЦИАЛИЗИРУЕМ months ПУСТЫМ СЛОВАРЕМ ПО УМОЛЧАНИЮ
        months = {}

        # Для календаря: группируем события по месяцам
        if view_mode == 'calendar':
            # Используем ТОТ ЖЕ unique_events, что и для карточек!
            for event_id, event_data in unique_events.items():
                event = event_data['event']

                for occ in event.occurrences.all():
                    if occ.end and occ.end.date() >= today:
                        current_date = occ.start.date()
                        end_date = occ.end.date()

                        while current_date <= end_date:
                            if current_date >= today:
                                month_key = current_date.strftime('%Y-%m')

                                if month_key not in months:
                                    first_day = current_date.replace(day=1)
                                    first_weekday = first_day.weekday()

                                    if current_date.month == 12:
                                        next_month = current_date.replace(year=current_date.year + 1, month=1, day=1)
                                    else:
                                        next_month = current_date.replace(month=current_date.month + 1, day=1)
                                    last_day = (next_month - timedelta(days=1)).day

                                    months[month_key] = {
                                        'year': current_date.year,
                                        'month': current_date.month,
                                        'month_name': current_date,  # передаем всю дату, а не строку
                                        'first_weekday': first_weekday,
                                        'days': range(1, last_day + 1),
                                        'events': [],
                                        'events_by_day': {}
                                    }

                                day = current_date.day

                                # Добавляем событие в список событий месяца
                                event_already_added = False
                                for e in months[month_key]['events']:
                                    if e['event'].id == event.id:
                                        event_already_added = True
                                        break

                                if not event_already_added:
                                    months[month_key]['events'].append({
                                        'event': event,
                                        'start': occ.start,
                                        'end': occ.end,
                                        'classes': event_data.get('classes', []),
                                    })

                                # Добавляем событие в конкретный день
                                if day not in months[month_key]['events_by_day']:
                                    months[month_key]['events_by_day'][day] = []

                                day_event_already_added = False
                                for e in months[month_key]['events_by_day'][day]:
                                    if e['event'].id == event.id:
                                        day_event_already_added = True
                                        break

                                if not day_event_already_added:
                                    org_s = event_data.get('org_stage')
                                    stage_page = event_data.get('stage')
                                    champ_page = event_data.get('championship')
                                    months[month_key]['events_by_day'][day].append({
                                        'event': event,
                                        'start': occ.start,
                                        'end': occ.end,
                                        'color': event_data.get('color', '#ffc107'),
                                        'stage_url': stage_page.url if stage_page else '',
                                        'champ_title': champ_page.title if champ_page else '',
                                        'reg_pk': org_s.pk if org_s else None,
                                        'start_str': occ.start.strftime('%d.%m %H:%M') if occ.start else '',
                                        'end_str': occ.end.strftime('%d.%m %H:%M') if occ.end else '',
                                        'classes': event_data.get('classes', []),
                                    })

                            current_date += timedelta(days=1)

            # Сортируем месяцы по дате
            import operator
            months = dict(sorted(months.items(), key=operator.itemgetter(0)))

            # Вычисляем CSS стиль для каждого дня с событиями
            import json as _json

            def _day_style(day_events):
                colors = [e['color'] for e in day_events]
                n = len(colors)
                txt = "color: #fff; text-shadow: 1px 1px 3px rgba(0,0,0,0.85); font-weight: bold;"
                if n == 1:
                    return f"background-color: {colors[0]}; {txt}"
                if n == 2:
                    return f"background: linear-gradient(45deg, {colors[0]} 50%, {colors[1]} 50%); {txt}"
                step = 360.0 / n
                stops = []
                sep = "rgba(15,15,15,0.55)"
                for i, c in enumerate(colors):
                    s = i * step
                    e = (i + 1) * step
                    stops.append(f"{c} {s:.2f}deg {e - 0.8:.2f}deg")
                    stops.append(f"{sep} {e - 0.8:.2f}deg {e:.2f}deg")
                conic = f"conic-gradient(from -90deg, {', '.join(stops)})"
                return f"background: {conic}; {txt}"

            for month_data in months.values():
                for day, day_events in month_data['events_by_day'].items():
                    meta = [
                        {
                            'title': e['event'].title,
                            'champ': e.get('champ_title', ''),
                            'stage_url': e.get('stage_url', ''),
                            'reg_pk': e.get('reg_pk'),
                            'dates': f"{e.get('start_str','')} — {e.get('end_str','')}",
                            'classes': e.get('classes', []),
                        }
                        for e in day_events
                    ]
                    month_data['events_by_day'][day] = {
                        'events': day_events,
                        'style': _day_style(day_events),
                        'count': len(day_events),
                        'meta_json': _json.dumps(meta, ensure_ascii=False),
                    }

        # ВАЖНО: ВСЕГДА передаем months в контекст, даже если это пустой словарь
        context['months'] = months

        return context


class HomePage(TransliteratedSlugMixin, CoderedWebPage):
    """
    Главная страница Gripline с 4 блоками:
    - Hero: ближайшее событие + счётчик
    - Новости: 4 последние статьи
    - Топ пилотов: 5 строк рейтинга
    - Календарь: ближайшие 5 событий
    """
    class Meta:
        verbose_name = "Главная страница"

    parent_page_types = ["wagtailcore.Page"]
    subpage_types = [
        'website.SeasonArchivePage',
        'website.ChampionshipPage',
        'website.WebPage',
        'website.ArticleIndexPage',
        'website.EventIndexPage',
        'website.LocationIndexPage',
        'website.TrackIndexPage',
        'website.EngineIndexPage',
        'website.PulseIndexPage',
        'website.RatingInfoPage',
        'website.EventCalendarPage',
    ]
    template = "coderedcms/pages/home_page.html"

    def get_context(self, request):
        context = super().get_context(request)
        from django.utils import timezone
        from datetime import timedelta

        # Используем московское время для всех сравнений
        now = timezone.localtime()
        context['now'] = now
        next_event = None  # <--- ВАЖНО: инициализируем переменную

        # ID страниц этапов, скрытых организатором (is_published=False)
        from organizers.models import Stage as OrgStage
        _draft_stage_page_ids = OrgStage.objects.filter(
            is_published=False, wagtail_page__isnull=False
        ).values_list('wagtail_page_id', flat=True)

        # 1. Сначала ищем StagePage, который идёт ПРЯМО СЕЙЧАС (start <= now <= end)
        current_stages = StagePage.objects.live().exclude(
            id__in=_draft_stage_page_ids
        ).filter(
            start_date__lte=now,
            end_date__gte=now
        ).distinct().select_related('track')

        if current_stages:
            current_stage = current_stages.first()
            next_event = {
                'event': current_stage,
                'title': current_stage.title,
                'start': current_stage.start_date,
                'end': current_stage.end_date,
                'track': current_stage.track,
                'championship': current_stage.get_parent().specific,
                'classes': current_stage.get_classes_with_results(),
                'url': current_stage.url,
                'is_current': True,
            }

        # 2. Если текущего нет — ищем ближайший БУДУЩИЙ StagePage
        if not next_event:
            upcoming_stages = StagePage.objects.live().exclude(
                id__in=_draft_stage_page_ids
            ).filter(
                start_date__gt=now
            ).order_by('start_date').distinct().select_related('track')

            upcoming_stage = upcoming_stages.first()
            if upcoming_stage:
                next_event = {
                    'event': upcoming_stage,
                    'title': upcoming_stage.title,
                    'start': upcoming_stage.start_date,
                    'end': upcoming_stage.end_date,
                    'track': upcoming_stage.track,
                    'championship': upcoming_stage.get_parent().specific,
                    'classes': upcoming_stage.get_classes_with_results(),
                    'url': upcoming_stage.url,
                    'is_current': False,
                }

        if next_event:
            from website.weather_utils import get_stage_weather
            next_event['weather'] = get_stage_weather(next_event['event'])

        context['next_event'] = next_event

        # --- БЛОК 2: Последние новости (без статей матчасти) ---
        tech_index = TechArticleIndexPage.objects.live().first()
        if tech_index:
            context['latest_articles'] = ArticlePage.objects.live().not_child_of(tech_index).filter(
                date_display__isnull=False
            ).order_by('-date_display')[:12]
            context['latest_tech_articles'] = ArticlePage.objects.child_of(tech_index).live().order_by('-first_published_at')[:8]
        else:
            context['latest_articles'] = ArticlePage.objects.live().filter(
                date_display__isnull=False
            ).order_by('-date_display')[:12]
            context['latest_tech_articles'] = []

        # --- БЛОК 3: Топ пилотов ---
        classes = list(RaceClass.objects.for_site())

        selected_class_id = request.GET.get('class')
        if selected_class_id and selected_class_id.isdigit():
            selected_class_id = int(selected_class_id)
        else:
            selected_class_id = classes[0].id if classes else None

        top_drivers = []
        if selected_class_id:
            import json, statistics as _stats
            from datetime import date as _date
            from django.db.models import Count, Q
            class_key = str(selected_class_id)
            _as = AnalyticsSettings.get()
            all_drivers = list(Driver.objects.exclude(rating_by_class={}).exclude(rating_by_class__isnull=True))
            from website.views import ClassSmoother, class_min_starts, rating_out_reason
            min_starts = class_min_starts(selected_class_id, all_drivers, _as)

            # Один запрос для всех статистик по классу
            race_stats = {
                s['driver_id']: s
                for s in RaceResult.objects.filter(
                    group__race_class_id=selected_class_id
                ).values('driver_id').annotate(
                    race_count=Count('id'),
                    win_count=Count('id', filter=Q(position=1)),
                )
            }

            candidates = []
            for driver in all_drivers:
                rbc = driver.rating_by_class
                if isinstance(rbc, str):
                    try:
                        rbc = json.loads(rbc)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        rbc = {}
                bt_data = rbc.get(class_key, {})
                if not bt_data:
                    continue

                # Давно не выступал или мало стартов — не в таблице
                if rating_out_reason(bt_data, _as, min_starts):
                    continue

                s = race_stats.get(driver.id, {})
                driver.race_count = s.get('race_count', 0)
                driver.win_count = s.get('win_count', 0)
                driver._bt_score = bt_data.get('score', 0)
                driver._starts = bt_data.get('starts', 0)
                driver._rating_entry = bt_data
                candidates.append(driver)

            if candidates:
                smoother = ClassSmoother([d._bt_score for d in candidates], _as)
                for d in candidates:
                    d._smoothed = smoother.smooth(d._bt_score, d._starts, d._rating_entry)
                candidates.sort(key=lambda x: x._smoothed, reverse=True)
                min_s = candidates[-1]._smoothed
                max_s = candidates[0]._smoothed
                rng = max_s - min_s if max_s > min_s else 1
                for i, d in enumerate(candidates, 1):
                    d.rank = i
                    d.normalized_rating = round((d._smoothed - min_s) / rng * 100, 1)
                top_drivers = candidates[:5]

        context['top_drivers'] = top_drivers
        context['classes'] = classes
        context['selected_class_id'] = selected_class_id

        # --- БЛОК 4: Ближайшие события (календарь) ---
        upcoming_stages_raw = StagePage.objects.live().exclude(
            id__in=_draft_stage_page_ids
        ).filter(
            start_date__gt=now
        ).order_by('start_date').distinct().select_related('track')

        grouped = {}
        for stage in upcoming_stages_raw:
            key = f"{stage.title}_{stage.start_date.date()}"
            if key not in grouped:
                grouped[key] = {
                    'title': stage.title,
                    'url': stage.url,  # ← URL StagePage, а не чемпионата
                    'start': stage.start_date,
                    'end': stage.end_date,
                    'track': stage.track,
                    'championship': stage.get_parent().specific,
                    'classes': stage.get_classes_with_results(),
                }

        calendar_events = sorted(grouped.values(), key=lambda x: x['start'])[:5]
        context['calendar_events'] = calendar_events

        return context

class StagePage(TransliteratedSlugMixin, CoderedWebPage):
    """
    Страница-хаб для этапа чемпионата.
    Объединяет все классовые страницы (EventPage) одного этапа.
    """
    class Meta:
        verbose_name = "Этап чемпионата"
        verbose_name_plural = "Этапы чемпионатов"

    parent_page_types = ["website.ChampionshipPage"]
    subpage_types = ["website.EventPage"]
    template = "coderedcms/pages/stage_page.html"

    # Общая информация об этапе
    start_date = models.DateTimeField(
        "Дата начала этапа",
        help_text="Дата и время начала этапа (используется для статуса и счётчика)"
    )
    end_date = models.DateTimeField(
        "Дата окончания этапа",
        help_text="Дата и время окончания этапа"
    )
    track = models.ForeignKey(
        'website.Track',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stages',
        verbose_name="Трасса"
    )
    # cover_image НЕ добавляем — оно уже есть в CoderedWebPage

    # Цвет этапа в общем календаре (используется для раскраски ячеек и разделения дня на секторы,
    # когда на одну дату приходится несколько разных этапов). Если не задан — наследуется цвет
    # родительского чемпионата (ChampionshipPage.calendar_color).
    calendar_color = models.CharField(
        "Цвет в календаре",
        max_length=7,
        blank=True,
        default="",
        help_text="Если не задан — используется цвет чемпионата"
    )

    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('start_date'),
        FieldPanel('end_date'),
        FieldPanel('track'),
        FieldPanel('calendar_color', widget=ColorSwatchWidget),
        # cover_image уже есть в родительских панелях
    ]

    def get_status(self):
        """
        Возвращает статус этапа:
        - 'future' — ещё не начался
        - 'current' — идёт сейчас
        - 'past' — завершён
        """
        from django.utils import timezone
        now = timezone.localtime()

        if self.start_date > now:
            status = 'future'
        elif self.start_date <= now <= self.end_date:
            status = 'current'
        else:
            status = 'past'

        return {
            'status': status,
            'start': self.start_date,
            'end': self.end_date,
        }

    def get_stage_weather(self):
        """Погода для этапа (прогноз/оценка/архив) — вызывается из шаблона как page.get_stage_weather."""
        from website.weather_utils import get_stage_weather
        return get_stage_weather(self)

    @property
    def seo_struct_event_dict(self) -> dict:
        """SportsEvent structured data. eventStatus считается из get_status(),
        не хранится отдельно — обновляется автоматически по датам этапа."""
        status_map = {
            'future': 'https://schema.org/EventScheduled',
            'current': 'https://schema.org/EventScheduled',
            'past': 'https://schema.org/EventCompleted',
        }
        data = {
            "@context": "https://schema.org",
            "@type": "SportsEvent",
            "name": self.title,
            "url": self.full_url,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "eventStatus": status_map[self.get_status()['status']],
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        }
        if self.track:
            site = self.get_site()
            track_url = (
                site.root_url.rstrip('/') + self.track.get_absolute_url()
                if site else self.track.get_absolute_url()
            )
            data["location"] = {
                "@type": "SportsActivityLocation",
                "name": self.track.name,
                "url": track_url,
            }
        return data

    @property
    def seo_struct_event_json(self):
        from website.schema import render_json_ld
        return render_json_ld(self.seo_struct_event_dict)

    @property
    def seo_description(self) -> str:
        from website.seo_meta import stage_page_description
        return super().seo_description or stage_page_description(self)

    def get_child_classes(self):
        """
        Возвращает все дочерние EventPage (классовые страницы) этого этапа.
        """
        return self.get_children().live().specific()

    def get_classes_with_results(self):
        """
        Возвращает список названий классов, у которых есть результаты — в
        едином порядке классов сайта (RaceClass.sort_order), а не в порядке
        появления событий/групп.
        """
        class_ids = set()
        for event in self.get_child_classes():
            for group in event.race_class_groups.all():
                if group.race_class_id:
                    class_ids.add(group.race_class_id)
        return list(RaceClass.objects.filter(id__in=class_ids).values_list('name', flat=True))

    def has_results(self):
        """
        Проверяет, есть ли результаты хотя бы в одном классе этапа.
        """
        for event in self.get_child_classes():
            if event.race_class_groups.exists():
                return True
        return False

    @property
    def race_results(self):
        """Все RaceResult across все дочерние EventPage (классы) этого этапа —
        используется в мини-таблице протокола (website/includes/event_results_mini_table.html)."""
        return RaceResult.objects.filter(group__page__in=self.get_child_classes()).select_related(
            'driver', 'team', 'group__race_class'
        ).order_by('group__race_class__sort_order', 'group__race_class__name', 'position')

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        try:
            from organizers.models import Stage
            from applications.models import Application
            org_stage = Stage.objects.filter(wagtail_page=self).first()
            if org_stage:
                context['org_stage'] = org_stage
                context['registration_closed_reason'] = org_stage.registration_closed_reason()
                context['entry_fee'] = org_stage.entry_fee
                context['available_classes'] = list(org_stage.championship.race_classes.all())

                if request.user.is_authenticated:
                    context['my_applications'] = Application.objects.filter(
                        stage=org_stage, submitted_by=request.user
                    ).exclude(status='cancelled').select_related('race_class').order_by('-created_at')

                    # Проверяем, является ли пользователь менеджером команды
                    try:
                        from teams.models import TeamManager
                        team_manager = TeamManager.objects.filter(
                            user=request.user, is_active=True
                        ).select_related('team').first()
                        context['user_is_team_manager'] = team_manager is not None
                        context['team_manager_obj'] = team_manager
                    except Exception:
                        context['user_is_team_manager'] = False
                        context['team_manager_obj'] = None
                else:
                    context['my_applications'] = []
                    context['user_is_team_manager'] = False
                    context['team_manager_obj'] = None

                # Публичный список участников — подтверждённые заявки
                confirmed = Application.objects.filter(
                    stage=org_stage, status='confirmed'
                ).select_related('race_class', 'pilot', 'pilot__driver').order_by(
                    'race_class__sort_order', 'race_class__name', 'start_number'
                )
                participants_by_class = {}
                for app in confirmed:
                    cls_name = app.race_class.name if app.race_class else 'Без класса'
                    participants_by_class.setdefault(cls_name, []).append(app)
                context['participants_by_class'] = participants_by_class
        except Exception:
            pass
        return context

# ========== ОБЪЯВЛЕНИЯ ==========
