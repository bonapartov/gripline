from django.contrib.auth.models import User
"""
Create or customize your page models here.
"""
from coderedcms.forms import CoderedFormField
from coderedcms.models import (
    CoderedArticleIndexPage, CoderedArticlePage, CoderedEmail,
    CoderedEventIndexPage, CoderedEventOccurrence, CoderedEventPage,
    CoderedFormPage, CoderedLocationIndexPage, CoderedLocationPage,
    CoderedWebPage)
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from django.db import models
from modelcluster.models import ClusterableModel
from wagtail.api import APIField
from wagtail.snippets.models import register_snippet
from wagtail.admin.panels import FieldPanel, FieldRowPanel, HelpPanel, InlinePanel, MultiFieldPanel
from wagtail.admin.forms.pages import WagtailAdminPageForm
from wagtail.models import DraftStateMixin, RevisionMixin, PreviewableMixin, Orderable
from django.urls import reverse
from django.utils.text import slugify
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from unidecode import unidecode
import datetime
from wagtail.models import Page
from django.db.models import Count
from django import forms
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.http import HttpResponse
from wagtail.fields import StreamField
from coderedcms.blocks import CONTENT_STREAMBLOCKS
from wagtailmarkdown.blocks import MarkdownBlock
from django.utils.html import format_html, format_html_join

# ---------- СТРАНИЦЫ (PAGES) ----------

class ArticlePageForm(WagtailAdminPageForm):
    """Мультиселект telegram_extra_tags должен показывать только теги,
    которые ещё не применяются автоматически (без раздела или с разделом,
    совпадающим с фактическим родителем статьи) — иначе редактор может
    выбрать тег, который и так уже будет опубликован."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get('telegram_extra_tags')
        if field is None:
            return

        parent = self.parent_page or (self.instance.get_parent() if self.instance.pk else None)
        auto_tags_filter = models.Q(parent_page__isnull=True)
        if parent is not None:
            auto_tags_filter |= models.Q(parent_page_id=parent.id)
        auto_tag_ids = TelegramTag.objects.filter(auto_tags_filter).values_list('pk', flat=True)
        field.queryset = TelegramTag.objects.exclude(pk__in=auto_tag_ids)


class ArticlePage(CoderedArticlePage):
    class Meta:
        verbose_name = "Article"
        ordering = ["-first_published_at"]
    parent_page_types = ["website.ArticleIndexPage", "website.TechArticleIndexPage"]
    template = "coderedcms/pages/article_page.html"

    body = StreamField(
        CONTENT_STREAMBLOCKS + [("markdown", MarkdownBlock(icon="code"))],
        null=True,
        blank=True,
        use_json_field=True,
    )

    telegram_teaser = models.TextField(
        max_length=900,
        blank=True,
        verbose_name="Тизер для Telegram",
        help_text=(
            "Короткий тизер для Telegram (3–5 предложений). "
            "Лимит ~900 символов — оставляет запас под ссылку и подпись к фото "
            "(Telegram ограничивает подпись к фото 1024 символами)."
        ),
    )
    telegram_extra_tags = ParentalManyToManyField(
        'website.TelegramTag',
        blank=True,
        verbose_name="Доп. теги для Telegram",
        help_text="Добавляются к автоматическим тегам раздела для этого конкретного поста.",
    )
    telegram_posted_at = models.DateTimeField(null=True, blank=True, editable=False)
    telegram_posted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        editable=False, related_name='+',
    )

    content_panels = CoderedArticlePage.content_panels + [
        FieldPanel('telegram_teaser'),
        FieldPanel('telegram_extra_tags'),
    ]

    base_form_class = ArticlePageForm

class ArticleIndexPage(CoderedArticleIndexPage):
    class Meta:
        verbose_name = "Article Landing Page"
    index_query_pagemodel = "website.ArticlePage"
    subpage_types = ["website.ArticlePage"]
    template = "coderedcms/pages/article_index_page.html"

    def get_context(self, request):
        context = super().get_context(request)
        
        # Получаем статьи только из этого раздела (исключаем матчасть и другие индексы)
        articles = ArticlePage.objects.child_of(self).live().order_by('-date_display')
        
        # Получаем данные классификаторов
        classifiers_data = self.get_classifiers_data()
        
        # Получаем все активные фильтры из GET-параметров
        active_filters = {}
        
        for classifier, terms in classifiers_data.items():
            classifier_slug = classifier.slug
            filter_value = request.GET.get(classifier_slug)
            if filter_value:
                active_filters[classifier_slug] = filter_value
                articles = articles.filter(
                    classifier_terms__slug=filter_value,
                    classifier_terms__classifier__slug=classifier_slug
                )
        
        context['articles'] = articles
        context['classifiers_data'] = classifiers_data
        context['active_filters'] = active_filters
        
        return context
    
    def get_classifiers_data(self):
        """Возвращает словарь классификаторов и их терминов, используемых в статьях"""
        from coderedcms.models import ClassifierTerm
        
        # Получаем термины только из дочерних статей этого раздела
        child_ids = ArticlePage.objects.child_of(self).live().values_list('id', flat=True)
        used_terms = ClassifierTerm.objects.filter(
            coderedpage__id__in=child_ids,
        ).distinct().select_related('classifier')
        
        # Группируем по классификаторам
        classifiers_dict = {}
        for term in used_terms:
            classifier = term.classifier
            if classifier not in classifiers_dict:
                classifiers_dict[classifier] = []
            if term not in classifiers_dict[classifier]:
                classifiers_dict[classifier].append(term)
        
        return classifiers_dict

class TechArticleIndexPage(CoderedArticleIndexPage):
    class Meta:
        verbose_name = "Матчасть (индекс)"
    subpage_types = ["website.ArticlePage"]
    template = "coderedcms/pages/tech_article_index_page.html"

    def get_index_children(self):
        return ArticlePage.objects.child_of(self).live().order_by('-first_published_at')

    def get_context(self, request):
        context = super().get_context(request)
        articles = ArticlePage.objects.child_of(self).live().order_by('-first_published_at')
        classifiers_data = self._get_section_classifiers()
        active_filters = {}
        for classifier, terms in classifiers_data.items():
            classifier_slug = classifier.slug
            filter_value = request.GET.get(classifier_slug)
            if filter_value:
                active_filters[classifier_slug] = filter_value
                articles = articles.filter(
                    classifier_terms__slug=filter_value,
                    classifier_terms__classifier__slug=classifier_slug
                )
        context['articles'] = articles
        context['classifiers_data'] = classifiers_data
        context['active_filters'] = active_filters
        return context

    def _get_section_classifiers(self):
        from coderedcms.models import ClassifierTerm
        section_ids = ArticlePage.objects.child_of(self).live().values_list('id', flat=True)
        used_terms = ClassifierTerm.objects.filter(
            coderedpage__id__in=section_ids,
            coderedpage__live=True,
        ).distinct().select_related('classifier')
        classifiers_dict = {}
        for term in used_terms:
            classifier = term.classifier
            if classifier not in classifiers_dict:
                classifiers_dict[classifier] = []
            if term not in classifiers_dict[classifier]:
                classifiers_dict[classifier].append(term)
        return classifiers_dict


class EventPage(CoderedEventPage):
    class Meta:
        verbose_name = "Event Page"
    parent_page_types = ["website.EventIndexPage", "website.ChampionshipPage", "website.StagePage"]
    template = "coderedcms/pages/event_page.html"

    # Новое поле для названия в админке
    admin_title = models.CharField(
        "Название для админки",
        max_length=255,
        blank=True,
        help_text="Название для отображения в списках админки (например, '1 этап Micro')"
    )

    # Связь с трассой
    track = models.ForeignKey(
        'website.Track',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        verbose_name="Трасса"
    )

    # Переопределяем content_panels
    content_panels = [
        # Сначала основные поля заголовка
        CoderedEventPage.content_panels[0],  # Это поле "Заголовок страницы видимый всем"
        FieldPanel('admin_title'),  # Теперь сразу под заголовком
    ] + CoderedEventPage.content_panels[1:] + [
        FieldPanel('track'),
        InlinePanel('race_class_groups', label="🏁 Результаты по классам"),
    ]

    def __str__(self):
        """Используем admin_title в админке, если он есть"""
        return self.admin_title or self.title

    def get_championship(self):
        """Ближайший ChampionshipPage: родитель напрямую либо родитель StagePage-родителя."""
        parent = self.get_parent().specific
        if isinstance(parent, ChampionshipPage):
            return parent
        if isinstance(parent, StagePage):
            return parent.get_parent().specific
        return None

    api_fields = [
        APIField('admin_title'),
    ]

class ColorSwatchWidget(forms.Widget):
    """Пикер цвета палитрой готовых образцов — по аналогии с выбором цвета в ЛК организатора."""

    PALETTE = [
        '#e63946', '#ea580c', '#d97706',
        '#16a34a', '#0891b2', '#2563eb',
        '#4f46e5', '#7c3aed', '#db2777',
        '#65a30d', '#0e7490', '#b91c1c',
        '#ffc107', '#0dcaf0',
    ]

    def render(self, name, value, attrs=None, renderer=None):
        value = value or ''
        widget_id = (attrs or {}).get('id') or f'id_{name}'
        unset_selected = '' if value else ' selected'
        swatches = format_html_join(
            '',
            '<span class="gl-color-swatch{}" style="background:{};" data-color="{}" title="{}"></span>',
            ((' selected' if c == value else '', c, c, c) for c in self.PALETTE),
        )
        return format_html(
            '''<input type="hidden" name="{name}" id="{id}" value="{value}">
<div class="gl-color-swatches" data-target="{id}">
    <span class="gl-color-swatch gl-color-unset{unset_selected}" data-color="" title="Не задан — унаследуется от родителя">&times;</span>
    {swatches}
</div>
<style>
    .gl-color-swatches {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }}
    .gl-color-swatch {{ width: 32px; height: 32px; border-radius: 6px; cursor: pointer; border: 3px solid transparent; transition: transform .15s, border-color .15s; }}
    .gl-color-swatch:hover {{ transform: scale(1.12); }}
    .gl-color-swatch.selected {{ border-color: #333; transform: scale(1.12); }}
    .gl-color-unset {{ background: repeating-linear-gradient(45deg, #888, #888 4px, #ccc 4px, #ccc 8px); display: flex; align-items: center; justify-content: center; font-weight: bold; color: #222; }}
</style>
<script>
    (function() {{
        document.querySelectorAll('.gl-color-swatches[data-target="{id}"] .gl-color-swatch').forEach(function(el) {{
            el.addEventListener('click', function() {{
                var box = this.parentElement;
                var target = document.getElementById(box.dataset.target);
                target.value = this.dataset.color;
                box.querySelectorAll('.gl-color-swatch').forEach(function(s) {{ s.classList.remove('selected'); }});
                this.classList.add('selected');
            }});
        }});
    }})();
</script>''',
            name=name, id=widget_id, value=value, swatches=swatches, unset_selected=unset_selected,
        )


class ChampionshipPage(CoderedWebPage):
    class Meta:
        verbose_name = "Чемпионат (Хаб)"

    parent_page_types = ["website.SeasonArchivePage", "website.WebPage"]
    subpage_types = ["website.EventPage", "website.StagePage"]
    template = "coderedcms/pages/championship_page.html"

    # Поле для отметки завершённости чемпионата
    is_completed = models.BooleanField(
        "Чемпионат завершён",
        default=False,
        help_text="Отметьте, если все этапы проведены"
    )

    # Цвет чемпионата в общем календаре. Наследуется всеми этапами, у которых цвет не задан явно,
    # но не отменяет индивидуальный цвет, выбранный на конкретном этапе (StagePage.calendar_color).
    calendar_color = models.CharField(
        "Цвет в календаре",
        max_length=7,
        blank=True,
        default="",
        help_text="Цвет по умолчанию для всех этапов чемпионата, у которых цвет не задан индивидуально"
    )

    # Убираем competition_types как ManyToMany поле
    # Будем использовать отдельную модель через InlinePanel

    # Основные поля
    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('is_completed'),
        FieldPanel('calendar_color', widget=ColorSwatchWidget),
        InlinePanel('championship_competition_types', label="Типы соревнований"),
    ]

    promote_panels = CoderedWebPage.promote_panels  # Без изменений

    def get_years(self):
        """
        Возвращает список годов, в которые проводились этапы чемпионата
        Учитывает годовые кубки (например, этапы в декабре и январе)
        """
        # Получаем все StagePage (этапы) этого чемпионата
        stages = self.get_children().live().specific()
        years = set()
    
        for stage in stages:
            # Получаем дату начала этапа из StagePage
            if stage.start_date:
                years.add(stage.start_date.year)
            
            # Также проверяем дочерние EventPage на случай, если даты отличаются
            for event in stage.get_children().live().specific():
                if hasattr(event, 'occurrences'):
                    for occurrence in event.occurrences.all():
                        if hasattr(occurrence, 'start') and occurrence.start:
                            years.add(occurrence.start.year)
                        elif hasattr(occurrence, 'start_time') and occurrence.start_time:
                            years.add(occurrence.start_time.year)
                        elif hasattr(occurrence, 'date') and occurrence.date:
                            years.add(occurrence.date.year)
    
        return sorted(list(years))

    def get_champions_by_class(self, year=None):
        """
        Возвращает топ-3 пилотов для каждого класса
        Если year указан и чемпионат не завершён (is_completed=False) — только этапы за этот год
        Если чемпионат завершён (is_completed=True) — все этапы
        """
        from django.db.models import Sum, Q
        from django.utils import timezone
        from .models import RaceResult, EventPage, StagePage
    
        # Получаем все StagePage (этапы) этого чемпионата
        stages = self.get_children().live().specific()
    
        # Собираем все EventPage из всех StagePage
        all_events = []
        for stage in stages:
            for event in stage.get_children().live().specific():
                if isinstance(event, EventPage):
                    all_events.append(event)
    
        # Фильтруем события по году, если нужно
        if year and not self.is_completed:
            filtered_events = []
            for event in all_events:
                if hasattr(event, 'occurrences'):
                    for occurrence in event.occurrences.all():
                        if occurrence.start and occurrence.start.year == year:
                            filtered_events.append(event)
                            break
            events = filtered_events
        else:
            events = all_events
    
        if not events:
            return {}
    
        # Получаем все результаты для отфильтрованных событий
        results = RaceResult.objects.filter(
            group__page__in=events
        ).select_related('driver', 'group__race_class')
    
        # Группируем по классам
        class_results = {}
    
        for result in results:
            class_id = result.group.race_class_id
            if class_id not in class_results:
                class_results[class_id] = {
                    'name': result.group.race_class.name,
                    'scores': {}
                }
    
            driver_id = result.driver_id
            if driver_id not in class_results[class_id]['scores']:
                class_results[class_id]['scores'][driver_id] = {
                    'driver': result.driver,
                    'total_points': 0,
                    'starts': 0
                }
    
            # Суммируем очки с учётом штрафов
            points_with_penalty = result.points - (result.penalty or 0)
            class_results[class_id]['scores'][driver_id]['total_points'] += points_with_penalty
            class_results[class_id]['scores'][driver_id]['starts'] += 1
    
        # Сортируем и берем топ-3 для каждого класса
        result_data = {}
    
        for class_id, data in class_results.items():
            # Сортируем пилотов по очкам
            sorted_drivers = sorted(
                data['scores'].values(),
                key=lambda x: -x['total_points']
            )[:3]  # Берем топ-3
    
            champions = []
            for position, driver_data in enumerate(sorted_drivers, 1):
                champions.append({
                    'position': position,
                    'driver': driver_data['driver'],
                    'points': driver_data['total_points'],
                    'starts': driver_data['starts']
                })
    
            result_data[class_id] = {
                'name': data['name'],
                'champions': champions
            }
    
        return result_data

    def get_champion(self):
        """Возвращает чемпиона (первое место в главном классе)"""
        return self.champion_driver

    def get_context(self, request):
      context = super().get_context(request)
  
      # Получаем ВСЕ дочерние StagePage (этапы) этого чемпионата
      all_stages = self.get_children().live().specific()
      
      # Собираем все EventPage из всех StagePage
      all_events = []
      for stage in all_stages:
          for event in stage.get_child_classes():
              if event not in all_events:
                  all_events.append(event)
  
      # Нормализуем входящее название класса
      raw_class_name = request.GET.get('race_class', '')
      from urllib.parse import unquote
      selected_class_name = unquote(raw_class_name.replace('+', ' '))
  
      # Получаем ВСЕ доступные классы для этого чемпионата
      available_class_ids = RaceResult.objects.filter(
          group__page__in=all_events
      ).values_list('group__race_class_id', flat=True).distinct()
  
      available_classes = RaceClass.objects.filter(id__in=available_class_ids)

      # Сортируем по алфавиту
      available_classes = sorted(available_classes, key=lambda x: x.name)
  
      # Получаем список названий для проверки
      available_class_names = [c.name for c in available_classes]
  
      # Если класс не выбран или не найден — берём первый из списка
      if not selected_class_name or selected_class_name not in available_class_names:
          selected_class_name = available_class_names[0] if available_class_names else None
  
      # Получаем ID групп результатов ТОЛЬКО для выбранного класса
      class_group_ids = RaceClassResultGroup.objects.filter(
          page__in=all_events,
          race_class__name=selected_class_name
      ).values_list('id', flat=True)
  
      # Функция для получения даты события
      def get_event_date(event):
          if event.occurrences.exists():
              return event.occurrences.first().start
          return event.first_published_at
  
      # Фильтруем события по выбранному классу
      events = []
      for event in all_events:
          if RaceResult.objects.filter(
              group__page=event,
              group__race_class__name=selected_class_name
          ).exists():
              events.append(event)
  
      # СОРТИРУЕМ СОБЫТИЯ ПО ДАТЕ (от раннего к позднему)
      events.sort(key=get_event_date)
  
      # Собираем статистику ТОЛЬКО для этого чемпионата и класса
      standings = {}
      for res in RaceResult.objects.filter(group_id__in=class_group_ids).select_related('driver', 'group__race_class', 'team'):
          driver_id = res.driver.id
          if driver_id not in standings:
              standings[driver_id] = {
                  'driver': res.driver,
                  'team': res.team,
                  'race_number': res.race_number,
                  'chassis': res.chassis_new,
                  'scores': {},
                  'total': 0,
                  'penalty_total': 0,
                  'tie_breaker_total': 0,
              }
          standings[driver_id]['scores'][res.group.page_id] = res.points
          standings[driver_id]['total'] += res.points - res.penalty
          standings[driver_id]['penalty_total'] += res.penalty
          standings[driver_id]['tie_breaker_total'] += res.tie_breaker
          if res.race_number:
              standings[driver_id]['race_number'] = res.race_number
          if res.chassis_new:
              standings[driver_id]['chassis_new'] = res.chassis_new
  
      # Сортировка
      sorted_standings = sorted(
          standings.values(),
          key=lambda x: (-x['total'], -x['tie_breaker_total'])
      )
  
      context['events'] = events
      context['standings'] = sorted_standings
      context['available_classes'] = available_classes
      context['selected_class'] = selected_class_name
  
      return context

# Добавьте эту модель ПОСЛЕ ChampionshipPage
class ChampionshipCompetitionType(models.Model):
    page = ParentalKey('ChampionshipPage', related_name='championship_competition_types')
    competition_type = models.ForeignKey('CompetitionType', on_delete=models.CASCADE)

    panels = [
        FieldPanel('competition_type'),
    ]

    class Meta:
        unique_together = ('page', 'competition_type')
        verbose_name = "Тип соревнования"
        verbose_name_plural = "Типы соревнований"

    def __str__(self):
        return self.competition_type.name

class EventIndexPage(CoderedEventIndexPage):
    class Meta:
        verbose_name = "Events Landing Page"
    index_query_pagemodel = "website.EventPage"
    subpage_types = ["website.EventPage"]
    template = "coderedcms/pages/event_index_page.html"

class EventOccurrence(CoderedEventOccurrence):
    event = ParentalKey(EventPage, related_name="occurrences")

class SeasonArchivePage(CoderedWebPage):
    class Meta:
        verbose_name = "Главная страница результатов"
    subpage_types = ["website.ChampionshipPage"]
    template = "coderedcms/pages/season_archive_page.html"
    

    def get_context(self, request):
        context = super().get_context(request)
        championships = self.get_children().live().specific()
        selected_slug = request.GET.get('champ')
        active_champ = championships.filter(slug=selected_slug).first() or championships.first()

        context['championships'] = championships
        context['active_champ'] = active_champ

        if active_champ:
            context.update(active_champ.get_context(request))
            context['events_list'] = active_champ.get_children().live().specific()
        return context


# ---------- ПИЛОТЫ (DRIVER) ----------
class DriverSocialLink(Orderable):
    page = ParentalKey("website.Driver", related_name="social_links")
    network_name = models.CharField("Название (например: ВК, Instagram)", max_length=100)
    link_url = models.URLField("Ссылка")

    panels = [
        FieldPanel('network_name'),
        FieldPanel('link_url'),
    ]

class Driver(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    first_name = models.CharField("Имя", max_length=100)
    last_name = models.CharField("Фамилия", max_length=100)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True)
    photo = models.ForeignKey(
        'wagtailimages.Image',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    city = models.CharField("Город", max_length=100, blank=True, null=True)
    biography = models.TextField("Биография", blank=True, null=True)
    telegram = models.URLField("Telegram", blank=True, null=True)
    instagram = models.URLField("Instagram", blank=True, null=True)
    # Поля для рейтингов
    rating_score = models.FloatField(
        "Рейтинг (Брэдли-Терри)",
        default=0.0,
        help_text="Рассчитывается аналитической моделью"
    )
    rating_updated_at = models.DateTimeField(
        "Дата обновления рейтинга",
        null=True,
        blank=True
    )
    rating_by_class = models.JSONField(
        "Рейтинги по классам",
        default=dict,
        blank=True,
        help_text="Формат: {'class_id': {'score': 35.2, 'starts': 5, 'updated': '2024-01-01'}}"
    )
    # === НОВЫЕ ПОЛЯ ДЛЯ PAGERANK ===
    pagerank_score = models.FloatField(
        "Рейтинг (PageRank)",
        default=0.0,
        help_text="Модифицированный PageRank - учитывает силу расписания"
    )
    pagerank_updated_at = models.DateTimeField(
        "Дата обновления PageRank",
        null=True,
        blank=True
    )
    pagerank_by_class = models.JSONField(
        "PageRank по классам",
        default=dict,
        blank=True,
        help_text="Формат: {'class_id': {'score': 0.15, 'starts': 5}}"
    )
    # === НОВЫЕ ПОЛЯ ДЛЯ АНСАМБЛЯ ===
    ensemble_score = models.FloatField(
        "Рейтинг (Ансамбль)",
        default=0.0,
        help_text="Комбинация Брэдли-Терри и PageRank"
    )
    ensemble_updated_at = models.DateTimeField(
        "Дата обновления ансамбля",
        null=True,
        blank=True
    )
    ensemble_by_class = models.JSONField(
        "Ансамбль по классам",
        default=dict,
        blank=True,
        help_text="Формат: {'class_id': {'score': 0.75, 'starts': 5}}"
    )
    # Поля для контекстной модели
    context_score = models.FloatField(
        "Рейтинг (Context-Aware)",
        default=0.0,
        help_text="Брэдли-Терри с учётом погоды и шин"
    )
    context_updated_at = models.DateTimeField(
        "Дата обновления контекстной модели",
        null=True,
        blank=True
    )
    context_by_class = models.JSONField(
        "Context-Aware по классам",
        default=dict,
        blank=True,
        help_text="Формат: {'class_id': {'score': 0.75, 'starts': 5}}"
    )
    context_weights = models.JSONField(
        "Веса контекстных факторов",
        default=dict,
        blank=True,
        help_text="Формат: {'temperature': 0.5, 'precipitation': -0.3, 'tyre': 0.2, 'track': 0.1}"
    )

    panels = [
        FieldPanel('first_name'),
        FieldPanel('last_name'),
        FieldPanel('slug'),
        FieldPanel('photo'),
        FieldPanel('city'),
        FieldPanel('biography'),
        InlinePanel('social_links', label="Социальные сети"),

    ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(f"{self.first_name} {self.last_name}"))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/drivers/{self.slug}/"

    class Meta:
        verbose_name = "Пилот"
        verbose_name_plural = "Пилоты"

class DriverResource(resources.ModelResource):
    class Meta:
        model = Driver
        fields = ('id', 'first_name', 'last_name', 'city', 'slug', 'biography')
        import_id_fields = ('first_name', 'last_name')
        skip_unchanged = True
        report_skipped = True


class TeamStaffSocialLink(Orderable):
    page = ParentalKey("website.TeamStaff", related_name="social_links")
    network_name = models.CharField("Название (например: ВК, Instagram)", max_length=100)
    link_url = models.URLField("Ссылка")

    panels = [
        FieldPanel('network_name'),
        FieldPanel('link_url'),
    ]

class TeamStaff(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    first_name = models.CharField("Имя", max_length=100)
    last_name = models.CharField("Фамилия", max_length=100)
    middle_name = models.CharField("Отчество", max_length=100, blank=True)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True)
    photo = models.ForeignKey(
        'wagtailimages.Image',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    position = models.CharField("Должность", max_length=255, blank=True,
                               help_text="например: Старший механик, тренер")
    biography = models.TextField("Биография", blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)

    panels = [
        FieldPanel('first_name'),
        FieldPanel('last_name'),
        FieldPanel('middle_name'),
        FieldPanel('slug'),
        FieldPanel('photo'),
        FieldPanel('position'),
        FieldPanel('biography'),
        FieldPanel('phone'),
        FieldPanel('email'),
        InlinePanel('social_links', label="Социальные сети"),
    ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        parts = [self.last_name, self.first_name, self.middle_name]
        return ' '.join(p for p in parts if p)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(unidecode(f"{self.last_name} {self.first_name} {self.middle_name}"))
            self.slug = base_slug
            # Проверка на уникальность
            counter = 1
            while TeamStaff.objects.filter(slug=self.slug).exists():
                self.slug = f"{base_slug}-{counter}"
                counter += 1
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/staff/{self.slug}/"

    class Meta:
        verbose_name = "Сотрудник команды"
        verbose_name_plural = "Сотрудники команд"

class TeamStaffMembership(models.Model):
    """Связь сотрудника с командой"""
    staff = models.ForeignKey('TeamStaff', on_delete=models.CASCADE, related_name='team_memberships')
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='staff_memberships')  # Строковая ссылка
    joined_at = models.DateField("Дата присоединения", auto_now_add=True)
    left_at = models.DateField("Дата ухода", null=True, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Участие сотрудника в команде"
        verbose_name_plural = "Участия сотрудников в командах"
        # unique_together = ['staff', 'team',  'is_active']  # Закомментировать или удалить
        unique_together = ['staff', 'team']  # Оставить только уникальность пары

    def __str__(self):
        return f"{self.staff.full_name} в {self.team.name}"

# ---------- КОМАНДЫ (TEAM) ----------

class TeamSocialLink(Orderable):
    page = ParentalKey("website.Team", related_name="social_links")
    network_name = models.CharField("Название (например: ВК, Instagram, Сайт)", max_length=100)
    link_url = models.URLField("Ссылка")

    panels = [
        FieldPanel('network_name'),
        FieldPanel('link_url'),
    ]


class Team(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    name = models.CharField("Название команды", max_length=255)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, null=True)
    logo = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="Логотип"
    )

    # Новые поля для руководителя
    manager_name = models.CharField("ФИО руководителя", max_length=255, blank=True)
    manager_photo = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="Фото руководителя"
    )
    manager_email = models.EmailField("Email руководителя", blank=True)
    manager_phone = models.CharField("Телефон", max_length=30, blank=True)
    manager_social = models.URLField("Соцсети руководителя", blank=True, help_text="Ссылка на VK, Telegram и т.д.")
    description = models.TextField("Описание", blank=True, null=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('logo'),
        FieldPanel('description'),
        InlinePanel('social_links', label="Социальные сети команды"),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(self.name))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/teams/{self.slug}/"

    class Meta:
        verbose_name = "Команда"
        verbose_name_plural = "Команды"

class TeamMembership(models.Model):
    """Связь пилота с командой с датами"""
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='team_memberships')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    race_class = models.ForeignKey('RaceClass', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Класс')
    joined_at = models.DateField("Дата присоединения", auto_now_add=True)
    left_at = models.DateField("Дата ухода", null=True, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Участие в команде"
        verbose_name_plural = "Участия в командах"
        unique_together = ['driver', 'team', 'joined_at']  # Защита от дублей

    def __str__(self):
        return f"{self.driver.full_name} в {self.team.name}"

# ---------- ТРАССЫ (TRACK) ----------

class TrackSocialLink(Orderable):
    page = ParentalKey("website.Track", related_name="social_links")
    network_name = models.CharField("Название (например: ВК, Instagram, Сайт)", max_length=100)
    link_url = models.URLField("Ссылка")

    panels = [
        FieldPanel('network_name'),
        FieldPanel('link_url'),
    ]

class Track(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    name = models.CharField("Название трассы", max_length=255)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, null=True)
    city = models.CharField("Город", max_length=100, blank=True, null=True)
    region = models.CharField("Регион", max_length=100, blank=True, null=True)
    address = models.CharField("Адрес", max_length=255, blank=True, null=True, help_text="Улица, дом")
    map_html = models.TextField(
        "Код карты",
        blank=True,
        null=True,
        help_text="HTML-код для вставки карты (например, iframe с Яндекс.Картами)"
    )
    # координаты трассы
    latitude = models.FloatField(
        "Широта",
        blank=True,
        null=True,
        help_text="Например: 43.5347 (для Сочи)"
    )
    longitude = models.FloatField(
        "Долгота",
        blank=True,
        null=True,
        help_text="Например: 39.8555 (для Сочи)"
    )
    photo = models.ForeignKey(
        'wagtailimages.Image',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name="Фото трассы"
    )
    description = models.TextField("Описание", blank=True, null=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('city'),
        FieldPanel('region'),
        FieldPanel('address'),
        FieldPanel('latitude'),
        FieldPanel('longitude'),
        FieldPanel('map_html'),
        FieldPanel('photo'),
        FieldPanel('description'),
        InlinePanel('social_links', label="Социальные сети"),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(self.name))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/tracks/{self.slug}/"

    class Meta:
        verbose_name = "Трасса"
        verbose_name_plural = "Трассы"

class TrackIndexPage(CoderedWebPage):
    """
    Страница со списком всех трасс
    """
    class Meta:
        verbose_name = "Список трасс"

    parent_page_types = ["website.WebPage", "website.SeasonArchivePage"]
    subpage_types = []  # Нельзя создавать дочерние страницы
    template = "coderedcms/pages/track_index_page.html"

    def get_context(self, request):
        context = super().get_context(request)
        # Получаем все трассы из сниппета Track
        tracks = Track.objects.all().order_by('name')
        context['tracks'] = tracks
        return context


# ---------- ШАССИ (CHASSIS) ----------

class ChassisSocialLink(Orderable):
    page = ParentalKey("website.Chassis", related_name="social_links")
    network_name = models.CharField("Название (например: ВК, Instagram, Сайт)", max_length=100)
    link_url = models.URLField("Ссылка")

    panels = [
        FieldPanel('network_name'),
        FieldPanel('link_url'),
    ]

class Chassis(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    name = models.CharField("Название шасси", max_length=100, unique=True)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, null=True)
    country = models.CharField("Страна производитель", max_length=100, blank=True, null=True)
    logo = models.ForeignKey(
        'wagtailimages.Image',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name="Логотип"
    )
    description = models.TextField("Описание", blank=True, null=True)
    website = models.URLField("Официальный сайт", blank=True, null=True)

    # Поля для рейтингов
    rating_score = models.FloatField(
        "Рейтинг (Брэдли-Терри)",
        default=0.0,
        help_text="Рассчитывается аналитической моделью"
    )
    rating_updated_at = models.DateTimeField(
        "Дата обновления рейтинга",
        null=True,
        blank=True
    )

    pagerank_score = models.FloatField(
        "Рейтинг (PageRank)",
        default=0.0,
        help_text="Модифицированный PageRank"
    )
    pagerank_updated_at = models.DateTimeField(
        "Дата обновления PageRank",
        null=True,
        blank=True
    )

    ensemble_score = models.FloatField(
        "Рейтинг (Ансамбль)",
        default=0.0,
        help_text="Комбинация Брэдли-Терри и PageRank"
    )
    ensemble_updated_at = models.DateTimeField(
        "Дата обновления ансамбля",
        null=True,
        blank=True
    )

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('country'),
        FieldPanel('logo'),
        FieldPanel('description'),
        FieldPanel('website'),
        InlinePanel('social_links', label="Социальные сети"),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(self.name))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/chassis/{self.slug}/"

    class Meta:
        verbose_name = "Шасси"
        verbose_name_plural = "Шасси"


# ---------- ШИНЫ (TYRES) ----------

class TyreBrand(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    """
    Производитель шин (Vega, Bridgestone, LeCont, Mojo и т.д.)
    """
    name = models.CharField("Название производителя", max_length=100, unique=True)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, null=True)
    country = models.CharField("Страна", max_length=100, blank=True, null=True)
    logo = models.ForeignKey(
        'wagtailimages.Image',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name="Логотип"
    )
    description = models.TextField("Описание", blank=True, null=True)
    website = models.URLField("Официальный сайт", blank=True, null=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('country'),
        FieldPanel('logo'),
        FieldPanel('description'),
        FieldPanel('website'),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(self.name))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/tyrebrands/{self.slug}/"

    class Meta:
        verbose_name = "Производитель шин"
        verbose_name_plural = "Производители шин"

class TyreType(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    """
    Тип шин (Слик, Дождь, Промежуточные)
    """
    TYRE_TYPE_CHOICES = [
        ('slick', 'Слик'),
        ('wet', 'Дождь'),
        ('intermediate', 'Промежуточные'),
    ]

    name = models.CharField("Название типа", max_length=50, choices=TYRE_TYPE_CHOICES, unique=True)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, null=True)
    description = models.TextField("Описание", blank=True, null=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('description'),
    ]

    def __str__(self):
        return self.get_name_display()

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(self.get_name_display()))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/tyretypes/{self.slug}/"

    class Meta:
        verbose_name = "Тип шин"
        verbose_name_plural = "Типы шин"

class Tyre(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    """
    Готовая шина (связывает производителя и тип)
    """
    brand = models.ForeignKey(
        TyreBrand,
        on_delete=models.CASCADE,
        related_name='tyres',
        verbose_name="Производитель"
    )
    type = models.ForeignKey(
        TyreType,
        on_delete=models.CASCADE,
        related_name='tyres',
        verbose_name="Тип шин"
    )
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, null=True)
    description = models.TextField("Описание", blank=True, null=True)

    panels = [
        FieldPanel('brand'),
        FieldPanel('type'),
        FieldPanel('slug'),
        FieldPanel('description'),
    ]

    def __str__(self):
        return f"{self.brand.name} {self.type.get_name_display()}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(f"{self.brand.name}-{self.type.get_name_display()}"))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/tyres/{self.slug}/"

    class Meta:
        verbose_name = "Шина"
        verbose_name_plural = "Шины"
        unique_together = ('brand', 'type')  # Чтобы не было дублей


# ---------- ДВИГАТЕЛИ (ENGINE) ----------

class Engine(DraftStateMixin, RevisionMixin, PreviewableMixin, ClusterableModel, models.Model):
    """
    Производитель/модель двигателя (Rotax, IAME, TM, Vortex и т.д.)
    """
    name = models.CharField("Название двигателя", max_length=100, unique=True)
    slug = models.SlugField("Slug", max_length=255, unique=True, blank=True, null=True)
    country = models.CharField("Страна производитель", max_length=100, blank=True, null=True)
    logo = models.ForeignKey(
        'wagtailimages.Image',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name="Логотип"
    )
    description = models.TextField("Описание", blank=True, null=True)
    website = models.URLField("Официальный сайт", blank=True, null=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('country'),
        FieldPanel('logo'),
        FieldPanel('description'),
        FieldPanel('website'),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(self.name))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/engines-list/{self.slug}/"

    class Meta:
        verbose_name = "Двигатель"
        verbose_name_plural = "Двигатели"


# ---------- КЛАССЫ ГОНОК (RaceClass) ----------

@register_snippet
class RaceClass(models.Model):
    name = models.CharField("Название класса", max_length=255)
    panels = [FieldPanel('name')]

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Класс гонки"
        verbose_name_plural = "Классы гонок"
@register_snippet
class CompetitionType(models.Model):
    name = models.CharField("Название типа", max_length=100)
    code = models.CharField("Код (cup, championship, competition)", max_length=50, unique=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('code'),
    ]

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Тип соревнований"
        verbose_name_plural = "Типы соревнований"

# ---------- РЕЗУЛЬТАТЫ ----------

class RaceClassResultGroup(Orderable, ClusterableModel):
    page = ParentalKey(EventPage, related_name='race_class_groups')
    race_class = models.ForeignKey(RaceClass, on_delete=models.CASCADE, verbose_name="Класс гонки")

    tyre = models.ForeignKey(
        Tyre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='race_groups',
        verbose_name="Шины"
    )

    engine = models.ForeignKey(
        Engine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='race_groups',
        verbose_name="Двигатель"
    )

    # Время заезда для этого класса (по умолчанию 14:00)
    race_time = models.TimeField(
        "Время заезда",
        default=datetime.time(14, 0),
        help_text="Время проведения заезда для этого класса (по умолчанию 14:00)"
    )

    # Поля погоды для всего класса
    air_temperature = models.FloatField(
        "Температура воздуха, °C",
        blank=True, null=True
    )
    humidity = models.IntegerField(
        "Влажность, %",
        blank=True, null=True
    )
    pressure = models.IntegerField(
        "Давление, мм рт. ст.",
        blank=True, null=True
    )
    wind_speed = models.FloatField(
        "Скорость ветра, м/с",
        blank=True, null=True
    )
    uv_index = models.FloatField(
        "УФ-индекс",
        blank=True, null=True
    )
    precipitation = models.FloatField(
        "Осадки, мм",
        blank=True, null=True,
        help_text="Количество осадков за час (0 - сухо, >0 - дождь)"
    )

    panels = [
        FieldRowPanel([FieldPanel('page'), FieldPanel('race_class')]),
        FieldRowPanel([FieldPanel('tyre'), FieldPanel('engine'), FieldPanel('race_time')]),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel('air_temperature'),
                FieldPanel('humidity'),
                FieldPanel('pressure'),
            ]),
            FieldRowPanel([
                FieldPanel('wind_speed'),
                FieldPanel('uv_index'),
                FieldPanel('precipitation'),
            ]),
        ], heading="Погода"),
        InlinePanel('class_results', label="Пилоты этого класса"),
    ]

    def __str__(self):
        return f"{self.page.title} - {self.race_class.name} (ID: {self.id})"

    def sorted_results(self):
        return self.class_results.order_by('-points', 'position')

    class Meta:
        verbose_name = "Группа результатов"
        verbose_name_plural = "Группы результатов"

class RaceResult(Orderable):
    group = ParentalKey(RaceClassResultGroup, related_name='class_results')
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, verbose_name="Пилот")
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='race_results',
        verbose_name="Команда"
    )

    race_number = models.CharField("Стартовый номер", max_length=10, blank=True, null=True)
    chassis_new = models.ForeignKey(
        'website.Chassis',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='race_results',
        verbose_name="Шасси (связанное)"
    )
    position = models.PositiveIntegerField("Место")
    points = models.FloatField("Очки", default=0)

    # Новое поле для тай-брейка (скрытые очки)
    tie_breaker = models.FloatField("Тай-брейк", default=0)
    penalty     = models.FloatField("Штраф", default=0)

    # --- Финал ---
    start_position        = models.IntegerField("Стартовая позиция (финал)", null=True, blank=True)
    best_lap_ms           = models.IntegerField("Круг, мс", null=True, blank=True)
    best_s1_ms            = models.IntegerField("S1, мс", null=True, blank=True)
    best_s2_ms            = models.IntegerField("S2, мс", null=True, blank=True)
    best_s3_ms            = models.IntegerField("S3, мс", null=True, blank=True)

    # --- Квалификация ---
    qual_position         = models.IntegerField("Позиция", null=True, blank=True)
    qual_best_lap_ms      = models.IntegerField("Круг, мс", null=True, blank=True)
    qual_s1_ms            = models.IntegerField("S1, мс", null=True, blank=True)
    qual_s2_ms            = models.IntegerField("S2, мс", null=True, blank=True)
    qual_s3_ms            = models.IntegerField("S3, мс", null=True, blank=True)

    # --- Предфинал ---
    pre_final_position    = models.IntegerField("Позиция", null=True, blank=True)
    pre_final_start_pos   = models.IntegerField("Старт", null=True, blank=True)
    pre_final_best_lap_ms = models.IntegerField("Круг, мс", null=True, blank=True)
    pre_final_s1_ms       = models.IntegerField("S1, мс", null=True, blank=True)
    pre_final_s2_ms       = models.IntegerField("S2, мс", null=True, blank=True)
    pre_final_s3_ms       = models.IntegerField("S3, мс", null=True, blank=True)

    panels = [
        FieldRowPanel([
            FieldPanel('driver', widget=forms.Select(attrs={'class': 'driver-search-select', 'data-search': 'true'})),
            FieldPanel('race_number'),
        ]),
        FieldRowPanel([
            FieldPanel('chassis_new'),
            FieldPanel('team'),
        ]),
        MultiFieldPanel([
            HelpPanel("Тай-брейк — скрытые очки для разрешения равенства, не отображаются на сайте. Штраф — вычитается из очков."),
            FieldRowPanel([
                FieldPanel('position'),
                FieldPanel('start_position'),
                FieldPanel('points'),
                FieldPanel('tie_breaker'),
                FieldPanel('penalty'),
            ]),
        ], heading="Финал"),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel('best_lap_ms'),
                FieldPanel('best_s1_ms'),
                FieldPanel('best_s2_ms'),
                FieldPanel('best_s3_ms'),
            ]),
        ], heading="Тайминг финала"),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel('qual_position'),
                FieldPanel('qual_best_lap_ms'),
                FieldPanel('qual_s1_ms'),
                FieldPanel('qual_s2_ms'),
                FieldPanel('qual_s3_ms'),
            ]),
        ], heading="Квалификация"),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel('pre_final_position'),
                FieldPanel('pre_final_start_pos'),
                FieldPanel('pre_final_best_lap_ms'),
                FieldPanel('pre_final_s1_ms'),
                FieldPanel('pre_final_s2_ms'),
                FieldPanel('pre_final_s3_ms'),
            ]),
        ], heading="Предфинал"),
    ]

    @property
    def best_lap_all_ms(self):
        times = [t for t in [self.best_lap_ms, self.qual_best_lap_ms, self.pre_final_best_lap_ms] if t]
        return min(times) if times else None

    @property
    def best_lap_session(self):
        candidates = [
            (self.qual_best_lap_ms, 'qual'),
            (self.pre_final_best_lap_ms, 'pre_final'),
            (self.best_lap_ms, 'final'),
        ]
        valid = [(ms, s) for ms, s in candidates if ms]
        if not valid:
            return None
        return min(valid, key=lambda x: x[0])[1]

    @property
    def ideal_lap_all_ms(self):
        s1 = [t for t in [self.best_s1_ms, self.qual_s1_ms, self.pre_final_s1_ms] if t]
        s2 = [t for t in [self.best_s2_ms, self.qual_s2_ms, self.pre_final_s2_ms] if t]
        s3 = [t for t in [self.best_s3_ms, self.qual_s3_ms, self.pre_final_s3_ms] if t]
        if s1 and s2 and s3:
            return min(s1) + min(s2) + min(s3)
        return None

    @property
    def ideal_lap_session(self):
        """Сессия, если все три сектора идеального круга взяты из неё же; иначе None (сектора вразнобой)."""
        s1 = [t for t in [self.best_s1_ms, self.qual_s1_ms, self.pre_final_s1_ms] if t]
        s2 = [t for t in [self.best_s2_ms, self.qual_s2_ms, self.pre_final_s2_ms] if t]
        s3 = [t for t in [self.best_s3_ms, self.qual_s3_ms, self.pre_final_s3_ms] if t]
        if not (s1 and s2 and s3):
            return None
        min_s1, min_s2, min_s3 = min(s1), min(s2), min(s3)
        sessions = {
            'qual': (self.qual_s1_ms, self.qual_s2_ms, self.qual_s3_ms),
            'pre_final': (self.pre_final_s1_ms, self.pre_final_s2_ms, self.pre_final_s3_ms),
            'final': (self.best_s1_ms, self.best_s2_ms, self.best_s3_ms),
        }
        for session, (a, b, c) in sessions.items():
            if a == min_s1 and b == min_s2 and c == min_s3:
                return session
        return None

    class Meta:
        verbose_name = "Результат"
        verbose_name_plural = "Результаты"
        ordering = ['position']


# ---------- ВСПОМОГАТЕЛЬНЫЕ МОДЕЛИ ----------

class FormPage(CoderedFormPage):
    class Meta:
        verbose_name = "Form"
    template = "coderedcms/pages/form_page.html"

class FormPageField(CoderedFormField):
    page = ParentalKey("FormPage", related_name="form_fields")

class FormConfirmEmail(CoderedEmail):
    page = ParentalKey("FormPage", related_name="confirmation_emails")

class LocationPage(CoderedLocationPage):
    class Meta:
        verbose_name = "Location Page"
    template = "coderedcms/pages/location_page.html"
    parent_page_types = ["website.LocationIndexPage"]

class LocationIndexPage(CoderedLocationIndexPage):
    class Meta:
        verbose_name = "Location Landing Page"
    index_query_pagemodel = "website.LocationPage"
    subpage_types = ["website.LocationPage"]
    template = "coderedcms/pages/location_index_page.html"

class WebPage(CoderedWebPage):
    class Meta:
        verbose_name = "Web Page"
    template = "coderedcms/pages/web_page.html"

class WeightsPage(CoderedWebPage):
    """
    Страница для отображения таблицы весов
    """
    class Meta:
        verbose_name = "Таблица весов"

    parent_page_types = ["website.WebPage", "website.SeasonArchivePage"]
    subpage_types = []
    template = "coderedcms/snippets/weights_table.html"

class AnalyticsMetadata(models.Model):
    """Хранилище метаданных для аналитики"""
    key = models.CharField(max_length=100, unique=True, verbose_name="Ключ")
    value = models.DateTimeField(null=True, blank=True, verbose_name="Значение")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Метаданные аналитики"
        verbose_name_plural = "Метаданные аналитики"

    def __str__(self):
        return f"{self.key}: {self.value}"

class AnalyticsSettings(models.Model):
    """
    Singleton-модель глобальных параметров аналитического движка.
    Доступна через AnalyticsSettings.get().
    Изменения вступают в силу при следующем запуске update_ratings.
    """

    # --- Temporal decay ---
    lambda_active = models.FloatField(
        default=0.8,
        verbose_name="λ активного пилота",
        help_text=(
            "Скорость затухания для пилотов с недавними гонками. "
            "Полураспад = ln(2)/λ лет. Рекомендуется 0.5–1.2."
        ),
    )
    lambda_inactive = models.FloatField(
        default=2.0,
        verbose_name="λ неактивного пилота",
        help_text=(
            "Скорость затухания для пилотов без гонок дольше порога. "
            "Должен быть выше lambda_active. Рекомендуется 1.5–3.0."
        ),
    )
    inactive_threshold_days = models.IntegerField(
        default=180,
        verbose_name="Порог неактивности (дней)",
        help_text=(
            "Количество дней без гонок в классе, после которого применяется "
            "lambda_inactive. Один летний сезон ≈ 180 дней."
        ),
    )

    # --- Пороги данных ---
    min_races_per_class = models.IntegerField(
        default=5,
        verbose_name="Мин. гонок для расчёта класса",
        help_text="Класс с меньшим количеством гонок пропускается при расчёте BT.",
    )
    min_comparisons = models.IntegerField(
        default=10,
        verbose_name="Мин. парных сравнений (BT)",
        help_text="Класс с меньшим количеством парных сравнений пропускается.",
    )
    min_starts_display = models.IntegerField(
        default=3,
        verbose_name="Мин. стартов для отображения рейтинга",
        help_text="Пилоты с меньшим числом стартов считаются без достаточной статистики.",
    )
    min_races_context = models.IntegerField(
        default=10,
        verbose_name="Мин. гонок для контекстной модели",
        help_text="Класс с меньшим количеством гонок пропускается при расчёте контекстной модели.",
    )
    min_comparisons_context = models.IntegerField(
        default=20,
        verbose_name="Мин. парных сравнений (контекстная модель)",
        help_text="Класс с меньшим числом сравнений пропускается в контекстной модели.",
    )

    # --- Параметры моделей ---
    bt_alpha = models.FloatField(
        default=0.1,
        verbose_name="Alpha (L1-регуляризация BT)",
        help_text=(
            "Lasso-регуляризация Bradley-Terry. Выше → сильнее сглаживание "
            "к среднему для пилотов с малым числом гонок. Диапазон: 0.01–1.0."
        ),
    )
    pagerank_damping = models.FloatField(
        default=0.85,
        verbose_name="Damping factor (PageRank)",
        help_text="Коэффициент затухания PageRank. Стандартное значение 0.85. Диапазон: 0.5–0.99.",
    )
    ensemble_min_common_drivers = models.IntegerField(
        default=3,
        verbose_name="Мин. общих пилотов для ансамбля",
        help_text="Минимальное число общих пилотов между BT и PageRank для построения ансамбля.",
    )
    trend_window = models.IntegerField(
        default=5,
        verbose_name="Окно тренда формы (гонок)",
        help_text=(
            "Число гонок для расчёта тренда. Сравниваются последние N и предыдущие N гонок. "
            "Минимум стартов для показа тренда = N+1."
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки аналитики"
        verbose_name_plural = "Настройки аналитики"

    def __str__(self):
        return (
            f"AnalyticsSettings (λ={self.lambda_active}/{self.lambda_inactive}, "
            f"inactive={self.inactive_threshold_days}d)"
        )

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TelegramTag(models.Model):
    """
    Тег для анонс-постинга в Telegram-канал. Список произвольной длины,
    редактируется в Wagtail Admin → Telegram → Теги.

    Категория — это ссылка на конкретную родительскую страницу (например,
    страницу «Матчасть» или «Новости»), а не жёстко зашитый список — так
    при появлении нового раздела сайта ему можно назначить тег без правки
    кода, и привязка существующих тегов (например, «Матчасть») не зашита
    в коде и может быть переназначена через админку.
    """

    tag = models.CharField(
        max_length=32,
        verbose_name="Тег",
        help_text="Например: #юниоры",
    )
    emoji = models.CharField(
        max_length=8,
        blank=True,
        verbose_name="Эмодзи",
        help_text="Например: 🔧. Необязательно, показывается перед тегом в посте.",
    )
    parent_page = models.ForeignKey(
        Page,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Раздел",
        help_text=(
            "Родительская страница, в которой должны быть статьи, чтобы получить "
            "этот тег (например, Матчасть или Новости). Если не выбрана — тег "
            "публикуется на всех постах."
        ),
        related_name='telegram_tags',
    )

    class Meta:
        verbose_name = "Тег Telegram"
        verbose_name_plural = "Теги Telegram"
        ordering = ['parent_page', 'tag']

    def __str__(self):
        return self.tag


class TelegramSettings(models.Model):
    """
    Singleton-модель настроек анонс-постинга в Telegram-канал.
    Доступна через TelegramSettings.get().
    Токен бота НЕ хранится здесь — только в переменной окружения
    TELEGRAM_ANNOUNCE_BOT_TOKEN (см. website/telegram.py).
    Теги — в отдельной модели TelegramTag, не здесь.
    """

    channel_id = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="Channel ID",
        help_text="Например: @gripline_channel или числовой chat_id.",
    )
    link_text = models.CharField(
        max_length=64,
        default="Читать статью →",
        verbose_name="Текст ссылки на статью",
        help_text="Показывается вместо длинного URL в тексте поста.",
    )

    class Meta:
        verbose_name = "Настройки Telegram"
        verbose_name_plural = "Настройки Telegram"

    def __str__(self):
        return "Настройки Telegram-канала"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class EngineIndexPage(CoderedWebPage):
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

    class Meta:
        verbose_name = "Лог обновления"
        verbose_name_plural = "Логи обновлений"
        ordering = ['-updated_at']

    def __str__(self):
        return f"Обновление от {self.updated_at.strftime('%d.%m.%Y %H:%M')}"

class WeightsTablePage(CoderedWebPage):
    """
    Страница для отображения таблицы весов контекстной модели
    """
    class Meta:
        verbose_name = "Таблица весов (динамическая)"

    parent_page_types = ["website.WebPage", "website.SeasonArchivePage"]
    subpage_types = []
    template = "coderedcms/snippets/weights_table.html"

class PulseIndexPage(CoderedWebPage):
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
        from .models import RaceResult, EventPage, StagePage, ChampionshipPage, RaceClass, CompetitionType
    
        # Получаем все чемпионаты
        championships = ChampionshipPage.objects.live().public().specific()
    
        # Получаем все доступные типы соревнований
        types = CompetitionType.objects.values_list('name', flat=True).distinct()
    
        # Получаем все доступные классы
        race_classes = RaceClass.objects.filter(
            raceclassresultgroup__isnull=False
        ).distinct().order_by('name')
    
        # Получаем все доступные годы из этапов (через новую структуру)
        all_years = set()
        for champ in championships:
            all_years.update(champ.get_years())
    
        # Текущий год
        current_year = timezone.now().year
    
        # Фильтруем годы: только текущий и прошедшие
        filtered_years = []
        for year in all_years:
            if year <= current_year:
                if year == current_year:
                    filtered_years.append(year)
                else:
                    # Проверяем, есть ли результаты за этот год
                    # Находим все StagePage с этим годом
                    stages_in_year = StagePage.objects.filter(
                        start_date__year=year,
                        live=True
                    )
                    has_results = False
                    for stage in stages_in_year:
                        for event in stage.get_children().live().specific():
                            if RaceResult.objects.filter(group__page=event).exists():
                                has_results = True
                                break
                        if has_results:
                            break
                    if has_results:
                        filtered_years.append(year)
    
        # Сортируем от большего к меньшему
        filtered_years = sorted(filtered_years, reverse=True)
    
        context['championships'] = championships
        context['available_types'] = list(types)
    
        # Сортируем классы по алфавиту
        context['available_classes'] = sorted(race_classes, key=lambda x: x.name)
        context['available_years'] = filtered_years
        context['current_year'] = filtered_years[0] if filtered_years else current_year
    
        return context

class RatingInfoPage(CoderedWebPage):
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

        from .models import AnalyticsMetadata, Driver, RaceResult, RaceClass
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

class EventCalendarPage(CoderedWebPage):
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
        from .models import EventPage, CompetitionType, ChampionshipPage
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

        enriched_events = list(unique_events.values())
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
                ed['org_stage'] = org_s if (org_s and org_s.registration_enabled) else None
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


class HomePage(CoderedWebPage):
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
            from .weather_utils import get_stage_weather
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
        classes = sorted(RaceClass.objects.all(), key=lambda x: x.name)

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
            all_drivers = Driver.objects.exclude(rating_by_class={}).exclude(rating_by_class__isnull=True)

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

                # Skip drivers inactive in this class beyond threshold
                last_race_str = bt_data.get('last_race_date')
                if last_race_str:
                    try:
                        last_race = _date.fromisoformat(last_race_str)
                        if (_date.today() - last_race).days > _as.inactive_threshold_days:
                            continue
                    except (ValueError, TypeError):
                        pass

                s = race_stats.get(driver.id, {})
                driver.race_count = s.get('race_count', 0)
                driver.win_count = s.get('win_count', 0)
                driver._bt_score = bt_data.get('score', 0)
                driver._starts = bt_data.get('starts', 0)
                candidates.append(driver)

            if candidates:
                mu = _stats.median(d._bt_score for d in candidates)
                C = 15
                for d in candidates:
                    d._smoothed = (d._starts * d._bt_score + C * mu) / (d._starts + C)
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

class StagePage(CoderedWebPage):
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
        from .weather_utils import get_stage_weather
        return get_stage_weather(self)

    def get_child_classes(self):
        """
        Возвращает все дочерние EventPage (классовые страницы) этого этапа.
        """
        return self.get_children().live().specific()

    def get_classes_with_results(self):
        """
        Возвращает список классов, у которых есть результаты.
        """
        classes = []
        for event in self.get_child_classes():
            if event.race_class_groups.exists():
                for group in event.race_class_groups.all():
                    if group.race_class and group.race_class.name not in classes:
                        classes.append(group.race_class.name)
        return classes

    def has_results(self):
        """
        Проверяет, есть ли результаты хотя бы в одном классе этапа.
        """
        for event in self.get_child_classes():
            if event.race_class_groups.exists():
                return True
        return False

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        try:
            from organizers.models import Stage
            from applications.models import Application
            org_stage = Stage.objects.filter(wagtail_page=self).first()
            if org_stage:
                context['org_stage'] = org_stage
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
                ).select_related('race_class', 'pilot', 'pilot__driver').order_by('race_class__name', 'start_number')
                participants_by_class = {}
                for app in confirmed:
                    cls_name = app.race_class.name if app.race_class else 'Без класса'
                    participants_by_class.setdefault(cls_name, []).append(app)
                context['participants_by_class'] = participants_by_class
        except Exception:
            pass
        return context

# ========== ОБЪЯВЛЕНИЯ ==========
class AdCategory(models.Model):
    """Категория объявления (роль или товар)"""
    name = models.CharField("Название", max_length=100)
    slug = models.SlugField("Slug", unique=True)
    is_role = models.BooleanField("Это роль (пилот/механик)", default=False)
    order = models.IntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Категория объявления"
        verbose_name_plural = "Категории объявлений"
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Ad(models.Model):
    """Универсальное объявление (ищу/предлагаю/куплю/продам)"""
    AD_TYPE_CHOICES = [
        ('looking', 'Ищу'),
        ('offering', 'Предлагаю'),
        ('buy', 'Куплю'),
        ('sell', 'Продам'),
    ]

    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Автор", related_name='ads')
    ad_type = models.CharField("Тип", max_length=20, choices=AD_TYPE_CHOICES, default='looking')
    category = models.ForeignKey(AdCategory, on_delete=models.SET_NULL, null=True, verbose_name="Категория")
    title = models.CharField("Заголовок", max_length=200)
    description = models.TextField("Описание")
    price = models.DecimalField("Цена", max_digits=10, decimal_places=2, null=True, blank=True)
    location = models.CharField("Местоположение", max_length=200, blank=True)
    contact_phone = models.CharField("Телефон", max_length=30, blank=True)
    contact_email = models.EmailField("Email", blank=True)
    contact_telegram = models.CharField("Telegram", max_length=100, blank=True)
    is_active = models.BooleanField("Активно", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    views_count = models.PositiveIntegerField("Просмотры", default=0)

    class Meta:
        verbose_name = "Объявление"
        verbose_name_plural = "Объявления"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_ad_type_display()}: {self.title}"

    def get_absolute_url(self):
        return f"/ads/{self.id}/"


class AdResponse(models.Model):
    """Отклик на объявление"""
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('accepted', 'Принят'),
        ('rejected', 'Отклонён'),
    ]

    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name='responses')
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Автор отклика", related_name='ad_responses')
    message = models.TextField("Сообщение")
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Отклик"
        verbose_name_plural = "Отклики"
        unique_together = ['ad', 'author']

    def __str__(self):
        return f"{self.author.email} -> {self.ad.title}"

class AdFavorite(models.Model):
    """Избранные объявления пользователя"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorite_ads')
    ad = models.ForeignKey('Ad', on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'ad']
        verbose_name = "Избранное объявление"
        verbose_name_plural = "Избранные объявления"

    def __str__(self):
        return f"{self.user.email} -> {self.ad.title}"


class PulseCache(models.Model):
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pulse Cache"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
