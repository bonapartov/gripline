"""
Настройки исходящей почты вынесены в Wagtail admin → Интеграции → Почта
(MailSettings, website/models.py) — см. ТЗ gripline_tz_zaschita_pochty.md
(компрометация ящика gripline.ru@yandex.ru спам-рассылкой, сентябрь 2026).

DBConfiguredEmailBackend читает MailSettings.get() при КАЖДОЙ отправке
письма (не один раз при старте процесса) — правка в админке действует
мгновенно, без рестарта gunicorn. Пустое текстовое поле в админке = fallback
на settings.EMAIL_HOST_USER/EMAIL_HOST_PASSWORD/DEFAULT_FROM_EMAIL
(переменные окружения) — деплой этого модуля сам по себе не меняет
поведение прода, пока админ не заполнит поле.

enabled=False — кил-свитч: письма молча не уходят (send_messages
возвращает 0, ни одного исключения наружу) — на случай повторной
компрометации ящика, чтобы не ждать деплоя.

Прокси (use_proxy/proxy_url, 22.09.2026): изначально подозревали, что прод-
хостинг блокирует прямой исходящий TCP на smtp.yandex.ru:587/465 тем же
DPI-паттерном, что и api.telegram.org (см. website/telegram.py), и завели
маршрутизацию через тот же локальный SOCKS5 Xray. Диагностика показала
другую причину: IMAP (993) и обычный HTTPS с того же сервера работают
мгновенно и напрямую, и через VPN-туннель, и с домашней сети пользователя —
блокирован конкретно SMTP submission (587/465), похоже на стандартную
антиспам-политику хостинг-провайдера (блокирует исходящий SMTP у всех
клиентов по умолчанию, снимается по заявке в поддержку). Прокси тут не
помогает (тот же провайдер блокирует порт независимо от прокси) — поэтому
use_proxy по умолчанию ВЫКЛЮЧЕН, прямое соединение остаётся дефолтом.
Тумблер оставлен в админке на случай, если для другого хостинга/будущей
ситуации это всё же понадобится — переключается без деплоя.
"""
from urllib.parse import urlparse
from smtplib import SMTP, SMTP_SSL

import socks
from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend


def _mail_settings():
    from .models import MailSettings
    return MailSettings.get()


def _proxy_url():
    """URL SOCKS5-прокси к использованию, или None если прокси выключен
    тумблером use_proxy в админке (дефолт — выключен, см. docstring модуля)."""
    cfg = _mail_settings()
    if not cfg.use_proxy:
        return None
    return cfg.proxy_url or getattr(settings, 'EMAIL_PROXY_URL', None)


def _socks_connect(proxy_url, host, port, timeout):
    parsed = urlparse(proxy_url)
    return socks.create_connection(
        (host, port),
        timeout=timeout if timeout else None,
        proxy_type=socks.SOCKS5,
        proxy_addr=parsed.hostname,
        proxy_port=parsed.port,
        proxy_rdns=True,
    )


class _ProxiedSMTP(SMTP):
    """SMTP с TCP-соединением через SOCKS5, если MailSettings.use_proxy включён
    (иначе — обычное прямое соединение)."""

    def _get_socket(self, host, port, timeout):
        proxy_url = _proxy_url()
        if not proxy_url:
            return super()._get_socket(host, port, timeout)
        return _socks_connect(proxy_url, host, port, timeout)


class _ProxiedSMTP_SSL(SMTP_SSL):
    """Тот же прокси, но с TLS-оборачиванием сокета — повторяет логику
    stdlib SMTP_SSL._get_socket(), только raw-сокет идёт через SOCKS5."""

    def _get_socket(self, host, port, timeout):
        proxy_url = _proxy_url()
        if not proxy_url:
            return super()._get_socket(host, port, timeout)
        raw_socket = _socks_connect(proxy_url, host, port, timeout)
        return self.context.wrap_socket(raw_socket, server_hostname=self._host)


def default_from_email():
    """Адрес отправителя (From) — переопределяется в админке, иначе settings.DEFAULT_FROM_EMAIL."""
    return _mail_settings().default_from_email or settings.DEFAULT_FROM_EMAIL


def admin_notify_email():
    """Куда падают уведомления администратору о новых заявках — не адрес отправителя."""
    return _mail_settings().admin_notify_email or 'gripline.ru@yandex.ru'


class DBConfiguredEmailBackend(SMTPEmailBackend):
    def __init__(self, *args, **kwargs):
        cfg = _mail_settings()
        self._mail_enabled = cfg.enabled
        kwargs.setdefault('host', cfg.host or None)
        kwargs.setdefault('port', cfg.port or None)
        kwargs.setdefault('username', cfg.host_user or None)
        kwargs.setdefault('password', cfg.host_password or None)
        kwargs.setdefault('use_tls', cfg.use_tls)
        kwargs.setdefault('use_ssl', cfg.use_ssl)
        kwargs.setdefault('timeout', cfg.timeout or None)
        super().__init__(*args, **kwargs)

    @property
    def connection_class(self):
        return _ProxiedSMTP_SSL if self.use_ssl else _ProxiedSMTP

    def send_messages(self, email_messages):
        if not self._mail_enabled:
            return 0
        return super().send_messages(email_messages)
