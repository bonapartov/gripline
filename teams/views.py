from django.urls import reverse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login
from django.db.models import Q
from .forms import TeamRegistrationForm
from website.models import Team, Driver, TeamSocialLink, TeamMembership
import logging
from website.mail import send_templated_mail
from website.services.balance_limits import ratelimit_post
from accounts.verification import (NEUTRAL_RESEND_MESSAGE, confirm_email, is_email_verified, mark_unverified,
                                   handle_existing_email, resend_verification_emails, user_from_token)
from .models import TeamClaim
from django.contrib.auth import authenticate, login as auth_login

from django.contrib.auth.decorators import login_required
from .models import TeamManager, TeamJoinRequest, TeamInvitation
from django.shortcuts import get_object_or_404
from django import forms
from django.utils import timezone
from datetime import timedelta
from website.models import RaceResult
from django.db.models import Max
from django.contrib.auth import logout
from website.models import TeamStaff, TeamStaffMembership, TeamStaffSocialLink
from django.db import IntegrityError
from wagtail.images.models import Image

# ========== EMAIL VERIFICATION ==========
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.conf import settings

logger = logging.getLogger(__name__)


def send_team_verification_email(user, request):
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verification_url = request.build_absolute_uri(f'/teams/verify-email/{uid}/{token}/')
    send_templated_mail('team_verification_email', 'Подтверждение регистрации команды на Gripline', [user.email], {
        'user': user,
        'verification_url': verification_url,
        'expiry_minutes': 30,
    })


def team_verification_sent(request):
    """Страница «Письмо отправлено» для команды"""
    return render(request, 'teams/verification_sent.html')


def team_verify_email(request, uidb64, token):
    """Ссылка из письма: подтверждает email и продолжает регистрацию команды. Название команды берётся
    из БД (не из сессии), повторный клик заявку не дублирует, заблокированный аккаунт не оживляется."""
    user = user_from_token(uidb64, token)
    if user is None:
        return render(request, 'teams/verification_failed.html')

    confirm_email(user)
    profile = user.profile
    requested_team_name = profile.pending_team_name
    if not requested_team_name:
        messages.success(request, 'Email подтверждён! Теперь вы можете войти.')
        return redirect('teams:login')

    if Team.objects.filter(name__icontains=requested_team_name).exists():
        messages.success(request, 'Email подтверждён! Теперь выберите команду.')
        target = reverse('teams:select_team')
        if request.user.is_authenticated and request.user.pk == user.pk:
            return redirect(target)
        return redirect(f"{reverse('accounts:login')}?next={target}")

    # Похожих команд нет — заявка на новую команду (один раз)
    TeamClaim.objects.get_or_create(
        user=user, requested_team_name=requested_team_name, status='pending')
    profile.pending_team_name = ''
    profile.save(update_fields=['pending_team_name', 'updated_at'])
    messages.success(request, 'Email подтверждён! Заявка отправлена администратору.')
    return redirect('teams:login')


@ratelimit_post('resend_verification_team', limit=10, window_seconds=3600)
def team_resend_verification(request):
    """Повторная отправка письма для команды (ответ одинаковый для любого адреса)."""
    if request.method == 'POST':
        resend_verification_emails(request.POST.get('email'), request)
        messages.success(request, NEUTRAL_RESEND_MESSAGE)
        return redirect('teams:team_verification_sent')
    return render(request, 'teams/verification_resend.html')


@ratelimit_post('register_team', limit=20, window_seconds=3600)
def register(request):
    """Регистрация представителя команды: аккаунт создаётся сразу, но войти и подать заявку
    можно только после перехода по ссылке из письма (см. team_verify_email)."""
    if request.method == 'POST':
        form = TeamRegistrationForm(request.POST)
        if form.is_valid():
            if handle_existing_email(form.cleaned_data['email'], request):
                messages.success(request, 'Письмо отправлено. Подтвердите email.')   # как для нового адреса
                return redirect('teams:team_verification_sent')

            user = form.save(commit=False)
            user.is_active = True
            user.save()
            # название команды — в БД, а не в сессии: ссылку из письма можно открыть в другом браузере
            mark_unverified(user, pending_team_name=form.cleaned_data['team_name'])

            try:
                send_team_verification_email(user, request)
                messages.success(request, 'Письмо отправлено. Подтвердите email.')
                return redirect('teams:team_verification_sent')
            except Exception:
                user.delete()
                logger.exception('team register: письмо подтверждения не отправлено')
                messages.error(request, 'Не удалось отправить письмо. Попробуйте позже.')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = TeamRegistrationForm()

    return render(request, 'teams/register.html', {'form': form})


@login_required
def select_team(request):
    """Выбор команды среди похожих по названию. Список считается по БД для request.user;
    выбрать можно только команду из него."""
    user = request.user
    if not is_email_verified(user):
        messages.error(request, 'Сначала подтвердите email — письмо со ссылкой отправлено при регистрации.')
        return redirect('teams:team_resend_verification')
    requested_team_name = user.profile.pending_team_name
    if not requested_team_name:
        return redirect('teams:dashboard')

    found = Team.objects.filter(name__icontains=requested_team_name)

    if request.method == 'POST':
        allowed = {str(t.id): t for t in found}
        selected_id = request.POST.get('team_id')
        if selected_id != 'none' and selected_id not in allowed:
            messages.error(request, 'Выберите команду из списка.')
            return redirect('teams:select_team')

        team = None if selected_id == 'none' else allowed[selected_id]
        TeamClaim.objects.create(
            user=user, team=team, requested_team_name=requested_team_name, status='pending')
        profile = user.profile
        profile.pending_team_name = ''
        profile.save(update_fields=['pending_team_name', 'updated_at'])
        if team:
            messages.success(request, f'Заявка на управление командой {team.name} отправлена администратору')
        else:
            messages.success(request, 'Заявка на создание команды отправлена администратору')
        return redirect('teams:dashboard')

    return render(request, 'teams/select_team.html', {
        'teams': [{'id': t.id, 'name': t.name} for t in found],
        'requested_team_name': requested_team_name,
    })


def login_view(request):
    """Вход для представителей команд"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        from django.contrib.auth.models import User
        try:
            user_obj = User.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
        except User.DoesNotExist:
            user = None

        if user is not None:
            if not is_email_verified(user):
                messages.error(request, 'Подтвердите email: мы отправляли письмо со ссылкой. Можно запросить новое.')
                return redirect('teams:team_resend_verification')
            if user.is_active:
                auth_login(request, user)
                if hasattr(user, 'organizer_profile'):
                    return redirect('organizers:dashboard')
                if TeamManager.objects.filter(user=user).exists():
                    return redirect('teams:dashboard')
                return redirect('accounts:profile')
            else:
                messages.error(request, 'Аккаунт не активирован. Проверьте почту.')
                return redirect('teams:team_resend_verification')
        else:
            messages.error(request, 'Неверный email или пароль')

    return render(request, 'teams/login.html')


# Формы для редактирования команды
class TeamForm(forms.ModelForm):
    logo_upload = forms.ImageField(
        label="Логотип команды",
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    manager_photo_upload = forms.ImageField(
        label="Фото руководителя",
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Team
        fields = ['city', 'description', 'manager_name', 'manager_email', 'manager_phone', 'manager_social']
        widgets = {
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Москва'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': 'Расскажите о команде...'}),
            'manager_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Иванов Иван Иванович'}),
            'manager_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'manager@team.ru'}),
            'manager_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+7 999 123-45-67'}),
            'manager_social': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://vk.com/id...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.logo:
                self.fields['logo_upload'].help_text = f'Текущий логотип: {self.instance.logo.title}'
            if self.instance.manager_photo:
                self.fields['manager_photo_upload'].help_text = f'Текущее фото: {self.instance.manager_photo.title}'


class TeamSocialLinkForm(forms.ModelForm):
    class Meta:
        model = TeamSocialLink
        fields = ['network_name', 'link_url']
        widgets = {
            'network_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ВК, Instagram...'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
        }


TeamSocialLinkFormSet = forms.inlineformset_factory(
    Team,
    TeamSocialLink,
    form=TeamSocialLinkForm,
    extra=3,
    can_delete=True,
)


class TeamStaffForm(forms.ModelForm):
    class Meta:
        model = TeamStaff
        fields = ['last_name', 'first_name', 'middle_name', 'position', 'photo', 'biography', 'phone', 'email']
        widgets = {
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Фамилия'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Имя'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Отчество'}),
            'position': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Должность'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
            'biography': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Краткая информация...'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+7 999 123-45-67'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
        }


class TeamStaffSocialLinkForm(forms.ModelForm):
    class Meta:
        model = TeamStaffSocialLink
        fields = ['network_name', 'link_url']
        widgets = {
            'network_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ВК, Instagram...'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
        }


TeamStaffSocialLinkFormSet = forms.inlineformset_factory(
    TeamStaff,
    TeamStaffSocialLink,
    form=TeamStaffSocialLinkForm,
    extra=3,
    can_delete=True,
)


@login_required
def dashboard(request):
    """Личный кабинет команды"""
    try:
        manager = TeamManager.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('team').first()

        if not manager:
            # Проверяем есть ли pending-заявка
            from .models import TeamClaim as TC
            pending = TC.objects.filter(user=request.user, status='pending').first()
            if pending:
                return render(request, 'teams/pending.html', {'claim': pending})
            messages.error(request, 'У вас нет прав на управление командой')
            return redirect('/')

        team = manager.team

        drivers = Driver.objects.filter(
            team_memberships__team=team,
            team_memberships__is_active=True
        ).distinct().order_by('last_name')

        driver_classes = []
        drivers_with_results = set()

        for driver in drivers:
            six_months_ago = timezone.now() - timedelta(days=180)

            classes_with_dates = RaceResult.objects.filter(
                team=team,
                driver=driver,
                group__page__last_published_at__gte=six_months_ago
            ).values('group__race_class__name').annotate(
                last_date=Max('group__page__last_published_at')
            ).order_by('-last_date')

            for item in classes_with_dates:
                driver_classes.append({
                    'driver': driver,
                    'class_name': item['group__race_class__name'],
                    'last_date': item['last_date'],
                })
                drivers_with_results.add(driver.id)

        driver_classes.sort(key=lambda x: x['last_date'], reverse=True)

        # Добавляем пилотов без результатов — по классу из членства
        from website.models import TeamMembership as TM
        from django.utils import timezone as tz
        for driver in drivers:
            if driver.id not in drivers_with_results:
                membership = TM.objects.filter(driver=driver, team=team, is_active=True).select_related('race_class').first()
                class_name = membership.race_class.name if membership and membership.race_class else '—'
                driver_classes.append({
                    'driver': driver,
                    'class_name': class_name,
                    'last_date': tz.now(),
                })

        pending_requests = TeamJoinRequest.objects.filter(
            team=team,
            status='pending'
        ).select_related('driver')

        # Определяем демо-команду по email менеджера
        is_demo_team = request.user.email.startswith('demo_team_')
        from accounts.models import DriverClaim
        if is_demo_team:
            demo_driver_ids = DriverClaim.objects.filter(
                user__email__startswith='demo_pilot_', status='approved'
            ).values_list('driver_id', flat=True)
            all_drivers = Driver.objects.filter(id__in=demo_driver_ids).order_by('last_name')
        else:
            demo_driver_ids = DriverClaim.objects.filter(
                user__email__startswith='demo_pilot_'
            ).values_list('driver_id', flat=True)
            all_drivers = Driver.objects.exclude(id__in=demo_driver_ids).order_by('last_name')

        form = TeamForm(instance=team)
        formset = TeamSocialLinkFormSet(instance=team)

        if request.method == 'POST':
            form = TeamForm(request.POST, request.FILES, instance=team)
            formset = TeamSocialLinkFormSet(request.POST, instance=team)

            if form.is_valid() and formset.is_valid():
                team = form.save()

                if request.POST.get('delete_logo') == 'true':
                    team.logo = None
                    team.save()
                elif 'logo_upload' in request.FILES:
                    logo_image = Image.objects.create(
                        title=f"Логотип {team.name}",
                        file=request.FILES['logo_upload']
                    )
                    team.logo = logo_image
                    team.save()

                if request.POST.get('delete_manager_photo') == 'true':
                    team.manager_photo = None
                    team.save()
                elif 'manager_photo_upload' in request.FILES:
                    photo_image = Image.objects.create(
                        title=f"Фото руководителя {team.manager_name or team.name}",
                        file=request.FILES['manager_photo_upload']
                    )
                    team.manager_photo = photo_image
                    team.save()

                formset.save()
                messages.success(request, 'Информация обновлена')
                return redirect('teams:dashboard')
            else:
                messages.error(request, f'Ошибка в форме: {form.errors}')

        all_staff = TeamStaff.objects.all().order_by('last_name', 'first_name')

        staff_members = TeamStaff.objects.filter(
            team_memberships__team=team,
            team_memberships__is_active=True
        ).distinct().order_by('last_name', 'first_name')

        staff_list = []
        for staff in staff_members:
            membership = TeamStaffMembership.objects.filter(
                staff=staff,
                team=team,
                is_active=True
            ).first()
            staff_list.append({
                'staff': staff,
                'membership': membership,
            })

        from website.models import RaceClass
        pending_invitations = TeamInvitation.objects.filter(team=team, status='pending').select_related('driver', 'race_class')

        return render(request, 'teams/dashboard.html', {
            'team': team,
            'driver_classes': driver_classes,
            'pending_requests': pending_requests,
            'all_drivers': all_drivers,
            'is_demo_team': is_demo_team,
            'all_staff': all_staff,
            'staff_members': staff_list,
            'form': form,
            'formset': formset,
            'race_classes': RaceClass.objects.all(),
            'pending_invitations': pending_invitations,
        })

    except Exception as e:
        logger.exception('team dashboard: ошибка')
        messages.error(request, 'Не удалось загрузить кабинет. Попробуйте обновить страницу.')
        return redirect('/')


@login_required
def add_driver(request):
    """Добавление пилота в команду (капитан)"""
    if request.method == 'POST':
        driver_id = request.POST.get('driver_id')

        manager = TeamManager.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not manager:
            messages.error(request, 'Нет прав')
            return redirect('teams:dashboard')

        driver = get_object_or_404(Driver, id=driver_id)
        team = manager.team

        existing_membership = TeamMembership.objects.filter(
            driver=driver,
            team=team,
            is_active=True
        ).exists()

        if existing_membership:
            messages.warning(request, f'{driver.full_name} уже в команде')
        else:
            old_membership = TeamMembership.objects.filter(
                driver=driver,
                team=team,
                is_active=False
            ).first()

            if old_membership:
                old_membership.is_active = True
                old_membership.left_at = None
                old_membership.save()
                messages.success(request, f'{driver.full_name} снова в команде')
            else:
                TeamMembership.objects.create(
                    driver=driver,
                    team=team,
                    joined_at=timezone.now().date(),
                    is_active=True
                )
                messages.success(request, f'{driver.full_name} добавлен в команду')

    return redirect('teams:dashboard')


@login_required
def invite_driver(request):
    """Пригласить пилота в команду (создаёт TeamInvitation + отправляет email)"""
    if request.method != 'POST':
        return redirect('teams:dashboard')

    manager = TeamManager.objects.filter(user=request.user, is_active=True).first()
    if not manager:
        messages.error(request, 'Нет прав')
        return redirect('teams:dashboard')

    team = manager.team
    driver_id = request.POST.get('driver_id')
    race_class_id = request.POST.get('race_class_id')

    if not driver_id:
        messages.error(request, 'Выберите пилота')
        return redirect('teams:dashboard')

    driver = get_object_or_404(Driver, id=driver_id)

    # Проверяем, что пилот зарегистрирован на сайте
    from accounts.models import DriverClaim
    claim = DriverClaim.objects.filter(driver=driver, status='approved').first()
    if not claim:
        messages.error(request, f'{driver.full_name} не зарегистрирован на сайте — отправить приглашение невозможно.')
        return redirect('teams:dashboard')

    # Демо-фильтрация
    is_demo_team = request.user.email.startswith('demo_team_')
    is_demo_pilot = claim.user.email.startswith('demo_pilot_')
    if is_demo_team and not is_demo_pilot:
        messages.error(request, 'Демо-команда может приглашать только демо-пилотов.')
        return redirect('teams:dashboard')
    if not is_demo_team and is_demo_pilot:
        messages.error(request, 'Нельзя приглашать демо-пилотов в реальную команду.')
        return redirect('teams:dashboard')

    # Проверяем уже существующее приглашение
    existing = TeamInvitation.objects.filter(driver=driver, team=team).first()
    if existing:
        if existing.status == 'pending':
            messages.warning(request, f'Приглашение для {driver.full_name} уже отправлено и ожидает ответа.')
        elif existing.status == 'accepted':
            messages.warning(request, f'{driver.full_name} уже в команде.')
        else:
            # declined — позволяем повторно пригласить
            existing.status = 'pending'
            existing.responded_at = None
            existing.invited_by = request.user
            if race_class_id:
                from website.models import RaceClass
                try:
                    existing.race_class = RaceClass.objects.get(pk=race_class_id)
                except RaceClass.DoesNotExist:
                    pass
            existing.save()
            _send_team_invitation_email(driver, team, claim.user, existing)
            messages.success(request, f'Повторное приглашение отправлено {driver.full_name}.')
        return redirect('teams:dashboard')

    # Проверяем уже в команде
    if TeamMembership.objects.filter(driver=driver, team=team, is_active=True).exists():
        messages.warning(request, f'{driver.full_name} уже в команде.')
        return redirect('teams:dashboard')

    race_class = None
    if race_class_id:
        from website.models import RaceClass
        try:
            race_class = RaceClass.objects.get(pk=race_class_id)
        except RaceClass.DoesNotExist:
            pass

    invitation = TeamInvitation.objects.create(
        team=team,
        driver=driver,
        race_class=race_class,
        invited_by=request.user,
        status='pending',
    )
    _send_team_invitation_email(driver, team, claim.user, invitation)
    messages.success(request, f'Приглашение отправлено {driver.full_name}.')
    return redirect('teams:dashboard')


def _send_team_invitation_email(driver, team, user, invitation):
    from django.urls import reverse
    base_url = getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')
    race_class = invitation.race_class.name if invitation.race_class else ''
    rows = [('Команда', team.name), ('Руководитель', getattr(team, 'manager_name', '')), ('Класс', race_class)]
    try:
        send_templated_mail('team_invitation', f'Приглашение в команду {team.name}', [user.email], {
            'driver_name': driver.full_name,
            'team_name': team.name,
            'rows': [(label, value) for label, value in rows if value],
            'accept_url': base_url + reverse('teams:accept_invitation', args=[invitation.pk]),
            'decline_url': base_url + reverse('teams:decline_invitation', args=[invitation.pk]),
            'profile_url': base_url + reverse('accounts:profile'),
        }, fail_silently=True)
    except Exception:
        pass


@login_required
def accept_invitation(request, inv_id):
    """Пилот принимает приглашение"""
    from accounts.models import DriverClaim
    claim = DriverClaim.objects.filter(user=request.user, status='approved').first()
    if not claim:
        messages.error(request, 'Нет привязанного профиля пилота.')
        return redirect('accounts:profile')

    invitation = get_object_or_404(TeamInvitation, pk=inv_id, driver=claim.driver, status='pending')

    # Создаём членство
    existing = TeamMembership.objects.filter(driver=invitation.driver, team=invitation.team).first()
    if existing:
        existing.is_active = True
        existing.left_at = None
        existing.race_class = invitation.race_class
        existing.save()
    else:
        TeamMembership.objects.create(
            driver=invitation.driver,
            team=invitation.team,
            race_class=invitation.race_class,
            joined_at=timezone.now().date(),
            is_active=True,
        )

    invitation.status = 'accepted'
    invitation.responded_at = timezone.now()
    invitation.save()
    messages.success(request, f'Вы приняты в команду {invitation.team.name}!')
    return redirect('accounts:profile')


@login_required
def decline_invitation(request, inv_id):
    """Пилот отклоняет приглашение"""
    from accounts.models import DriverClaim
    claim = DriverClaim.objects.filter(user=request.user, status='approved').first()
    if not claim:
        return redirect('accounts:profile')

    invitation = get_object_or_404(TeamInvitation, pk=inv_id, driver=claim.driver, status='pending')
    invitation.status = 'declined'
    invitation.responded_at = timezone.now()
    invitation.save()
    messages.info(request, f'Приглашение от команды {invitation.team.name} отклонено.')
    return redirect('accounts:profile')


@login_required
def remove_driver(request, driver_id):
    """Удаление пилота из команды"""
    if request.method == 'POST':
        manager = TeamManager.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not manager:
            messages.error(request, 'Нет прав')
            return redirect('teams:dashboard')

        driver = get_object_or_404(Driver, id=driver_id)

        membership = TeamMembership.objects.filter(
            driver=driver,
            team=manager.team,
            is_active=True
        ).first()

        if membership:
            membership.left_at = timezone.now().date()
            membership.is_active = False
            membership.save()
            messages.success(request, f'{driver.full_name} удалён из команды')
        else:
            messages.warning(request, f'{driver.full_name} не найден в команде')

    return redirect('teams:dashboard')


@login_required
def approve_request(request, request_id):
    """Подтверждение заявки на вступление"""
    if request.method == 'POST':
        join_request = get_object_or_404(TeamJoinRequest, id=request_id)

        manager = TeamManager.objects.filter(
            user=request.user,
            team=join_request.team,
            is_active=True
        ).exists()

        if not manager:
            messages.error(request, 'Нет прав')
            return redirect('teams:dashboard')

        join_request.status = 'approved'
        join_request.reviewed_by = request.user
        join_request.reviewed_at = timezone.now()
        join_request.save()

        messages.success(request, f'{join_request.driver.full_name} принят в команду')

    return redirect('teams:dashboard')


@login_required
def reject_request(request, request_id):
    """Отклонение заявки на вступление"""
    if request.method == 'POST':
        join_request = get_object_or_404(TeamJoinRequest, id=request_id)

        manager = TeamManager.objects.filter(
            user=request.user,
            team=join_request.team,
            is_active=True
        ).exists()

        if not manager:
            messages.error(request, 'Нет прав')
            return redirect('teams:dashboard')

        join_request.status = 'rejected'
        join_request.reviewed_by = request.user
        join_request.reviewed_at = timezone.now()
        join_request.save()

        messages.success(request, f'Заявка {join_request.driver.full_name} отклонена')

    return redirect('teams:dashboard')


@login_required
def logout_view(request):
    """Выход из системы"""
    logout(request)
    return redirect('choose_role')


@login_required
def add_staff(request):
    """Добавление сотрудника в команду"""
    if request.method == 'POST':
        manager = TeamManager.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not manager:
            messages.error(request, 'Нет прав')
            return redirect('teams:dashboard')

        team = manager.team
        staff_id = request.POST.get('staff_id')

        if staff_id == 'new':
            form = TeamStaffForm(request.POST, request.FILES)
            formset = TeamStaffSocialLinkFormSet(request.POST)

            if form.is_valid() and formset.is_valid():
                staff = form.save(commit=False)

                if 'photo_upload' in request.FILES:
                    photo_file = request.FILES['photo_upload']
                    wagtail_image = Image(
                        title=f"{staff.last_name} {staff.first_name} - фото сотрудника",
                        file=photo_file
                    )
                    wagtail_image.save()
                    staff.photo = wagtail_image
                else:
                    staff.photo = None

                staff.save()
                formset.instance = staff
                formset.save()

                TeamStaffMembership.objects.create(
                    staff=staff,
                    team=team,
                    is_active=True
                )
                messages.success(request, f'Сотрудник {staff.full_name} добавлен')
            else:
                error_msg = "Ошибка в форме: "
                if form.errors:
                    error_msg += f"Основная форма: {form.errors}"
                if formset.errors:
                    error_msg += f" Соцсети: {formset.errors}"
                messages.error(request, error_msg)
        else:
            try:
                staff = TeamStaff.objects.get(id=staff_id)
                existing_membership = TeamStaffMembership.objects.filter(
                    staff=staff,
                    team=team
                ).first()

                if existing_membership:
                    if existing_membership.is_active:
                        messages.info(request, f'{staff.full_name} уже активен в вашей команде')
                    else:
                        existing_membership.is_active = True
                        existing_membership.left_at = None
                        existing_membership.joined_at = timezone.now().date()
                        existing_membership.save()
                        messages.success(request, f'{staff.full_name} снова в команде')
                else:
                    TeamStaffMembership.objects.create(
                        staff=staff,
                        team=team,
                        joined_at=timezone.now().date(),
                        is_active=True
                    )
                    messages.success(request, f'{staff.full_name} добавлен в команду')
            except TeamStaff.DoesNotExist:
                messages.error(request, 'Сотрудник не найден')

    return redirect('teams:dashboard')


@login_required
def remove_staff(request, staff_id):
    """Удаление сотрудника из команды"""
    if request.method == 'POST':
        manager = TeamManager.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not manager:
            messages.error(request, 'Нет прав')
            return redirect('teams:dashboard')

        membership = TeamStaffMembership.objects.filter(
            staff_id=staff_id,
            team=manager.team,
            is_active=True
        ).first()

        if membership:
            membership.is_active = False
            membership.left_at = timezone.now().date()
            membership.save()
            messages.success(request, 'Сотрудник удалён из команды')
        else:
            messages.warning(request, 'Сотрудник не найден в команде')

    return redirect('teams:dashboard')


@login_required
def edit_staff(request, staff_id):
    """Редактирование сотрудника"""
    if request.method == 'POST':
        manager = TeamManager.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not manager:
            messages.error(request, 'Нет прав')
            return redirect('teams:dashboard')

        staff = get_object_or_404(TeamStaff, id=staff_id)

        membership = TeamStaffMembership.objects.filter(
            staff=staff,
            team=manager.team,
            is_active=True
        ).exists()

        if not membership:
            messages.error(request, 'Этот сотрудник не в вашей команде')
            return redirect('teams:dashboard')

        form = TeamStaffForm(request.POST, request.FILES, instance=staff)
        formset = TeamStaffSocialLinkFormSet(request.POST, instance=staff)

        if form.is_valid() and formset.is_valid():
            staff = form.save(commit=False)

            if 'photo_upload' in request.FILES:
                photo_file = request.FILES['photo_upload']
                wagtail_image = Image(
                    title=f"{staff.last_name} {staff.first_name} - фото сотрудника",
                    file=photo_file
                )
                wagtail_image.save()
                staff.photo = wagtail_image

            staff.save()
            formset.save()

            messages.success(request, f'Данные {staff.full_name} обновлены')
        else:
            messages.error(request, f'Ошибка в форме: {form.errors}')

    return redirect('teams:dashboard')

def join_team(request, team_slug):
    """Заявка авторизованного пилота на вступление в команду."""
    from website.models import Team, TeamMembership

    team = get_object_or_404(Team, slug=team_slug)

    if not request.user.is_authenticated:
        messages.error(request, 'Войдите в аккаунт чтобы подать заявку')
        return redirect(f'/accounts/login/?next=/teams/{team_slug}/')

    if request.method != 'POST':
        return redirect('team_detail', slug=team_slug)

    try:
        driver = request.user.profile.driver
    except Exception:
        driver = None

    if not driver:
        messages.error(request, 'Привяжите профиль пилота в личном кабинете')
        return redirect('team_detail', slug=team_slug)

    comment = request.POST.get('comment', '').strip()

    if TeamMembership.objects.filter(driver=driver, team=team, is_active=True).exists():
        messages.warning(request, f'Вы уже являетесь членом команды {team.name}')
        return redirect('team_detail', slug=team_slug)

    if TeamJoinRequest.objects.filter(driver=driver, team=team, status='pending').exists():
        messages.warning(request, f'Ваша заявка в команду {team.name} уже ожидает рассмотрения')
        return redirect('team_detail', slug=team_slug)

    TeamJoinRequest.objects.update_or_create(
        driver=driver,
        team=team,
        defaults={'status': 'pending', 'comment': comment},
    )
    messages.success(
        request,
        f'Заявка отправлена! Менеджер команды {team.name} рассмотрит её в ближайшее время.'
    )
    return redirect('team_detail', slug=team_slug)


@login_required
def team_apply(request, stage_id):
    """Регистрация пилота на этап от имени команды."""
    from organizers.models import Stage
    from applications.models import Application, ApplicationPilot, ApplicationApplicant, ApplicationPayment
    from website.models import TeamMembership, Driver

    manager = TeamManager.objects.filter(
        user=request.user, is_active=True
    ).select_related('team').first()
    if not manager:
        messages.error(request, 'У вас нет прав менеджера команды.')
        return redirect('teams:dashboard')

    stage = get_object_or_404(Stage, pk=stage_id)
    if not stage.registration_enabled:
        messages.error(request, 'Регистрация на этот этап закрыта.')
        return redirect('teams:dashboard')

    team = manager.team
    members = TeamMembership.objects.filter(team=team, is_active=True).select_related('driver')

    # Помечаем тех кто уже зарегистрирован
    for m in members:
        m.already_registered = Application.objects.filter(
            stage=stage, pilot__driver=m.driver
        ).exclude(status='cancelled').exists()

    # Тот же источник, что и applications/views.py::_stage_classes — раньше
    # тут был fallback на RaceClass.objects.filter(stageoptions__stage=stage),
    # но такой связи на RaceClass не существует (StageOption — про платные
    # опции регистрации в applications/models.py, не про классы вообще);
    # обращение к ней падало FieldError на любом чемпионате с пустым
    # race_classes — поймано тестом, а не наблюдением, значит багался вживую.
    classes = list(stage.championship.race_classes.all())

    if request.method == 'POST':
        driver_id = request.POST.get('driver_id')
        race_class_id = request.POST.get('race_class')
        start_number = request.POST.get('start_number')

        if not driver_id:
            messages.error(request, 'Выберите пилота.')
        else:
            # Проверяем через тот же members (активный ростер команды), а не
            # голый Driver.objects.get — иначе менеджер одной команды мог бы
            # заявкой на этап зарегистрировать произвольного пилота чужой
            # команды по одному только его id.
            membership = members.filter(driver_id=driver_id).first()
            if not membership:
                messages.error(request, 'Выбранный пилот не является членом вашей команды.')
                return render(request, 'teams/team_apply.html', {
                    'stage': stage,
                    'team': team,
                    'members': members,
                    'classes': classes,
                    'available_numbers': stage.get_available_numbers(),
                    'rep_first_name': request.user.first_name,
                    'rep_last_name': request.user.last_name,
                    'rep_email': request.user.email,
                })
            driver = membership.driver

            # Проверка дублирования
            if Application.objects.filter(stage=stage, pilot__driver=driver).exclude(status='cancelled').exists():
                messages.error(request, f'Пилот {driver.full_name} уже зарегистрирован на этот этап.')
            else:
                chosen_number = None
                if start_number:
                    try:
                        chosen_number = int(start_number)
                    except ValueError:
                        pass

                entry_fee = stage.entry_fee or 0

                app = Application.objects.create(
                    stage=stage,
                    submitted_by=request.user,
                    submitted_by_type='team',
                    race_class_id=race_class_id or None,
                    start_number=chosen_number,
                    status='draft',
                    entry_fee_amount=entry_fee,
                )

                ApplicationPilot.objects.create(
                    application=app,
                    driver=driver,
                    first_name=driver.full_name.split()[1] if len(driver.full_name.split()) > 1 else '',
                    last_name=driver.full_name.split()[0],
                    email=driver.user_profile.user.email if hasattr(driver, 'user_profile') and driver.user_profile else '',
                    phone='',
                )

                ApplicationApplicant.objects.create(
                    application=app,
                    type='team',
                    team=team,
                    name=team.name,
                    rep_first_name=request.POST.get('rep_first_name', ''),
                    rep_last_name=request.POST.get('rep_last_name', ''),
                    rep_email=request.POST.get('rep_email', request.user.email),
                    rep_phone=request.POST.get('rep_phone', ''),
                )

                ApplicationPayment.objects.create(
                    application=app,
                    amount=entry_fee,
                    status='pending',
                    method='manual',
                )

                messages.success(request, f'Заявка для {driver.full_name} создана.')
                return redirect('applications:detail', application_id=app.pk)

    available_numbers = stage.get_available_numbers()

    return render(request, 'teams/team_apply.html', {
        'stage': stage,
        'team': team,
        'members': members,
        'classes': classes,
        'available_numbers': available_numbers,
        'rep_first_name': request.user.first_name,
        'rep_last_name': request.user.last_name,
        'rep_email': request.user.email,
    })


@login_required
def team_add_driver(request, stage_id):
    """Добавить пилота в команду и вернуться к регистрации."""
    from website.models import TeamMembership, Driver

    manager = TeamManager.objects.filter(
        user=request.user, is_active=True
    ).select_related('team').first()
    if not manager or request.method != 'POST':
        return redirect('teams:dashboard')

    driver_id = request.POST.get('driver_id')
    if driver_id:
        driver = get_object_or_404(Driver, pk=driver_id)
        TeamMembership.objects.get_or_create(
            driver=driver,
            team=manager.team,
            defaults={'is_active': True},
        )
        obj = TeamMembership.objects.filter(driver=driver, team=manager.team).first()
        if obj and not obj.is_active:
            obj.is_active = True
            obj.save()
        messages.success(request, f'{driver.full_name} добавлен в команду.')

    return redirect('teams:team_apply', stage_id=stage_id)


def team_driver_search(request):
    """AJAX-поиск пилотов по имени."""
    from django.http import JsonResponse
    from website.models import Driver

    q = request.GET.get('q', '').strip()
    results = []
    if len(q) >= 2:
        from website.services.demo import without_demo
        drivers = without_demo(Driver.objects.filter(full_name__icontains=q))[:10]
        results = [{'id': d.pk, 'name': d.full_name} for d in drivers]
    return JsonResponse({'drivers': results})
