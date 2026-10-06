"""
Шифрование токена бота обратной связи (Fernet).

Ключ — settings.FEEDBACK_FERNET_KEY (только окружение). Токен хранится в
БД шифртекстом (FeedbackBotSettings.bot_token_encrypted), расшифровывается
в момент использования и нигде не логируется.
"""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class CryptoConfigError(Exception):
    """FEEDBACK_FERNET_KEY не задан или некорректен."""


def _fernet():
    key = getattr(settings, 'FEEDBACK_FERNET_KEY', None)
    if not key:
        raise CryptoConfigError('FEEDBACK_FERNET_KEY не задан в окружении сервера.')
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise CryptoConfigError('FEEDBACK_FERNET_KEY некорректен (ожидается ключ Fernet).') from exc


def encrypt(plain):
    if not plain:
        return ''
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token):
    """Пустая строка при пустом входе или если ключ не подходит (потеря
    ключа = токен нужно ввести заново, а не падать)."""
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ''


def mask_token(plain):
    """123456:AAxxxx… → 123456:AA••••. Для показа в админке."""
    if not plain:
        return ''
    head, sep, tail = plain.partition(':')
    if not sep:
        return plain[:2] + '••••'
    return f'{head}:{tail[:2]}••••'
