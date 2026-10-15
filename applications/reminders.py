"""
Напоминания об истечении документов из ЛК пилота (accounts.PilotDocument).

Сроки — DocumentReminderSettings.days_before (по умолчанию 30, 10, 1 день). Документу
отправляется одно напоминание за проход — по самому близкому наступившему сроку; более
дальние сроки при этом отмечаются как пройденные (документ загрузили за 5 дней до конца —
придёт одно письмо «за 10 дней», а не два). Отметки (DocumentReminder) включают дату
окончания: новый файл или новая дата начинают отсчёт заново.

Получатели: email аккаунта; пилоту младше 18 — ещё и email родителя из профиля. Telegram —
если в ЛК подключены уведомления (UserProfile.telegram_id через бота обратной связи).
"""
import html
import logging
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from . import document_kinds

logger = logging.getLogger(__name__)


def _base_url():
    return getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')


def due(today=None, days=None):
    """[(документ, срок в днях, дней осталось)] — кому пора напомнить сегодня."""
    from accounts.models import PilotDocument
    from .models import DocumentReminder, DocumentReminderSettings
    today = today or timezone.localdate()
    days = days if days is not None else DocumentReminderSettings.get().days()
    if not days:
        return []
    horizon = today + timedelta(days=max(days))
    docs = (PilotDocument.objects.filter(expiry_date__gte=today, expiry_date__lte=horizon)
            .select_related('profile__user'))
    sent = set(DocumentReminder.objects.filter(document__in=docs).values_list(
        'document_id', 'days_before', 'expiry_date'))
    result = []
    for doc in docs:
        left = (doc.expiry_date - today).days
        reached = [d for d in days if left <= d]
        if not reached:
            continue
        closest = min(reached)
        if (doc.id, closest, doc.expiry_date) not in sent:
            result.append((doc, closest, left))
    return result


def recipients(profile):
    emails = []
    if profile.user.email and profile.user.is_active:
        emails.append(profile.user.email)
    if profile.is_minor and profile.parent_email and profile.parent_email.lower() not in {e.lower() for e in emails}:
        emails.append(profile.parent_email)
    return emails


def days_word(n):
    if n % 10 == 1 and n % 100 != 11:
        return 'день'
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return 'дня'
    return 'дней'


def when_text(left):
    if left == 0:
        return 'сегодня'
    if left == 1:
        return 'завтра'
    return f'через {left} {days_word(left)}'


def owner_name(profile):
    driver = profile.driver
    if driver:
        return driver.full_name
    return profile.user.get_full_name() or profile.user.email


def send_email(doc, left, emails):
    from website.mail import send_templated_mail
    link = _base_url() + reverse('accounts:profile') + '#documents'
    subject = f'{doc.name}: срок действия заканчивается {when_text(left)}'
    context = {
        'subject': subject,
        'preheader': f'Документ «{doc.name}» действует до {doc.expiry_date:%d.%m.%Y}. Загрузите новый в личном кабинете.',
        'status': 'wait', 'status_label': 'Срок документа', 'status_text': 'Срок документа',
        'title': f'«{doc.name}» истекает {when_text(left)}',
        'pilot_name': owner_name(doc.profile),
        'lead': (f'Срок действия документа «{doc.name}» заканчивается {doc.expiry_date:%d.%m.%Y}. '
                 'Загрузите новый в личном кабинете — он подставится в следующие заявки на этапы.'),
        'rows': [('Документ', doc.name), ('Действует до', f'{doc.expiry_date:%d.%m.%Y}')],
        'comment': '', 'comment_label': '',
        'button': 'Открыть личный кабинет', 'link': link,
    }
    send_templated_mail('application_update', subject, emails, context)


def telegram_text(doc, left):
    link = _base_url() + reverse('accounts:profile') + '#documents'
    who = owner_name(doc.profile)
    return (f'📄 <b>{html.escape(doc.name)}</b> ({html.escape(who)}) — срок действия заканчивается '
            f'{when_text(left)}, {doc.expiry_date:%d.%m.%Y}.\n'
            f'Загрузите новый документ в <a href="{html.escape(link, quote=True)}">личном кабинете</a>.')


def send_all(today=None, dry_run=False):
    """Отправляет напоминания. Возвращает (отправлено, ошибок, строки для лога)."""
    from website.feedback import notify
    from .models import DocumentReminder, DocumentReminderSettings
    cfg = DocumentReminderSettings.get()
    if not cfg.enabled:
        return 0, 0, ['напоминания выключены в настройках']
    days = cfg.days()
    sent = failed = 0
    log = []
    for doc, closest, left in due(today, days):
        profile = doc.profile
        channels = []
        emails = recipients(profile) if cfg.send_email else []
        telegram = cfg.send_telegram and profile.telegram_notifications and profile.telegram_id
        log.append(f'документ {doc.id} ({doc.kind}), осталось {left}, срок {closest}: '
                   f'{len(emails)} email, telegram={"да" if telegram else "нет"}')
        if dry_run:
            continue
        if emails:
            try:
                send_email(doc, left, emails)
                channels.append('email')
            except Exception as exc:
                logger.warning('Напоминание о документе %s: письмо не отправлено: %s', doc.id, exc)
        if telegram:
            result = notify.send_user_message(profile.telegram_id, telegram_text(doc, left))
            if result == 'blocked':  # пользователь остановил бота — больше не пишем
                type(profile).objects.filter(pk=profile.pk).update(telegram_notifications=False)
            elif result:
                channels.append('telegram')
        if not channels and (emails or telegram):
            failed += 1  # повторим завтра: отметку не ставим
            continue
        # Отмечаем этот срок и все более дальние, чтобы не догонять их следующими письмами.
        for d in days:
            if d >= closest:
                DocumentReminder.objects.get_or_create(
                    document=doc, days_before=d, expiry_date=doc.expiry_date,
                    defaults={'channels': ','.join(channels) if d == closest else ''})
        sent += 1
    return sent, failed, log


def alerts(profile, today=None):
    """Документы ЛК, о которых стоит предупредить на сайте: истёкшие и истекающие в пределах
    самого дальнего срока напоминаний. [(документ, дней осталось)]."""
    from .models import DocumentReminderSettings
    if profile is None:
        return []
    today = today or timezone.localdate()
    horizon = max(DocumentReminderSettings.get().days() or [30])
    result = []
    for doc in profile.documents.exclude(expiry_date=None).order_by('expiry_date'):
        left = (doc.expiry_date - today).days
        if left <= horizon:
            result.append((doc, left))
    return result


def _ics_escape(text):
    return text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def ics(doc, today=None, days=None):
    """Файл календаря: событие на каждый срок напоминания и на день окончания, с будильником
    в 9:00. Работает без нашей рассылки — напоминания живут в календаре телефона."""
    from .models import DocumentReminderSettings
    today = today or timezone.localdate()
    days = days if days is not None else DocumentReminderSettings.get().days()
    link = _base_url() + reverse('accounts:profile') + '#documents'
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    events = [(doc.expiry_date, f'Сегодня истекает: {doc.name}')]
    events += [(doc.expiry_date - timedelta(days=d), f'Через {d} {days_word(d)} истекает: {doc.name}')
               for d in days if d > 0]
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Gripline//Documents//RU', 'CALSCALE:GREGORIAN',
             'METHOD:PUBLISH']
    for i, (day, title) in enumerate(sorted(events)):
        if day < today:
            continue
        lines += [
            'BEGIN:VEVENT',
            f'UID:gripline-doc-{doc.id}-{doc.expiry_date:%Y%m%d}-{i}@gripline.ru',
            f'DTSTAMP:{stamp}',
            f'DTSTART;VALUE=DATE:{day:%Y%m%d}',
            f'DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}',
            f'SUMMARY:{_ics_escape(title)}',
            f'DESCRIPTION:{_ics_escape(f"Действует до {doc.expiry_date:%d.%m.%Y}. Новый документ: {link}")}',
            f'URL:{link}',
            'BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{_ics_escape(title)}',
            'TRIGGER;RELATED=START:PT9H', 'END:VALARM',
            'END:VEVENT',
        ]
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'


def ics_filename(doc):
    slug = {document_kinds.LICENSE: 'license', document_kinds.POWER_OF_ATTORNEY: 'doverennost',
            document_kinds.INSURANCE: 'insurance', document_kinds.MEDICAL: 'medical'}.get(doc.kind, 'document')
    return f'gripline-{slug}-{doc.expiry_date:%Y%m%d}.ics'


