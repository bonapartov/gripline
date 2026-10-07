"""
Подтверждение email при регистрации (пилот, команда, организатор).

`UserProfile.email_verified` — единственный признак «ссылка из письма не открыта».
`User.is_active` теперь значит только «не заблокирован»: ссылка из письма его НЕ меняет, а
повторную отправку письма получают только активные неподтверждённые пользователи — так
отключённый админом аккаунт нельзя вернуть через «запросить новое письмо».
"""
import logging

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ObjectDoesNotExist
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

logger = logging.getLogger(__name__)

NEUTRAL_RESEND_MESSAGE = 'Если такой аккаунт ожидает подтверждения, мы отправили письмо. Проверьте почту.'


def is_email_verified(user):
    try:
        return user.profile.email_verified
    except ObjectDoesNotExist:
        return True


def mark_unverified(user, **profile_fields):
    """Новая регистрация по email: профиль создаёт сигнал, ставим флаг и сопутствующие поля."""
    profile = user.profile
    profile.email_verified = False
    for name, value in profile_fields.items():
        setattr(profile, name, value)
    profile.save()
    return profile


def user_from_token(uidb64, token):
    """Пользователь по ссылке из письма; None — токен неверный/просрочен или аккаунт заблокирован."""
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None
    if not user.is_active or not default_token_generator.check_token(user, token):
        return None
    return user


def confirm_email(user):
    """Ставит флаг; возвращает True, если подтверждение произошло сейчас (а не повторным кликом)."""
    profile = user.profile
    first_time = not profile.email_verified
    if first_time:
        profile.email_verified = True
        profile.save(update_fields=['email_verified', 'updated_at'])
    return first_time


def _send_verification_for(user, request):
    """Письмо подтверждения того вида, который соответствует регистрации пользователя."""
    from accounts.views import send_verification_email
    from organizers.views import send_organizer_verification_email
    from teams.views import send_team_verification_email

    if user.profile.pending_team_name:
        send_team_verification_email(user, request)
    elif hasattr(user, 'organizer_profile'):
        send_organizer_verification_email(user, request)
    else:
        send_verification_email(user, request)


def resend_verification_emails(email, request):
    """Шлёт письмо каждому активному неподтверждённому пользователю с этим адресом.
    Ничего не сообщает вызывающему о том, нашёлся ли аккаунт (против перебора адресов)."""
    for user in User.objects.filter(email__iexact=(email or '').strip(), is_active=True,
                                    profile__email_verified=False):
        try:
            _send_verification_for(user, request)
        except Exception:
            logger.exception('resend verification: письмо не отправлено (user #%s)', user.pk)


def handle_existing_email(email, request):
    """Регистрация на уже занятый адрес. На форме отвечаем так же, как при успехе (иначе по тексту
    ответа можно перебирать адреса), а владельцу адреса сообщаем письмом: неподтверждённому — новая
    ссылка, подтверждённому — «вы уже зарегистрированы» со ссылками на вход и восстановление пароля.
    Заблокированному — ничего. Возвращает True, если адрес занят."""
    from django.conf import settings
    from django.urls import reverse
    from website.mail import send_templated_mail

    users = list(User.objects.filter(email__iexact=(email or '').strip()))
    if not users:
        return False
    base = settings.BASE_URL.rstrip('/')
    for user in users:
        if not user.is_active:
            continue
        try:
            if not is_email_verified(user):
                _send_verification_for(user, request)
            else:
                send_templated_mail('account_exists', 'Этот адрес уже зарегистрирован на Gripline', [user.email], {
                    'login_url': f"{base}{reverse('accounts:login')}",
                    'reset_url': f"{base}/accounts/password-reset/",
                })
        except Exception:
            logger.exception('existing email: письмо не отправлено (user #%s)', user.pk)
    return True
