from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login
from django.db.models import Q
from .forms import TeamRegistrationForm
from website.models import Team, Driver, TeamSocialLink, TeamMembership
from .models import TeamClaim
from django.contrib.auth import authenticate, login as auth_login

from django.contrib.auth.decorators import login_required
from .models import TeamManager, TeamJoinRequest
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
        fail_silently=False,
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
                return redirect('teams:dashboard')
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
            messages.error(request, 'У вас нет прав на управление командой')
            return redirect('/')

        team = manager.team

        drivers = Driver.objects.filter(
            team_memberships__team=team,
            team_memberships__is_active=True
        ).distinct().order_by('last_name')

        driver_classes = []

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

        driver_classes.sort(key=lambda x: x['last_date'], reverse=True)

        pending_requests = TeamJoinRequest.objects.filter(
            team=team,
            status='pending'
        ).select_related('driver')

        all_drivers = Driver.objects.all().order_by('last_name')

        form = TeamForm(instance=team)
        formset = TeamSocialLinkFormSet(instance=team)

        if request.method == 'POST':
            form = TeamForm(request.POST, request.FILES, instance=team)
            formset = TeamSocialLinkFormSet(request.POST, instance=team)

            if form.is_valid() and formset.is_valid():
                team = form.save()

                if 'logo_upload' in request.FILES:
                    logo_image = Image.objects.create(
                        title=f"Логотип {team.name}",
                        file=request.FILES['logo_upload']
                    )
                    team.logo = logo_image
                    team.save()

                if 'manager_photo_upload' in request.FILES:
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

        return render(request, 'teams/dashboard.html', {
            'team': team,
            'driver_classes': driver_classes,
            'pending_requests': pending_requests,
            'all_drivers': all_drivers,
            'all_staff': all_staff,
            'staff_members': staff_list,
            'form': form,
            'formset': formset,
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
    return redirect('/')


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
