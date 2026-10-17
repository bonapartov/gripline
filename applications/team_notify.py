"""Заявка команды → пилот: уведомление «вас заявила команда N» и отказ от участия.

Подтверждение пилота не требуется (решение владельца 17.10.2026) — только уведомление.
Пилот (или законный представитель) может отказаться по подписанной ссылке из письма —
без входа на сайт: у многих пилотов нет аккаунта. Пилот с подтверждённым аккаунтом видит
заявку в своём ЛК и может отказаться оттуда же.
"""
import html
import logging

from django.conf import settings
from django.core import signing
from django.urls import reverse

logger = logging.getLogger(__name__)

SALT = 'team-entry-decline'


def _base_url():
    return getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')


def decline_token(application):
    return signing.dumps(application.id, salt=SALT)


def check_token(application, token):
    try:
        return signing.loads(token, salt=SALT) == application.id
    except signing.BadSignature:
        return False


def decline_url(application):
    return _base_url() + reverse('applications:team_decline', args=[application.id, decline_token(application)])


def pilot_profile(application):
    """Подтверждённый аккаунт пилота заявки или None."""
    from accounts.models import UserProfile
    pilot = getattr(application, 'pilot', None)
    if pilot is None or not pilot.driver_id:
        return None
    return (UserProfile.objects.filter(driver_id=pilot.driver_id, verified=True)
            .select_related('user').first())


def is_team_pilot(user, application):
    """Пользователь — сам пилот командной заявки (подтверждённый аккаунт этого пилота)."""
    if not user.is_authenticated or not application.team_entry_id:
        return False
    profile = getattr(user, 'profile', None)
    pilot = getattr(application, 'pilot', None)
    return bool(profile is not None and profile.verified and pilot is not None
                and pilot.driver_id and profile.driver_id == pilot.driver_id)


def pilot_emails(application, profile=None):
    """Адреса пилота: аккаунт (если подтверждён) или email из заявки; несовершеннолетнему —
    ещё законный представитель. Менеджеры команды исключаются (они и так в курсе)."""
    pilot = application.pilot
    emails = []
    if profile is not None and profile.user.email and profile.user.is_active:
        emails.append(profile.user.email)
    elif pilot.email:
        emails.append(pilot.email)
    if pilot.is_minor and pilot.parent_email:
        emails.append(pilot.parent_email)
    from teams.models import TeamManager
    managers = {e.lower() for e in TeamManager.objects.filter(
        team_id=application.team_entry.team_id, is_active=True).values_list('user__email', flat=True)}
    seen, result = set(), []
    for e in emails:
        key = e.strip().lower()
        if key and key not in seen and key not in managers:
            seen.add(key)
            result.append(e.strip())
    return result


def notify_pilot_entered(application):
    """Письмо (и Telegram, если подключён) пилоту: команда заявила его на этап."""
    from website.mail import send_templated_mail
    entry, stage = application.team_entry, application.stage
    profile = pilot_profile(application)
    pilot = application.pilot
    rows = [('Команда', entry.team.name), ('Этап', stage.title), ('Чемпионат', stage.championship.title),
            ('Класс', application.race_class.name if application.race_class else '—')]
    if application.start_number:
        rows.append(('Стартовый номер', str(application.start_number)))
    link = decline_url(application)
    for email in pilot_emails(application, profile):
        try:
            subject = f'Команда {entry.team.name} заявила вас на {stage.title}'
            send_templated_mail('application_update', subject, [email], {
                'subject': subject,
                'preheader': f'{pilot.full_name}: заявка на {stage.title} подана командой {entry.team.name}.',
                'status': 'wait', 'status_label': 'Заявка команды', 'status_text': 'Заявка команды',
                'title': 'Вас заявили на этап',
                'lead': (f'Команда {entry.team.name} подала заявку на участие пилота {pilot.full_name} в этапе. '
                         'Подтверждать ничего не нужно. Если вы не планируете ехать — откажитесь по кнопке ниже: '
                         'заявка будет отозвана, стартовый номер освободится, команда и организатор получат уведомление.'),
                'pilot_name': pilot.full_name,
                'rows': rows, 'comment': '', 'comment_label': '',
                'button': 'Отказаться от участия', 'link': link,
            }, fail_silently=True)
        except Exception as exc:
            logger.warning('Заявка %s: письмо пилоту не отправлено: %s', application.id, exc)
    if profile is not None and profile.telegram_notifications and profile.telegram_id:
        from website.feedback import notify
        text = (f'🏁 Команда <b>{html.escape(entry.team.name)}</b> заявила вас на «{html.escape(stage.title)}»'
                f' ({html.escape(rows[3][1])}'
                + (f', №{application.start_number}' if application.start_number else '') + ').\n'
                f'Не едете — <a href="{html.escape(link, quote=True)}">откажитесь от участия</a>.')
        result = notify.send_user_message(profile.telegram_id, text)
        if result == 'blocked':
            type(profile).objects.filter(pk=profile.pk).update(telegram_notifications=False)


def notify_declined(application):
    """Пилот отказался: письмо всем менеджерам команды и организатору этапа."""
    from website.mail import send_templated_mail
    from teams.models import TeamManager
    from .views import _app_link, _notify_organizer_withdrawn
    _notify_organizer_withdrawn(application)
    entry, stage, pilot = application.team_entry, application.stage, application.pilot
    link = _base_url() + reverse('teams:team_entry_review', args=[entry.id])
    for m in TeamManager.objects.filter(team_id=entry.team_id, is_active=True).select_related('user'):
        if not m.user.email:
            continue
        subject = f'{pilot.full_name} отказался от участия — {stage.title}'
        try:
            send_templated_mail('application_update', subject, [m.user.email], {
                'subject': subject,
                'preheader': f'{pilot.full_name} отказался от заявки команды {entry.team.name} на {stage.title}.',
                'status': 'bad', 'status_label': 'Отказ пилота', 'status_text': 'Отказ пилота',
                'title': 'Пилот отказался от участия',
                'lead': 'Заявка отозвана, стартовый номер освобождён. Организатор этапа получил уведомление.',
                'pilot_name': m.user.get_full_name() or m.user.email,
                'rows': [('Пилот', pilot.full_name), ('Этап', stage.title),
                         ('Класс', application.race_class.name if application.race_class else '—'),
                         ('Заявка', f'№{application.id}')],
                'comment': application.withdraw_reason, 'comment_label': 'Причина',
                'button': 'Открыть заявку команды', 'link': link,
            }, fail_silently=True)
        except Exception as exc:
            logger.warning('Заявка %s: письмо менеджеру об отказе не отправлено: %s', application.id, exc)
    return _app_link(application)
