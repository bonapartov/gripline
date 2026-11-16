"""Классы гонок, группы результатов и результаты."""

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

from .balance import ChassisTypePreset
from .equipment import Engine, Tyre
from .pages import EventPage
from .people import Driver, Team


class RaceClassQuerySet(models.QuerySet):
    def for_site(self):
        """Классы для публичного сайта — без «только для приложения» (13.10.2026)."""
        return self.filter(app_only=False)


@register_snippet
class RaceClass(models.Model):
    name = models.CharField("Название класса", max_length=255)
    app_only = models.BooleanField(
        "Только для приложения", default=False,
        help_text="Класс есть в приложении GripLine SetupKart, но не показывается на сайте (фильтры, рейтинги, "
                  "сравнения, /balance/). Например, X30 Junior/Senior — гонок с результатами в России нет.")

    objects = RaceClassQuerySet.as_manager()
    sort_order = models.PositiveIntegerField(
        "Порядок сортировки", default=0,
        help_text=(
            "Определяет место класса во всех фильтрах/вкладках по классам на сайте "
            "(вместо сортировки по алфавиту). Меньше значение — выше в списке."
        ),
    )
    app_chassis_image = models.ForeignKey(
        'website.AppChassisImage', null=True, blank=True, on_delete=models.SET_NULL, related_name='race_classes',
        verbose_name="Картинка шасси в приложении",
        help_text="Тип шасси, картинка которого показывается в приложении GripLine SetupKart для этого класса. "
                  "Пусто — встроенная схема. Картинки: «Техника» → «Картинки шасси».",
    )
    min_weight_kg = models.DecimalField(
        "Минимальный вес с пилотом, кг", max_digits=5, decimal_places=1, null=True, blank=True,
        help_text="По регламенту класса. Приложение GripLine SetupKart сверяет с ним вес по углам (развесовка) "
                  "и предупреждает о недоборе. Пусто — проверки нет. Доходит до приложения после «Публикации».")
    # Развесовка /balance/ (12.10.2026 — вместо отдельного справочника KartClass):
    # тип шасси ограничивает, к каким картам применим класс; геометрия — переопределение
    # пресета типа шасси (ChassisTypePreset).
    chassis_type = models.CharField(
        "Тип шасси (развесовка)", max_length=10, blank=True,
        choices=[("junior", "Детское"), ("senior", "Взрослое")],
        help_text="Для калькулятора развесовки на сайте: класс доступен только картам этого типа. "
                  "Пусто — любым картам.")
    wheelbase_mm = models.PositiveIntegerField(
        "Колёсная база, мм", null=True, blank=True,
        help_text="Развесовка: переопределение пресета типа шасси. Пусто — берётся пресет.")
    track_front_mm = models.PositiveIntegerField(
        "Колея перед, мм", null=True, blank=True,
        help_text="Развесовка: переопределение пресета типа шасси. Пусто — берётся пресет.")
    track_rear_mm = models.PositiveIntegerField(
        "Колея зад, мм", null=True, blank=True,
        help_text="Развесовка: переопределение пресета типа шасси. Пусто — берётся пресет.")

    panels = [
        FieldPanel('name'), FieldPanel('app_only'), FieldPanel('sort_order'), FieldPanel('app_chassis_image'), FieldPanel('min_weight_kg'),
        MultiFieldPanel([
            FieldPanel('chassis_type'),
            FieldRowPanel([FieldPanel('wheelbase_mm'), FieldPanel('track_front_mm'), FieldPanel('track_rear_mm')]),
        ], heading="Развесовка"),
    ]

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Класс гонки"
        verbose_name_plural = "Классы гонок"
        ordering = ['sort_order', 'name']

    @staticmethod
    def sort_key_map():
        """{название: sort_order} — для мест, где группировка уже идёт по
        строке названия класса (dict/list), а не по самому объекту RaceClass
        (агрегаты по пилоту/команде, где ключ — это имя класса, а не FK).
        Значение по умолчанию для .get() на незнакомое имя (например,
        текстовая заглушка "Без класса") задаёт вызывающая сторона."""
        return dict(RaceClass.objects.values_list('name', 'sort_order'))

    def effective_geometry(self):
        """Геометрия для развесовки: переопределение класса → пресет типа шасси →
        None (не заполнено). Без типа шасси пресет не подставляется."""
        preset = None
        if self.chassis_type:
            preset = ChassisTypePreset.objects.filter(chassis_type=self.chassis_type).first()
        return {
            "wheelbase_mm": self.wheelbase_mm or (preset.wheelbase_mm if preset else None),
            "track_front_mm": self.track_front_mm or (preset.track_front_mm if preset else None),
            "track_rear_mm": self.track_rear_mm or (preset.track_rear_mm if preset else None),
        }


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
        from website.services.race_results import with_classification_order
        return with_classification_order(self.class_results.all()).order_by('_unclassified', '-points', 'position')

    def lap_chart_race_numbers(self):
        """race_number'ы, для которых есть данные LapPosition (сессия final) —
        чтобы не рисовать кнопку «Ход гонки» там, где нечего показывать
        (см. lap_chart_api в website/views.py)."""
        driver_ids = self.lap_positions.filter(session_type='final').values_list('driver_id', flat=True)
        return set(
            self.class_results.filter(driver_id__in=driver_ids, race_number__isnull=False)
                               .exclude(race_number='')
                               .values_list('race_number', flat=True)
        )

    def get_forecast_weather(self):
        """Прогноз/оценка погоды на дату этапа — только пока архив (air_temperature
        и т.д.) ещё не заполнен. Вызывается из шаблона как group.get_forecast_weather."""
        from website.weather_utils import get_group_forecast_weather
        return get_group_forecast_weather(self)

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

    # --- Статусы схода/дисквалификации по сессиям ---
    # Пусто = финишировал штатно. points остаётся источником правды по очкам —
    # организатор может начислить очки за сошедшего в финале, если он набрал их
    # в квалификации/предфинале, поэтому статус не пересчитывает points сам.
    STATUS_CHOICES = [
        ('DNF', 'DNF — не финишировал'),
        ('DQ', 'DQ — дисквалифицирован'),
        ('DNS', 'DNS — не стартовал'),
    ]
    qual_status       = models.CharField("Статус квалификации", max_length=3, choices=STATUS_CHOICES, blank=True, default='')
    pre_final_status  = models.CharField("Статус предфинала", max_length=3, choices=STATUS_CHOICES, blank=True, default='')
    final_status      = models.CharField("Статус финала", max_length=3, choices=STATUS_CHOICES, blank=True, default='')

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
            FieldPanel('final_status'),
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
            FieldPanel('qual_status'),
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
            FieldPanel('pre_final_status'),
        ], heading="Предфинал"),
    ]

    @property
    def is_classified(self):
        return self.position > 0 and self.final_status not in ('DNS', 'DQ')

    @property
    def display_position(self):
        if self.is_classified:
            return str(self.position)
        return self.final_status or '—'

    @property
    def best_lap_all_ms(self):
        from website.services.race_results import best_session_lap
        return best_session_lap(self)[0]

    @property
    def best_lap_session(self):
        from website.services.race_results import best_session_lap
        return best_session_lap(self)[1]

    @property
    def ideal_lap_all_ms(self):
        """Сумма лучших секторов по всем сессиям — только если она быстрее лучшего круга.

        Не быстрее — значит, секторов не хватает: в протоколе секторы только лучшего круга
        (сумма = круг, 6 этап Rotax 2026) или у сессии с лучшим кругом секторов нет вовсе
        (идеальный получался медленнее лучшего). Такой «идеальный» не показываем.
        """
        from website.services.race_results import session_sectors
        sectors = list(session_sectors(self).values())
        s1, s2, s3 = ([s[k] for s in sectors if s[k] and s[k] > 0] for k in range(3))
        if not (s1 and s2 and s3):
            return None
        ideal = min(s1) + min(s2) + min(s3)
        best = self.best_lap_all_ms
        if best and ideal >= best:
            return None
        return ideal

    @property
    def ideal_lap_session(self):
        """Сессия, если все три сектора идеального круга взяты из неё же; иначе None (сектора вразнобой)."""
        from website.services.race_results import session_sectors
        sessions = session_sectors(self)
        s1, s2, s3 = ([s[k] for s in sessions.values() if s[k] and s[k] > 0] for k in range(3))
        if not (s1 and s2 and s3) or self.ideal_lap_all_ms is None:
            return None
        min_s1, min_s2, min_s3 = min(s1), min(s2), min(s3)
        for session, (a, b, c) in sessions.items():
            if a == min_s1 and b == min_s2 and c == min_s3:
                return session
        return None

    class Meta:
        verbose_name = "Результат"
        verbose_name_plural = "Результаты"
        ordering = ['position']


class LapPosition(models.Model):
    """Позиция пилота на трассе после конкретного круга (lap=0 — старт).

    Заполняется импортом lap_chart (website/import_utils.py) — отдельно от
    RaceResult, так как это N записей на пилота (по кругу), а не одна.
    Резолв пилота при импорте идёт по race_number из уже загруженного
    protocol той же группы, а не по имени."""

    SESSION_CHOICES = [
        ('pre_final', 'Предфинал'),
        ('final', 'Финал'),
    ]

    group = models.ForeignKey(
        RaceClassResultGroup,
        on_delete=models.CASCADE,
        related_name='lap_positions'
    )
    driver = models.ForeignKey(
        Driver,
        on_delete=models.CASCADE,
        related_name='lap_positions'
    )
    session_type = models.CharField(max_length=16, choices=SESSION_CHOICES)
    lap = models.PositiveSmallIntegerField("Круг (0 = старт)")
    position = models.PositiveSmallIntegerField("Позиция")

    class Meta:
        verbose_name = "Позиция по кругу"
        verbose_name_plural = "Позиции по кругам"
        unique_together = ('group', 'driver', 'session_type', 'lap')
        indexes = [
            models.Index(fields=['group', 'session_type']),
        ]


# ---------- ВСПОМОГАТЕЛЬНЫЕ МОДЕЛИ ----------
