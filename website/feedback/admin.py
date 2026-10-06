"""Wagtail-админка бота обратной связи: раздел «Обратная связь» в боковом меню."""
import re

from django import forms
from django.contrib.admin.utils import quote
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel, ObjectList
from wagtail_modeladmin.helpers import PermissionHelper
from wagtail_modeladmin.options import ModelAdmin, ModelAdminGroup
from wagtail_modeladmin.views import IndexView

from website.feedback import crypto
from website.models import (
    Feedback, FeedbackAttachment, FeedbackBotSettings, FeedbackCategory,
    FeedbackModerator, FeedbackText, FeedbackUser,
)

TOKEN_RE = re.compile(r'^\d{5,}:[A-Za-z0-9_-]{20,}$')


class FeedbackBotSettingsForm(WagtailAdminModelForm):
    new_bot_token = forms.CharField(
        label='Токен бота', required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password', 'placeholder': 'Не менять'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        mask = ''
        try:
            mask = self.instance.token_mask() if self.instance.pk else ''
        except crypto.CryptoConfigError:
            pass
        self.fields['new_bot_token'].help_text = (
            f'Сейчас: {mask}. ' if mask else 'Токен не задан. '
        ) + 'Оставьте поле пустым, чтобы не менять. В БД токен хранится шифртекстом.'

    def clean_new_bot_token(self):
        value = (self.cleaned_data.get('new_bot_token') or '').strip()
        if not value:
            return ''
        if not TOKEN_RE.match(value):
            raise forms.ValidationError('Это не похоже на токен бота (формат 123456:AA…).')
        try:
            crypto.encrypt(value)
        except crypto.CryptoConfigError as exc:
            raise forms.ValidationError(str(exc))
        return value

    def save(self, commit=True):
        obj = super().save(commit=False)
        token = self.cleaned_data.get('new_bot_token')
        if token:
            obj.set_token(token)
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class SingletonIndexView(IndexView):
    """У singleton-настроек нет списка: сразу открываем форму редактирования."""
    def dispatch(self, request, *args, **kwargs):
        obj = self.model.get()
        return redirect(self.url_helper.get_action_url('edit', quote(obj.pk)))


class ReadOnlyCreatePermissionHelper(PermissionHelper):
    """Записи создаёт бот (или data-миграция) — «Добавить» в админке не нужен."""
    def user_can_create(self, user):
        return False


class SingletonPermissionHelper(ReadOnlyCreatePermissionHelper):
    def user_can_delete_obj(self, user, obj):
        return False


class FeedbackBotSettingsAdmin(ModelAdmin):
    model = FeedbackBotSettings
    menu_label = 'Настройки бота'
    menu_icon = 'cog'
    index_view_class = SingletonIndexView
    permission_helper_class = SingletonPermissionHelper
    edit_template_name = 'feedback/admin/settings_edit.html'
    edit_handler = ObjectList(
        [
            MultiFieldPanel([
                FieldPanel('is_enabled'),
                FieldPanel('new_bot_token'),
                FieldPanel('bot_username'),
                FieldPanel('use_vpn'),
                FieldPanel('admin_chat_id'),
            ], heading='Подключение'),
            MultiFieldPanel([
                FieldPanel('rate_limit_per_hour'),
                FieldPanel('max_text_length'),
                FieldPanel('max_file_size_mb'),
                FieldPanel('max_files_per_feedback'),
                FieldPanel('allowed_file_types'),
            ], heading='Лимиты'),
            MultiFieldPanel([
                FieldPanel('retention_months'),
                FieldPanel('privacy_policy_url'),
            ], heading='Персональные данные'),
            MultiFieldPanel([
                FieldPanel('settings_refresh_sec'),
            ], heading='Служебное'),
        ],
        base_form_class=FeedbackBotSettingsForm,
    )


class FeedbackAdmin(ModelAdmin):
    model = Feedback
    menu_label = 'Обращения'
    menu_icon = 'mail'
    permission_helper_class = ReadOnlyCreatePermissionHelper
    list_display = ('id', 'category', 'status', 'user', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('id', 'user__username', 'user__display_name', 'messages__text')
    inspect_view_enabled = True
    inspect_template_name = 'feedback/admin/feedback_inspect.html'
    # Содержимое обращения — только просмотр; правятся статус, исполнитель, заметка
    edit_handler = ObjectList([
        FieldPanel('status'), FieldPanel('assigned_to'), FieldPanel('admin_note'),
    ])


class FeedbackCategoryAdmin(ModelAdmin):
    model = FeedbackCategory
    menu_label = 'Категории и шаги'
    menu_icon = 'list-ul'
    list_display = ('title', 'emoji', 'slug', 'sort_order', 'is_active', 'deep_link_code', 'admin_topic_id')
    edit_handler = ObjectList([
        MultiFieldPanel([
            FieldPanel('title'), FieldPanel('emoji'), FieldPanel('slug'),
            FieldPanel('sort_order'), FieldPanel('is_active'),
            FieldPanel('admin_topic_id'), FieldPanel('deep_link_code'),
        ], heading='Категория'),
        InlinePanel('steps', label='Шаг сценария', heading='Шаги (порядок — перетаскиванием)'),
    ])


class FeedbackTextAdmin(ModelAdmin):
    model = FeedbackText
    menu_label = 'Тексты бота'
    menu_icon = 'doc-full'
    permission_helper_class = SingletonPermissionHelper
    list_display = ('key', 'description', 'text')
    search_fields = ('key', 'text', 'description')
    edit_handler = ObjectList([FieldPanel('text')])


class FeedbackModeratorAdmin(ModelAdmin):
    model = FeedbackModerator
    menu_label = 'Модераторы'
    menu_icon = 'group'
    list_display = ('name', 'channel', 'external_user_id', 'is_active', 'role')
    list_filter = ('is_active',)


class FeedbackUserAdmin(ModelAdmin):
    model = FeedbackUser
    menu_label = 'Пользователи бота'
    menu_icon = 'user'
    permission_helper_class = ReadOnlyCreatePermissionHelper
    list_display = ('__str__', 'channel', 'external_user_id', 'is_banned', 'first_seen_at')
    list_filter = ('is_banned',)
    search_fields = ('username', 'display_name', 'external_user_id')
    edit_handler = ObjectList([FieldPanel('is_banned'), FieldPanel('ban_reason')])


class FeedbackGroup(ModelAdminGroup):
    menu_label = 'Обратная связь'
    menu_icon = 'mail'
    menu_order = 350
    items = (
        FeedbackAdmin, FeedbackBotSettingsAdmin, FeedbackCategoryAdmin,
        FeedbackTextAdmin, FeedbackModeratorAdmin, FeedbackUserAdmin,
    )
