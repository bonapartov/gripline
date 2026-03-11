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
from tg_bot.qr_code import generate_telegram_qr

def register(request):
    """Регистрация представителя команды"""
    if request.method == 'POST':
        form = TeamRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            print(f"Создан пользователь: {user.username}, {user.email}")
            team_name = form.cleaned_data['team_name']

            # === НОВАЯ ПРОВЕРКА 1: Уже менеджер? ===
            from .models import TeamManager
            if TeamManager.objects.filter(user=user, is_active=True).exists():
                messages.warning(request, 'Вы уже являетесь менеджером команды')
                return redirect('teams:dashboard')

            # === НОВАЯ ПРОВЕРКА 2: Уже есть pending заявка? ===
            existing_claim = TeamClaim.objects.filter(
                user=user,
                status='pending'
            ).first()

            if existing_claim:
                # Показываем статус существующей заявки
                from tg_bot.qr_code import generate_telegram_qr
                qr_code = generate_telegram_qr('gripline_bot', user.email)

                return render(request, 'teams/register.html', {
                    'form': form,
                    'show_qr': True,
                    'qr_code': qr_code,
                    'existing_claim': existing_claim,
                    'registration_success': True
                })

            # Ищем похожие команды
            teams = Team.objects.filter(name__icontains=team_name)

            if teams.exists():
                # Сохраняем в сессию
                request.session['found_teams'] = [
                    {'id': t.id, 'name': t.name}
                    for t in teams
                ]
                request.session['user_id'] = user.id
                request.session['requested_team_name'] = team_name

                return redirect('teams:select_team')
            else:
                # Создаем заявку
                TeamClaim.objects.create(
                    user=user,
                    requested_team_name=team_name,
                    status='pending'
                )

                # Генерируем QR-код
                from tg_bot.qr_code import generate_telegram_qr
                qr_code = generate_telegram_qr('gripline_bot', user.email)

                print(f"🔍 QR-код для email: {user.email}")
                print(f"🔍 Ссылка: https://t.me/gripline_moderation_bot?start={user.email}")

                return render(request, 'teams/register.html', {
                    'form': form,
                    'show_qr': True,
                    'qr_code': qr_code,
                    'registration_success': True
                })


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
            # Создаем заявку на новую команду
            TeamClaim.objects.create(
                user=user,
                requested_team_name=requested_team_name,
                status='pending'
            )
            messages.success(request, 'Заявка на создание команды отправлена администратору')
        else:
            # Привязываем к существующей команде
            team = Team.objects.get(id=selected_id)
            TeamClaim.objects.create(
                user=user,
                team=team,
                requested_team_name=requested_team_name,
                status='pending'
            )
            messages.success(request, f'Заявка на управление командой {team.name} отправлена администратору')

        # Очищаем сессию
        for key in ['found_teams', 'user_id', 'requested_team_name']:
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

        # СПОСОБ 1: Ищем пользователя по email
        from django.contrib.auth.models import User
        try:
            user_obj = User.objects.get(email=email)
            # Аутентифицируем по username (который нашли по email)
            user = authenticate(request, username=user_obj.username, password=password)
        except User.DoesNotExist:
            user = None

        if user is not None:
            auth_login(request, user)
            return redirect('teams:dashboard')
        else:
            messages.error(request, 'Неверный email или пароль')

    return render(request, 'teams/login.html')

# Формы для редактирования команды
class TeamForm(forms.ModelForm):
    # Добавляем отдельное поле для загрузки файла
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
        # Если редактируем существующую команду, показываем текущие файлы
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
    extra=1,
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
    # Проверяем, является ли пользователь менеджером команды
    try:
        print("\n" + "="*50)
        print("ЗАПРОС К DASHBOARD")
        print(f"METHOD: {request.method}")
        if request.method == 'POST':
            print(f"POST keys: {request.POST.keys()}")
            print(f"FILES keys: {request.FILES.keys()}")
            print(f"logo in FILES: {'logo' in request.FILES}")
            if 'logo' in request.FILES:
                print(f"logo filename: {request.FILES['logo'].name}")
        print("="*50 + "\n")

        manager = TeamManager.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('team').first()

        if not manager:
            messages.error(request, 'У вас нет прав на управление командой')
            return redirect('/')

        team = manager.team

        # Получаем пилотов команды (только активные членства)
        drivers = Driver.objects.filter(
            team_memberships__team=team,
            team_memberships__is_active=True
        ).distinct().order_by('last_name')

        # Создаем словарь для хранения последнего этапа по каждому классу
        driver_classes = []

        for driver in drivers:
            # Для каждого пилота получаем все классы, в которых он выступал за эту команду за 6 месяцев
            six_months_ago = timezone.now() - timedelta(days=180)

            classes_with_dates = RaceResult.objects.filter(
                team=team,
                driver=driver,
                group__page__last_published_at__gte=six_months_ago
            ).values('group__race_class__name').annotate(
                last_date=Max('group__page__last_published_at')
            ).order_by('-last_date')

            # Добавляем каждую запись в driver_classes
            for item in classes_with_dates:
                driver_classes.append({
                    'driver': driver,
                    'class_name': item['group__race_class__name'],
                    'last_date': item['last_date'],
                })

        # Сортируем по дате (самые свежие сверху)
        driver_classes.sort(key=lambda x: x['last_date'], reverse=True)

        # Получаем заявки на вступление
        pending_requests = TeamJoinRequest.objects.filter(
            team=team,
            status='pending'
        ).select_related('driver')

        # Получаем всех пилотов для добавления
        all_drivers = Driver.objects.all().order_by('last_name')

        # СОЗДАЕМ ФОРМЫ ЗДЕСЬ (для GET и для случая, если POST не сработал)
        form = TeamForm(instance=team)
        formset = TeamSocialLinkFormSet(instance=team)

        if request.method == 'POST':
            print("\n" + "="*50)
            print("🔥 POST запрос получен")
            print(f"FILES: {request.FILES}")
            print(f"POST: {request.POST}")
            print("="*50)

            form = TeamForm(request.POST, request.FILES, instance=team)
            formset = TeamSocialLinkFormSet(request.POST, instance=team)

            if form.is_valid() and formset.is_valid():
                # Сохраняем форму
                team = form.save()

                # Обработка логотипа
                if 'logo_upload' in request.FILES:
                    from wagtail.images.models import Image
                    logo_image = Image.objects.create(
                        title=f"Логотип {team.name}",
                        file=request.FILES['logo_upload']
                    )
                    team.logo = logo_image
                    team.save()
                    print(f"✅ Логотип сохранен: ID {logo_image.id}")

                # Обработка фото руководителя
                if 'manager_photo_upload' in request.FILES:
                    from wagtail.images.models import Image
                    photo_image = Image.objects.create(
                        title=f"Фото руководителя {team.manager_name or team.name}",
                        file=request.FILES['manager_photo_upload']
                    )
                    team.manager_photo = photo_image
                    team.save()
                    print(f"✅ Фото руководителя сохранено: ID {photo_image.id}")

                formset.save()
                messages.success(request, 'Информация обновлена')
                return redirect('teams:dashboard')
            else:
                print(f"❌ ОШИБКИ ФОРМЫ: {form.errors}")
                print(f"❌ ОШИБКИ ФОРМСЕТА: {formset.errors}")
                messages.error(request, f'Ошибка в форме: {form.errors}')




        # Получаем всех сотрудников для поиска
        all_staff = TeamStaff.objects.all().order_by('last_name', 'first_name')

        # Получаем активных сотрудников команды
        staff_members = TeamStaff.objects.filter(
            team_memberships__team=team,
            team_memberships__is_active=True
        ).distinct().order_by('last_name', 'first_name')

        # Для каждого сотрудника получаем его членство (если нужно)
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

        print(f"Найдено сотрудников: {len(staff_list)}")  # для отладки

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

        # Проверяем, есть ли уже активное членство
        existing_membership = TeamMembership.objects.filter(
            driver=driver,
            team=team,
            is_active=True
        ).exists()

        if existing_membership:
            messages.warning(request, f'{driver.full_name} уже в команде')
        else:
            # Проверяем, было ли членство раньше (неактивное)
            old_membership = TeamMembership.objects.filter(
                driver=driver,
                team=team,
                is_active=False
            ).first()

            if old_membership:
                # Реактивируем старое членство
                old_membership.is_active = True
                old_membership.left_at = None
                old_membership.save()
                messages.success(request, f'{driver.full_name} снова в команде')
            else:
                # Создаем новое членство
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

        # Находим активное участие пилота в этой команде
        membership = TeamMembership.objects.filter(
            driver=driver,
            team=manager.team,
            is_active=True
        ).first()

        if membership:
            # Отмечаем дату ухода и деактивируем
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

        # Здесь логика добавления в команду
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

from django.db import IntegrityError  # добавь в начало файла, если нет

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
            # Создаём нового сотрудника
            form = TeamStaffForm(request.POST, request.FILES)
            formset = TeamStaffSocialLinkFormSet(request.POST)

            if form.is_valid() and formset.is_valid():
                staff = form.save(commit=False)

                # Обработка фото для Wagtail
                if 'photo_upload' in request.FILES:
                    from wagtail.images.models import Image
                    photo_file = request.FILES['photo_upload']

                    # Создаем изображение Wagtail
                    wagtail_image = Image(
                        title=f"{staff.last_name} {staff.first_name} - фото сотрудника",
                        file=photo_file
                    )
                    wagtail_image.save()
                    staff.photo = wagtail_image
                else:
                    staff.photo = None

                staff.save()

                # Сохраняем формсет с привязкой к сотруднику
                formset.instance = staff
                formset.save()

                # Создаём членство в этой команде
                TeamStaffMembership.objects.create(
                    staff=staff,
                    team=team,
                    is_active=True
                )
                messages.success(request, f'Сотрудник {staff.full_name} добавлен')

            else:
                # Подробный вывод ошибок
                error_msg = "Ошибка в форме: "
                if form.errors:
                    error_msg += f"Основная форма: {form.errors}"
                if formset.errors:
                    error_msg += f" Соцсети: {formset.errors}"
                messages.error(request, error_msg)

        else:
            # Добавляем существующего сотрудника
            try:
                staff = TeamStaff.objects.get(id=staff_id)

                # Проверяем, было ли членство в ЭТОЙ команде раньше (активное или неактивное)
                existing_membership = TeamStaffMembership.objects.filter(
                    staff=staff,
                    team=team
                ).first()

                if existing_membership:
                    if existing_membership.is_active:
                        # Уже активен в этой команде
                        messages.info(request, f'{staff.full_name} уже активен в вашей команде')
                    else:
                        # Реактивируем существующее членство
                        existing_membership.is_active = True
                        existing_membership.left_at = None
                        existing_membership.joined_at = timezone.now().date()  # Обновляем дату
                        existing_membership.save()
                        messages.success(request, f'{staff.full_name} снова в команде')
                else:
                    # Создаем новое членство (никогда не был в этой команде)
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
            messages.success(request, f'Сотрудник удалён из команды')
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

        # Проверяем, что сотрудник действительно в команде
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
            # Сохраняем сотрудника (с защитой от перезаписи фото)
            staff = form.save(commit=False)
            print(f"Данные до сохранения: {staff.last_name} {staff.first_name}")

            # Если новое фото не загружено, оставляем старое
            if 'photo_upload' in request.FILES:
                from wagtail.images.models import Image
                photo_file = request.FILES['photo_upload']
                wagtail_image = Image(
                    title=f"{staff.last_name} {staff.first_name} - фото сотрудника",
                    file=photo_file
                )
                wagtail_image.save()
                staff.photo = wagtail_image
            # Если нет нового фото, staff.photo остается как было (уже установлено из instance)
            staff.save()
            formset.save()  # <-- ОДИН РАЗ
            print(f"Сотрудник сохранен с ID: {staff.id}")
            print("Формсет сохранен")

            messages.success(request, f'Данные {staff.full_name} обновлены')
        else:
            # Выводим ошибки для отладки
            print("Ошибки формы:", form.errors)
            print("Ошибки формсета:", formset.errors)
            messages.error(request, f'Ошибка в форме: {form.errors}')

    # ВСЕГДА возвращаем на dashboard
    return redirect('teams:dashboard')
