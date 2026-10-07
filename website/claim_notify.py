"""
Уведомление администратора о новой заявке (пилота или команды): письмо + админ-чат Telegram.

Вызывается из post_save-сигналов `DriverClaim`/`TeamClaim` (accounts/signals.py,
teams/signals.py), а не из views — любая новая точка входа, создающая заявку,
уведомит админа автоматически.

В Telegram уходят только тип заявки, название команды и ссылка на заявку в админке.
E-mail и имя заявителя, как и контакт в обращениях по ПД, в групповой чат не
попадают; у заявки пилота нет и имени профиля — во флоу «новый пилот» это ещё не
опубликованный человек, а отличить его от существующего по заявке нельзя.
"""
import html
import logging

from django.conf import settings
from django.urls import reverse

from website.mail import admin_notify_email, send_templated_mail

logger = logging.getLogger(__name__)

NEW_PILOT = 'новый пилот'


def _admin_edit_url(claim):
    name = 'accounts_driverclaim_modeladmin_edit' if claim._meta.model_name == 'driverclaim' \
        else 'teams_teamclaim_modeladmin_edit'
    return f"{settings.BASE_URL.rstrip('/')}{reverse(name, args=[claim.pk])}"


def _driver_parts(claim):
    name = f'{claim.requested_first_name} {claim.requested_last_name}'.strip()
    return {
        'title': 'Заявка на управление пилотом',
        'subject': '[Gripline] Новая заявка на управление пилотом',
        'rows': [
            ('Тип', 'Управление пилотом'), ('E-mail', claim.user.email), ('Имя', name),
            ('Город', claim.requested_city),
            ('Выбранный пилот', claim.driver.full_name if claim.driver else NEW_PILOT),
        ],
        'who': name,
        'tg_title': 'Новая заявка пилота',
        'tg_subject': 'Привязка профиля пилота',
    }


def _team_parts(claim):
    team_name = claim.team.name if claim.team else claim.requested_team_name
    return {
        'title': 'Заявка на управление командой',
        'subject': '[Gripline] Новая заявка от команды',
        'rows': [('E-mail', claim.user.email), ('Команда', team_name), ('Статус', 'Новая заявка')],
        'who': team_name,
        'tg_title': 'Новая заявка команды',
        'tg_subject': team_name,
    }


def telegram_text(parts, claim_id, admin_url):
    return (
        f'🆕 <b>{html.escape(parts["tg_title"])} №{claim_id}</b>\n'
        f'{html.escape(parts["tg_subject"])}\n'
        f'<a href="{html.escape(admin_url, quote=True)}">Открыть в админке</a>'
    )


def _deliver(subject, preheader, title, rows, admin_url, tg_text, ref):
    """Письмо на admin_notify_email + сообщение в админ-чат. Сбой одного канала
    не мешает другому и не ломает основное действие пользователя."""
    try:
        send_templated_mail('admin_claim', subject, [admin_notify_email()], {
            'admin': True,
            'subject': subject,
            'preheader': preheader,
            'title': title,
            'rows': [(label, value) for label, value in rows if value],
            'admin_url': admin_url,
        }, fail_silently=True)
    except Exception:
        logger.exception('%s: письмо админу не отправлено', ref)

    try:
        from website.feedback.notify import notify_admin_chat
        notify_admin_chat(tg_text, ref)
    except Exception:
        logger.exception('%s: уведомление в Telegram не подготовлено', ref)


def notify_admins_new_claim(claim):
    parts = _driver_parts(claim) if claim._meta.model_name == 'driverclaim' else _team_parts(claim)
    admin_url = _admin_edit_url(claim)
    _deliver(
        parts['subject'],
        f"{parts['who']}, {claim.user.email} — ожидает подтверждения в админке.",
        parts['title'], parts['rows'], admin_url,
        telegram_text(parts, claim.pk, admin_url), f'claim #{claim.pk}',
    )


def notify_admins_registration_without_claim(user, first_name, last_name, city, matches):
    """Пилот зарегистрировался, а в базе есть однофамильцы — заявки ещё нет, она
    появится после выбора профиля. Без этого уведомления админ о таком человеке
    не узнаёт, если тот закрыл страницу выбора."""
    try:
        admin_url = f"{settings.BASE_URL.rstrip('/')}{reverse('wagtailusers_users:edit', args=[user.pk])}"
    except Exception:
        admin_url = f"{settings.BASE_URL.rstrip('/')}/admin/"
    name = f'{first_name} {last_name}'.strip()
    _deliver(
        '[Gripline] Новая регистрация пилота (профиль не выбран)',
        f'{name}, {user.email} — зарегистрировался, но ещё не выбрал профиль пилота.',
        'Регистрация пилота без заявки',
        [('E-mail', user.email), ('Имя', name), ('Город', city),
         ('Совпадений в базе', str(matches)), ('Статус', 'Профиль пилота не выбран, заявки нет')],
        admin_url,
        (f'👤 <b>Новая регистрация пилота</b>\nПрофиль пока не выбран, заявки нет.\n'
         f'<a href="{html.escape(admin_url, quote=True)}">Открыть пользователя в админке</a>'),
        f'registration user#{user.pk}',
    )
