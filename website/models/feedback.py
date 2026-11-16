"""Обращения, категории, шаги, сообщения и вложения."""

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

from .content import FEEDBACK_CHANNEL_CHOICES, FEEDBACK_CHANNEL_TELEGRAM
from .site_settings import VpnSettings


class FeedbackBotSettings(models.Model):
    """Singleton настроек бота обратной связи. FeedbackBotSettings.get().

    Токен хранится шифртекстом (Fernet, ключ — FEEDBACK_FERNET_KEY в env),
    в админке маскируется; пустое значение при сохранении формы = «не менять».
    Адрес прокси — централизованно в VpnSettings, здесь только галочка."""

    is_enabled = models.BooleanField('Бот включён', default=False)
    bot_token_encrypted = models.TextField('Токен бота (шифртекст)', blank=True, editable=False)
    bot_username = models.CharField(
        'Юзернейм бота', max_length=64, blank=True, default='gripline_support_bot',
        help_text='Без @. Telegram требует, чтобы юзернейм бота заканчивался на «bot». '
                  'Используется в deep links с сайта.',
    )
    use_vpn = models.BooleanField(
        'Использовать Xray/VPN', default=True,
        help_text='Прод блокирует прямые соединения к api.telegram.org. Адрес прокси — '
                  'в разделе «VPN» (VpnSettings), не здесь. Снять галочку = прямое соединение.',
    )
    admin_chat_id = models.BigIntegerField(
        'ID админ-чата', null=True, blank=True,
        help_text='Закрытая супергруппа модерации (отрицательное число вида -100…). '
                  'Для тем по категориям в группе должны быть включены «Темы».',
    )
    settings_refresh_sec = models.PositiveIntegerField(
        'Период перечитывания настроек, сек', default=60,
        help_text='Минимум 10. Тексты, лимиты и сценарии применяются без перезапуска.',
    )
    rate_limit_per_hour = models.PositiveIntegerField('Лимит обращений в час', default=5)
    max_text_length = models.PositiveIntegerField('Макс. длина ответа, символов', default=2000)
    max_file_size_mb = models.PositiveIntegerField(
        'Макс. размер вложения, МБ', default=10,
        help_text='Потолок Bot API на скачивание — 20 МБ.',
    )
    max_files_per_feedback = models.PositiveIntegerField('Макс. вложений в обращении', default=3)
    allowed_file_types = models.CharField(
        'Допустимые типы файлов', max_length=255, default='jpg, jpeg, png, webp, pdf',
        help_text='Через запятую. Тип проверяется по содержимому, не по расширению.',
    )
    retention_months = models.PositiveIntegerField(
        'Срок хранения персональных данных, мес.', default=12,
        help_text='После срока обращения анонимизируются командой feedback_cleanup.',
    )
    privacy_policy_url = models.URLField(
        'Ссылка на политику конфиденциальности', blank=True,
        default='https://gripline.ru/legal/privacy/',
    )
    digest_enabled = models.BooleanField(
        'Утренняя сводка включена', default=True,
        help_text='Сводка уходит в админ-чат: что требует внимания, что нового за сутки, состояние системы.',
    )
    digest_time = models.TimeField(
        'Время отправки сводки', default=datetime.time(9, 0),
        help_text='По московскому времени. Проверка идёт каждые 10 минут, поэтому сводка придёт в ближайшие 10 минут после этого времени.',
    )
    digest_last_sent_on = models.DateField('Сводка последний раз отправлена', null=True, blank=True, editable=False)
    restart_requested_at = models.DateTimeField('Перезапуск запрошен', null=True, blank=True, editable=False)
    heartbeat_at = models.DateTimeField('Последний heartbeat бота', null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Настройки бота обратной связи'
        verbose_name_plural = 'Настройки бота обратной связи'

    def __str__(self):
        return 'Бот обратной связи' + ('' if self.is_enabled else ' (выключен)')

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        super().clean()
        if self.settings_refresh_sec is not None and self.settings_refresh_sec < 10:
            raise ValidationError({'settings_refresh_sec': 'Минимум 10 секунд.'})
        if self.max_file_size_mb is not None and self.max_file_size_mb > 20:
            raise ValidationError({'max_file_size_mb': 'Bot API отдаёт файлы до 20 МБ.'})

    # --- токен ---
    def set_token(self, plain):
        from website.feedback import crypto
        self.bot_token_encrypted = crypto.encrypt(plain.strip())

    def get_token(self):
        from website.feedback import crypto
        return crypto.decrypt(self.bot_token_encrypted)

    def token_mask(self):
        from website.feedback import crypto
        return crypto.mask_token(self.get_token())

    def allowed_types_list(self):
        return [t.strip().lower().lstrip('.') for t in self.allowed_file_types.split(',') if t.strip()]

    def proxy_url(self):
        """URL прокси к использованию или None (прямое соединение)."""
        return VpnSettings.get().effective_url() if self.use_vpn else None


class FeedbackCategory(ClusterableModel):
    slug = models.SlugField('Слаг', max_length=40, unique=True)
    title = models.CharField('Название', max_length=100)
    emoji = models.CharField('Эмодзи', max_length=8, blank=True)
    sort_order = models.PositiveIntegerField(
        'Порядок', default=10,
        help_text='Чем меньше число, тем выше пункт. Порядок общий: в меню бота и в виджете «Обратная связь» на сайте. '
                  'Удобно нумеровать с шагом 10 — чтобы потом вставить новый пункт между старыми.',
    )
    is_active = models.BooleanField('Активна', default=True)
    admin_topic_id = models.BigIntegerField(
        'ID темы в админ-чате', null=True, blank=True,
        help_text='Пусто = общий чат. Заполняется кнопкой «Создать темы по категориям».',
    )
    widget_hint = models.CharField(
        'Подсказка в виджете на сайте', max_length=120, blank=True,
        help_text='Короткая строка под названием в окне «Обратная связь» на сайте.',
    )
    deep_link_code = models.SlugField(
        'Код для deep link', max_length=10, blank=True,
        help_text='Короткий код (например, err) для ссылки t.me/<бот>?start=err_s_142. '
                  'Только латиница/цифры.',
    )

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Категория обращений'
        verbose_name_plural = 'Категории обращений'

    def __str__(self):
        return f'{self.emoji} {self.title}'.strip()

    def clean(self):
        super().clean()
        if self.deep_link_code and not self.deep_link_code.isalnum():
            raise ValidationError({'deep_link_code': 'Только латинские буквы и цифры (без _ и -).'})


class FeedbackStep(Orderable):
    # sort_order — из Orderable (порядок шагов перетаскиванием в админке)
    TYPE_TEXT = 'text'
    TYPE_ATTACHMENT = 'attachment'
    TYPE_CHOICES = [(TYPE_TEXT, 'Текст'), (TYPE_ATTACHMENT, 'Вложение')]

    category = ParentalKey(FeedbackCategory, on_delete=models.CASCADE, related_name='steps', verbose_name='Категория')
    key = models.SlugField('Ключ', max_length=40, help_text='Ключ ответа в карточке и JSON (например, where).')
    prompt_text = models.TextField('Вопрос пользователю')
    type = models.CharField('Тип', max_length=12, choices=TYPE_CHOICES, default=TYPE_TEXT)
    is_required = models.BooleanField('Обязательный', default=True)
    skip_button_text = models.CharField(
        'Текст кнопки «Пропустить»', max_length=40, blank=True,
        help_text='Пусто = пропуск невозможен.',
    )
    skip_if_source_set = models.BooleanField(
        'Пропускать, если обращение пришло по ссылке с объектом', default=False,
    )

    class Meta(Orderable.Meta):
        verbose_name = 'Шаг сценария'
        verbose_name_plural = 'Шаги сценария'
        unique_together = [('category', 'key')]

    def __str__(self):
        return f'{self.category.slug}/{self.key}'


class FeedbackText(models.Model):
    """Редактируемые тексты бота. Ключи — website/feedback/texts.py::DEFAULT_TEXTS."""
    key = models.CharField('Ключ', max_length=40, unique=True, editable=False)
    text = models.TextField('Текст')
    description = models.CharField('Назначение', max_length=255, blank=True, editable=False)

    class Meta:
        ordering = ['key']
        verbose_name = 'Текст бота'
        verbose_name_plural = 'Тексты бота'

    def __str__(self):
        return self.key


class FeedbackModerator(models.Model):
    ROLE_MODERATOR = 'moderator'
    ROLE_CHOICES = [(ROLE_MODERATOR, 'Модератор')]

    channel = models.CharField('Канал', max_length=20, choices=FEEDBACK_CHANNEL_CHOICES, default=FEEDBACK_CHANNEL_TELEGRAM)
    external_user_id = models.CharField('ID пользователя в канале', max_length=64, help_text='Telegram user id (число).')
    name = models.CharField('Имя', max_length=100)
    is_active = models.BooleanField('Активен', default=True)
    role = models.CharField('Роль', max_length=20, choices=ROLE_CHOICES, default=ROLE_MODERATOR)

    class Meta:
        verbose_name = 'Модератор обращений'
        verbose_name_plural = 'Модераторы обращений'
        unique_together = [('channel', 'external_user_id')]

    def __str__(self):
        return self.name


class FeedbackUser(models.Model):
    channel = models.CharField(max_length=20, choices=FEEDBACK_CHANNEL_CHOICES, default=FEEDBACK_CHANNEL_TELEGRAM)
    external_user_id = models.CharField('ID в канале', max_length=64)
    username = models.CharField('Username', max_length=64, blank=True)
    display_name = models.CharField('Имя', max_length=200, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    privacy_notice_shown_at = models.DateTimeField(null=True, blank=True)
    is_banned = models.BooleanField('Заблокирован', default=False)
    ban_reason = models.CharField('Причина блокировки', max_length=255, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Пользователь бота'
        verbose_name_plural = 'Пользователи бота'
        unique_together = [('channel', 'external_user_id')]

    def __str__(self):
        return f'@{self.username}' if self.username else (self.display_name or self.external_user_id)


class Feedback(models.Model):
    STATUS_NEW = 'new'
    STATUS_IN_WORK = 'in_work'
    STATUS_DONE = 'done'
    STATUS_CHOICES = [(STATUS_NEW, 'Новое'), (STATUS_IN_WORK, 'В работе'), (STATUS_DONE, 'Закрыто')]

    SOURCE_STAGE = 'stage'
    SOURCE_PILOT = 'pilot'
    SOURCE_TRACK = 'track'
    SOURCE_CHAMP = 'champ'
    SOURCE_HUB = 'hub'
    SOURCE_RATING = 'rating'
    SOURCE_CHOICES = [
        (SOURCE_STAGE, 'Этап (класс)'), (SOURCE_PILOT, 'Пилот'), (SOURCE_TRACK, 'Трасса'),
        (SOURCE_CHAMP, 'Чемпионат'), (SOURCE_HUB, 'Этап (общая страница)'), (SOURCE_RATING, 'Рейтинг (класс)'),
    ]

    # id — публичный номер обращения (№123)
    user = models.ForeignKey(FeedbackUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='feedbacks', verbose_name='Пользователь')
    category = models.ForeignKey(FeedbackCategory, null=True, on_delete=models.SET_NULL, related_name='feedbacks', verbose_name='Категория')
    answers = models.JSONField('Ответы', default=dict, blank=True)
    source_kind = models.CharField('Источник (тип)', max_length=10, choices=SOURCE_CHOICES, blank=True)
    source_id = models.PositiveIntegerField('Источник (PK)', null=True, blank=True)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True)
    assigned_to = models.ForeignKey(FeedbackModerator, null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned', verbose_name='Взял в работу')
    admin_note = models.TextField('Внутренняя заметка', blank=True)
    admin_chat_message_id = models.BigIntegerField(null=True, blank=True, editable=False)
    admin_thread_id = models.BigIntegerField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)
    closed_at = models.DateTimeField('Закрыто', null=True, blank=True)
    anonymized_at = models.DateTimeField('Анонимизировано', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Обращение'
        verbose_name_plural = 'Обращения'

    def __str__(self):
        return f'№{self.pk}'


class FeedbackDraft(models.Model):
    """Состояние сценария пользователя. Живёт в БД, а не в памяти — переживает
    перезапуски бота. Незавершённые черновики чистятся через 24 часа."""
    user = models.OneToOneField(FeedbackUser, on_delete=models.CASCADE, related_name='draft')
    category = models.ForeignKey(FeedbackCategory, on_delete=models.CASCADE)
    step_index = models.PositiveIntegerField(default=0)
    answers = models.JSONField(default=dict, blank=True)
    source_kind = models.CharField(max_length=10, blank=True)
    source_id = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Черновик обращения'
        verbose_name_plural = 'Черновики обращений'


def _feedback_attachment_storage():
    from website.feedback.storage import private_storage
    return private_storage()


def _feedback_attachment_path(instance, filename):
    from website.feedback.storage import attachment_upload_path
    return attachment_upload_path(instance, filename)


class FeedbackAttachment(models.Model):
    feedback = models.ForeignKey(Feedback, null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    draft = models.ForeignKey(FeedbackDraft, null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to=_feedback_attachment_path, storage=_feedback_attachment_storage, max_length=255)
    original_name = models.CharField(max_length=255, blank=True)
    mime = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Вложение обращения'
        verbose_name_plural = 'Вложения обращений'

    def __str__(self):
        return self.original_name or self.file.name


class FeedbackMessage(models.Model):
    DIR_IN = 'in'
    DIR_OUT = 'out'
    DIRECTION_CHOICES = [(DIR_IN, 'От пользователя'), (DIR_OUT, 'От модератора')]

    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name='messages')
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    moderator = models.ForeignKey(FeedbackModerator, null=True, blank=True, on_delete=models.SET_NULL)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    delivered = models.BooleanField(default=False)
    # id сообщения в админ-чате — по нему reply модератора находит обращение
    admin_chat_message_id = models.BigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['created_at', 'id']
        verbose_name = 'Сообщение по обращению'
        verbose_name_plural = 'Сообщения по обращениям'


# ==================== ГЛАВНАЯ СТРАНИЦА АДМИНКИ (дашборд) ====================
# Панели и проверки — website/dashboard/. Здесь только то, что нужно хранить.
