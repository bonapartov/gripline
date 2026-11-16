"""Развесовка, карты, сетапы и балласт."""

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


class ChassisTypePreset(models.Model):
    """
    Геометрия шасси по умолчанию — ровно две записи (детское/взрослое).
    Подставляется в новый Setup, если у класса (RaceClass) нет собственного
    переопределения (см. RaceClass.effective_geometry).
    """
    CHASSIS_TYPE_CHOICES = [
        ("junior", "Детское"),
        ("senior", "Взрослое"),
    ]

    chassis_type = models.CharField(
        max_length=10, choices=CHASSIS_TYPE_CHOICES, unique=True,
        verbose_name="Тип шасси",
    )
    wheelbase_mm = models.PositiveIntegerField(verbose_name="Колёсная база, мм")
    track_front_mm = models.PositiveIntegerField(verbose_name="Колея перед, мм")
    track_rear_mm = models.PositiveIntegerField(verbose_name="Колея зад, мм")

    panels = [
        FieldPanel("chassis_type"),
        FieldPanel("wheelbase_mm"),
        FieldPanel("track_front_mm"),
        FieldPanel("track_rear_mm"),
    ]

    class Meta:
        verbose_name = "Пресет геометрии шасси"
        verbose_name_plural = "Пресеты геометрии шасси"

    def __str__(self):
        return self.get_chassis_type_display()


class BalanceThreshold(models.Model):
    """
    Пороги цветовой индикации калькулятора развесовки. Общие — по одной записи на метрику
    (front_rear, left_right, cross_weight), без класса: по ним работают /balance/ и приложение.
    С классом гонок (11.10.2026) — эталон этого класса в приложении: заменяет общий порог той же
    метрики только для этого класса. Красная зона — всё вне жёлтой, отдельно не хранится.
    """
    METRIC_CHOICES = [
        ("front_rear", "Перед/зад, %"),
        ("left_right", "Лево/право, %"),
        ("cross_weight", "Cross weight, %"),
    ]

    metric = models.CharField(
        max_length=20, choices=METRIC_CHOICES, verbose_name="Метрика",
    )
    race_class = models.ForeignKey(
        'website.RaceClass', on_delete=models.CASCADE, null=True, blank=True, related_name='balance_thresholds',
        verbose_name="Класс гонок",
        help_text="Пусто — общий порог (сайт /balance/ и все классы в приложении). Класс — эталон этого класса "
                  "в приложении: зоны, диагностика и цель центра тяжести считаются по нему; метрики, не заданные "
                  "для класса, берутся из общих. Доходит до приложения после «Публикации».")
    green_min = models.DecimalField(max_digits=4, decimal_places=1, verbose_name="Зелёная зона, от")
    green_max = models.DecimalField(max_digits=4, decimal_places=1, verbose_name="Зелёная зона, до")
    yellow_min = models.DecimalField(max_digits=4, decimal_places=1, verbose_name="Жёлтая зона, от")
    yellow_max = models.DecimalField(max_digits=4, decimal_places=1, verbose_name="Жёлтая зона, до")

    panels = [
        FieldRowPanel([FieldPanel("metric"), FieldPanel("race_class")]),
        FieldRowPanel([
            FieldPanel("green_min"),
            FieldPanel("green_max"),
        ]),
        FieldRowPanel([
            FieldPanel("yellow_min"),
            FieldPanel("yellow_max"),
        ]),
    ]

    class Meta:
        verbose_name = "Порог цветовой индикации"
        verbose_name_plural = "Пороги цветовой индикации"
        constraints = [
            models.UniqueConstraint(fields=['metric', 'race_class'], name='balance_threshold_metric_class'),
            models.UniqueConstraint(fields=['metric'], condition=models.Q(race_class__isnull=True),
                                    name='balance_threshold_metric_common'),
        ]

    def __str__(self):
        return self.get_metric_display() + (f" — {self.race_class.name}" if self.race_class_id else " — общий")

    def clean(self):
        super().clean()
        for name in ('green_min', 'green_max', 'yellow_min', 'yellow_max'):
            if getattr(self, name) is None:
                return
        if not (self.yellow_min <= self.green_min <= self.green_max <= self.yellow_max):
            raise ValidationError("Нужно: жёлтая «от» ≤ зелёная «от» ≤ зелёная «до» ≤ жёлтая «до».")

    def classify(self, value):
        if self.green_min <= value <= self.green_max:
            return "green"
        if self.yellow_min <= value <= self.yellow_max:
            return "yellow"
        return "red"


class BalanceDiagnosticRule(models.Model):
    """
    Диагностика калькулятора развесовки (ТЗ Блок 6, раздел 7.1) + обучающий
    блок (7.2, condition="why_43_57_target" — не триггерится метриками,
    показывается всегда, отдельно от остальных семи).

    Условие (condition) — код, привязанный к реальной логике классификации
    (website/services/balance_calc.py::diagnose) и потому не редактируется
    через админку. Текст и ссылка на статью Матчасти — редактируются: текст
    предзаполнен формулировками из самого ТЗ (миграция 0039), ссылка изначально
    пуста — какая статья куда ведёт, было открытым вопросом ТЗ №10 («список
    финализировать перед реализацией блока»); вместо ожидания решили не
    блокировать реализацию — блок работает и без ссылок (просто не показывает
    «Подробнее»), Владимир проставляет статьи в «Развесовка», когда они
    определены/опубликованы.
    """
    CONDITION_CHOICES = [
        ("front_high", "Перед > верхней жёлтой границы"),
        ("front_low", "Перед < нижней жёлтой границы"),
        ("cross_diagonal", "Cross не идеален при нормальном L/R"),
        ("cross_mechanical", "Cross за пределами жёлтой зоны"),
        ("lr_asymmetry", "L/R за пределами жёлтой зоны"),
        ("wet_weather", "Погода: дождь"),
        ("under_min_weight", "Не набрана минималка класса"),
        ("why_43_57_target", "Обучающий блок: почему 43/57"),
    ]

    condition = models.CharField(
        max_length=30, choices=CONDITION_CHOICES, unique=True, verbose_name="Условие",
    )
    text = models.TextField(
        verbose_name="Текст",
        help_text='Для "Не набрана минималка класса" доступна подстановка {shortfall_kg}.',
    )
    article = models.ForeignKey(
        "website.ArticlePage", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", verbose_name="Статья Матчасти («Подробнее»)",
    )

    panels = [
        FieldPanel("condition"),
        FieldPanel("text"),
        FieldPanel("article"),
    ]

    class Meta:
        verbose_name = "Правило диагностики (развесовка)"
        verbose_name_plural = "Правила диагностики (развесовка)"
        ordering = ["condition"]

    def __str__(self):
        return self.get_condition_display()


# ==================== РАЗВЕСОВКА (Balance) — данные пользователей ====================
#
# В отличие от справочников выше — это не Wagtail-снипеты и не управляются
# через Wagtail admin. Создаются/редактируются пользователями через сам
# инструмент /balance/ (Блоки 2-4); здесь только модели данных (Блок 1).
# Поддержка/отладка — через обычный django-admin (website/admin.py), как
# TeamManager/TeamClaim в teams/admin.py, а не через CMS.

# Пометка для формы добавления записи в ростер (ТЗ 13.3, третий пункт) —
# самой формы ещё нет (её строит Блок 3, ЛК менеджера команды), сюда просто
# кладём готовую формулировку заранее, чтобы Блок 3 не изобретал её заново.
# Ссылка — на политику, создаваемую management-командой
# create_legal_pages (см. website/management/commands/).
ROSTER_PRIVACY_NOTICE = (
    'Данные (только фамилия и имя) обрабатываются согласно '
    '<a href="/legal/privacy/" target="_blank" rel="noopener">политике конфиденциальности</a>. '
    'Дату рождения указывать не нужно — мы её не собираем.'
)


class TeamRosterEntry(models.Model):
    """
    Позволяет команде вести сетапы пилотов, у которых ещё нет аккаунта.
    Год рождения сознательно НЕ хранится (152-ФЗ — вносится третьим лицом,
    для расчёта развесовки бесполезен; для различения однофамильцев
    достаточно свободной метки label). См. CLAUDE.md, раздел «Развесовка
    карта» → «Персональные данные» (Блок 11).
    """
    team = models.ForeignKey(
        "website.Team", on_delete=models.CASCADE,
        related_name="balance_roster_entries", verbose_name="Команда",
    )
    last_name = models.CharField(max_length=100, verbose_name="Фамилия")
    first_name = models.CharField(max_length=100, verbose_name="Имя")
    label = models.CharField(
        max_length=100, blank=True, verbose_name="Метка",
        help_text="Для различения однофамильцев, например «синий шлем», «старший».",
    )
    driver = models.ForeignKey(
        "website.Driver", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="balance_roster_entries", verbose_name="Профиль пилота",
        help_text="Заполняется, когда пилот регистрируется и его DriverClaim подтверждён — вся история сетапов сохраняется.",
    )
    gear_weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        verbose_name="Вес в экипировке, кг",
    )
    is_archived = models.BooleanField(default=False, verbose_name="В архиве")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Запись ростера (развесовка)"
        verbose_name_plural = "Ростер (развесовка)"
        ordering = ["last_name", "first_name"]

    def __str__(self):
        name = f"{self.last_name} {self.first_name}".strip()
        return f"{name} ({self.label})" if self.label else (name or f"Ростер #{self.pk}")


class Kart(models.Model):
    """Физическое шасси. Класс — на Setup, не здесь (одно шасси может ехать
    в разных классах при смене мотора, каждый требует полного пересчёта
    развесовки — держим сетапы разных классов на одном шасси без разрыва
    истории)."""

    name = models.CharField(
        max_length=100, verbose_name="Название",
        help_text="Произвольная метка, например «Карт №1», «Синий Tony».",
    )
    chassis = models.ForeignKey(
        "website.Chassis", on_delete=models.PROTECT,
        related_name="balance_karts", verbose_name="Шасси",
        help_text="Существующий справочник шасси сайта.",
    )
    chassis_type = models.CharField(
        max_length=10, choices=ChassisTypePreset.CHASSIS_TYPE_CHOICES,
        verbose_name="Тип шасси",
        help_text="У справочника «Шасси» такого признака нет — указывается здесь вручную.",
    )
    model = models.CharField(max_length=100, blank=True, verbose_name="Модель рамы")
    year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Год")

    owner_driver = models.ForeignKey(
        "website.Driver", on_delete=models.CASCADE, null=True, blank=True,
        related_name="balance_karts", verbose_name="Владелец-пилот",
    )
    owner_team = models.ForeignKey(
        "website.Team", on_delete=models.CASCADE, null=True, blank=True,
        related_name="balance_karts", verbose_name="Владелец-команда",
    )
    roster_entry = models.ForeignKey(
        TeamRosterEntry, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="karts", verbose_name="Закреплён за",
        help_text="За кем из ростера закреплён — только для карта команды.",
    )

    is_archived = models.BooleanField(default=False, verbose_name="В архиве")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Карт (развесовка)"
        verbose_name_plural = "Карты (развесовка)"
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(owner_driver__isnull=False, owner_team__isnull=True)
                    | Q(owner_driver__isnull=True, owner_team__isnull=False)
                ),
                name="balance_kart_exactly_one_owner",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if bool(self.owner_driver_id) == bool(self.owner_team_id):
            raise ValidationError("Укажите владельца — либо пилота, либо команду, но не оба и не ни одного.")
        if self.roster_entry_id:
            if not self.owner_team_id:
                raise ValidationError({"roster_entry": "«Закреплён за» имеет смысл только для карта, принадлежащего команде."})
            if self.roster_entry.team_id != self.owner_team_id:
                raise ValidationError({"roster_entry": "Запись ростера должна принадлежать той же команде, что и владелец карта."})


class Setup(models.Model):
    """Снимок развесовки на конкретных условиях. Копирование (не создание
    с нуля) — основной способ завести новый сетап, см. parent_setup."""

    WEATHER_CHOICES = [
        ("dry", "Сухо"),
        ("wet", "Дождь"),
        ("mixed", "Переменная"),
    ]
    TEMP_SOURCE_CHOICES = [
        ("auto", "Автоматически"),
        ("manual", "Вручную"),
    ]

    kart = models.ForeignKey(Kart, on_delete=models.CASCADE, related_name="setups", verbose_name="Карт")
    name = models.CharField(
        max_length=150, verbose_name="Название",
        help_text="Например «Мячково, сухо, полбака».",
    )
    race_class = models.ForeignKey(
        "website.RaceClass", on_delete=models.PROTECT, related_name="balance_setups", verbose_name="Класс",
    )

    weight_lf = models.DecimalField(max_digits=5, decimal_places=1, verbose_name="Левый перед, кг")
    weight_rf = models.DecimalField(max_digits=5, decimal_places=1, verbose_name="Правый перед, кг")
    weight_lr = models.DecimalField(max_digits=5, decimal_places=1, verbose_name="Левый зад, кг")
    weight_rr = models.DecimalField(max_digits=5, decimal_places=1, verbose_name="Правый зад, кг")

    driver_weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        verbose_name="Вес пилота, кг",
        help_text="Подставляется из ростера/профиля пилота, можно переопределить.",
    )

    track = models.ForeignKey(
        "website.Track", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="balance_setups", verbose_name="Трасса",
    )
    weather = models.CharField(max_length=10, choices=WEATHER_CHOICES, default="dry", verbose_name="Погода")
    temp_air_c = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, verbose_name="Температура воздуха, °C",
    )
    temp_track_c = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, verbose_name="Температура покрытия, °C",
        help_text="Только ручной ввод — погодные API её не дают.",
    )
    temp_source = models.CharField(
        max_length=10, choices=TEMP_SOURCE_CHOICES, default="manual", verbose_name="Источник температуры",
    )

    wheelbase_mm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Колёсная база, мм")
    track_front_mm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Колея перед, мм")
    track_rear_mm = models.PositiveIntegerField(null=True, blank=True, verbose_name="Колея зад, мм")

    notes = models.TextField(blank=True, verbose_name="Заметки")

    shared_with_team = models.BooleanField(default=False, verbose_name="Открыт команде")
    shared_with_driver = models.BooleanField(default=False, verbose_name="Открыт пилоту")

    parent_setup = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="copies", verbose_name="Копия из",
    )

    is_archived = models.BooleanField(default=False, verbose_name="В архиве")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Сетап (развесовка)"
        verbose_name_plural = "Сетапы (развесовка)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} — {self.kart.name}"

    def clean(self):
        if (self.kart_id and self.race_class_id and self.race_class.chassis_type
                and self.race_class.chassis_type != self.kart.chassis_type):
            raise ValidationError({
                "race_class": "Класс не подходит типу шасси этого карта (детское/взрослое).",
            })

    @property
    def total_weight_kg(self):
        return self.weight_lf + self.weight_rf + self.weight_lr + self.weight_rr

    def effective_geometry(self):
        """Своё переопределение → переопределение класса → пресет типа шасси."""
        class_geometry = self.race_class.effective_geometry()
        return {
            "wheelbase_mm": self.wheelbase_mm or class_geometry["wheelbase_mm"],
            "track_front_mm": self.track_front_mm or class_geometry["track_front_mm"],
            "track_rear_mm": self.track_rear_mm or class_geometry["track_rear_mm"],
        }


class Ballast(models.Model):
    """Груз на схеме. weight_kg может быть отрицательным — симуляция снятия
    уже установленного груза (см. ТЗ 2.6)."""

    setup = models.ForeignKey(Setup, on_delete=models.CASCADE, related_name="ballasts", verbose_name="Сетап")
    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, verbose_name="Вес, кг",
    )
    pos_x_mm = models.DecimalField(
        max_digits=6, decimal_places=1, verbose_name="Поперёк, мм", help_text="От левого края колеи.",
    )
    pos_y_mm = models.DecimalField(
        max_digits=6, decimal_places=1, verbose_name="Вдоль, мм", help_text="От передней оси.",
    )
    label = models.CharField(max_length=100, blank=True, verbose_name="Метка")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Груз на схеме"
        verbose_name_plural = "Грузы на схеме"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.label or f"Груз {self.weight_kg} кг"
