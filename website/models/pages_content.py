"""Формы, локации, веса и настройки аналитики."""

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

from .pages import TransliteratedSlugMixin


class FormPage(TransliteratedSlugMixin, CoderedFormPage):
    class Meta:
        verbose_name = "Form"
    template = "coderedcms/pages/form_page.html"

class FormPageField(CoderedFormField):
    page = ParentalKey("FormPage", related_name="form_fields")

class FormConfirmEmail(CoderedEmail):
    page = ParentalKey("FormPage", related_name="confirmation_emails")

class LocationPage(TransliteratedSlugMixin, CoderedLocationPage):
    class Meta:
        verbose_name = "Location Page"
    template = "coderedcms/pages/location_page.html"
    parent_page_types = ["website.LocationIndexPage"]

class LocationIndexPage(TransliteratedSlugMixin, CoderedLocationIndexPage):
    class Meta:
        verbose_name = "Location Landing Page"
    index_query_pagemodel = "website.LocationPage"
    subpage_types = ["website.LocationPage"]
    template = "coderedcms/pages/location_index_page.html"

class WebPage(TransliteratedSlugMixin, CoderedWebPage):
    class Meta:
        verbose_name = "Web Page"
    template = "coderedcms/pages/web_page.html"

class WeightsPage(TransliteratedSlugMixin, CoderedWebPage):
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
            "Скорость затухания веса гонки со временем (одна для всех гонок). "
            "Полураспад = ln(2)/λ лет. Рекомендуется 0.5–1.2."
        ),
    )
    # С 18.10.2026 не используется: одна плавная кривая затухания (lambda_active)
    # для всех гонок, без скачка веса на пороге неактивности. Поле оставлено в БД.
    lambda_inactive = models.FloatField(
        default=2.0,
        editable=False,
        verbose_name="λ неактивного пилота (не используется)",
    )
    inactive_threshold_days = models.IntegerField(
        default=180,
        verbose_name="Порог неактивности (дней)",
        help_text=(
            "Пилот, не выступавший в классе дольше этого срока, не показывается "
            "в таблице рейтинга (на его странице — «вне рейтинга»)."
        ),
    )
    bayes_c = models.FloatField(
        default=4.0,
        verbose_name="Вес сглаживания (C)",
        help_text=(
            "Байесовское сглаживание: (N × BT + C × медиана) / (N + C). При N = C стартов "
            "пилот получает 50% доверия к своим результатам. Обычно пилот проводит в классе "
            "3–9 этапов, поэтому C ≈ 4. Действует сразу, пересчёт не нужен."
        ),
    )
    class_transfer_weight = models.FloatField(
        default=0.5,
        verbose_name="Учёт прошлого класса при переходе",
        help_text=(
            "Пилот, перешедший в новый класс, начинает не с середины таблицы, а ближе к месту, "
            "которое занимал в прошлом классе. 0 — не учитывать (все с середины), 1 — то же "
            "место, что в прошлом классе, 0.5 — посередине. Действует сразу, пересчёт не нужен."
        ),
    )

    # --- Пороги данных ---
    min_races_per_class = models.IntegerField(
        default=3,
        verbose_name="Мин. заездов для расчёта класса",
        help_text="Число отдельных групп результатов класса с допущенными результатами, не число пилотов. По умолчанию 3; дополнительно проверяется минимум сравнений.",
    )
    min_comparisons = models.IntegerField(
        default=10,
        verbose_name="Мин. парных сравнений (BT)",
        help_text="Класс с меньшим количеством парных сравнений пропускается.",
    )
    min_starts_display = models.IntegerField(
        default=3,
        verbose_name="Мин. стартов для отображения рейтинга",
        help_text=(
            "Пилоты с меньшим числом стартов в классе не показываются в таблице рейтинга "
            "и на главной; на странице пилота — «вне рейтинга: мало стартов». Действует сразу."
        ),
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

    # --- Медиа-кит пилота ---
    mediakit_top10_min_field = models.IntegerField(
        default=15,
        verbose_name="Мин. размер поля для «топ-10» в медиа-ките",
        help_text=(
            "Медиа-кит показывает бейдж «стабильно топ-10» только если типичный "
            "размер стартового поля пилота в классе не меньше этого значения — "
            "иначе формулировка была бы нечестной. Порог для «топ-5» берётся "
            "вдвое меньшим."
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки аналитики"
        verbose_name_plural = "Настройки аналитики"

    def __str__(self):
        return (
            f"AnalyticsSettings (λ={self.lambda_active}, C={self.bayes_c}, "
            f"inactive={self.inactive_threshold_days}d)"
        )

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
