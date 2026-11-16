"""Пилоты, команды, сотрудники и членство в команде."""

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
    city = models.CharField("Город / база", max_length=100, blank=True, null=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('logo'),
        FieldPanel('city'),
        FieldPanel('description'),
        InlinePanel('social_links', label="Социальные сети команды"),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(unidecode(self.name)) or 'team'
            slug, n = base, 1
            while Team.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f'{base}-{n}'
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/teams/{self.slug}/"

    class Meta:
        verbose_name = "Команда"
        verbose_name_plural = "Команды"

class TeamMembership(models.Model):
    """Связь пилота с командой с датами.

    Подтверждение отделено от активности: исторический/ручной состав может быть
    активен, но не давать операционного доступа к документам и сессиям. Результат
    пилота за команду, принятое приглашение и явное действие администратора
    подтверждают membership (confirmed_at + источник + актор).
    """
    CONFIRMATION_SOURCES = [
        ('result', 'Результат пилота за команду'),
        ('invitation', 'Принятое приглашение'),
        ('join_request', 'Одобренная заявка на вступление'),
        ('admin', 'Подтверждение администратора'),
        ('legacy', 'Сохранено при миграции'),
    ]

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='team_memberships')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    race_class = models.ForeignKey('RaceClass', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Класс')
    joined_at = models.DateField("Дата присоединения", auto_now_add=True)
    left_at = models.DateField("Дата ухода", null=True, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    # --- подтверждённое операционное членство ---
    confirmed_at = models.DateTimeField("Подтверждено", null=True, blank=True, db_index=True)
    confirmed_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='confirmed_team_memberships', verbose_name='Кто подтвердил')
    confirmation_source = models.CharField(
        "Источник подтверждения", max_length=20, choices=CONFIRMATION_SOURCES, blank=True, default='')
    confirmation_note = models.TextField("Основание подтверждения", blank=True, default='')

    class Meta:
        verbose_name = "Участие в команде"
        verbose_name_plural = "Участия в командах"
        unique_together = ['driver', 'team', 'joined_at']  # Защита от дублей

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None

    def confirm(self, *, source, actor=None, note=''):
        """Отметить связь подтверждённой; повторный вызов обновляет источник."""
        self.confirmed_at = timezone.now()
        self.confirmed_by = actor
        self.confirmation_source = source
        if note:
            self.confirmation_note = note
        return self

    def __str__(self):
        return f"{self.driver.full_name} в {self.team.name}"

# ---------- ТРАССЫ (TRACK) ----------
