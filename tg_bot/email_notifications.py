from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse

def send_team_claim_approved_email(user, team):
    """Отправка уведомления о подтверждении заявки команды"""
    subject = '✅ Ваша заявка на управление командой подтверждена'

    login_url = f"{settings.BASE_URL}{reverse('teams:login')}"
    team_url = f"{settings.BASE_URL}{team.get_absolute_url()}"

    message = f"""
Здравствуйте!

Ваша заявка на управление командой "{team.name}" подтверждена администратором.

Теперь вы можете войти в личный кабинет команды:
{login_url}

Страница вашей команды на сайте:
{team_url}

С уважением,
Команда Gripline
    """

    html_message = f"""
<h2>✅ Заявка подтверждена</h2>

<p>Здравствуйте!</p>

<p>Ваша заявка на управление командой <strong>"{team.name}"</strong> подтверждена администратором.</p>

<p>Теперь вы можете войти в <a href="{login_url}">личный кабинет команды</a>.</p>

<p>Страница вашей команды на сайте: <a href="{team_url}">{team_url}</a></p>

<br>
<p>С уважением,<br>Команда Gripline</p>
    """

    send_mail(
        subject=subject,
        message=message,
        html_message=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

def send_team_claim_rejected_email(user, team_name, reason=None):
    """Отправка уведомления об отклонении заявки команды"""
    subject = '❌ Ваша заявка на управление командой отклонена'

    register_url = f"{settings.BASE_URL}{reverse('teams:register')}"

    message = f"""
Здравствуйте!

Ваша заявка на управление командой "{team_name}" отклонена администратором.
{f'Причина: {reason}' if reason else ''}

Вы можете подать заявку повторно:
{register_url}

Если вы считаете, что произошла ошибка, свяжитесь с администрацией.

С уважением,
Команда Gripline
    """

    html_message = f"""
<h2>❌ Заявка отклонена</h2>

<p>Здравствуйте!</p>

<p>Ваша заявка на управление командой <strong>"{team_name}"</strong> отклонена администратором.</p>
{f'<p><strong>Причина:</strong> {reason}</p>' if reason else ''}

<p>Вы можете подать заявку повторно: <a href="{register_url}">Регистрация команды</a></p>

<p>Если вы считаете, что произошла ошибка, свяжитесь с администрацией.</p>

<br>
<p>С уважением,<br>Команда Gripline</p>
    """

    send_mail(
        subject=subject,
        message=message,
        html_message=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
