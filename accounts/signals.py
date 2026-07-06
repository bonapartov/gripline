from django.db.models.signals import post_save, post_delete, pre_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from .models import UserProfile


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


def send_driver_claim_approved_email(user, driver):
    """Отправка уведомления пилоту о подтверждении заявки на привязку профиля."""
    if not user.email:
        return

    login_url = f"{settings.BASE_URL}/accounts/login/"
    profile_url = f"{settings.BASE_URL}{driver.get_absolute_url()}" if driver else ''
    driver_name = driver.full_name if driver else ''

    subject = '✅ Ваша заявка на привязку профиля пилота подтверждена'
    message = f"""Здравствуйте!

Ваша заявка на привязку к профилю пилота{f' "{driver_name}"' if driver_name else ''} подтверждена администратором.

Личный кабинет: {login_url}
{f'Профиль на сайте: {profile_url}' if profile_url else ''}

С уважением,
Команда Gripline
"""
    html_message = f"""<h2>✅ Заявка подтверждена</h2>
<p>Здравствуйте!</p>
<p>Ваша заявка на привязку к профилю пилота{f' <strong>{driver_name}</strong>' if driver_name else ''} подтверждена администратором.</p>
<p>Теперь вы можете войти в <a href="{login_url}">личный кабинет</a>.</p>
{f'<p>Профиль на сайте: <a href="{profile_url}">{profile_url}</a></p>' if profile_url else ''}
<br>
<p>С уважением,<br>Команда Gripline</p>
"""
    try:
        send_mail(
            subject=subject,
            message=message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        # Не даём сбою почты сломать сохранение заявки в админке
        pass


def _claim_driver_name(claim):
    if claim.driver:
        return claim.driver.full_name
    return f"{claim.requested_first_name} {claim.requested_last_name}".strip()


def send_driver_claim_pending_email(user, claim):
    """Отправка уведомления пилоту о том, что заявка принята и ожидает проверки."""
    if not user.email:
        return

    profile_url = f"{settings.BASE_URL}{reverse('accounts:profile')}"
    driver_name = _claim_driver_name(claim)

    subject = '⏳ Ваша заявка на привязку профиля пилота принята на рассмотрение'
    message = f"""Здравствуйте!

Ваша заявка на привязку к профилю пилота{f' "{driver_name}"' if driver_name else ''} принята и отправлена администратору на проверку.

Обычно это занимает 1–2 рабочих дня. Как только заявку рассмотрят, мы пришлём письмо на этот адрес.

Проверить статус заявки: {profile_url}

С уважением,
Команда Gripline
"""
    html_message = f"""<h2>⏳ Заявка принята на рассмотрение</h2>
<p>Здравствуйте!</p>
<p>Ваша заявка на привязку к профилю пилота{f' <strong>{driver_name}</strong>' if driver_name else ''} принята и отправлена администратору на проверку.</p>
<p>Обычно это занимает 1–2 рабочих дня. Как только заявку рассмотрят, мы пришлём письмо на этот адрес.</p>
<p>Проверить статус заявки: <a href="{profile_url}">{profile_url}</a></p>
<br>
<p>С уважением,<br>Команда Gripline</p>
"""
    try:
        send_mail(
            subject=subject,
            message=message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        pass


def send_driver_claim_rejected_email(user, claim):
    """Отправка уведомления пилоту об отклонении заявки на привязку профиля."""
    if not user.email:
        return

    from .models import SocialAuthSettings

    driver_name = _claim_driver_name(claim)
    reason = (claim.admin_comment or '').strip()

    contact_email = ''
    telegram_contact = ''
    try:
        social_auth = SocialAuthSettings.get()
        contact_email = social_auth.contact_email
        telegram_contact = social_auth.telegram_contact
    except Exception:
        pass

    subject = '❌ Ваша заявка на привязку профиля пилота отклонена'
    message = f"""Здравствуйте!

Ваша заявка на привязку к профилю пилота{f' "{driver_name}"' if driver_name else ''} отклонена администратором.
{f'Комментарий администратора: {reason}' if reason else ''}

Если это ошибка или у вас есть вопросы, свяжитесь с нами:
{f'Email: {contact_email}' if contact_email else ''}
{f'Telegram: {telegram_contact}' if telegram_contact else ''}

С уважением,
Команда Gripline
"""
    html_message = f"""<h2>❌ Заявка отклонена</h2>
<p>Здравствуйте!</p>
<p>Ваша заявка на привязку к профилю пилота{f' <strong>{driver_name}</strong>' if driver_name else ''} отклонена администратором.</p>
{f'<p>Комментарий администратора: {reason}</p>' if reason else ''}
<p>Если это ошибка или у вас есть вопросы, свяжитесь с нами:</p>
{f'<p>Email: <a href="mailto:{contact_email}">{contact_email}</a></p>' if contact_email else ''}
{f'<p>Telegram: <a href="https://t.me/{telegram_contact.lstrip("@")}">{telegram_contact}</a></p>' if telegram_contact else ''}
<br>
<p>С уважением,<br>Команда Gripline</p>
"""
    try:
        send_mail(
            subject=subject,
            message=message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        pass


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
