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
from modelcluster.fields import ParentalKey
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from django.db import models
from modelcluster.models import ClusterableModel
from wagtail.api import APIField
from wagtail.snippets.models import register_snippet
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
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

# ---------- СТРАНИЦЫ (PAGES) ----------

class ArticlePage(CoderedArticlePage):
    class Meta:
        verbose_name = "Article"
        ordering = ["-first_published_at"]
    parent_page_types = ["website.ArticleIndexPage"]
    template = "coderedcms/pages/article_page.html"

class ArticleIndexPage(CoderedArticleIndexPage):
    class Meta:
        verbose_name = "Article Landing Page"
    index_query_pagemodel = "website.ArticlePage"
    subpage_types = ["website.ArticlePage"]
    template = "coderedcms/pages/article_index_page.html"

    def get_context(self, request):
        context = super().get_context(request)
        
        # Получаем все статьи
        articles = ArticlePage.objects.live().order_by('-date_display')
        
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
        
        # Получаем все термины, привязанные к живым статьям
        used_terms = ClassifierTerm.objects.filter(
            coderedpage__live=True,
            
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

    api_fields = [
        APIField('admin_title'),
    ]

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

    # Убираем competition_types как ManyToMany поле
    # Будем использовать отдельную модель через InlinePanel

    # Основные поля
    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('is_completed'),
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
  
      # Сортируем как надо
      class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                  'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters']
  
      available_classes = sorted(
          available_classes,
          key=lambda x: class_order.index(x.name) if x.name in class_order else 999
      )
  
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
        FieldPanel('page'),
        FieldPanel('race_class'),
        FieldPanel('tyre'),
        FieldPanel('engine'),
        FieldPanel('race_time'),
        FieldPanel('air_temperature'),
        FieldPanel('humidity'),
        FieldPanel('pressure'),
        FieldPanel('wind_speed'),
        FieldPanel('uv_index'),
        FieldPanel('precipitation'),
        InlinePanel('class_results', label="Пилоты этого класса"),
    ]

    def __str__(self):
        return f"{self.page.title} - {self.race_class.name} (ID: {self.id})"

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
    tie_breaker = models.FloatField(
        "Тай-брейк",
        default=0,
        help_text="Скрытые очки для разрешения равенства (не отображаются на сайте)"
    )
    # Поле для штрафов
    penalty = models.FloatField(
        "Штраф",
        default=0,
        help_text="Штрафные баллы (вычитаются из очков)"
    )

    panels = [
        FieldPanel('driver', widget=forms.Select(attrs={
            'class': 'driver-search-select',
            'data-search': 'true'
        })),
        FieldPanel('team'),
        FieldPanel('race_number'),
        FieldPanel('chassis_new'),
        FieldPanel('position'),
        FieldPanel('points'),
        FieldPanel('tie_breaker'),
        FieldPanel('penalty'),
    ]

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
    
        # Сортируем классы в нужном порядке
        class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                    'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters']
    
        sorted_classes = sorted(
            race_classes,
            key=lambda x: class_order.index(x.name) if x.name in class_order else 999
        )
    
        context['available_classes'] = sorted_classes
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
                                    months[month_key]['events_by_day'][day].append({
                                        'event': event,
                                        'start': occ.start,
                                        'end': occ.end,
                                    })

                            current_date += timedelta(days=1)

            # Сортируем месяцы по дате
            import operator
            months = dict(sorted(months.items(), key=operator.itemgetter(0)))

            # Отладка
            print(f"Календарь: {len(months)} месяцев")
            for month_key in months.keys():
                print(f"  {month_key}: {len(months[month_key]['events'])} событий")

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
        
        # 1. Сначала ищем StagePage, который идёт ПРЯМО СЕЙЧАС (start <= now <= end)
        current_stages = StagePage.objects.live().filter(
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
            upcoming_stages = StagePage.objects.live().filter(
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
        
        context['next_event'] = next_event

        # --- БЛОК 2: Последние новости ---
        context['latest_articles'] = ArticlePage.objects.live().filter(
            date_display__isnull=False
        ).order_by('-date_display')[:12]

        # --- БЛОК 3: Топ пилотов ---
        class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                       'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters']
        all_classes = list(RaceClass.objects.all())
        classes = sorted(all_classes,
                         key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

        selected_class_id = request.GET.get('class')
        if selected_class_id and selected_class_id.isdigit():
            selected_class_id = int(selected_class_id)
        else:
            selected_class_id = classes[0].id if classes else None

        top_drivers = []
        if selected_class_id:
            import json
            drivers = Driver.objects.exclude(ensemble_by_class={})
            for driver in drivers:
                # ensemble_by_class может быть строкой или dict
                ebc = driver.ensemble_by_class
                if isinstance(ebc, str):
                    try:
                        ebc = json.loads(ebc)
                    except:
                        ebc = {}
                ensemble_data = ebc.get(str(selected_class_id), {})
                if not ensemble_data:
                    continue
                results = RaceResult.objects.filter(
                    driver=driver, group__race_class_id=selected_class_id
                )
                race_count = results.count()
                win_count = results.filter(position=1).count()
                driver.rating_score = ensemble_data.get('score', 0)
                driver.race_count = race_count
                driver.win_count = win_count
                driver.win_percentage = round(win_count / race_count * 100, 1) if race_count > 0 else 0
                top_drivers.append(driver)

            top_drivers.sort(key=lambda x: x.rating_score, reverse=True)
            top_drivers = top_drivers[:5]

            if top_drivers:
                max_r = top_drivers[0].rating_score
                min_r = top_drivers[-1].rating_score
                rng = max_r - min_r if max_r > min_r else 1
                for i, d in enumerate(top_drivers, 1):
                    d.rank = i
                    d.normalized_rating = round((d.rating_score - min_r) / rng * 100, 1)

        context['top_drivers'] = top_drivers
        context['classes'] = classes
        context['selected_class_id'] = selected_class_id

        # --- БЛОК 4: Ближайшие события (календарь) ---
        upcoming_stages_raw = StagePage.objects.live().filter(
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

    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('start_date'),
        FieldPanel('end_date'),
        FieldPanel('track'),
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
                else:
                    context['my_applications'] = []

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
