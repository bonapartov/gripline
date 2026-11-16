"""Настройки и данные приложения SetupKart."""

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

from .dashboard import APP_ENGINE_FIELD_CHOICES, APP_PARAMETER_CHOICES
from .people import Driver


class AppValueSpec(models.Model):
    """Описание набора значений поля: диапазон (мин/макс/шаг) или явный список."""
    MODE_RANGE = 'range'
    MODE_LIST = 'list'

    label = models.CharField("Подпись", max_length=80, blank=True,
                             help_text="Пусто — стандартное название поля.")
    unit = models.CharField("Единица", max_length=20, blank=True)
    mode = models.CharField("Значения", max_length=5, default=MODE_RANGE,
                            choices=[(MODE_RANGE, 'Диапазон: минимум, максимум, шаг'), (MODE_LIST, 'Список')])
    min_value = models.DecimalField("Минимум", max_digits=9, decimal_places=3, null=True, blank=True)
    max_value = models.DecimalField("Максимум", max_digits=9, decimal_places=3, null=True, blank=True)
    step = models.DecimalField("Шаг", max_digits=9, decimal_places=3, null=True, blank=True,
                               help_text="Например 1, 0.25 или 0.5.")
    # Не «prefix»: так называется служебный атрибут Django-формы, Wagtail строит из него id инлайн-блока
    # (inline_child_{{ form.prefix }}) — поле с таким именем подменяет его и ломает разметку админки.
    value_prefix = models.CharField("Префикс", max_length=10, blank=True, help_text="Например K → K46, K47…")
    options_text = models.TextField("Список значений", blank=True, help_text="По одному значению в строке.")
    default_value = models.CharField("По умолчанию", max_length=40, blank=True)
    allow_custom = models.BooleanField("Можно своё значение («Другое…»)", default=True)

    panels = [
        FieldRowPanel([FieldPanel('label'), FieldPanel('unit')]),
        FieldPanel('mode'),
        FieldRowPanel([FieldPanel('min_value'), FieldPanel('max_value'), FieldPanel('step'), FieldPanel('value_prefix')]),
        FieldPanel('options_text'),
        FieldRowPanel([FieldPanel('default_value'), FieldPanel('allow_custom')]),
    ]

    class Meta:
        abstract = True

    def clean(self):
        from website.setupkart.spec import spec_errors
        errors = spec_errors(self)
        if errors:
            raise ValidationError(errors)


class AppEngineField(Orderable, AppValueSpec):
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_fields')
    key = models.CharField("Поле", max_length=30, choices=APP_ENGINE_FIELD_CHOICES)

    panels = [FieldPanel('key')] + AppValueSpec.panels

    class Meta(Orderable.Meta):
        verbose_name = "Поле карбюратора"
        verbose_name_plural = "Поля карбюратора"
        constraints = [models.UniqueConstraint(fields=['engine', 'key'], name='app_engine_field_unique_key')]

    def __str__(self):
        return f"{self.engine} · {self.get_key_display()}"


class AppEngineClassPreset(Orderable):
    """Рекомендация производителя по классу (11.10.2026, таблица Rotax: жиклёр, поплавок, воздушный винт,
    температура). В приложении — значение по умолчанию для сессии этого класса и подсказка у поля;
    пользователь может выбрать любое другое значение."""
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_class_presets')
    race_class = models.ForeignKey('website.RaceClass', on_delete=models.CASCADE, related_name='+',
                                   verbose_name="Класс")
    key = models.CharField("Поле", max_length=30, choices=APP_ENGINE_FIELD_CHOICES)
    value = models.CharField("Рекомендуемое значение", max_length=30, blank=True,
                             help_text="Как в списке поля (например, 115 или 1.75). Пусто — только диапазон, "
                                       "без подстановки.")
    range_from = models.CharField("Диапазон от", max_length=30, blank=True)
    range_to = models.CharField("Диапазон до", max_length=30, blank=True)

    panels = [FieldRowPanel([FieldPanel('race_class'), FieldPanel('key')]),
              FieldRowPanel([FieldPanel('value'), FieldPanel('range_from'), FieldPanel('range_to')])]

    class Meta(Orderable.Meta):
        verbose_name = "Рекомендация по классу"
        verbose_name_plural = "Рекомендации по классам"
        constraints = [models.UniqueConstraint(fields=['engine', 'race_class', 'key'],
                                               name='app_engine_class_preset_unique')]

    def __str__(self):
        return f"{self.engine} · {self.race_class} · {self.get_key_display()}"


class AppEngineJetBase(Orderable):
    """База для пересчёта жиклёра под погоду (12.10.2026, Rotax MAX Jetting): номер жиклёра класса при
    «RAD базы» двигателя. У Rotax две таблицы — текущая версия двигателя и прежняя (legacy)."""
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_jet_bases')
    race_class = models.ForeignKey('website.RaceClass', on_delete=models.CASCADE, related_name='+',
                                   verbose_name="Класс")
    base = models.PositiveSmallIntegerField("Жиклёр")
    base_legacy = models.PositiveSmallIntegerField("Жиклёр, старая версия", null=True, blank=True)

    panels = [FieldRowPanel([FieldPanel('race_class'), FieldPanel('base'), FieldPanel('base_legacy')])]

    class Meta(Orderable.Meta):
        verbose_name = "База жиклёра по классу"
        verbose_name_plural = "Базы жиклёра по классам"
        constraints = [models.UniqueConstraint(fields=['engine', 'race_class'], name='app_engine_jet_base_unique')]

    def __str__(self):
        return f"{self.engine} · {self.race_class} · {self.base}"


class AppEngineScrewModel(Orderable):
    """Винты High/Low мембранного карбюратора по погоде (13.10.2026, разбор «Jetting for IAME X30» 1.4.0 —
    только формула и коэффициенты). Строка — модификация двигателя с конкретным карбюратором
    (например, «X30 Senior · Tillotson HW-27»). Обороты винта = (плотность воздуха × поправка модели ×
    наклон) + смещение; давление открытия и длина выхлопа — от плотности воздуха."""
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_screw_models')
    name = models.CharField("Модификация и карбюратор", max_length=80)
    is_default = models.BooleanField("По умолчанию", default=False,
                                     help_text="Подставляется в сессию, пока пилот не выбрал свою модификацию.")
    model_factor = models.DecimalField("Поправка модели", max_digits=6, decimal_places=4, default=0.9581,
                                       help_text="Множитель плотности (при доле масла 4 %).")
    high_slope = models.DecimalField("High: наклон", max_digits=6, decimal_places=4, default=1.0881)
    high_offset = models.DecimalField("High: смещение, оборотов", max_digits=6, decimal_places=4, default=0)
    low_slope = models.DecimalField("Low: наклон", max_digits=6, decimal_places=4, default=1.0881)
    low_offset = models.DecimalField("Low: смещение, оборотов", max_digits=6, decimal_places=4, default=0)
    popoff_open_psi = models.DecimalField("Давление открытия, PSI", max_digits=5, decimal_places=2, default=10.8,
                                          help_text="При плотности 1,2 кг/м³ (+0,2); меняется на 70 % от изменения плотности.")
    popoff_close_psi = models.DecimalField("Давление закрытия, PSI", max_digits=5, decimal_places=2, default=8.5)
    exhaust_mm = models.DecimalField("Длина выхлопа, мм", max_digits=6, decimal_places=1, null=True, blank=True,
                                     help_text="Пусто — не показывать (выхлоп не регулируется).")
    exhaust_long_straight_mm = models.DecimalField(
        "Выхлоп на трассе с длинной прямой, мм", max_digits=5, decimal_places=1, default=-10,
        help_text="Поправка к длине выхлопа (обычно короче: −10 мм).")
    water_temp_c = models.DecimalField("Температура воды, °C", max_digits=4, decimal_places=1, null=True, blank=True)
    egt_min_c = models.PositiveSmallIntegerField("EGT от, °C", null=True, blank=True, default=593)
    egt_max_c = models.PositiveSmallIntegerField("EGT до, °C", null=True, blank=True, default=635)
    plug_gap_mm = models.DecimalField("Зазор свечи, мм", max_digits=4, decimal_places=2, null=True, blank=True,
                                      default=0.75)

    panels = [
        FieldRowPanel([FieldPanel('name'), FieldPanel('is_default')]),
        FieldRowPanel([FieldPanel('model_factor'), FieldPanel('high_slope'), FieldPanel('high_offset'),
                       FieldPanel('low_slope'), FieldPanel('low_offset')]),
        FieldRowPanel([FieldPanel('popoff_open_psi'), FieldPanel('popoff_close_psi'), FieldPanel('exhaust_mm'),
                       FieldPanel('exhaust_long_straight_mm')]),
        FieldRowPanel([FieldPanel('water_temp_c'), FieldPanel('egt_min_c'), FieldPanel('egt_max_c'),
                       FieldPanel('plug_gap_mm')]),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "Винты по погоде: модификация"
        verbose_name_plural = "Винты по погоде: модификации"

    def __str__(self):
        return f"{self.engine} · {self.name}"


class AppEngineFloatCarbModel(Orderable):
    """Поплавковый карбюратор по погоде (13.10.2026, разбор «Jetting Rotax Max EVO» 1.3.0 — только формула
    и коэффициенты): главный жиклёр, положение иглы и воздушный винт по плотности воздуха. Строка —
    модификация двигателя (например, «Senior EVO, цилиндр 2018+»)."""
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_float_models')
    name = models.CharField("Модификация", max_length=80)
    race_class = models.ForeignKey('website.RaceClass', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name="Класс",
                                   help_text="Подставляется для сессии этого класса. Пусто — только ручной выбор.")
    is_default = models.BooleanField("По умолчанию", default=False)
    jet_base = models.DecimalField("Жиклёр: база", max_digits=7, decimal_places=4, default=123.5,
                                   help_text="Жиклёр = база × (наклон × плотность + свободный член) × бензин × трасса.")
    jet_slope = models.DecimalField("Жиклёр: наклон", max_digits=14, decimal_places=12, default=0.335088816668)
    jet_intercept = models.DecimalField("Жиклёр: свободный член", max_digits=8, decimal_places=6, default=0.6117)
    jet_rounding = models.CharField("Номера жиклёров", max_length=10, default='dellorto',
                                    choices=[('dellorto', "Dell'Orto: 100, 102, 105, 108, 110…"),
                                             ('step1', 'Через 1 номер (85, 86, 87…)')])
    fuel95_factor = models.DecimalField("АИ-95: множитель жиклёра", max_digits=8, decimal_places=7, default=1.0015022)
    float_height_ref_mm = models.DecimalField("Высота поплавка: опорная, мм", max_digits=3, decimal_places=1,
                                              default=3.5, help_text="Поправка плотности +0,5875 % на мм выше опорной.")
    float_factor_fixed = models.DecimalField("Поправка поплавка: постоянная", max_digits=8, decimal_places=7,
                                             null=True, blank=True,
                                             help_text="Если задано — вместо поправки по высоте поплавка (ROK Mini: 1,0440625).")
    float_weight_g = models.DecimalField("Вес поплавка, г", max_digits=3, decimal_places=1, null=True, blank=True,
                                         help_text="Поправка плотности × (1,0956 − 0,0238 × вес). Пусто — без поправки.")
    air_screw_ladder = models.CharField(
        "Воздушный винт по игле", max_length=120, default="0.5:3; 1.75:2.75; 2.75:2.5; 3.75:2.25; 4.75:2; 1.75",
        help_text="«До позиции иглы : оборотов винта» через «;», последнее число — для остальных. "
                  "Добавка выше прибавляется.")
    spark_by_temp = models.CharField(
        "Свеча по температуре воздуха", max_length=200, blank=True,
        default="-2:NGK BR7EG; 10:NGK BR8EG; 25:NGK BR9EG; 30:NGK BR10EG; NGK BR11EG",
        help_text="«Ниже °C : свеча» через «;», последняя — для остальных.")
    extra_info = models.TextField("Справка", blank=True,
                                  help_text="Постоянные жиклёры и детали — показываются под расчётом.")
    needle_slope = models.DecimalField("Игла: наклон", max_digits=8, decimal_places=5, default=21.10694)
    needle_offset = models.DecimalField("Игла: смещение", max_digits=8, decimal_places=5, default=-21.64850)
    air_screw_bonus = models.DecimalField("Воздушный винт: добавка, оборотов", max_digits=4, decimal_places=2,
                                          default=0, help_text="Micro/Mini — +0,5 оборота.")
    float_height_mm = models.DecimalField("Высота поплавка по умолчанию, мм", max_digits=3, decimal_places=1,
                                          default=3.5)
    oil_pct = models.DecimalField("Масло в смеси по умолчанию, %", max_digits=3, decimal_places=1, default=2)
    water_temp_c = models.DecimalField("Температура воды, °C", max_digits=4, decimal_places=1, null=True, blank=True)
    plug_gap_mm = models.DecimalField("Зазор свечи, мм", max_digits=4, decimal_places=2, null=True, blank=True)
    spark_plug = models.CharField("Свеча", max_length=40, blank=True)
    gear_oil = models.CharField("Масло в редукторе", max_length=40, blank=True)

    panels = [
        FieldRowPanel([FieldPanel('name'), FieldPanel('race_class'), FieldPanel('is_default')]),
        FieldRowPanel([FieldPanel('jet_base'), FieldPanel('jet_slope'), FieldPanel('jet_intercept'),
                       FieldPanel('jet_rounding'), FieldPanel('fuel95_factor')]),
        FieldRowPanel([FieldPanel('needle_slope'), FieldPanel('needle_offset'), FieldPanel('air_screw_bonus')]),
        FieldPanel('air_screw_ladder'),
        FieldRowPanel([FieldPanel('float_height_mm'), FieldPanel('float_height_ref_mm'), FieldPanel('float_factor_fixed'),
                       FieldPanel('float_weight_g'), FieldPanel('oil_pct')]),
        FieldRowPanel([FieldPanel('spark_plug'), FieldPanel('plug_gap_mm'), FieldPanel('water_temp_c'),
                       FieldPanel('gear_oil')]),
        FieldPanel('spark_by_temp'),
        FieldPanel('extra_info'),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "Карбюратор по погоде: модификация"
        verbose_name_plural = "Карбюратор по погоде: модификации"

    def __str__(self):
        return f"{self.engine} · {self.name}"


VHSH_EMULSION_CHOICES = [('DP', 'DP'), ('DQ', 'DQ (номер на 2 меньше)')]
VHSH_IDLE_EMULSIFIER_CHOICES = [('B', 'B (B30…B100)'), ('CD', 'CD (CD1)')]


class AppEngineVhshVariant(Orderable):
    """Карбюратор Dell'Orto VHSH по погоде (13.10.2026, разбор «Jetting TM KZ» 1.4.0 — только формула и числа):
    модель двигателя (K9, KZ10, KZ R1…) — поправка ко всем каналам и значения по умолчанию. Расчёт — по
    «Настройкам VHSH» ниже, их показывает приложение для выбранной модели."""
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_vhsh_variants')
    name = models.CharField("Модель двигателя", max_length=60)
    race_class = models.ForeignKey('website.RaceClass', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name="Класс",
                                   help_text="Подставляется для сессии этого класса. Пусто — только ручной выбор.")
    is_default = models.BooleanField("По умолчанию", default=False)
    engine_factor = models.DecimalField("Поправка двигателя", max_digits=7, decimal_places=5, default=1,
                                        help_text="Множитель плотности для всех каналов (K9 0,9925 … KZ R1 1,0125).")
    float_height_mm = models.DecimalField("Высота поплавка по умолчанию, мм", max_digits=4, decimal_places=1, default=11)
    float_weight_g = models.DecimalField("Вес поплавка, г", max_digits=3, decimal_places=1, default=4.5,
                                         help_text="1 × 9 г — 4,5; 2 × 4 г — 4,0; 2 × 5,2 г — 5,2.")
    oil_pct = models.DecimalField("Масло в смеси по умолчанию, %", max_digits=3, decimal_places=1, default=4)
    emulsion_type = models.CharField("Эмульсионная трубка", max_length=2, choices=VHSH_EMULSION_CHOICES, default='DP')
    spark_by_temp = models.CharField(
        "Свеча по температуре воздуха", max_length=200, blank=True,
        default="-1:NGK BR9EG; 15:NGK BR10EG; NGK BR11EG",
        help_text="«Ниже °C : свеча» через «;», последняя — для остальных.")
    extra_info = models.TextField("Справка", blank=True, help_text="Показывается под расчётом.")

    panels = [
        FieldRowPanel([FieldPanel('name'), FieldPanel('race_class'), FieldPanel('is_default')]),
        FieldRowPanel([FieldPanel('engine_factor'), FieldPanel('emulsion_type'), FieldPanel('float_height_mm'),
                       FieldPanel('float_weight_g'), FieldPanel('oil_pct')]),
        FieldPanel('spark_by_temp'),
        FieldPanel('extra_info'),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "Карбюратор VHSH: модель двигателя"
        verbose_name_plural = "Карбюратор VHSH: модели двигателя"

    def __str__(self):
        return f"{self.engine} · {self.name}"


class AppEngineVhshSetup(Orderable):
    """Базовая настройка карбюратора Dell'Orto VHSH (в исходнике их 12): каждый канал — A × плотность + B,
    плотность с поправками на масло, поплавок, бензин, модель двигателя и трассу (docs/carb_vhsh_by_weather.md
    в репозитории приложения)."""
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_vhsh_setups')
    name = models.CharField("Настройка", max_length=60)
    jet_a = models.DecimalField("Жиклёр: A", max_digits=8, decimal_places=4)
    jet_b = models.DecimalField("Жиклёр: B", max_digits=8, decimal_places=4)
    needles = models.CharField("Иглы", max_length=60, help_text="Через запятую, например «K21, K28, K27».")
    needle_index = models.PositiveSmallIntegerField("Игла: номер в списке", default=2,
                                                    help_text="1 — первая. Положение клипсы сдвигается на ½: "
                                                              "первая игла +½, третья и дальше −½.")
    needle_clips = models.PositiveSmallIntegerField("Позиций клипсы", default=4)
    clip_a = models.DecimalField("Клипса: A", max_digits=8, decimal_places=4)
    clip_b = models.DecimalField("Клипса: B", max_digits=8, decimal_places=4)
    emulsion_a = models.DecimalField("Эмульсионная трубка: A", max_digits=8, decimal_places=4)
    emulsion_b = models.DecimalField("Эмульсионная трубка: B", max_digits=8, decimal_places=4)
    idle_emulsifier_type = models.CharField("Холостой эмульсор", max_length=2, choices=VHSH_IDLE_EMULSIFIER_CHOICES,
                                            default='B')
    idle_emulsifier_a = models.DecimalField("Холостой эмульсор: A", max_digits=8, decimal_places=4, default=0)
    idle_emulsifier_b = models.DecimalField("Холостой эмульсор: B", max_digits=8, decimal_places=4, default=1)
    idle_jet_a = models.DecimalField("Холостой жиклёр: A", max_digits=8, decimal_places=4, default=0)
    idle_jet_b = models.DecimalField("Холостой жиклёр: B", max_digits=8, decimal_places=4, default=60)
    idle_jet_min = models.DecimalField("Холостой жиклёр: не меньше", max_digits=5, decimal_places=1,
                                       null=True, blank=True)
    air_screw_turns = models.DecimalField("Воздушный винт, оборотов", max_digits=4, decimal_places=2, default=1.5)
    throttle_valve = models.PositiveSmallIntegerField("Золотник", default=50)

    panels = [
        FieldRowPanel([FieldPanel('name'), FieldPanel('jet_a'), FieldPanel('jet_b')]),
        FieldRowPanel([FieldPanel('needles'), FieldPanel('needle_index'), FieldPanel('needle_clips'),
                       FieldPanel('clip_a'), FieldPanel('clip_b')]),
        FieldRowPanel([FieldPanel('emulsion_a'), FieldPanel('emulsion_b'), FieldPanel('air_screw_turns'),
                       FieldPanel('throttle_valve')]),
        FieldRowPanel([FieldPanel('idle_emulsifier_type'), FieldPanel('idle_emulsifier_a'),
                       FieldPanel('idle_emulsifier_b'), FieldPanel('idle_jet_a'), FieldPanel('idle_jet_b'),
                       FieldPanel('idle_jet_min')]),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "Карбюратор VHSH: настройка"
        verbose_name_plural = "Карбюратор VHSH: настройки"

    def __str__(self):
        return f"{self.engine} · {self.name}"

    def needle_list(self):
        return [n.strip() for n in self.needles.split(',') if n.strip()]


class AppEngineSparkPlug(Orderable):
    engine = ParentalKey('website.Engine', on_delete=models.CASCADE, related_name='app_spark_plugs')
    name = models.CharField("Свеча", max_length=60)
    is_default = models.BooleanField("По умолчанию", default=False)

    panels = [FieldRowPanel([FieldPanel('name'), FieldPanel('is_default')])]

    class Meta(Orderable.Meta):
        verbose_name = "Свеча"
        verbose_name_plural = "Свечи"

    def __str__(self):
        return self.name


APP_TYRE_KIND_CHOICES = [
    ('slick', 'Слик'),
    ('wet', 'Дождь'),
]


class AppTyreCompound(Orderable):
    """Состав шины марки для приложения (мягкая, средняя, жёсткая, дождь…) — плитка с фото.
    Тип (слик/дождь) задаётся у состава: выбор состава в приложении ставит и тип."""
    brand = ParentalKey('website.TyreBrand', on_delete=models.CASCADE, related_name='app_compounds')
    name = models.CharField("Название", max_length=40, help_text="Как подписать плитку: «Мягкая», «Средняя», «Дождь»…")
    kind = models.CharField("Тип", max_length=20, choices=APP_TYRE_KIND_CHOICES, default='slick')
    image = models.ForeignKey('wagtailimages.Image', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='+', verbose_name="Фото")

    target_temp_c = models.PositiveSmallIntegerField(
        "Рабочая температура, °C", null=True, blank=True, validators=[MinValueValidator(30), MaxValueValidator(120)],
        help_text="Температура протектора, при которой состав работает лучше всего. В приложении — подсказка "
                  "для анализа шин. Пусто — 80 °C.")

    panels = [FieldRowPanel([FieldPanel('name'), FieldPanel('kind'), FieldPanel('target_temp_c')]), FieldPanel('image')]

    class Meta(Orderable.Meta):
        verbose_name = "Состав шины (приложение)"
        verbose_name_plural = "Составы шин (приложение)"

    def __str__(self):
        return f"{self.brand} · {self.name}"


class AppParameter(AppValueSpec):
    key = models.CharField("Параметр", max_length=30, choices=APP_PARAMETER_CHOICES, unique=True)

    panels = [FieldPanel('key')] + AppValueSpec.panels

    class Meta:
        verbose_name = "Параметр приложения"
        verbose_name_plural = "Параметры приложения"
        ordering = ['key']

    def __str__(self):
        return self.get_key_display()


class AppChassisImage(models.Model):
    """Картинка шасси для приложения на тип шасси (детское, мини, взрослое, KZ…): подложка под схемой
    давления, колеи и развала. Классы гонок ссылаются на тип (RaceClass.app_chassis_image); классу со своей
    картинкой — свой тип. Положение левых колёс — доли ширины/высоты картинки (0…1), правые — зеркально."""
    name = models.CharField("Тип шасси", max_length=60, unique=True, help_text="Например: «Взрослое», «Детское малое».")
    image = models.ForeignKey('wagtailimages.Image', null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+', verbose_name="Картинка")
    front_x = models.FloatField("Левое переднее колесо, x", null=True, blank=True)
    front_y = models.FloatField("Левое переднее колесо, y", null=True, blank=True)
    rear_x = models.FloatField("Левое заднее колесо, x", null=True, blank=True)
    rear_y = models.FloatField("Левое заднее колесо, y", null=True, blank=True)
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        verbose_name = "Картинка шасси (приложение)"
        verbose_name_plural = "Картинки шасси (приложение)"
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @property
    def calibrated(self):
        return None not in (self.front_x, self.front_y, self.rear_x, self.rear_y)

    @property
    def ready(self):
        """Можно отдавать в приложение: есть картинка и отмечены колёса."""
        return self.image_id is not None and self.calibrated


APP_HELP_IMAGE_CHOICES = [
    ('steering_column_hole', 'Рулевая колонка: отверстия'),
    # Слева от выбора 1–5 в разделе карбюратора (Rotax, Vortex, TM) — для всех двигателей с этим полем.
    ('needle_position', 'Карбюратор: положение иглы'),
]


class AppHelpImage(models.Model):
    """Картинка-подсказка к полю сетапа в приложении (например, номера отверстий рулевой колонки).
    Приложение показывает её рядом с полем; нет картинки — поле без подсказки."""
    key = models.CharField("Поле", max_length=40, choices=APP_HELP_IMAGE_CHOICES, unique=True)
    image = models.ForeignKey('wagtailimages.Image', on_delete=models.CASCADE, related_name='+', verbose_name="Картинка")
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    panels = [FieldPanel('key'), FieldPanel('image')]

    class Meta:
        verbose_name = "Картинка-подсказка (приложение)"
        verbose_name_plural = "Картинки-подсказки (приложение)"
        ordering = ['key']

    def __str__(self):
        return self.get_key_display()


APP_ABOUT_TEXT_DEFAULT = (
    "GripLine SetupKart сделали в Gripline — проекте о российском картинге. На gripline.ru собраны "
    "результаты соревнований, рейтинги пилотов и шасси, календарь этапов и статьи о настройке карта.\n\n"
    "Приложение — для механиков и пилотов: быстро записать настройку прямо на трассе, сравнить с прошлыми "
    "сессиями и не потерять то, что сработало. Есть идея или нашли ошибку — напишите нам."
)

APP_SHARE_TEXT_DEFAULT = "Веду настройки карта в приложении GripLine SetupKart — попробуй: {link}"


class AppTyreAnalysisSettings(models.Model):
    """Пороги анализа шин в приложении (singleton, AppTyreAnalysisSettings.get(); 12.10.2026). Начальные
    значения — из разбора Kart Chassis Setup Pro (docs/chassis_analysis_rules.md в репозитории приложения).
    В приложение — после «Публикации»."""
    D = models.DecimalField
    hot_pct = D("Порог «горячее», %", max_digits=4, decimal_places=1, default=8,
                help_text="Насколько одна зона протектора должна быть горячее другой, чтобы это считалось "
                          "картиной (середина горячее краёв, внутренний край горячее и т. п.).")
    camber_weak_pct = D("Камбер: слабо, %", max_digits=4, decimal_places=1, default=4,
                        help_text="Разница внутреннего и наружного края обеих передних шин.")
    camber_medium_pct = D("Камбер: средне, %", max_digits=4, decimal_places=1, default=8)
    camber_strong_pct = D("Камбер: сильно, %", max_digits=4, decimal_places=1, default=16)
    balance_pct = D("Баланс перед/зад, %", max_digits=4, decimal_places=1, default=10,
                    help_text="Перед горячее зада (или давление выше) больше чем на столько — совет сдвинуть "
                              "сиденье или балласт.")
    temp_spread_limit = D("Разброс температур: порог", max_digits=4, decimal_places=2, default=1.4,
                          help_text="Среднее (|отклонение от средней| / средняя + 1)⁴ по колёсам; больше — "
                                    "«проверить развесовку на весах».")
    pressure_tolerance_pct = D("Давление: допуск роста, п. п.", max_digits=4, decimal_places=1, default=5,
                               help_text="Фактический рост давления отличается от ожидаемого меньше — правка "
                                         "не нужна.")
    pressure_correction = D("Давление: доля поправки", max_digits=4, decimal_places=3, default=0.375,
                            help_text="Поправка холодного давления = (ожидаемый рост − фактический) × доля × "
                                      "холодное.")
    min_cold_bar = D("Минимальное холодное давление, бар", max_digits=4, decimal_places=2, default=0.48)
    rise_aluminium_pct = D("Рост давления на °C: алюминиевые диски, %", max_digits=5, decimal_places=3, default=0.4)
    rise_magnesium_pct = D("Рост давления на °C: магниевые диски, %", max_digits=5, decimal_places=3, default=0.333)
    pressure_spread_limit = D("Разброс роста давления: порог", max_digits=4, decimal_places=2, default=1.3)
    temp_dir_front = D("Направление: перед внешней стороны (температура)", max_digits=4, decimal_places=3,
                       default=0.97, help_text="Множитель колёс внешней к повороту стороны: они греются сильнее.")
    temp_dir_rear = D("Направление: зад внешней стороны (температура)", max_digits=4, decimal_places=3, default=0.94)
    temp_dir_rear_inner = D("Направление: зад внутренней стороны (температура)", max_digits=4, decimal_places=3,
                            default=0.97)
    pressure_dir_front = D("Направление: перед внешней стороны (давление)", max_digits=4, decimal_places=3, default=0.9)
    pressure_dir_rear = D("Направление: зад внешней стороны (давление)", max_digits=4, decimal_places=3,
                          default=0.76)
    pressure_dir_rear_inner = D("Направление: зад внутренней стороны (давление)", max_digits=4, decimal_places=3,
                                default=0.95)
    updated_at = models.DateTimeField("Изменено", auto_now=True)
    del D

    panels = [
        MultiFieldPanel([FieldPanel('hot_pct'),
                         FieldRowPanel([FieldPanel('camber_weak_pct'), FieldPanel('camber_medium_pct'),
                                        FieldPanel('camber_strong_pct')]),
                         FieldPanel('balance_pct'), FieldPanel('temp_spread_limit')], heading="Температура протектора"),
        MultiFieldPanel([FieldRowPanel([FieldPanel('rise_aluminium_pct'), FieldPanel('rise_magnesium_pct')]),
                         FieldPanel('pressure_tolerance_pct'), FieldPanel('pressure_correction'),
                         FieldPanel('min_cold_bar'), FieldPanel('pressure_spread_limit')], heading="Давление"),
        MultiFieldPanel([FieldRowPanel([FieldPanel('temp_dir_front'), FieldPanel('temp_dir_rear'),
                                        FieldPanel('temp_dir_rear_inner')]),
                         FieldRowPanel([FieldPanel('pressure_dir_front'), FieldPanel('pressure_dir_rear'),
                                        FieldPanel('pressure_dir_rear_inner')])],
                        heading="Поправка на направление трассы"),
    ]

    class Meta:
        verbose_name = "Анализ шин (пороги)"
        verbose_name_plural = "Анализ шин (пороги)"

    def __str__(self):
        return "Пороги анализа шин"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def payload(self):
        f = lambda v: float(v)  # noqa: E731
        return {
            'hot_ratio': 1 + f(self.hot_pct) / 100,
            'camber_ratios': [1 + f(self.camber_weak_pct) / 100, 1 + f(self.camber_medium_pct) / 100,
                              1 + f(self.camber_strong_pct) / 100],
            'balance_ratio': 1 + f(self.balance_pct) / 100,
            'temp_spread_limit': f(self.temp_spread_limit),
            'pressure_tolerance': f(self.pressure_tolerance_pct) / 100,
            'pressure_correction': f(self.pressure_correction),
            'min_cold_bar': f(self.min_cold_bar),
            'rise_aluminium': f(self.rise_aluminium_pct) / 100,
            'rise_magnesium': f(self.rise_magnesium_pct) / 100,
            'pressure_spread_limit': f(self.pressure_spread_limit),
            'temp_direction': [f(self.temp_dir_front), f(self.temp_dir_rear), f(self.temp_dir_rear_inner)],
            'pressure_direction': [f(self.pressure_dir_front), f(self.pressure_dir_rear),
                                   f(self.pressure_dir_rear_inner)],
        }


class AppSyncSettings(models.Model):
    """Связь приложения GripLine SetupKart с сайтом (singleton, AppSyncSettings.get()).

    Приложение спрашивает интервал при каждой связи (GET /api/setupkart/config/) и, пока открыто,
    раз в этот интервал загружает справочник и трассы и отправляет очереди (предложения, обратная
    связь). Фоновой работы при закрытом приложении нет."""
    sync_interval_minutes = models.PositiveIntegerField(
        "Интервал связи приложения с сайтом, мин.", default=60,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
        help_text="Как часто открытое приложение проверяет справочник и трассы и отправляет предложения "
                  "и обратную связь. Для проверки — 1–5 минут, в работе — 60 и больше. Новое значение "
                  "приложение узнает при следующей связи.",
    )
    site_url = models.URLField("Сайт", default="https://gripline.ru",
                               help_text="Ссылка в «О приложении».")
    contact_email = models.EmailField("E-mail для связи", blank=True, default="gripline.ru@yandex.ru")
    contact_telegram = models.CharField(
        "Telegram для связи", max_length=64, blank=True, default="@gripline_support",
        help_text="@имя или ссылка t.me/…; пусто — строка в приложении не показывается.")
    about_text = models.TextField(
        "Текст «О нас»", blank=True, default=APP_ABOUT_TEXT_DEFAULT,
        help_text="Показывается в приложении внизу экрана «О приложении», под логотипом Gripline.")
    share_text = models.TextField(
        "Текст «Рекомендовать приложение»", blank=True, default=APP_SHARE_TEXT_DEFAULT,
        help_text="Уходит через стандартное меню «Поделиться». {link} — место для ссылки; "
                  "без {link} ссылка добавляется в конце.")
    share_url = models.URLField(
        "Ссылка «Рекомендовать приложение»", default="https://gripline.ru",
        help_text="Куда ведёт рекомендация: страница приложения, Google Play, RuStore и т. п.")
    splash_image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        verbose_name="Фото при запуске",
        help_text="На весь экран, пока приложение загружается. Вертикальное (например 1080×1920), главное — "
                  "по центру: края обрезаются под экран телефона. Новое фото появится со следующего запуска "
                  "после связи с сайтом. Пусто — тёмный экран.")
    splash_seconds = models.DecimalField(
        "Сколько показывать фото, секунд", max_digits=3, decimal_places=1, default=2,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Не меньше этого времени (если приложение загрузилось раньше); нажатие на фото закрывает его "
                  "сразу. 0 — только пока приложение загружается.")
    privacy_notice_date = models.DateField(
        "Политика изменена", null=True, blank=True,
        help_text="Дата новой редакции политики конфиденциальности приложения. Приложение один раз покажет "
                  "уведомление с текстом ниже и ссылкой на политику (п. 9.1 политики: при новых случаях передачи "
                  "данных по сети). Новая дата — уведомление покажется снова.")
    privacy_notice = models.TextField(
        "Текст уведомления", blank=True,
        help_text="Коротко, что изменилось. Пусто — уведомление не показывается.")
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    panels = [
        FieldPanel('sync_interval_minutes'),
        MultiFieldPanel([FieldPanel('about_text'), FieldPanel('site_url'), FieldPanel('contact_email'),
                         FieldPanel('contact_telegram')],
                        heading="«О приложении» — сайт и контакты",
                        help_text="Приложение получает изменения при следующей связи с сайтом, без новой версии."),
        MultiFieldPanel([FieldPanel('share_text'), FieldPanel('share_url')],
                        heading="«Рекомендовать приложение»",
                        help_text="Пункт меню в приложении; изменения доходят при следующей связи с сайтом."),
        FieldRowPanel([FieldPanel('splash_image'), FieldPanel('splash_seconds')]),
        MultiFieldPanel([FieldPanel('privacy_notice_date'), FieldPanel('privacy_notice')],
                        heading="Уведомление об изменении политики конфиденциальности"),
    ]

    def privacy_notice_payload(self):
        """{date, text, url} или None — приложение показывает уведомление один раз на каждую дату."""
        text = (self.privacy_notice or '').strip()
        if not self.privacy_notice_date or not text:
            return None
        from django.conf import settings
        return {'date': self.privacy_notice_date.isoformat(), 'text': text,
                'url': f"{settings.BASE_URL.rstrip('/')}/legal/setupkart-privacy/"}

    def splash_payload(self):
        """{url, width, height} или None. URL меняется вместе с файлом — по нему приложение видит новое фото."""
        if not self.splash_image:
            return None
        from django.conf import settings
        r = self.splash_image.get_rendition('max-1440x3200|format-webp|webpquality-85')
        return {'url': f"{settings.BASE_URL.rstrip('/')}{r.url}", 'width': r.width, 'height': r.height}

    def share_message(self):
        text = (self.share_text or '').strip()
        if '{link}' in text:
            return text.replace('{link}', self.share_url)
        return f"{text} {self.share_url}".strip()

    def telegram_url(self):
        t = (self.contact_telegram or '').strip()
        if not t:
            return ''
        if t.startswith('http'):
            return t
        return 'https://t.me/' + t.lstrip('@').removeprefix('t.me/')

    def about_payload(self):
        return {
            'text': self.about_text.strip(),
            'site_url': self.site_url,
            'email': self.contact_email,
            'telegram': self.contact_telegram.strip(),
            'telegram_url': self.telegram_url(),
        }

    class Meta:
        verbose_name = "Связь приложения с сайтом"
        verbose_name_plural = "Связь приложения с сайтом"

    def __str__(self):
        return f"Связь приложения: раз в {self.sync_interval_minutes} мин."

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# Функции приложения для разграничения бесплатной и Pro-версии (решение 10.10.2026). Список задаётся
# здесь — новая функция появляется только с новой версией приложения; в админке выбирается «Бесплатно»/«Pro»
# и лимиты. (ключ, название, вид: 'limit' — лимит для бесплатной версии, 'toggle' — Бесплатно/Pro, умолчание)
APP_PRO_FEATURES = [
    ('saved_sessions', 'Сохранённые сессии', 'limit', 10),
    ('karts', 'Карты', 'limit', 1),
    ('engines', 'Двигатели', 'limit', 1),
    ('compare', 'Сравнение сетапов', 'toggle', 'pro'),
    ('engine_service', 'Моточасы и интервалы ТО', 'toggle', 'pro'),
    ('track_records', 'Рекорды трасс с сайта', 'toggle', 'pro'),
    ('laps_analysis', 'Анализ кругов (статистика и график)', 'toggle', 'pro'),
    ('dictation', 'Диктовка заметок', 'toggle', 'pro'),
    ('balance_diagnosis', 'Диагностика развесовки', 'toggle', 'pro'),
    ('stopwatch', 'Секундомер', 'toggle', 'free'),
    ('quick_change', 'Быстрая правка', 'toggle', 'free'),
    ('share_setup', 'Обмен сетапами (.gripsetup)', 'toggle', 'free'),
    ('weather', 'Погода', 'toggle', 'free'),
    # 11.10.2026 — новые поля шасси и плотность воздуха
    ('toe', 'Схождение', 'toggle', 'free'),
    ('seat_struts', 'Распорки сиденья', 'toggle', 'free'),
    ('torsion_bars', 'Торсионные стабилизаторы', 'toggle', 'free'),
    ('seat_position', 'Положение сиденья', 'toggle', 'free'),
    ('grip_level', 'Уровень зацепа трассы', 'toggle', 'free'),
    ('air_density', 'Плотность воздуха (RAD) по погоде', 'toggle', 'pro'),
    ('chassis_advice', 'Советы по поведению карта', 'toggle', 'pro'),
    ('tyre_analysis', 'Анализ шин (температуры и давление)', 'toggle', 'pro'),
    ('cloud_sync', 'Копия сессий на сайте и синхронизация', 'toggle', 'free'),
    # 18.10.2026 — подбор сетапа из своих прошлых сессий по трассе, классу и погоде
    ('smart_setup', 'Smart Setup — подбор сетапа по прошлым сессиям', 'toggle', 'pro'),
]
APP_PRO_FEATURE_KINDS = {k: kind for k, _, kind, _ in APP_PRO_FEATURES}


# ───── Советы по поведению карта (приложение, 12.10.2026; логика — по разбору Kart Chassis Setup Pro) ─────
# Что менять в приложении по кнопке «Применить»: код → (подпись, поля профиля приложения). Пары лево/право
# и «перед и зад» меняются вместе. Ключи полей — из встроенного профиля приложения (assets/profiles/common.json).
APP_ADVICE_TARGETS = {
    'track_width_front_cm': ('Колея передняя', ['track_width_front_cm']),
    'track_width_rear_cm': ('Колея задняя', ['track_width_rear_cm']),
    'torsion_front': ('Передний стабилизатор', ['torsion_front']),
    'torsion_rear': ('Задний стабилизатор', ['torsion_rear']),
    'front_bumper': ('Передний бампер', ['front_bumper']),
    'sidepods': ('Крепления понтонов', ['sidepods']),
    'toe_mm': ('Схождение (− развал)', ['toe_mm']),
    'camber': ('Камбер (оба)', ['camber_left', 'camber_right']),
    'caster': ('Кастер (оба)', ['caster_left', 'caster_right']),
    'ackermann': ('Аккерман', ['ackermann']),
    'front_height': ('Высота передней оси', ['front_height']),
    'rear_axle_height': ('Высота задней оси', ['rear_axle_height']),
    'heights': ('Высота передней и задней оси', ['front_height', 'rear_axle_height']),
    'seat_shift_mm': ('Сиденье: сдвиг назад', ['seat_shift_mm']),
    'seat_raise_mm': ('Сиденье: подъём', ['seat_raise_mm']),
    'hub_width_mm': ('Задние ступицы (ширина)', ['hub_width_mm']),
    'front_hub_length_mm': ('Передние ступицы (длина)', ['front_hub_length_mm']),
    'rear_axle_stiffness': ('Жёсткость задней оси', ['rear_axle_stiffness']),
    'seat_struts': ('Распорки сиденья (обе)', ['seat_strut_left', 'seat_strut_right']),
    'rain_meister': ('Rainmeister', ['rain_meister']),
}
APP_ADVICE_TARGET_CHOICES = [('', '— только совет —')] + [(k, v[0]) for k, v in APP_ADVICE_TARGETS.items()]
APP_ADVICE_ACTION_CHOICES = [
    ('', '— без кнопки —'),
    ('inc', 'На шаг больше (следующий вариант списка)'),
    ('dec', 'На шаг меньше (предыдущий вариант списка)'),
    ('set', 'Установить значение'),
]
APP_HANDLING_SYMPTOMS = [
    ('understeer', 'Недостаточная поворачиваемость'),
    ('oversteer', 'Избыточная поворачиваемость'),
    ('hopping', 'Прыжки / сильный отскок одного колеса'),
    ('lifting', 'Отрыв обоих внутренних колёс'),
    ('drift', 'Скольжение всеми колёсами'),
]
APP_HANDLING_PHASES = [('any', 'Любая фаза'), ('entry', 'Вход в поворот'), ('middle', 'Середина поворота'),
                       ('exit', 'Выход из поворота')]
APP_ADVICE_LEVELS = [('strong', 'Сильно'), ('medium', 'Средне'), ('weak', 'Слабо')]
APP_ADVICE_GROUPS = [
    ('jacking_up', 'Больше подъёма внутреннего заднего колеса'),
    ('jacking_down', 'Меньше подъёма внутреннего заднего колеса'),
    ('front_grip_up', 'Больше сцепления спереди'),
    ('front_grip_down', 'Меньше сцепления спереди'),
    ('rear_grip_up', 'Больше сцепления сзади'),
    ('rear_grip_down', 'Меньше сцепления сзади'),
    ('driving', 'Стиль пилотирования'),
    ('other', 'Другое'),
]
APP_ADVICE_BALLAST = [
    ('any', 'Любой'), ('none', 'Без балласта'), ('low', 'Мало (< 4 % веса пилота)'),
    ('normal', 'Норма (4–12 %)'), ('high', 'Много (> 12 %)'), ('low_normal', 'Мало или норма'),
]
APP_ADVICE_WEATHER = [('any', 'Любая'), ('dry', 'Сухо'), ('wet', 'Дождь / мокро')]
APP_ADVICE_GRIP = [('any', 'Любой'), ('low', 'Низкий (первый вариант списка)'), ('normal', 'Средний'),
                   ('high', 'Высокий (последний вариант списка)')]


class AppChassisAdvice(ClusterableModel):
    """Совет по шасси для раздела «Поведение карта» в приложении: что сделать, почему и (необязательно) какое
    поле сессии поменять по кнопке «Применить». Когда показывать — правила ниже (симптом, фаза, сила)."""
    code = models.SlugField("Код", max_length=40, unique=True,
                            help_text="Латиницей, не меняется после публикации (по нему приложение узнаёт совет).")
    title = models.CharField("Что сделать", max_length=120)
    text = models.TextField("Почему", blank=True, help_text="Короткое объяснение для пилота.")
    image = models.ForeignKey('wagtailimages.Image', null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+', verbose_name="Картинка")
    target = models.CharField("Поле в приложении", max_length=40, blank=True, choices=APP_ADVICE_TARGET_CHOICES)
    action = models.CharField("Кнопка «Применить»", max_length=10, blank=True, choices=APP_ADVICE_ACTION_CHOICES,
                              help_text="«На шаг» — следующий/предыдущий вариант списка или шаг числа. "
                                        "Значение — для «Установить» (как в списке поля, например loose или Нет).")
    value = models.CharField("Значение", max_length=30, blank=True)
    sort_order = models.PositiveIntegerField("Порядок", default=0)

    panels = [
        FieldPanel('code'), FieldPanel('title'), FieldPanel('text'), FieldPanel('image'),
        FieldRowPanel([FieldPanel('target'), FieldPanel('action'), FieldPanel('value')]),
        FieldPanel('sort_order'),
        InlinePanel('rules', label="Когда советовать",
                    help_text="Симптом и фаза поворота, которые отметил пилот; сила — насколько регулировка "
                              "меняет поведение (в приложении советы идут от сильных к слабым)."),
    ]

    class Meta:
        verbose_name = "Совет по шасси"
        verbose_name_plural = "Советы по шасси"
        ordering = ['sort_order', 'title']

    def __str__(self):
        return self.title

    def clean(self):
        if self.action and not self.target:
            raise ValidationError({'target': "Для кнопки «Применить» выберите поле."})
        if self.action == 'set' and not self.value.strip():
            raise ValidationError({'value': "Укажите значение для «Установить»."})

    def payload_fields(self):
        return APP_ADVICE_TARGETS.get(self.target, ('', []))[1]


class AppChassisRule(Orderable):
    advice = ParentalKey(AppChassisAdvice, on_delete=models.CASCADE, related_name='rules')
    symptom = models.CharField("Симптом", max_length=20, choices=APP_HANDLING_SYMPTOMS)
    phase = models.CharField("Фаза", max_length=10, choices=APP_HANDLING_PHASES, default='any')
    level = models.CharField("Сила", max_length=10, choices=APP_ADVICE_LEVELS, default='medium')
    group = models.CharField("Эффект", max_length=20, choices=APP_ADVICE_GROUPS, default='other')
    ballast = models.CharField("Балласт", max_length=12, choices=APP_ADVICE_BALLAST, default='any')
    weather = models.CharField("Погода", max_length=5, choices=APP_ADVICE_WEATHER, default='any')
    grip = models.CharField("Зацеп трассы", max_length=6, choices=APP_ADVICE_GRIP, default='any')

    panels = [FieldRowPanel([FieldPanel('symptom'), FieldPanel('phase'), FieldPanel('level')]),
              FieldRowPanel([FieldPanel('group'), FieldPanel('ballast'), FieldPanel('weather'), FieldPanel('grip')])]

    class Meta(Orderable.Meta):
        verbose_name = "Правило"
        verbose_name_plural = "Правила"


class AppProSettings(ClusterableModel):
    """Pro-версия приложения GripLine SetupKart (singleton, AppProSettings.get()). Пока платная версия
    выключена, в приложении всё доступно всем. Оплата (RuStore) — следующий этап."""
    enabled = models.BooleanField(
        "Платная версия включена", default=False,
        help_text="Выключено — в приложении всё бесплатно у всех. Включено — действуют пробный период и "
                  "разграничение ниже.")
    trial_days = models.PositiveIntegerField(
        "Пробный период, дней", default=30, validators=[MaxValueValidator(365)],
        help_text="С первого запуска приложения всё доступно, как в Pro. 0 — без пробного периода.")
    price_text = models.CharField("Цена (для показа)", max_length=40, blank=True, help_text="Например «990 ₽».")
    purchase_url = models.URLField(
        "Ссылка на покупку", blank=True,
        help_text="Временная — пока нет оплаты в приложении (например, страница в RuStore). Пусто — кнопка "
                  "«Купить» показывает «скоро».")
    description = models.TextField(
        "Текст на экране «Pro-версия»", blank=True,
        default="Одна покупка — навсегда, без подписки. Все ваши сетапы остаются доступны в любой версии.")
    offline_grace_days = models.PositiveIntegerField(
        "Пробный период без связи с сайтом, дней", default=7, validators=[MaxValueValidator(365)],
        help_text="Пробный период считается по телефону, только пока его не подтвердил сайт: без связи он "
                  "закончится через столько дней после первого запуска (иначе переустановка в режиме полёта "
                  "давала бы новый пробный период). После связи с сайтом срок берётся с сайта. 0 — без "
                  "ограничения.")
    trial_retention_months = models.PositiveIntegerField(
        "Хранить записи пробного периода, месяцев", default=24, validators=[MinValueValidator(1)],
        help_text="Запись устройства («Устройства пробного периода») удаляется, если оно столько не выходило на "
                  "связь (политика конфиденциальности приложения, п. 7.2 — при изменении срока поправьте и её). Очистка — ежедневно "
                  "(команда setupkart_trial_cleanup).")
    enabled_at = models.DateTimeField(
        "Платная версия впервые включена", null=True, blank=True, editable=False,
        help_text="Пробный период начинается не раньше этой даты — у тех, кто поставил приложение, пока всё "
                  "было бесплатно, он не заканчивается в момент включения.")
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    panels = [
        FieldPanel('enabled'),
        FieldRowPanel([FieldPanel('trial_days'), FieldPanel('offline_grace_days'), FieldPanel('price_text')]),
        FieldPanel('trial_retention_months'),
        FieldPanel('purchase_url'),
        FieldPanel('description'),
        InlinePanel('features', label="Функция",
                    heading="Функции: бесплатно или Pro",
                    help_text="Для «Сохранённые сессии», «Карты», «Двигатели» — лимит бесплатной версии "
                              "(пусто — без лимита). Для остальных — «Бесплатно» или «Pro». Сохранённое "
                              "пользователем никогда не блокируется: лимит запрещает только создавать сверх него."),
    ]

    class Meta:
        verbose_name = "Pro-версия"
        verbose_name_plural = "Pro-версия"

    def __str__(self):
        return "Pro-версия: " + ("включена" if self.enabled else "выключена (всё бесплатно)")

    def save(self, *args, **kwargs):
        # Только первое включение: повторное выключение/включение не перезапускает пробный период всем.
        if self.enabled and self.enabled_at is None:
            from django.utils import timezone
            self.enabled_at = timezone.now()
        super().save(*args, **kwargs)

    def trial_window(self, first_seen_at, override_ends_at=None):
        """(начало, конец) пробного периода устройства: не раньше первого включения платной версии;
        продление из админки («Устройства пробного периода») — вместо расчёта."""
        start = max(first_seen_at, self.enabled_at) if self.enabled_at else first_seen_at
        end = override_ends_at or start + timedelta(days=self.trial_days)
        return start, end

    @classmethod
    def get(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        # Новые функции из кода (с новой версией приложения) дописываются со значением по умолчанию.
        if created or obj.features.count() < len(APP_PRO_FEATURES):
            for key, _, kind, default in APP_PRO_FEATURES:
                AppProFeature.objects.get_or_create(
                    settings=obj, key=key,
                    defaults={'tier': 'free' if kind == 'limit' else default,
                              'free_limit': default if kind == 'limit' else None})
        return obj

    def payload(self):
        rows = {f.key: f for f in self.features.all()}
        features = {}
        for key, _, kind, default in APP_PRO_FEATURES:
            f = rows.get(key)
            if kind == 'limit':
                features[key] = {'limit': f.free_limit if f else default}
            else:
                features[key] = {'tier': f.tier if f else default}
        return {'enabled': self.enabled, 'trial_days': self.trial_days, 'price': self.price_text.strip(),
                'purchase_url': self.purchase_url, 'description': self.description.strip(), 'features': features,
                'offline_grace_days': self.offline_grace_days,
                'trial_not_before': self.enabled_at.isoformat() if self.enabled_at else None}


class AppTrialDevice(models.Model):
    """Устройство с пробным периодом Pro (11.10.2026). Начало пробного периода хранится здесь, а не только
    на телефоне: переустановка и «Очистить данные» не дают новый пробный период.

    Ключ — SHA-256 от ANDROID_ID с солью приложения: сам идентификатор на сайт не уходит. ANDROID_ID
    переживает переустановку, меняется только при сбросе телефона к заводским настройкам.
    """
    device_hash = models.CharField("Устройство (хэш)", max_length=64, unique=True)
    first_seen_at = models.DateTimeField("Первый запуск", db_index=True)
    last_seen_at = models.DateTimeField("Последняя связь")
    client_id = models.CharField("Установка", max_length=64, blank=True, db_index=True,
                                 help_text="Идентификатор текущей установки (как в журналах приложения).")
    installs = models.PositiveIntegerField("Установок", default=1,
                                           help_text="Сколько раз приложение ставили заново на этом устройстве.")
    app_version = models.CharField("Версия приложения", max_length=40, blank=True)
    trial_ends_override = models.DateTimeField(
        "Пробный период до (вручную)", null=True, blank=True,
        help_text="Продлить или сократить пробный период этого устройства. Пусто — по общим настройкам "
                  "«Pro-версии».")
    note = models.CharField("Заметка", max_length=200, blank=True)

    panels = [FieldPanel('trial_ends_override'), FieldPanel('note')]

    class Meta:
        verbose_name = "Устройство пробного периода"
        verbose_name_plural = "Устройства пробного периода"
        ordering = ['-last_seen_at']

    def __str__(self):
        return f"Устройство {self.device_hash[:10]}…"

    def trial_ends_at(self):
        return AppProSettings.get().trial_window(self.first_seen_at, self.trial_ends_override)[1]
    trial_ends_at.short_description = "Пробный период до"


class AppDeviceToken(models.Model):
    """Вход в приложение аккаунтом сайта (17.10.2026): токен на одно устройство.

    Хранится только SHA-256 токена — сам токен видит лишь телефон. Выход в приложении или в ЛК
    («Устройства приложения») ставит `revoked_at`; заблокированный пользователь не проходит проверку токена.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='app_tokens')
    key_hash = models.CharField("Токен (хэш)", max_length=64, unique=True)
    device_name = models.CharField("Устройство", max_length=120, blank=True)
    app_version = models.CharField("Версия приложения", max_length=40, blank=True)
    created_at = models.DateTimeField("Вход", auto_now_add=True)
    last_used_at = models.DateTimeField("Последняя связь", null=True, blank=True)
    revoked_at = models.DateTimeField("Выход", null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Вход в приложение"
        verbose_name_plural = "Входы в приложение"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} — {self.device_name or 'устройство'}"


APP_SYNC_TABLES = ['karts', 'engines', 'tracks', 'sessions']


class AppSyncRecord(models.Model):
    """Запись приложения на сайте (17.10.2026, этап 2 плана setupkart-account-sync): карт, двигатель, трасса
    или сессия пользователя — строка drift `toJson()` как есть (`data`), по UUID приложения.

    Источник правды — телефон: запись заменяется, только если `updatedAt` присланной строки новее
    (`client_updated_at`); прежняя версия уходит в `AppSyncRecordVersion`. Протокол v3 дополнительно
    сверяет `server_revision`: правка, основанная на устаревшей ревизии, не перезаписывает запись,
    а возвращает клиенту конфликт с текущей серверной строкой. У сессий — поля для ЛК: пилот сайта
    (только свой или из состава своей команды), трасса сайта, видимость команде и на странице пилота.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='app_records')
    table = models.CharField("Вид", max_length=16, choices=[(t, t) for t in APP_SYNC_TABLES])
    uuid = models.CharField("UUID", max_length=64)
    data = models.JSONField("Данные")
    schema_version = models.PositiveIntegerField("Версия схемы приложения", default=0)
    client_updated_at = models.BigIntegerField("Изменено в приложении (мс)")
    deleted = models.BooleanField("Удалено", default=False)
    server_updated_at = models.DateTimeField("Получено", db_index=True)
    server_revision = models.PositiveBigIntegerField(
        "Серверная ревизия", default=1,
        help_text="Увеличивается при каждом принятом изменении строки. Клиент присылает "
                  "ревизию, на которой основана его правка: несовпадение — конфликт без перезаписи.")

    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='app_sessions')
    track = models.ForeignKey('Track', on_delete=models.SET_NULL, null=True, blank=True, related_name='app_sessions')
    started_at = models.DateTimeField("Начало сессии", null=True, blank=True, db_index=True)
    visible_to_team = models.BooleanField("Видна команде", default=True)
    public = models.BooleanField("На странице пилота", default=False)

    class Meta:
        verbose_name = "Запись приложения"
        verbose_name_plural = "Записи приложения"
        unique_together = [('user', 'table', 'uuid')]
        indexes = [models.Index(fields=['user', 'server_updated_at', 'id'])]

    def __str__(self):
        return f"{self.table} {self.uuid}"


class AppSyncRecordVersion(models.Model):
    """Прежняя версия записи, заменённой более новой (конфликт двух телефонов — ничего не теряется)."""
    KEEP = 10
    record = models.ForeignKey(AppSyncRecord, on_delete=models.CASCADE, related_name='versions')
    data = models.JSONField()
    client_updated_at = models.BigIntegerField()
    replaced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-replaced_at']


class AppProFeature(Orderable):
    settings = ParentalKey(AppProSettings, on_delete=models.CASCADE, related_name='features')
    key = models.CharField("Функция", max_length=30, choices=[(k, name) for k, name, _, _ in APP_PRO_FEATURES])
    tier = models.CharField("Доступна", max_length=10, choices=[('free', 'Бесплатно'), ('pro', 'Только Pro')],
                            default='free')
    free_limit = models.PositiveIntegerField(
        "Лимит бесплатной версии", null=True, blank=True,
        help_text="Только для «Сохранённые сессии», «Карты», «Двигатели»; пусто — без лимита.")

    panels = [FieldRowPanel([FieldPanel('key'), FieldPanel('tier'), FieldPanel('free_limit')])]

    class Meta(Orderable.Meta):
        verbose_name = "Функция"
        verbose_name_plural = "Функции"
        constraints = [models.UniqueConstraint(fields=['settings', 'key'], name='app_pro_feature_unique_key')]

    def clean(self):
        from django.core.exceptions import ValidationError
        kind = APP_PRO_FEATURE_KINDS.get(self.key)
        if kind == 'toggle' and self.free_limit is not None:
            raise ValidationError({'free_limit': 'Лимит бывает только у сессий, картов и двигателей.'})
        if kind == 'limit' and self.tier != 'free':
            raise ValidationError({'tier': 'У лимитов выбирается число, а не «Только Pro». Лимит 0 — только в Pro.'})

    def __str__(self):
        return self.get_key_display()


class AppCatalogVersion(models.Model):
    """Опубликованная версия справочников. Приложение получает только опубликованное."""
    version = models.PositiveIntegerField("Версия", unique=True)
    published_at = models.DateTimeField("Опубликовано", auto_now_add=True)
    published_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Кто")
    note = models.CharField("Комментарий", max_length=200, blank=True)
    payload = models.JSONField("Содержимое", default=dict)

    class Meta:
        verbose_name = "Версия справочников приложения"
        verbose_name_plural = "Версии справочников приложения"
        ordering = ['-version']

    def __str__(self):
        return f"v{self.version} от {self.published_at:%d.%m.%Y %H:%M}"


class AppDiagnosticReport(models.Model):
    """Журнал работы приложения, отправленный пользователем из «Настроек» (11.10.2026).

    Только техническое: версии, связь с сайтом, ошибки, счётчики данных — без содержимого сессий
    и без контактов. Нужен, чтобы разбирать случаи вроде «на сайте трасс больше, чем в приложении».
    """
    client_id = models.CharField("Установка", max_length=64, db_index=True)
    app_version = models.CharField("Версия приложения", max_length=40, blank=True)
    device_info = models.CharField("Устройство", max_length=120, blank=True)
    comment = models.TextField("Комментарий пользователя", blank=True)
    log = models.TextField("Журнал")
    created_at = models.DateTimeField("Получен", auto_now_add=True, db_index=True)
    is_read = models.BooleanField("Просмотрен", default=False)

    class Meta:
        verbose_name = "Журнал приложения"
        verbose_name_plural = "Журналы приложения"
        ordering = ['-created_at']

    def __str__(self):
        return f"Журнал №{self.pk} ({self.app_version})"


class AppSuggestion(models.Model):
    """Значение из «Другое…», присланное пользователями с согласия (анонимно), сгруппированное."""
    STATUS_NEW = 'new'
    STATUS_ADDED = 'added'
    STATUS_HIDDEN = 'hidden'
    STATUS_CHOICES = [(STATUS_NEW, 'Новое'), (STATUS_ADDED, 'Добавлено в справочник'), (STATUS_HIDDEN, 'Скрыто')]

    field_key = models.CharField("Поле", max_length=30)
    value = models.CharField("Значение", max_length=60)
    engine = models.ForeignKey('website.Engine', null=True, blank=True, on_delete=models.CASCADE,
                               related_name='app_suggestions', verbose_name="Двигатель")
    count = models.PositiveIntegerField("Сколько раз прислали", default=1)
    first_seen = models.DateTimeField("Впервые", auto_now_add=True)
    last_seen = models.DateTimeField("Последний раз", auto_now=True)
    status = models.CharField("Статус", max_length=10, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True)
    # Только для предложений трасс (field_key='track'): координаты из своей трассы пользователя.
    latitude = models.FloatField("Широта", null=True, blank=True)
    longitude = models.FloatField("Долгота", null=True, blank=True)

    class Meta:
        verbose_name = "Предложение пользователей"
        verbose_name_plural = "Предложения пользователей"
        ordering = ['-count', '-last_seen']
        constraints = [models.UniqueConstraint(fields=['field_key', 'engine', 'value'], name='app_suggestion_unique')]

    def __str__(self):
        return f"{self.field_key}: {self.value}"
