from django.db import transaction
from django.db.models.signals import post_save, post_delete, pre_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.conf import settings
from django.urls import reverse
from .models import UserProfile
from website.mail import send_templated_mail


def _sync_roles(user):
    """Пересчитывает roles/driver/team/verified для UserProfile на основе источников правды."""
    from .models import DriverClaim
    from teams.models import TeamManager

    profile, _ = UserProfile.objects.get_or_create(user=user)

    roles = []
    driver = None
    team = None
    verified = False

    approved_claim = (
        DriverClaim.objects
        .filter(user=user, status='approved')
        .select_related('driver')
        .first()
    )
    if approved_claim and approved_claim.driver:
        roles.append('pilot')
        driver = approved_claim.driver
        verified = True

    active_mgr = (
        TeamManager.objects
        .filter(user=user, is_active=True)
        .select_related('team')
        .first()
    )
    if active_mgr:
        roles.append('manager')
        team = active_mgr.team

    UserProfile.objects.filter(pk=profile.pk).update(
        roles=roles,
        driver=driver,
        team=team,
        verified=verified,
    )


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else:
        UserProfile.objects.get_or_create(user=instance)


def _send_claim_email(template, subject, user, context):
    if not user.email:
        return
    try:
        send_templated_mail(template, subject, [user.email], context)
    except Exception:
        # Не даём сбою почты сломать сохранение заявки в админке
        pass


def send_driver_claim_approved_email(user, driver):
    """Уведомление пилоту о подтверждении заявки на привязку профиля."""
    name = driver.full_name if driver else ''
    _send_claim_email('claim_approved', 'Ваша заявка на привязку профиля пилота подтверждена', user, {
        'rows': _rows(('Профиль пилота', name), ('Статус', 'Подтверждена')),
        'login_url': f"{settings.BASE_URL}/accounts/login/",
        'profile_url': f"{settings.BASE_URL}{driver.get_absolute_url()}" if driver else '',
    })


def _claim_driver_name(claim):
    if claim.driver:
        return claim.driver.full_name
    return f"{claim.requested_first_name} {claim.requested_last_name}".strip()


def _rows(*pairs):
    return [pair for pair in pairs if pair[1]]


def send_driver_claim_pending_email(user, claim):
    """Уведомление пилоту о том, что заявка принята и ожидает проверки."""
    _send_claim_email('claim_pending', 'Ваша заявка на привязку профиля пилота принята на рассмотрение', user, {
        'rows': _rows(('Профиль пилота', _claim_driver_name(claim)), ('Срок рассмотрения', '1–2 рабочих дня')),
        'profile_url': f"{settings.BASE_URL}{reverse('accounts:profile')}",
    })


def _support_contact_rows():
    """Контакты поддержки из SocialAuthSettings — для письма об отказе."""
    from .models import SocialAuthSettings

    contact_email = telegram_contact = ''
    try:
        social_auth = SocialAuthSettings.get()
        contact_email = social_auth.contact_email
        telegram_contact = (social_auth.telegram_contact or '').strip()
    except Exception:
        pass
    handle = telegram_contact.lstrip('@')
    contact_rows = []
    if contact_email:
        contact_rows.append(('E-mail', contact_email, f'mailto:{contact_email}'))
    if handle:
        contact_rows.append(('Telegram', f'@{handle}'))
    return contact_rows


def send_driver_claim_rejected_email(user, claim):
    """Уведомление пилоту об отклонении заявки на привязку профиля."""
    _send_claim_email('claim_rejected', 'Ваша заявка на привязку профиля пилота отклонена', user, {
        'rows': _rows(('Профиль пилота', _claim_driver_name(claim)), ('Статус', 'Отклонена')),
        'reason': (claim.admin_comment or '').strip(),
        'contact_rows': _support_contact_rows(),
    })


def _team_claim_name(claim):
    return claim.team.name if claim.team else claim.requested_team_name


def send_team_claim_pending_email(user, claim):
    """Уведомление представителю команды: заявка принята и ожидает проверки."""
    _send_claim_email('team_claim_pending', 'Ваша заявка на управление командой принята на рассмотрение', user, {
        'rows': _rows(('Команда', _team_claim_name(claim)), ('Срок рассмотрения', '1–2 рабочих дня')),
        'dashboard_url': f"{settings.BASE_URL}{reverse('teams:dashboard')}",
    })


def send_team_claim_approved_email(user, claim):
    """Уведомление представителю команды: доступ к управлению командой выдан."""
    _send_claim_email('team_claim_approved', 'Ваша заявка на управление командой подтверждена', user, {
        'rows': _rows(('Команда', _team_claim_name(claim)), ('Статус', 'Подтверждена')),
        'dashboard_url': f"{settings.BASE_URL}{reverse('teams:dashboard')}",
        'team_url': f"{settings.BASE_URL}{claim.team.get_absolute_url()}" if claim.team else '',
    })


def send_team_claim_rejected_email(user, claim):
    """Уведомление представителю команды об отклонении заявки."""
    _send_claim_email('team_claim_rejected', 'Ваша заявка на управление командой отклонена', user, {
        'rows': _rows(('Команда', _team_claim_name(claim)), ('Статус', 'Отклонена')),
        'reason': (claim.admin_comment or '').strip(),
        'contact_rows': _support_contact_rows(),
    })


@receiver(pre_save, sender='accounts.DriverClaim')
def stash_old_driver_claim_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_status = sender.objects.get(pk=instance.pk).status
        except sender.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender='accounts.DriverClaim')
def on_driver_claim_save(sender, instance, created, **kwargs):
    _sync_roles(instance.user)

    old_status = getattr(instance, '_old_status', None)

    if created and instance.status == 'pending':
        send_driver_claim_pending_email(instance.user, instance)
        from website.claim_notify import notify_admins_new_claim
        transaction.on_commit(lambda: notify_admins_new_claim(instance))
    elif not created and old_status != 'approved' and instance.status == 'approved':
        send_driver_claim_approved_email(instance.user, instance.driver)
    elif not created and old_status != 'rejected' and instance.status == 'rejected':
        send_driver_claim_rejected_email(instance.user, instance)


@receiver(post_save, sender='teams.TeamManager')
def on_team_manager_save(sender, instance, **kwargs):
    _sync_roles(instance.user)


@receiver(post_delete, sender='teams.TeamManager')
def on_team_manager_delete(sender, instance, **kwargs):
    _sync_roles(instance.user)
