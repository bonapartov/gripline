"""
Привязка Telegram к аккаунту для уведомлений (напоминания о документах и т.п.).

Бот не может написать человеку первым, номер телефона тут не помогает: человек сам
нажимает «Подключить Telegram» в ЛК → t.me/<бот обратной связи>?start=link-<код> → бот
получает /start с кодом и запоминает его Telegram ID в UserProfile. Код одноразовый,
живёт LINK_TTL. За несовершеннолетнего подключает родитель из аккаунта ребёнка — тогда
сообщения приходят родителю; один Telegram можно подключить к нескольким аккаунтам.
"""
import secrets
from datetime import timedelta

from django.utils import timezone

PREFIX = 'link-'
LINK_TTL = timedelta(hours=1)


def bot_username():
    from website.models import FeedbackBotSettings
    cfg = FeedbackBotSettings.get()
    return cfg.bot_username.strip().lstrip('@') if cfg.is_enabled else ''


def start_link(profile):
    """Ссылка на бота с новым кодом или None, если бот выключен."""
    username = bot_username()
    if not username:
        return None
    profile.telegram_link_token = secrets.token_urlsafe(24)
    profile.telegram_link_created_at = timezone.now()
    profile.save(update_fields=['telegram_link_token', 'telegram_link_created_at'])
    return f'https://t.me/{username}?start={PREFIX}{profile.telegram_link_token}'


def complete_link(start_param, telegram_id):
    """/start link-<код> из бота → профиль или None (код неверный или устарел)."""
    from .models import UserProfile
    token = (start_param or '')[len(PREFIX):]
    if not (start_param or '').startswith(PREFIX) or len(token) < 16:
        return None
    profile = UserProfile.objects.filter(telegram_link_token=token).select_related('user').first()
    if profile is None or not profile.telegram_link_created_at \
            or timezone.now() - profile.telegram_link_created_at > LINK_TTL:
        return None
    profile.telegram_id = telegram_id
    profile.telegram_notifications = True
    profile.telegram_link_token = ''
    profile.telegram_link_created_at = None
    profile.save(update_fields=['telegram_id', 'telegram_notifications',
                                'telegram_link_token', 'telegram_link_created_at'])
    return profile


def is_link_param(start_param):
    return (start_param or '').startswith(PREFIX)


def unlink(profile):
    profile.telegram_id = None
    profile.telegram_notifications = False
    profile.save(update_fields=['telegram_id', 'telegram_notifications'])
