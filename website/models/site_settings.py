"""Соцсети, Telegram/MAX/VK, погода, почта и VPN."""

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


class SocialTag(models.Model):
    """
    Тег для анонс-постинга в соцсети (Telegram, MAX и др.) — общий на все
    каналы. Список произвольной длины, редактируется в Wagtail Admin →
    Интеграции → Теги.

    Категория — это ссылка на конкретную родительскую страницу (например,
    страницу «Матчасть» или «Новости»), а не жёстко зашитый список — так
    при появлении нового раздела сайта ему можно назначить тег без правки
    кода, и привязка существующих тегов (например, «Матчасть») не зашита
    в коде и может быть переназначена через админку.
    """

    tag = models.CharField(
        max_length=32,
        verbose_name="Тег",
        help_text="Например: #юниоры",
    )
    emoji = models.CharField(
        max_length=8,
        blank=True,
        verbose_name="Эмодзи",
        help_text="Например: 🔧. Необязательно, показывается перед тегом в посте.",
    )
    parent_page = models.ForeignKey(
        Page,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Раздел",
        help_text=(
            "Родительская страница, в которой должны быть статьи, чтобы получить "
            "этот тег (например, Матчасть или Новости). Если не выбрана — тег "
            "публикуется на всех постах."
        ),
        related_name='social_tags',
    )

    class Meta:
        verbose_name = "Тег соцсетей"
        verbose_name_plural = "Теги соцсетей"
        ordering = ['parent_page', 'tag']

    def __str__(self):
        return self.tag


class TelegramSettings(models.Model):
    """
    Singleton-модель настроек анонс-постинга в Telegram-канал.
    Доступна через TelegramSettings.get().
    Токен бота НЕ хранится здесь — только в переменной окружения
    TELEGRAM_ANNOUNCE_BOT_TOKEN (см. website/telegram.py).
    Теги — в отдельной общей модели SocialTag (общая для всех соцсетей), не здесь.
    """

    channel_id = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="Channel ID",
        help_text="Например: @gripline_channel или числовой chat_id.",
    )
    link_text = models.CharField(
        max_length=64,
        default="Читать статью →",
        verbose_name="Текст ссылки на статью",
        help_text="Показывается вместо длинного URL в тексте поста.",
    )
    use_vpn = models.BooleanField(
        default=True,
        verbose_name="Использовать Xray/VPN",
        help_text=(
            "Хостинг блокирует прямые соединения к api.telegram.org — без "
            "этого анонс-постинг не работает. Адрес прокси — в разделе "
            "«VPN» (VpnSettings), не здесь. Включено по умолчанию — "
            "повторяет текущее рабочее поведение."
        ),
    )

    class Meta:
        verbose_name = "Настройки Telegram"
        verbose_name_plural = "Настройки Telegram"

    def __str__(self):
        return "Настройки Telegram-канала"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MaxSettings(models.Model):
    """
    Singleton-модель настроек анонс-постинга в канал MAX.
    Доступна через MaxSettings.get().
    Токен бота НЕ хранится здесь — только в переменной окружения
    MAX_ANNOUNCE_BOT_TOKEN (см. website/max.py).
    Теги — в отдельной общей модели SocialTag (общая для всех соцсетей), не здесь.
    """

    chat_id = models.CharField(
        max_length=32,
        blank=True,
        verbose_name="Chat ID",
        help_text=(
            "Числовой ID канала MAX. В отличие от Telegram, у MAX нет @username — "
            "id получается одноразовой командой 'python manage.py max_get_chat_id' "
            "после того как бот добавлен администратором в канал."
        ),
    )
    link_text = models.CharField(
        max_length=64,
        default="Читать статью →",
        verbose_name="Текст ссылки на статью",
        help_text="Показывается вместо длинного URL в тексте поста.",
    )

    class Meta:
        verbose_name = "Настройки MAX"
        verbose_name_plural = "Настройки MAX"

    def __str__(self):
        return "Настройки MAX-канала"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class VkSettings(models.Model):
    """
    Singleton-модель настроек анонс-постинга в сообщество VK.
    Доступна через VkSettings.get().
    Токен доступа НЕ хранится здесь — только в переменной окружения
    VK_ANNOUNCE_ACCESS_TOKEN (см. website/vk.py).
    Теги — в отдельной общей модели SocialTag (общая для всех соцсетей), не здесь.
    """

    group_id = models.CharField(
        max_length=32,
        blank=True,
        verbose_name="Group ID",
        help_text=(
            "Числовой ID сообщества VK (без минуса). Получается одноразовой "
            "командой 'python manage.py vk_get_group_id --screen-name gripline'."
        ),
    )
    link_text = models.CharField(
        max_length=64,
        default="Читать статью →",
        verbose_name="Текст ссылки на статью",
        help_text="Показывается вместо длинного URL в тексте поста.",
    )

    class Meta:
        verbose_name = "Настройки VK"
        verbose_name_plural = "Настройки VK"

    def __str__(self):
        return "Настройки VK-сообщества"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class WeatherWidgetSnapshot(models.Model):
    """Погодный виджет этапа/группы, посчитанный заранее (11.10.2026). Страницы только читают эту таблицу;
    Open-Meteo опрашивает cron-команда refresh_weather_widgets — иначе недоступный сервис при рендере
    главной вешал воркер gunicorn (Internal Server Error). Не кэш: clear_wagtail_cache его не стирает."""
    namespace = models.CharField(max_length=16)  # 'stage' (StagePage) | 'group' (RaceClassResultGroup)
    object_id = models.PositiveIntegerField()
    target_date = models.DateField()
    category = models.CharField(max_length=16)  # archive | forecast | estimate
    data = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Погодный виджет (снимок)"
        verbose_name_plural = "Погодные виджеты (снимки)"
        constraints = [models.UniqueConstraint(fields=['namespace', 'object_id', 'target_date'],
                                               name='weather_snapshot_unique')]

    def __str__(self):
        return f"{self.namespace}:{self.object_id} {self.target_date} ({self.category})"


class WeatherSettings(models.Model):
    """
    Singleton-модель настроек погодного виджета Open-Meteo.
    Доступна через WeatherSettings.get().
    Раньше значения были захардкожены в website/weather_utils.py
    (ARCHIVE_API_URL, FORECAST_API_URL, FORECAST_HORIZON_DAYS,
    CLIMATOLOGY_YEARS, DAY_START_HOUR, DAY_END_HOUR, timezone "Europe/Moscow"
    в двух местах) — вынесены сюда, чтобы менять без деплоя.
    """

    archive_api_url = models.URLField(
        default="https://archive-api.open-meteo.com/v1/archive",
        verbose_name="URL архивного API",
        help_text="Исторические данные — для прошедших этапов.",
    )
    forecast_api_url = models.URLField(
        default="https://api.open-meteo.com/v1/forecast",
        verbose_name="URL API прогноза",
        help_text="Прогноз — для этапов в пределах горизонта прогноза.",
    )
    timezone = models.CharField(
        max_length=64,
        default="Europe/Moscow",
        verbose_name="Часовой пояс",
        help_text="Передаётся в Open-Meteo как параметр timezone (IANA-имя).",
    )
    forecast_horizon_days = models.PositiveSmallIntegerField(
        default=15,
        verbose_name="Горизонт прогноза, дней",
        help_text="За пределами — используется статистическая оценка по прошлым годам.",
    )
    climatology_years = models.PositiveSmallIntegerField(
        default=5,
        verbose_name="Лет для статистической оценки",
        help_text="Сколько прошлых лет усредняется для оценки погоды, если этап дальше горизонта прогноза.",
    )
    day_start_hour = models.PositiveSmallIntegerField(
        default=9,
        verbose_name="Начало дня, час",
        help_text="Нижняя граница часового диапазона для сводки погоды на день этапа.",
    )
    day_end_hour = models.PositiveSmallIntegerField(
        default=18,
        verbose_name="Конец дня, час",
        help_text="Верхняя граница часового диапазона для сводки погоды на день этапа.",
    )
    use_vpn = models.BooleanField(
        default=True,
        verbose_name="Использовать Xray/VPN",
        help_text=(
            "С сервера соединения с Open-Meteo (Hetzner) то проходят, то обрываются — через прокси стабильно "
            "(11.10.2026). Адрес прокси — в разделе «VPN»."
        ),
    )

    class Meta:
        verbose_name = "Настройки погоды"
        verbose_name_plural = "Настройки погоды"

    def __str__(self):
        return "Настройки погодного виджета"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TrackPageSettings(models.Model):
    """Singleton: общие настройки страницы трассы для всех трасс (TrackPageSettings.get()).
    Сохранение сбрасывает кэш страниц /tracks/ (signals.py)."""

    kart_scale = models.FloatField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name="Размер карта в 3D",
        help_text=(
            "Во сколько раз метка-карт в 3D больше настоящего (1,85 м). 1 — настоящий размер, "
            "3 — около 5,6 м. В виде «Обзор» трасса около километра, и карт настоящего размера там не разглядеть."
        ),
    )

    class Meta:
        verbose_name = "Настройки страницы трассы"
        verbose_name_plural = "Настройки страницы трассы"

    def __str__(self):
        return "Настройки страницы трассы"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MailSettings(models.Model):
    """
    Singleton-модель настроек исходящей почты приложения.
    Доступна через MailSettings.get(), фактически применяется через
    website.mail.DBConfiguredEmailBackend (см. EMAIL_BACKEND в settings/base.py
    и prod.py) — бэкенд читает эту модель при КАЖДОЙ отправке, не при старте
    процесса, поэтому правка здесь действует мгновенно, без рестарта gunicorn.

    Вынесено в админку 22.09.2026 по ТЗ gripline_tz_zaschita_pochty.md —
    компрометация ящика gripline.ru@yandex.ru (сторонняя спам-рассылка через
    валидный DKIM Яндекса). host_user/host_password/default_from_email пустые
    по умолчанию — падают обратно на settings.EMAIL_HOST_USER/PASSWORD/
    DEFAULT_FROM_EMAIL (переменные окружения), поэтому сам факт добавления
    этой модели не меняет поведение прода, пока админ не заполнит поле сам.
    host/port/use_tls/use_ssl/timeout — DB-авторитетны сразу (дефолты
    повторяют текущий prod.py), это не секреты.

    enabled — кил-свитч: False мгновенно останавливает всю исходящую почту
    приложения (see DBConfiguredEmailBackend.send_messages) без исключений
    наружу — на случай повторной компрометации, чтобы не ждать деплоя.

    use_proxy — только галочка «использовать Xray/VPN»; сам адрес прокси
    централизован в VpnSettings (см. ниже), не дублируется здесь.
    """

    enabled = models.BooleanField(
        default=True,
        verbose_name="Отправка писем включена",
        help_text=(
            "Кил-свитч. Выключить — немедленно останавливает всю исходящую "
            "почту приложения (уведомления, письма подтверждения) без деплоя. "
            "Использовать при компрометации почтового ящика."
        ),
    )
    host = models.CharField(
        max_length=255,
        default="smtp.yandex.ru",
        verbose_name="SMTP host",
    )
    port = models.PositiveIntegerField(
        default=587,
        verbose_name="SMTP порт",
    )
    use_tls = models.BooleanField(
        default=True,
        verbose_name="STARTTLS (use_tls)",
        help_text="Для порта 587. Взаимоисключимо с SSL ниже.",
    )
    use_ssl = models.BooleanField(
        default=False,
        verbose_name="SSL (use_ssl)",
        help_text="Для порта 465. Взаимоисключимо с STARTTLS выше.",
    )
    timeout = models.PositiveIntegerField(
        default=5,
        verbose_name="Таймаут соединения, сек",
    )
    use_proxy = models.BooleanField(
        default=False,
        verbose_name="Использовать Xray/VPN",
        help_text=(
            "По умолчанию выключено — прямое соединение. IP сервера внесён "
            "в белый список хостинг-провайдера по SMTP (587/465), поэтому "
            "включать прокси в норме не требуется. Адрес прокси — в разделе "
            "«VPN» (VpnSettings), не здесь. Переключается без деплоя — "
            "оставлено как аварийный рубильник на случай повторной "
            "блокировки в будущем."
        ),
    )
    host_user = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Логин SMTP (адрес ящика)",
        help_text="Пусто = переменная окружения EMAIL_HOST_USER на сервере.",
    )
    host_password = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Пароль SMTP",
        help_text=(
            "Пусто = переменная окружения EMAIL_HOST_PASSWORD на сервере. "
            "Хранится в БД открытым текстом (как yandex_client_secret у "
            "SocialAuthSettings) — доступ только у пользователей с правами "
            "в Wagtail admin."
        ),
    )
    default_from_email = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="From (адрес отправителя)",
        help_text='Пусто = settings.DEFAULT_FROM_EMAIL. Формат: "Gripline <адрес@домен>".',
    )
    admin_notify_email = models.EmailField(
        blank=True,
        verbose_name="Адрес для уведомлений администратору",
        help_text=(
            "Куда падают уведомления о новых заявках (привязка пилота/команды). "
            "Пусто = gripline.ru@yandex.ru (прежнее поведение)."
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки почты"
        verbose_name_plural = "Настройки почты"

    def __str__(self):
        return "Настройки исходящей почты" if self.enabled else "Настройки исходящей почты (ВЫКЛЮЧЕНА)"

    def clean(self):
        super().clean()
        if self.use_tls and self.use_ssl:
            raise ValidationError(
                "STARTTLS (use_tls) и SSL (use_ssl) взаимоисключимы — "
                "включите только одно из двух (587+STARTTLS либо 465+SSL). "
                "Обе галочки разом роняют отправку письма с необрабатываемым "
                "исключением ДО проверки кил-свитча «Отправка писем включена»."
            )

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class VpnSettings(models.Model):
    """
    Singleton — единственное место, где живёт адрес локального SOCKS5-
    прокси (Xray/VPN-туннель). Централизовано 22.09.2026 по просьбе
    пользователя: раньше каждая интеграция (Telegram, потом Почта) хранила
    свой собственный proxy_url — теперь у интеграций только галочка
    «Использовать Xray/VPN» (TelegramSettings.use_vpn, MailSettings.use_proxy),
    сам адрес — здесь и только здесь, не дублируется по разделам админки.

    Сами настройки VLESS/Reality-туннеля (UUID, ключи Reality, адрес
    VPN-сервера) живут ВНЕ Django — /usr/local/etc/xray/config.json на
    сервере, права 600, не в git и не в БД (см. память
    project_gripline_telegram_proxy). Здесь хранится только локальный адрес
    SOCKS5-листенера Xray (127.0.0.1:10808) — сам по себе не секрет, Xray
    слушает localhost без авторизации.
    """

    proxy_url = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="URL SOCKS5-прокси",
        help_text=(
            "Локальный SOCKS5-листенер Xray на сервере. Пусто = переменная "
            "окружения TELEGRAM_PROXY_URL (историческое имя — прокси заводился "
            "изначально только для Telegram). Формат: socks5h://host:port."
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки VPN"
        verbose_name_plural = "Настройки VPN"

    def __str__(self):
        return f"VPN-прокси: {self.proxy_url}" if self.proxy_url else "VPN-прокси не задан"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def effective_url(self):
        """URL прокси к использованию — DB-значение или fallback на
        переменную окружения TELEGRAM_PROXY_URL."""
        from django.conf import settings
        return self.proxy_url or getattr(settings, 'TELEGRAM_PROXY_URL', None)


# ==================== РАЗВЕСОВКА (Balance) — справочники ====================
#
# Все числа ниже (геометрия по умолчанию, минимальные веса классов, пороги
# цветовой индикации) — регламентные величины РАФ и общеотраслевые нормы,
# которые меняются между сезонами и не должны жить в коде/миграциях.
# Заполняются и правятся через админку («Развесовка» в боковом меню,
# см. website/wagtail_hooks.py) — не хардкодить конкретные значения нигде
# в balance-приложении.
