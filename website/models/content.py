"""Объявления, кэш пульса и обращения по данным."""

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


def add_working_days(start, days):
    """Дата через `days` рабочих дней после `start` (суббота/воскресенье пропускаются).
    Праздничный календарь РФ не учитывается — срок «не более 10 рабочих дней» (152-ФЗ,
    ст. 20-21) считается по будням, с запасом это безопаснее, чем недосчитать."""
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


class DataRequest(models.Model):
    """
    Обращение субъекта персональных данных с публичной формы /legal/data-request/
    (Политика обработки ПД п. 8, Пользовательское соглашение п. 2.4 и 3).

    Хранится в БД, а не только уходит письмом: исходящий SMTP на проде может
    блокироваться хостингом (см. website/mail.py), а срок ответа по закону — 10
    рабочих дней, обращение нельзя потерять. Разбирается в админке → «Обращения по ПД».

    По политике (п. 4.3, 6.1) контакт и текст заявителя нужны только на время
    рассмотрения — после статуса «Рассмотрено/Отклонено» их надо очистить
    (поле admin_note с итогом решения остаётся).
    """
    TYPE_CHOICES = [
        ('deletion', 'Удаление данных'),
        ('correction', 'Уточнение данных'),
        ('stop_processing', 'Прекращение обработки'),
        ('consent_withdrawal', 'Отзыв согласия'),
    ]
    STATUS_CHOICES = [
        ('new', 'Новое'),
        ('in_progress', 'В работе'),
        ('done', 'Рассмотрено'),
        ('rejected', 'Отклонено'),
    ]

    request_type = models.CharField('Тип обращения', max_length=20, choices=TYPE_CHOICES)
    page_url = models.CharField('Ссылка на страницу', max_length=500, blank=True)
    # blank=True: после рассмотрения админ очищает контакт/текст (политика п. 6.1);
    # публичная форма (DataRequestForm) при этом по-прежнему требует оба поля.
    contact = models.CharField('Контакт для ответа', max_length=200, blank=True)
    text = models.TextField('Текст обращения', blank=True)
    is_confirmed = models.BooleanField(
        'Заявитель подтвердил, что он субъект ПД или его законный представитель',
        default=False,
    )
    status = models.CharField('Статус', max_length=12, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField('Получено', auto_now_add=True)
    due_date = models.DateField('Ответить до', null=True, blank=True)
    resolved_at = models.DateTimeField('Рассмотрено', null=True, blank=True)
    admin_note = models.TextField(
        'Решение / заметка', blank=True,
        help_text='Что сделано по обращению. После рассмотрения очистите «Контакт» и «Текст» '
                  '(политика п. 6.1 — данные заявителя хранятся только на время рассмотрения).',
    )

    class Meta:
        verbose_name = 'Обращение по персональным данным'
        verbose_name_plural = 'Обращения по персональным данным'
        ordering = ['-created_at']

    def __str__(self):
        return f'№{self.pk} · {self.get_request_type_display()} · {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if self.due_date is None:
            from django.utils import timezone
            self.due_date = add_working_days(timezone.localdate(), 10)
        super().save(*args, **kwargs)


# ==================== БОТ ОБРАТНОЙ СВЯЗИ (Telegram) ====================
#
# ТЗ: ~/Загрузки/gripline_tz_feedback_bot_v1.md. Модели каналонезависимы
# (поля channel/external_user_id) — второй канал (MAX, VK) добавляется
# адаптером, не правкой моделей. Код — website/feedback/, процесс бота —
# `manage.py run_feedback_bot`.

FEEDBACK_CHANNEL_TELEGRAM = 'telegram'
FEEDBACK_CHANNEL_SETUPKART = 'setupkart'
FEEDBACK_CHANNEL_CHOICES = [(FEEDBACK_CHANNEL_TELEGRAM, 'Telegram'), (FEEDBACK_CHANNEL_SETUPKART, 'Приложение SetupKart')]
# Категория обращений из приложения: своя тема в админ-чате, но в меню бота и виджете сайта её нет (is_active=False).
APP_FEEDBACK_CATEGORY_SLUG = 'setupkart'
