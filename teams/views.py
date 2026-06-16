from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login
from django.db.models import Q
from .forms import TeamRegistrationForm
from website.models import Team, Driver, TeamSocialLink, TeamMembership
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
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings


def send_team_verification_email(user, request):
    """Отправка письма с подтверждением email для команды"""
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verification_url = request.build_absolute_uri(
        f'/teams/verify-email/{uid}/{token}/'
    )
    
    subject = 'Подтверждение регистрации команды на Gripline'
    html_message = render_to_string('emails/team_verification_email.html', {
        'user': user,
        'verification_url': verification_url,
        'expiry_minutes': 30,
    })
    plain_message = f'Перейдите по ссылке для подтверждения: {verification_url}'
    
    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False,
    )


def send_team_admin_notification(claim_data):
    """Отправка уведомления администратору о новой заявке команды"""
    subject = '[Gripline] Новая заявка от команды'
    message = f"""
Поступила новая заявка на управление командой:

Email пользователя: {claim_data.get('user_email')}
Название команды: {claim_data.get('team_name')}
Статус: новая заявка

Зайдите в админку для подтверждения: https://gripline.ru/admin/
"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        ['gripline.ru@yandex.ru'],
        fail_silently=True,
    )


def team_verification_sent(request):
    """Страница «Письмо отправлено» для команды"""
    return render(request, 'teams/verification_sent.html')


def team_verify_email(request, uidb64, token):
    """Подтверждение email для команды"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    
    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        
        # Проверяем, есть ли данные в сессии
        requested_team_name = request.session.get('team_requested_name')
        if requested_team_name:
            # Ищем похожие команды
            teams = Team.objects.filter(name__icontains=requested_team_name)
            if teams.exists():
                request.session['found_teams'] = [
                    {'id': t.id, 'name': t.name}
                    for t in teams
                ]
                request.session['user_id'] = user.id
                request.session['requested_team_name'] = requested_team_name
                messages.success(request, 'Email подтверждён! Теперь выберите команду.')
                return redirect('teams:select_team')
            else:
                # Создаём заявку на новую команду
                TeamClaim.objects.create(
                    user=user,
                    requested_team_name=requested_team_name,
                    status='pending'
                )
                send_team_admin_notification({
                    'user_email': user.email,
                    'team_name': requested_team_name,
                })
                messages.success(request, 'Email подтверждён! Заявка отправлена администратору.')
                return redirect('teams:login')
        else:
            messages.success(request, 'Email подтверждён! Теперь вы можете войти.')
            return redirect('teams:login')
    else:
        return render(request, 'teams/verification_failed.html')


def team_resend_verification(request):
    """Повторная отправка письма для команды"""
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email, is_active=False)
            send_team_verification_email(user, request)
            messages.success(request, 'Письмо отправлено повторно.')
            return redirect('teams:team_verification_sent')
        except User.DoesNotExist:
            messages.error(request, 'Пользователь с таким email не найден или уже активирован.')
    return render(request, 'teams/verification_resend.html')


def register(request):
    """Регистрация представителя команды с email-подтверждением"""
    if request.method == 'POST':
        form = TeamRegistrationForm(request.POST)
        if form.is_valid():
            email = request.POST.get('email')
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Пользователь с таким email уже зарегистрирован.')
                return render(request, 'teams/register.html', {'form': form})
            
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            
            team_name = form.cleaned_data['team_name']
            request.session['team_requested_name'] = team_name
            request.session['team_user_id'] = user.id
            
            try:
                send_team_verification_email(user, request)
                messages.success(request, 'Письмо отправлено. Подтвердите email.')
                return redirect('teams:team_verification_sent')
            except Exception as e:
                user.delete()
                messages.error(request, f'Ошибка отправки письма: {str(e)}')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = TeamRegistrationForm()
    
    return render(request, 'teams/register.html', {'form': form})


def select_team(request):
    """Страница выбора команды из найденных"""
    found_teams = request.session.get('found_teams', [])
    user_id = request.session.get('user_id')
    requested_team_name = request.session.get('requested_team_name')

    if not found_teams or not user_id:
        return redirect('teams:register')

    if request.method == 'POST':
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=user_id)

        selected_id = request.POST.get('team_id')

        if selected_id == 'none':
            TeamClaim.objects.create(
                user=user,
                requested_team_name=requested_team_name,
                status='pending'
            )
            send_team_admin_notification({
                'user_email': user.email,
                'team_name': requested_team_name,
            })
            messages.success(request, 'Заявка на создание команды отправлена администратору')
        else:
            team = Team.objects.get(id=selected_id)
            TeamClaim.objects.create(
                user=user,
                team=team,
                requested_team_name=requested_team_name,
                status='pending'
            )
            send_team_admin_notification({
                'user_email': user.email,
                'team_name': team.name,
            })
            messages.success(request, f'Заявка на управление командой {team.name} отправлена администратору')

        for key in ['found_teams', 'user_id', 'requested_team_name', 'team_requested_name', 'team_user_id']:
            if key in request.session:
                del request.session[key]

        return redirect('teams:login')

    return render(request, 'teams/select_team.html', {
        'teams': found_teams,
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
        fields = ['description', 'manager_name', 'manager_email', 'manager_phone', 'manager_social']
        widgets = {
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
            'all_staff': all_staff,
            'staff_members': staff_list,
            'form': form,
            'formset': formset,
            'race_classes': RaceClass.objects.all().order_by('name'),
            'pending_invitations': pending_invitations,
        })

    except Exception as e:
        messages.error(request, f'Ошибка: {str(e)}')
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
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.conf import settings
    try:
        body = render_to_string('teams/email_invitation.html', {
            'driver': driver,
            'team': team,
            'invitation': invitation,
            'base_url': getattr(settings, 'BASE_URL', 'https://gripline.ru'),
        })
        send_mail(
            subject=f'Приглашение в команду {team.name}',
            message='',
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user.email],
            html_message=body,
            fail_silently=True,
        )
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

@login_required
def team_apply(request, stage_id):
    """Регистрация пилота команды на этап от имени команды"""
    from organizers.models import Stage
    from applications.models import (
        Application, ApplicationApplicant, ApplicationPilot, ApplicationPayment
    )
    from django.http import JsonResponse
    from decimal import Decimal
    from django.utils import timezone as tz

    manager = TeamManager.objects.filter(
        user=request.user, is_active=True
    ).select_related('team').first()

    if not manager:
        messages.error(request, 'У вас нет прав управления командой.')
        return redirect('/')

    stage = get_object_or_404(Stage, pk=stage_id)
    if not stage.registration_enabled:
        messages.error(request, 'Регистрация на этот этап закрыта.')
        return redirect('/')

    team = manager.team
    memberships = TeamMembership.objects.filter(
        team=team, is_active=True
    ).select_related('driver')

    classes = list(stage.championship.race_classes.all())
    first_class = classes[0] if classes else None
    available_numbers = stage.get_available_numbers(race_class=first_class)

    # Вычисляем взнос с учётом позднего срока
    entry_fee = stage.entry_fee
    if (getattr(stage, 'late_registration_allowed', False)
            and getattr(stage, 'registration_deadline', None)
            and tz.now() > stage.registration_deadline):
        multiplier = getattr(stage, 'late_registration_fee_multiplier', Decimal('1'))
        entry_fee = entry_fee * multiplier

    # Определяем, кто уже зарегистрирован
    already_registered_ids = set(
        Application.objects.filter(
            stage=stage
        ).exclude(status='cancelled').values_list('pilot__driver_id', flat=True)
    )

    # Данные менеджера для автозаполнения представителя
    user = request.user
    rep_first_name = user.first_name or ''
    rep_last_name = user.last_name or ''
    rep_email = user.email or ''
    rep_phone = ''
    try:
        profile = user.profile
        rep_phone = getattr(profile, 'phone', '') or ''
        if not rep_first_name:
            rep_first_name = getattr(profile, 'first_name', '') or ''
        if not rep_last_name:
            rep_last_name = getattr(profile, 'last_name', '') or ''
    except Exception:
        pass

    if request.method == 'POST':
        driver_id = request.POST.get('driver_id')
        race_class_id = request.POST.get('race_class')
        start_number = request.POST.get('start_number')
        post_rep_first = request.POST.get('rep_first_name', rep_first_name).strip()
        post_rep_last = request.POST.get('rep_last_name', rep_last_name).strip()
        post_rep_email = request.POST.get('rep_email', rep_email).strip()
        post_rep_phone = request.POST.get('rep_phone', rep_phone).strip()

        # Валидация
        errors = []
        if not driver_id:
            errors.append('Выберите пилота.')
        if not race_class_id:
            errors.append('Выберите класс.')
        if not start_number:
            errors.append('Выберите стартовый номер.')

        driver = None
        if driver_id:
            membership = memberships.filter(driver_id=driver_id).first()
            if not membership:
                errors.append('Выбранный пилот не является членом вашей команды.')
            else:
                driver = membership.driver

        chosen_number = None
        if start_number:
            try:
                chosen_number = int(start_number)
                # Пересчитываем доступные номера для выбранного класса
                from website.models import RaceClass
                selected_class = None
                if race_class_id:
                    try:
                        selected_class = RaceClass.objects.get(pk=race_class_id)
                    except Exception:
                        pass
                current_available = stage.get_available_numbers(race_class=selected_class)
                if chosen_number not in current_available:
                    errors.append('Выбранный номер уже занят. Выберите другой.')
            except ValueError:
                errors.append('Некорректный стартовый номер.')

        if driver and not errors:
            # Проверяем, нет ли уже активной заявки для этого пилота
            existing = Application.objects.filter(
                stage=stage, pilot__driver=driver
            ).exclude(status='cancelled').first()
            if existing:
                errors.append(
                    f'Пилот {driver.full_name} уже зарегистрирован на этот этап.'
                )

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            # Создаём заявку
            application = Application.objects.create(
                stage=stage,
                submitted_by=request.user,
                submitted_by_type='team',
                race_class_id=race_class_id,
                start_number=chosen_number,
                status='draft',
                entry_fee_amount=entry_fee,
            )

            # Данные пилота из Driver
            ApplicationPilot.objects.create(
                application=application,
                driver=driver,
                first_name=driver.first_name,
                last_name=driver.last_name,
                email='',
                phone='',
            )

            # Заявитель — команда
            ApplicationApplicant.objects.create(
                application=application,
                type='team',
                team=team,
                name=team.name,
                rep_first_name=post_rep_first,
                rep_last_name=post_rep_last,
                rep_email=post_rep_email,
                rep_phone=post_rep_phone,
            )

            # Оплата
            ApplicationPayment.objects.create(
                application=application,
                amount=entry_fee,
                method='manual',
                status='pending',
            )

            messages.success(
                request,
                f'Заявка для пилота {driver.full_name} успешно создана!'
            )
            return redirect('applications:detail', application_id=application.pk)

    return render(request, 'teams/team_apply.html', {
        'stage': stage,
        'team': team,
        'memberships': memberships,
        'already_registered_ids': already_registered_ids,
        'classes': classes,
        'available_numbers': available_numbers,
        'entry_fee': entry_fee,
        'rep_first_name': rep_first_name,
        'rep_last_name': rep_last_name,
        'rep_email': rep_email,
        'rep_phone': rep_phone,
    })


@login_required
def team_add_driver(request, stage_id):
    """Добавляет водителя в команду и возвращает на team_apply"""
    from django.http import JsonResponse

    if request.method != 'POST':
        return redirect('teams:team_apply', stage_id=stage_id)

    manager = TeamManager.objects.filter(
        user=request.user, is_active=True
    ).select_related('team').first()

    if not manager:
        messages.error(request, 'Нет прав.')
        return redirect('/')

    driver_id = request.POST.get('driver_id')
    if not driver_id:
        messages.error(request, 'Не указан пилот.')
        return redirect('teams:team_apply', stage_id=stage_id)

    driver = get_object_or_404(Driver, pk=driver_id)
    team = manager.team

    existing = TeamMembership.objects.filter(driver=driver, team=team).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.left_at = None
            existing.save()
            messages.success(request, f'{driver.full_name} снова добавлен в команду.')
        else:
            messages.info(request, f'{driver.full_name} уже в команде.')
    else:
        TeamMembership.objects.create(
            driver=driver, team=team,
            joined_at=timezone.now().date(), is_active=True
        )
        messages.success(request, f'{driver.full_name} добавлен в команду.')

    return redirect('teams:team_apply', stage_id=stage_id)


def team_driver_search(request):
    """AJAX-поиск пилотов по имени для добавления в команду"""
    from django.http import JsonResponse

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'drivers': []})

    drivers = Driver.objects.filter(
        Q(first_name__icontains=q) | Q(last_name__icontains=q)
    ).order_by('last_name', 'first_name')[:15]

    data = [
        {
            'id': d.id,
            'full_name': d.full_name,
            'city': getattr(d, 'city', '') or '',
        }
        for d in drivers
    ]
    return JsonResponse({'drivers': data})


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

    manager = TeamManager.objects.filter(user=request.user).select_related('team').first()
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

    from website.models import RaceClass
    classes = list(stage.championship.race_classes.all()) if hasattr(stage.championship, 'race_classes') else []
    if not classes:
        from organizers.models import Stage as OrgStage
        classes = list(RaceClass.objects.filter(stageoptions__stage=stage).distinct())

    if request.method == 'POST':
        driver_id = request.POST.get('driver_id')
        race_class_id = request.POST.get('race_class')
        start_number = request.POST.get('start_number')

        if not driver_id:
            messages.error(request, 'Выберите пилота.')
        else:
            driver = get_object_or_404(Driver, pk=driver_id)

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

    manager = TeamManager.objects.filter(user=request.user).select_related('team').first()
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
        drivers = Driver.objects.filter(full_name__icontains=q)[:10]
        results = [{'id': d.pk, 'name': d.full_name} for d in drivers]
    return JsonResponse({'drivers': results})
