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

class EventPage(CoderedEventPage):
    class Meta:
        verbose_name = "Event Page"
    parent_page_types = ["website.EventIndexPage", "website.ChampionshipPage"]
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
    subpage_types = ["website.EventPage"]
    template = "coderedcms/pages/championship_page.html"

    # Только competition_type (year и champion_driver УДАЛЕНЫ)
     # для PostgreSQL

    TYPE_CHOICES = [
        ('cup', 'Кубок'),
        ('championship', 'Чемпионат'),
        ('competition', 'Первенство'),
    ]
    competition_types = models.ManyToManyField(
        'CompetitionType',
        verbose_name="Типы соревнований",
        blank=True,
        related_name='championships',
        help_text="Выберите один или несколько типов"
    )
    # Поле для отметки завершённости чемпионата
    is_completed = models.BooleanField(
        "Чемпионат завершён",
        default=False,
        help_text="Отметьте, если все этапы проведены"
    )

    # Обновляем content_panels - УБИРАЕМ year и champion_driver
    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('competition_types', widget=forms.CheckboxSelectMultiple),
        FieldPanel('is_completed'),
    ]

    def get_years(self):
        """
        Возвращает список годов, в которые проводились этапы чемпионата
        Учитывает годовые кубки (например, этапы в декабре и январе)
        """
        events = self.get_children().live().specific()
        years = set()

        for event in events:
            # Проверяем, есть ли у события поле occurrences
            if hasattr(event, 'occurrences'):
                for occurrence in event.occurrences.all():
                    # В CoderedEventOccurrence поле называется 'start', а не 'start_time'
                    if hasattr(occurrence, 'start') and occurrence.start:
                        years.add(occurrence.start.year)
                    # На всякий случай проверяем и другие возможные имена
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

        events = self.get_children().live().specific()

        # Фильтруем события по году, если нужно
        if year and not self.is_completed:
            # Оставляем только этапы, которые проходили в указанном году
            filtered_events = []
            for event in events:
                if hasattr(event, 'occurrences'):
                    for occurrence in event.occurrences.all():
                        if occurrence.start and occurrence.start.year == year:
                            filtered_events.append(event)
                            break
            events = filtered_events

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

        # Получаем ТОЛЬКО события ЭТОГО чемпионата (self)
        all_events = self.get_children().live().specific()

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

        # Получаем ID групп результатов ТОЛЬКО для этого чемпионата и выбранного класса
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
            standings[driver_id]['total'] += res.points - res.penalty  # вычитаем штраф
            standings[driver_id]['penalty_total'] += res.penalty       # копим штрафы
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

        # Получаем все чемпионаты
        championships = ChampionshipPage.objects.live().public().specific()

        # Получаем все доступные типы соревнований через ManyToMany
        types = set()
        for champ in championships:
            for comp_type in champ.competition_types.all():
                types.add(comp_type.name)
        types = list(types)

        # Получаем все доступные классы
        race_classes = RaceClass.objects.filter(
            raceclassresultgroup__isnull=False
        ).distinct().order_by('name')

        # Получаем все доступные годы из этапов
        all_years = set()
        for champ in championships:
            all_years.update(champ.get_years())
        all_years = sorted(list(all_years), reverse=True)

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
        context['available_years'] = all_years
        context['current_year'] = all_years[0] if all_years else None

        return context

class RatingInfoPage(CoderedWebPage):
    """
    Страница с информацией о расчёте рейтингов
    """
    class Meta:
        verbose_name = "Как считается рейтинг"
        verbose_name_plural = "Как считается рейтинг"

    parent_page_types = ["website.WebPage"]  # Можно создавать где угодно
    subpage_types = []  # Нельзя создавать дочерние
    template = "coderedcms/pages/rating_info_page.html"

    def get_context(self, request):
        context = super().get_context(request)

        # Получаем глобальную дату обновления (как на странице пилота)
        from .models import AnalyticsMetadata
        import zoneinfo

        try:
            last_update_utc = AnalyticsMetadata.objects.get(key='last_updated').value
            moscow_tz = zoneinfo.ZoneInfo('Europe/Moscow')
            context['last_update'] = last_update_utc.astimezone(moscow_tz)
        except AnalyticsMetadata.DoesNotExist:
            context['last_update'] = None

        # Получаем веса (если есть)
        from .models import Driver
        driver_with_weights = Driver.objects.exclude(context_weights={}).first()
        context['weights'] = driver_with_weights.context_weights if driver_with_weights else None

        return context
