"""Служебные записи панели администратора."""

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


class ScheduledJobRun(models.Model):
    """Последний запуск регулярной (cron) задачи — чтобы дашборд видел, что она не молчит.
    Пишется через website.dashboard.jobs.record_job(); реестр ожидаемых задач — там же."""
    name = models.CharField('Задача', max_length=64, unique=True)
    last_success_at = models.DateTimeField('Последний успешный запуск', null=True, blank=True)
    last_failure_at = models.DateTimeField('Последний сбой', null=True, blank=True)
    last_message = models.CharField('Сообщение', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Запуск регулярной задачи'
        verbose_name_plural = 'Запуски регулярных задач'

    def __str__(self):
        return self.name


class AdminDashboardVisit(models.Model):
    """Когда пользователь админки в последний раз смотрел главную — для блока
    «Что нового с вашего прошлого визита». since — начало текущего окна."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='dashboard_visit')
    last_seen = models.DateTimeField()
    since = models.DateTimeField()

    class Meta:
        verbose_name = 'Визит на главную админки'
        verbose_name_plural = 'Визиты на главную админки'


# ---------- Справочники мобильного приложения GripLine SetupKart (ТЗ приложения §13.3) ----------
# Принцип: справочники сайта (Engine, Chassis, TyreBrand, Track, RaceClass) не дублируются —
# приложение ссылается на них (галочка show_in_app). Здесь только то, чего на сайте нет:
# поля карбюратора и свечи двигателя, общие параметры, версии публикации, предложения пользователей.

# Поля, которые приложение умеет показывать (виджет выбирается по ключу — как в оригинале на скриншотах:
# список с «Другое…», плитки 1–5 для положения иглы).
APP_ENGINE_FIELD_CHOICES = [
    ('main_jet', 'Главный жиклёр'),
    ('main_jet_in', 'Главный жиклёр (дюймы)'),
    ('idle_jet', 'Жиклёр холостого хода'),
    ('needle', 'Игла'),
    ('mixing_tube', 'Смесительная трубка'),
    ('throttle_slide', 'Золотник'),
    ('idle_turns', 'Холостой ход'),
    ('air_screw_turns', 'Воздушный винт'),
    ('needle_position', 'Положение иглы (1 — бедная … 5 — богатая)'),
    ('needle_clip', 'Клипса иглы'),
    ('needle_high', 'Винт High (Tillotson)'),
    ('needle_low', 'Винт Low (Tillotson)'),
    ('plug_gap_mm', 'Зазор свечи, мм'),
    ('float_height_mm', 'Высота поплавка, мм'),
    ('float_drop_mm', 'Провал поплавка, мм'),
    ('water_temp_c', 'Температура воды, °C'),
]
APP_PARAMETER_CHOICES = [
    ('hub_width_mm', 'Ширина ступицы, мм'),
    ('pinion_teeth', 'Пиньон, зубья'),
    ('sprocket_teeth', 'Звезда, зубья'),
    ('spacer', 'Проставки (кольца)'),
    # 11.10.2026 — по статье «Настройка шасси карта»: числа «−/+» и списки для новых полей приложения
    ('toe_mm', 'Схождение, мм (− развал)'),
    ('seat_strut', 'Распорки сиденья (на сторону)'),
    ('seat_shift_mm', 'Сиденье: сдвиг назад, мм'),
    ('seat_raise_mm', 'Сиденье: подъём, мм'),
    ('seat_side_mm', 'Сиденье: сдвиг вправо, мм'),
    ('torsion_bar', 'Торсионный стабилизатор (варианты)'),
    ('grip_level', 'Уровень зацепа трассы (варианты)'),
    # 12.10.2026 — новые поля шасси (значения — по Kart Chassis Setup Pro)
    ('front_hub_length_mm', 'Длина передней ступицы, мм'),
    ('seat_type', 'Сиденье: жёсткость (варианты)'),
    ('seat_size', 'Сиденье: размер (варианты)'),
]
# Колея и давление в шинах — свободный ввод числа в приложении (решение владельца 07.10.2026), здесь не настраиваются.
