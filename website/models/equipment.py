"""Трассы, шасси, шины и двигатели."""

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


class TrackSocialLink(Orderable):
    page = ParentalKey("website.Track", related_name="social_links")
    network_name = models.CharField("Название (например: ВК, Instagram, Сайт)", max_length=100)
    link_url = models.URLField("Ссылка")

    panels = [
        FieldPanel('network_name'),
        FieldPanel('link_url'),
    ]

def _private_storage():
    from website.feedback.storage import private_storage
    return private_storage()


class TrackSchemePanel(Panel):
    """Кнопка «Редактор схемы» на форме трассы (у новой, ещё не сохранённой трассы — подсказка)."""

    class BoundPanel(Panel.BoundPanel):
        template_name = "website/admin/track_scheme_panel.html"

        def get_context_data(self, parent_context=None):
            context = super().get_context_data(parent_context)
            context['track'] = self.instance
            return context


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

    # Материализованные рекорды трасс по классам — не редактируется в
    # админке, обновляется командой update_track_records (запускается
    # вручную после ввода новых результатов, как update_ratings).
    # Структура: {"<class_id>": {"final_holder_id", "record_year", "lap_ms", "ever_holder_ids"}}
    records_cache = models.JSONField(
        "Рекорды трасс (пересчитываемые)",
        default=dict,
        blank=True,
        editable=False,
    )

    show_in_app = models.BooleanField(
        "Показывать в приложении", default=False,
        help_text="Запись попадёт в мобильное приложение GripLine SetupKart после публикации справочников "
                  "(меню «Приложение» → «Публикация»). Без галочки — только на сайте.",
    )
    # Имя поля историческое (сначала было только для приложения) — теперь это направление трассы
    # и для сайта (шапка, PDF, проверка схемы в редакторе), и для приложения.
    app_direction = models.CharField(
        "Направление движения", max_length=3, blank=True, choices=[('cw', 'По часовой'), ('ccw', 'Против часовой')],
        help_text="Показывается на странице трассы и в PDF-схеме, по нему редактор схемы проверяет, в какую "
                  "сторону нарисована линия. В приложении подставляется в сессию на этой трассе. Пусто — не показывается.")

    length_m = models.DecimalField(
        "Длина, м", max_digits=7, decimal_places=2, blank=True, null=True,
        help_text="Например 1603.45. Нужна для 3D-схемы (масштаб) — без длины 3D не показывается.")
    turns_count = models.PositiveSmallIntegerField(
        "Число поворотов", blank=True, null=True,
        help_text="Пусто — берётся число поворотов со схемы трассы.")
    # Схема — пишет только редактор схемы (админка → Трассы → «Редактор схемы»), руками не правится.
    scheme_data = models.JSONField("Схема трассы (данные)", blank=True, null=True, editable=False)
    scheme_svg = models.TextField("Схема трассы (SVG)", blank=True, editable=False)
    scheme_reference = models.FileField(
        "Подложка для обводки схемы", blank=True, editable=False,
        storage=_private_storage, upload_to='track_scheme_reference/',
        help_text="Только для редактора схемы, на сайт не выводится.")
    scheme_updated_at = models.DateTimeField("Схема сохранена", blank=True, null=True, editable=False)

    panels = [
        FieldPanel('show_in_app'),
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
        MultiFieldPanel([
            FieldPanel('length_m'),
            FieldPanel('turns_count'),
            FieldPanel('app_direction'),
            TrackSchemePanel(),
        ], heading="Характеристики и схема трассы"),
        InlinePanel('social_links', label="Социальные сети"),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(unidecode(self.name))
        if self.scheme_data:
            # толщина полотна на схеме зависит от длины трассы и направления (подпись) — пересобрать SVG
            from website.services import track_scheme
            try:
                self.scheme_svg = track_scheme.render_svg(
                    self.scheme_data, aria_label=track_scheme.aria_label(self, self.scheme_data), length_m=self.length_m)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                pass  # битые данные схемы не должны мешать сохранить трассу
            update_fields = kwargs.get('update_fields')
            if update_fields is not None and 'scheme_svg' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['scheme_svg']
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/tracks/{self.slug}/"

    @property
    def has_scheme(self):
        """Схема на сайте: сохранена и не черновик (или черновик с галочкой «Опубликовать черновик»)."""
        from website.services.track_scheme import is_publishable
        return bool(self.scheme_svg and self.scheme_data) and is_publishable(self.scheme_data)

    @property
    def scheme_is_draft(self):
        from website.services.track_scheme import is_draft
        return bool(self.scheme_data) and is_draft(self.scheme_data)

    @property
    def effective_turns_count(self):
        """Поле «Число поворотов», а если пусто — число маркеров поворотов на схеме."""
        if self.turns_count:
            return self.turns_count
        turns = (self.scheme_data or {}).get('turns') or []
        return len(turns) or None

    class Meta:
        verbose_name = "Трасса"
        verbose_name_plural = "Трассы"

class TrackIndexPage(TransliteratedSlugMixin, CoderedWebPage):
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

    show_in_app = models.BooleanField(
        "Показывать в приложении", default=False,
        help_text="Запись попадёт в мобильное приложение GripLine SetupKart после публикации справочников "
                  "(меню «Приложение» → «Публикация»). Без галочки — только на сайте.",
    )
    aliases = models.CharField(
        "Синонимы", max_length=255, blank=True, default='',
        help_text="Другие написания через запятую, например «Cosmik». Импорт протоколов находит шасси и по ним, "
                  "приложение подставляет основное название, если пользователь ввёл синоним через «Другое…».",
    )

    panels = [
        FieldPanel('show_in_app'),
        FieldPanel('name'),
        FieldPanel('aliases'),
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

    def alias_list(self):
        return [a.strip() for a in (self.aliases or '').split(',') if a.strip()]

    @classmethod
    def find_by_name(cls, name):
        """Шасси по названию или синониму, без учёта регистра; None — не найдено."""
        name = (name or '').strip()
        if not name:
            return None
        found = cls.objects.filter(name__iexact=name).first()
        if found:
            return found
        folded = name.casefold()
        for c in cls.objects.exclude(aliases=''):
            if folded in {a.casefold() for a in c.alias_list()}:
                return c
        return None

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

    show_in_app = models.BooleanField(
        "Показывать в приложении", default=False,
        help_text="Запись попадёт в мобильное приложение GripLine SetupKart после публикации справочников "
                  "(меню «Приложение» → «Публикация»). Без галочки — только на сайте.",
    )

    panels = [
        FieldPanel('show_in_app'),
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('country'),
        FieldPanel('logo'),
        FieldPanel('description'),
        FieldPanel('website'),
    ]
    app_panels = [
        HelpPanel(content="Составы шин этой марки для приложения GripLine SetupKart: пользователь выбирает "
                          "марку и видит составы плитками с фото. Порядок — перетаскиванием. Фото — "
                          "шина крупно, лучше квадратное, на однотонном фоне. Без составов в приложении "
                          "остаётся выбор типа (слик/дождь) и поле для своего текста."),
        InlinePanel('app_compounds', label="Состав"),
    ]
    edit_handler = TabbedInterface([
        ObjectList(panels, heading="Основное"),
        ObjectList(app_panels, heading="Приложение"),
    ])

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
    Тип шин: слик или дождь. Промежуточных в картинге нет — убраны 11.10.2026.
    """
    TYRE_TYPE_CHOICES = [
        ('slick', 'Слик'),
        ('wet', 'Дождь'),
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

    show_in_app = models.BooleanField(
        "Показывать в приложении", default=False,
        help_text="Запись попадёт в мобильное приложение GripLine SetupKart после публикации справочников "
                  "(меню «Приложение» → «Публикация»). Без галочки — только на сайте.",
    )
    app_family = models.CharField(
        "Семейство (для импорта .kart)", max_length=20, blank=True,
        choices=[('rotax', 'Rotax'), ('iame', 'IAME'), ('vortex', 'Vortex'), ('tm', 'TM'),
                 ('honda', 'Honda'), ('briggs', 'Briggs'), ('other', 'Другое')],
        help_text="Нужно, чтобы сетапы из оригинального приложения (марка + категория) сопоставлялись с этим двигателем.",
    )
    app_electric = models.BooleanField(
        "Электромотор", default=False,
        help_text="Без карбюратора, свечи и выхлопа (например Rotax E10): в приложении для него скрываются "
                  "разделы «Карбюратор» и «Температура выхлопа», жиклёр в «Быстрой правке» и моточасы. "
                  "Поля карбюратора и свечи ему не задаются. Шасси, развесовка и звёзды — как у всех.")
    app_screw_long_straight_pct = models.DecimalField(
        "Длинная прямая: High, %", max_digits=4, decimal_places=1, default=5,
        help_text="На трассе с длинной прямой винт High открывается больше на столько процентов.")
    app_screw_short_straight_pct = models.DecimalField(
        "Короткие прямые: High, %", max_digits=4, decimal_places=1, default=-5)
    app_fuel_mix_ratio = models.DecimalField(
        "Пропорция смеси, 1 : N", max_digits=4, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(10), MaxValueValidator(200)],
        help_text="Рекомендация для калькулятора топливной смеси в приложении: N частей бензина на одну масла "
                  "(1 : 50 — 2 %). Пусто — без рекомендации.")
    app_jet_base_rad = models.DecimalField(
        "RAD базы жиклёра, %", max_digits=4, decimal_places=1, null=True, blank=True,
        help_text="Плотность воздуха, при которой верны «Базы жиклёра по классу» ниже. Приложение пересчитывает "
                  "жиклёр под погоду сессии по формуле Rotax MAX Jetting: база × (1 + √(RAD сейчас / RAD базы)) / 2. "
                  "У Rotax базы заданы при стандартной атмосфере (15 °C, 1013 гПа, уровень моря): 100. "
                  "Пусто — без пересчёта.",
    )
    app_jet_step = models.PositiveSmallIntegerField(
        "Шаг номеров жиклёра", default=1,
        help_text="Округление пересчитанного жиклёра: 1 — до целого номера (как в Rotax MAX Jetting), "
                  "2 — через номер от базового.",
    )
    app_race_classes = ParentalManyToManyField(
        'website.RaceClass', blank=True, related_name='app_engines', verbose_name="Классы в приложении",
        help_text="Классы, которые пользователь сможет выбрать с этим двигателем.",
    )
    app_carburetor_image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        verbose_name="Картинка карбюратора",
        help_text="Показывается в приложении по центру раздела «Карбюратор», над настройками. Своё фото или "
                  "схема (не из других приложений). Пусто — раздел без картинки.",
    )

    panels = [
        FieldPanel('name'),
        FieldPanel('slug'),
        FieldPanel('country'),
        FieldPanel('logo'),
        FieldPanel('description'),
        FieldPanel('website'),
    ]

    app_panels = [
        FieldPanel('show_in_app'),
        FieldPanel('app_family'),
        FieldPanel('app_electric'),
        FieldPanel('app_race_classes', widget=forms.CheckboxSelectMultiple),
        FieldPanel('app_carburetor_image'),
        FieldPanel('app_fuel_mix_ratio'),
        MultiFieldPanel([FieldPanel('app_jet_base_rad'), FieldPanel('app_jet_step')], heading="Жиклёр по погоде"),
        InlinePanel('app_float_models', label="Модификация (поплавковый карбюратор)",
                    help_text="Жиклёр, игла и воздушный винт по плотности воздуха (модель JetLab для Rotax EVO). "
                              "Пусто — без этой подсказки."),
        InlinePanel('app_vhsh_variants', label="Модель (карбюратор VHSH)",
                    help_text="Dell'Orto VHSH по погоде (модель JetLab для TM KZ): модель двигателя — поправка и "
                              "значения по умолчанию. Нужны и «Настройки VHSH». Пусто — без подсказки."),
        InlinePanel('app_vhsh_setups', label="Настройка VHSH",
                    help_text="Базовые настройки карбюратора: каждый канал — A × плотность + B. Пилот выбирает "
                              "настройку в приложении."),
        MultiFieldPanel([FieldPanel('app_screw_long_straight_pct'), FieldPanel('app_screw_short_straight_pct')],
                        heading="Винты High/Low по погоде (мембранный карбюратор)"),
        InlinePanel('app_screw_models', label="Модификация",
                    help_text="Коэффициенты расчёта винтов High/Low, давления открытия и выхлопа по плотности "
                              "воздуха. Пусто — без подсказки."),
        InlinePanel('app_jet_bases', label="База жиклёра по классу",
                    help_text="Жиклёр класса при «RAD базы». «Старая версия» — для двигателей прежнего выпуска "
                              "(в приложении галочка у двигателя); пусто — как у текущей версии."),
        InlinePanel('app_fields', label="Поле карбюратора",
                    help_text="Числа — минимум, максимум и шаг; остальное — список (по одному значению в строке)."),
        InlinePanel('app_spark_plugs', label="Свеча"),
        InlinePanel('app_class_presets', label="Рекомендация по классу",
                    help_text="Рекомендации производителя для класса: в приложении — значение по умолчанию "
                              "и подсказка у поля. Поле должно быть среди полей карбюратора выше."),
    ]
    edit_handler = TabbedInterface([
        ObjectList(panels, heading="Основное"),
        ObjectList(app_panels, heading="Приложение"),
    ])

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
