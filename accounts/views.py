from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.db.models import Q
from .forms import RegistrationForm, DriverProfileForm, SocialLinkFormSet
from website.models import Driver
from .models import DriverClaim, PilotDocument, YandexSocialAuth, SocialAuthSettings
from wagtail.images.models import Image
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
import json
import secrets
import urllib.parse
import urllib.request as urllib_request


def send_admin_notification(claim_type, claim_data):
    """Отправка уведомления администратору о новой заявке"""
    subject = f'[Gripline] Новая заявка на управление {claim_type}'
    message = f"""
Поступила новая заявка:

Тип: {claim_type}
Email пользователя: {claim_data.get('user_email')}
Имя: {claim_data.get('first_name')} {claim_data.get('last_name')}
Город: {claim_data.get('city', 'не указан')}
"""
    if claim_type == 'пилотом':
        message += f"Выбранный пилот: {claim_data.get('driver_name', 'новый пилот')}\n"
    else:
        message += f"Команда: {claim_data.get('team_name')}\n"
    
    message += "\nЗайдите в админку для подтверждения: https://gripline.ru/admin/"
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        ['gripline.ru@yandex.ru'],
        fail_silently=True,
    )


def send_verification_email(user, request):
    """Отправка письма с подтверждением email"""
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verification_url = request.build_absolute_uri(
        f'/accounts/verify-email/{uid}/{token}/'
    )
    
    subject = 'Подтверждение регистрации на Gripline'
    html_message = render_to_string('emails/verification_email.html', {
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


def register(request):
    """Регистрация нового пользователя — мгновенная, без подтверждения email"""
    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        email = request.POST.get('email')
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Пользователь с таким email уже зарегистрирован.')
            return render(request, 'accounts/register.html', {'form': form})

        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = True
            user.save()

            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            city = form.cleaned_data.get('city', '')

            login(request, user)

            drivers = Driver.objects.filter(
                first_name__iexact=first_name,
                last_name__iexact=last_name,
            )

            if drivers.exists():
                request.session['found_drivers'] = [
                    {'id': d.id, 'name': d.full_name, 'city': d.city or ''}
                    for d in drivers
                ]
                request.session['user_id'] = user.id
                request.session['first_name'] = first_name
                request.session['last_name'] = last_name
                request.session['city'] = city
                messages.success(request, 'Аккаунт создан! Выберите своего пилота.')
                return redirect('accounts:select_driver')
            else:
                DriverClaim.objects.create(
                    user=user,
                    requested_first_name=first_name,
                    requested_last_name=last_name,
                    requested_city=city,
                    status='pending',
                )
                send_admin_notification('пилотом', {
                    'user_email': user.email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'city': city,
                    'driver_name': 'новый пилот',
                })
                messages.success(request, 'Аккаунт создан! Ваша заявка отправлена администратору.')
                return redirect('accounts:profile')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


def verification_sent(request):
    """Страница «Письмо отправлено»"""
    return render(request, 'accounts/verification_sent.html')


def verify_email(request, uidb64, token):
    """Подтверждение email по ссылке из письма"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    
    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        
        # Восстанавливаем данные из сессии (если они есть)
        pending_user_id = request.session.get('pending_user_id')
        if pending_user_id == user.id:
            first_name = request.session.get('pending_first_name')
            last_name = request.session.get('pending_last_name')
            city = request.session.get('pending_city', '')
            
            # Ищем похожих пилотов
            drivers = Driver.objects.filter(
                first_name__iexact=first_name,
                last_name__iexact=last_name
            )
            
            if drivers.exists():
                request.session['found_drivers'] = [
                    {'id': d.id, 'name': d.full_name, 'city': d.city or ''}
                    for d in drivers
                ]
                request.session['user_id'] = user.id
                request.session['first_name'] = first_name
                request.session['last_name'] = last_name
                request.session['city'] = city
                
                # Очищаем временные данные
                for key in ['pending_user_id', 'pending_first_name', 'pending_last_name', 'pending_city']:
                    if key in request.session:
                        del request.session[key]
                
                messages.success(request, 'Email подтверждён! Теперь выберите пилота.')
                return redirect('accounts:select_driver')
            else:
                # Создаём заявку без привязки
                claim = DriverClaim.objects.create(
                    user=user,
                    requested_first_name=first_name,
                    requested_last_name=last_name,
                    requested_city=city,
                    status='pending'
                )
                
                # Отправляем уведомление администратору
                send_admin_notification('пилотом', {
                    'user_email': user.email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'city': city,
                    'driver_name': 'новый пилот',
                })
                
                messages.success(request, 'Email подтверждён! Ваша заявка отправлена администратору.')
                return redirect('accounts:login')
        else:
            messages.success(request, 'Email подтверждён! Теперь вы можете войти.')
            return redirect('accounts:login')
    else:
        return render(request, 'accounts/verification_failed.html')


def resend_verification(request):
    """Повторная отправка письма с подтверждением"""
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email, is_active=False)
            send_verification_email(user, request)
            messages.success(request, 'Письмо отправлено повторно. Проверьте почту.')
            return redirect('accounts:verification_sent')
        except User.DoesNotExist:
            messages.error(request, 'Пользователь с таким email не найден или уже активирован.')
    return render(request, 'accounts/verification_resend.html')


def select_driver(request):
    """Страница выбора пилота из найденных"""
    found_drivers = request.session.get('found_drivers', [])
    user_id = request.session.get('user_id')
    
    # Если нет данных в сессии — пробуем взять из pending
    if not found_drivers or not user_id:
        pending_user_id = request.session.get('pending_user_id')
        if pending_user_id:
            user = User.objects.get(id=pending_user_id)
            first_name = request.session.get('pending_first_name')
            last_name = request.session.get('pending_last_name')
            city = request.session.get('pending_city', '')
            
            drivers = Driver.objects.filter(
                first_name__iexact=first_name,
                last_name__iexact=last_name
            )
            
            if drivers.exists():
                request.session['found_drivers'] = [
                    {'id': d.id, 'name': d.full_name, 'city': d.city or ''}
                    for d in drivers
                ]
                request.session['user_id'] = user.id
                request.session['first_name'] = first_name
                request.session['last_name'] = last_name
                request.session['city'] = city
                found_drivers = request.session['found_drivers']
                user_id = request.session['user_id']
            else:
                return redirect('accounts:register')
        else:
            return redirect('accounts:register')

    if request.method == 'POST':
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=user_id)

        selected_id = request.POST.get('driver_id')

        if selected_id == 'none':
            claim = DriverClaim.objects.create(
                user=user,
                requested_first_name=request.session['first_name'],
                requested_last_name=request.session['last_name'],
                requested_city=request.session.get('city', ''),
                status='pending'
            )
            
            # Отправляем уведомление администратору
            send_admin_notification('пилотом', {
                'user_email': user.email,
                'first_name': request.session.get('first_name'),
                'last_name': request.session.get('last_name'),
                'city': request.session.get('city', ''),
                'driver_name': 'новый пилот',
            })
            
            messages.success(request, 'Ваша заявка отправлена администратору.')
        elif selected_id:
            driver = Driver.objects.get(id=selected_id)
            claim = DriverClaim.objects.create(
                user=user,
                driver=driver,
                requested_first_name=request.session['first_name'],
                requested_last_name=request.session['last_name'],
                requested_city=request.session.get('city', ''),
                status='pending'
            )
            
            # Отправляем уведомление администратору
            send_admin_notification('пилотом', {
                'user_email': user.email,
                'first_name': request.session.get('first_name'),
                'last_name': request.session.get('last_name'),
                'city': request.session.get('city', ''),
                'driver_name': driver.full_name,
            })
            
            messages.success(request, f'Заявка на привязку к {driver.full_name} отправлена администратору.')

        # Очищаем сессию
        for key in ['found_drivers', 'user_id', 'first_name', 'last_name', 'city', 'pending_user_id', 'pending_first_name', 'pending_last_name', 'pending_city']:
            if key in request.session:
                del request.session[key]

        return redirect('accounts:login')

    return render(request, 'accounts/select_driver.html', {
        'drivers': found_drivers,
        'first_name': request.session.get('first_name'),
        'last_name': request.session.get('last_name'),
    })


def login_view(request):
    """Вход пользователя"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, username=email, password=password)
        if user is None:
            from django.contrib.auth.models import User as AuthUser
            for candidate in AuthUser.objects.filter(email__iexact=email):
                user = authenticate(request, username=candidate.username, password=password)
                if user is not None:
                    break

        if user is not None:
            if user.is_active:
                login(request, user)
                if hasattr(user, 'organizer_profile'):
                    return redirect('organizers:dashboard')
                from teams.models import TeamManager
                if TeamManager.objects.filter(user=user).exists():
                    return redirect('teams:dashboard')
                return redirect('accounts:profile')
            else:
                messages.error(request, 'Аккаунт не активирован. Проверьте почту или запросите новое письмо.')
                return redirect('accounts:resend_verification')
        else:
            messages.error(request, 'Неверный email или пароль')

    return render(request, 'accounts/login.html')


@login_required
def profile(request):
    """Личный кабинет пилота"""
    try:
        claim = DriverClaim.objects.filter(
            user=request.user,
            status='approved'
        ).latest('created_at')

        if claim.driver:
            driver = claim.driver

            if request.method == 'POST':
                form = DriverProfileForm(request.POST, request.FILES, instance=driver)
                formset = SocialLinkFormSet(request.POST, instance=driver)

                if form.is_valid() and formset.is_valid():
                    # Сохраняем основную информацию
                    driver = form.save(commit=False)

                    # Обрабатываем фото отдельно
                    if 'photo_file' in request.FILES:
                        photo_file = request.FILES['photo_file']
                        # Создаем объект Image Wagtail
                        wagtail_image = Image.objects.create(
                            title=f"{driver.full_name} - фото профиля",
                            file=photo_file
                        )
                        driver.photo = wagtail_image

                    driver.save()
                    formset.save()

                    messages.success(request, 'Профиль обновлён')
                    return redirect('accounts:profile')
            else:
                form = DriverProfileForm(instance=driver)
                formset = SocialLinkFormSet(instance=driver)

            profile = getattr(request.user, 'profile', None)
            pilot_docs = profile.documents.all() if profile else []
            return render(request, 'accounts/profile.html', {
                'driver': driver,
                'claim': claim,
                'form': form,
                'formset': formset,
                'pilot_docs': pilot_docs,
            })
        else:
            messages.warning(request, 'Ваша заявка ещё не подтверждена администратором.')
            return render(request, 'accounts/profile_pending.html', {'claim': claim})

    except DriverClaim.DoesNotExist:
        pending = DriverClaim.objects.filter(user=request.user, status='pending').first()
        if pending:
            return render(request, 'accounts/profile_pending.html', {'claim': pending})
        if YandexSocialAuth.objects.filter(user=request.user).exists():
            return _redirect_by_role(request.user, request)
        messages.warning(request, 'У вас нет активной заявки. Зарегистрируйтесь как пилот.')
        return redirect('accounts:register')


def logout_view(request):
    """Выход пользователя"""
    logout(request)
    return redirect('accounts:login')


@staff_member_required
@csrf_exempt
def process_claim_api(request):
    """API для подтверждения/отклонения заявок"""
    if request.method == 'POST':
        data = json.loads(request.body)
        claim_id = data.get('claim_id')
        action = data.get('action')

        try:
            claim = DriverClaim.objects.get(id=claim_id)

            if action == 'approve':
                driver_id = data.get('driver_id')
                from website.models import Driver
                driver = Driver.objects.get(id=driver_id)

                # Привязываем пилота к пользователю
                claim.user.profile.driver = driver
                claim.user.profile.save()

                claim.driver = driver
                claim.status = 'approved'
                claim.reviewed_by = request.user
                claim.reviewed_at = timezone.now()
                claim.save()

                return JsonResponse({'success': True})

            elif action == 'reject':
                claim.status = 'rejected'
                claim.admin_comment = data.get('comment', '')
                claim.reviewed_by = request.user
                claim.reviewed_at = timezone.now()
                claim.save()

                return JsonResponse({'success': True})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Method not allowed'})
@login_required
def favorite_ads(request):
    """Избранные объявления пользователя"""
    from website.models import AdFavorite
    favorites = AdFavorite.objects.filter(user=request.user).select_related('ad')
    return render(request, 'accounts/favorite_ads.html', {'favorites': favorites})

from website.models import Ad, AdResponse, AdFavorite

@login_required
def my_responses(request):
    """Мои отклики (как автор откликов)"""
    responses = AdResponse.objects.filter(author=request.user).select_related('ad')
    return render(request, 'accounts/my_responses.html', {'responses': responses})


@login_required
def ad_responses(request, ad_id):
    """Отклики на моё объявление"""
    ad = get_object_or_404(Ad, id=ad_id, author=request.user)
    responses = ad.responses.all()
    return render(request, 'accounts/ad_responses.html', {'ad': ad, 'responses': responses})


@login_required
def response_action(request, response_id, action):
    """Принять/отклонить отклик"""
    response = get_object_or_404(AdResponse, id=response_id, ad__author=request.user)
    if action == 'accept':
        response.status = 'accepted'
        messages.success(request, 'Отклик принят!')
    elif action == 'reject':
        response.status = 'rejected'
        messages.success(request, 'Отклик отклонён.')
    response.save()
    return redirect('ad_responses', ad_id=response.ad.id)


@login_required
def favorite_ads(request):
    """Избранные объявления пользователя"""
    favorites = AdFavorite.objects.filter(user=request.user).select_related('ad')
    return render(request, 'accounts/favorite_ads.html', {'favorites': favorites})


@login_required
def upload_pilot_document(request):
    """AJAX: загрузка документа в личное хранилище пилота"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    profile = getattr(request.user, 'profile', None)
    if not profile:
        return JsonResponse({'error': 'Профиль не найден'}, status=404)

    name = request.POST.get('name', '').strip()
    file = request.FILES.get('file')
    expiry_date = request.POST.get('expiry_date') or None

    if not name or not file:
        return JsonResponse({'error': 'Название и файл обязательны'}, status=400)

    doc = PilotDocument.objects.create(
        profile=profile,
        name=name,
        file=file,
        expiry_date=expiry_date,
    )
    return JsonResponse({
        'success': True,
        'id': doc.id,
        'name': doc.name,
        'file_url': doc.file.url,
        'expiry_date': doc.expiry_date.strftime('%d.%m.%Y') if doc.expiry_date else '',
        'is_expired': doc.is_expired,
        'expires_soon': doc.expires_soon,
    })


@login_required
def delete_pilot_document(request, doc_id):
    """AJAX: удаление документа из личного хранилища"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    profile = getattr(request.user, 'profile', None)
    doc = get_object_or_404(PilotDocument, pk=doc_id, profile=profile)
    doc.file.delete(save=False)
    doc.delete()
    return JsonResponse({'success': True})


# ─── Яндекс OAuth ────────────────────────────────────────────────────────────

_YANDEX_CALLBACK_URI = 'https://gripline.ru/accounts/yandex/callback/'


def _redirect_by_role(user, request=None):
    from teams.models import TeamManager, TeamClaim
    from organizers.models import OrganizerProfile as OrgProfile

    org = getattr(user, 'organizer_profile', None)
    has_organizer_active = org is not None and org.status == 'active'
    has_organizer_pending = org is not None and org.status == 'pending'
    has_team = TeamManager.objects.filter(user=user, is_active=True).exists()
    has_driver_approved = DriverClaim.objects.filter(user=user, status='approved').exists()

    # Добавление второй роли: пользователь уже имеет роль, но хочет добавить новую
    if request is not None:
        yandex_role = request.session.get('yandex_role')
        has_pending_driver = DriverClaim.objects.filter(user=user, status='pending').exists()
        has_pending_team = TeamClaim.objects.filter(user=user, status='pending').exists()
        if yandex_role == 'pilot' and not has_driver_approved and not has_pending_driver:
            request.session['yandex_onboarding'] = True
            if not request.session.get('yandex_first_name'):
                request.session['yandex_first_name'] = user.first_name
                request.session['yandex_last_name'] = user.last_name
            return redirect('accounts:yandex_pilot_onboarding')
        if yandex_role == 'team' and not has_team and not has_pending_team:
            request.session['yandex_onboarding'] = True
            if not request.session.get('yandex_first_name'):
                request.session['yandex_first_name'] = user.first_name
                request.session['yandex_last_name'] = user.last_name
            return redirect('accounts:yandex_team_onboarding')

    # Мультироль: одобренный пилот + активный менеджер команды
    if has_driver_approved and has_team:
        if request is not None:
            active_role = request.session.get('active_role')
            if active_role == 'team':
                return redirect('teams:dashboard')
            if active_role == 'pilot':
                return redirect('accounts:profile')
        return redirect('accounts:yandex_role_switch')

    if has_organizer_active:
        return redirect('organizers:dashboard')
    if has_team:
        return redirect('teams:dashboard')
    if has_driver_approved:
        return redirect('accounts:profile')

    # Pending-заявки
    if has_organizer_pending:
        return redirect('organizers:pending')
    if DriverClaim.objects.filter(user=user, status='pending').exists():
        return redirect('accounts:profile')
    if TeamClaim.objects.filter(user=user, status='pending').exists():
        return redirect('teams:dashboard')

    # Нет ни одной роли — онбординг по роли из сессии
    if request is not None:
        role = request.session.get('yandex_role', 'pilot')
        # Разрешаем повторный онбординг (например после удаления заявки в админке)
        request.session['yandex_onboarding'] = True
        if not request.session.get('yandex_first_name'):
            request.session['yandex_first_name'] = user.first_name
            request.session['yandex_last_name'] = user.last_name
        url_map = {
            'pilot': 'accounts:yandex_pilot_onboarding',
            'team': 'accounts:yandex_team_onboarding',
            'organizer': 'accounts:yandex_organizer_onboarding',
        }
        return redirect(url_map.get(role, 'accounts:yandex_pilot_onboarding'))
    return redirect('accounts:profile')


def yandex_login(request):
    settings_obj = SocialAuthSettings.get()
    if not settings_obj.yandex_enabled:
        messages.error(request, 'Вход через Яндекс временно недоступен.')
        return redirect('accounts:login')
    role = request.GET.get('role', 'pilot')
    if role not in ('pilot', 'team', 'organizer'):
        role = 'pilot'
    request.session['yandex_role'] = role
    state = secrets.token_urlsafe(16)
    request.session['yandex_oauth_state'] = state
    params = {
        'response_type': 'code',
        'client_id': settings_obj.yandex_client_id,
        'redirect_uri': _YANDEX_CALLBACK_URI,
        'state': state,
        'scope': 'login:email login:info',
        'force_confirm': 'no',
    }
    return redirect('https://oauth.yandex.ru/authorize?' + urllib.parse.urlencode(params))


def yandex_callback(request):
    state = request.GET.get('state', '')
    if state != request.session.pop('yandex_oauth_state', None):
        messages.error(request, 'Ошибка безопасности. Попробуйте снова.')
        return redirect('accounts:login')

    code = request.GET.get('code')
    if request.GET.get('error') or not code:
        messages.error(request, 'Вход через Яндекс отменён.')
        return redirect('accounts:login')

    settings_obj = SocialAuthSettings.get()

    try:
        token_data = urllib.parse.urlencode({
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': settings_obj.yandex_client_id,
            'client_secret': settings_obj.yandex_client_secret,
        }).encode()
        req = urllib_request.Request('https://oauth.yandex.ru/token', data=token_data, method='POST')
        with urllib_request.urlopen(req, timeout=10) as resp:
            token_response = json.loads(resp.read())
        access_token = token_response.get('access_token')
        if not access_token:
            raise ValueError('no access_token')
    except Exception:
        messages.error(request, 'Ошибка получения токена от Яндекса.')
        return redirect('accounts:login')

    try:
        info_req = urllib_request.Request(
            'https://login.yandex.ru/info?format=json',
            headers={'Authorization': f'OAuth {access_token}'},
        )
        with urllib_request.urlopen(info_req, timeout=10) as resp:
            ya = json.loads(resp.read())
    except Exception:
        messages.error(request, 'Ошибка получения данных от Яндекса.')
        return redirect('accounts:login')

    yandex_uid = str(ya.get('id', ''))
    yandex_login_name = ya.get('login', '')
    emails = ya.get('emails', [])
    yandex_email = ya.get('default_email') or (emails[0] if emails else '')
    first_name = ya.get('first_name', '')
    last_name = ya.get('last_name', '')

    if not yandex_uid or not yandex_email:
        messages.error(request, 'Не удалось получить данные аккаунта от Яндекса.')
        return redirect('accounts:login')

    # Шаг 1: ищем по yandex_uid
    try:
        social_auth = YandexSocialAuth.objects.get(yandex_uid=yandex_uid)
        user = social_auth.user
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)
        return _redirect_by_role(user, request)
    except YandexSocialAuth.DoesNotExist:
        pass

    # Шаг 2: ищем существующего User по email
    try:
        user = User.objects.get(email__iexact=yandex_email)
        YandexSocialAuth.objects.create(user=user, yandex_uid=yandex_uid, yandex_login=yandex_login_name)
        if not user.is_active:
            user.is_active = True
            user.save()
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)
        return _redirect_by_role(user, request)
    except User.DoesNotExist:
        pass

    # Шаг 3: новый пользователь — создаём и направляем на онбординг по роли
    username = yandex_email
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f'{yandex_email}_{counter}'
        counter += 1
    user = User.objects.create_user(
        username=username,
        email=yandex_email,
        first_name=first_name,
        last_name=last_name,
        password=None,
    )
    user.set_unusable_password()
    user.save()
    YandexSocialAuth.objects.create(user=user, yandex_uid=yandex_uid, yandex_login=yandex_login_name)
    request.session['yandex_first_name'] = first_name
    request.session['yandex_last_name'] = last_name
    request.session['yandex_onboarding'] = True
    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)
    return _redirect_by_role(user, request)


def yandex_search_drivers(request):
    """AJAX: поиск Driver по имени/фамилии"""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    from django.db.models import Q as DQ
    drivers = Driver.objects.filter(
        DQ(first_name__icontains=q) | DQ(last_name__icontains=q)
    ).values('id', 'first_name', 'last_name', 'city')[:20]
    results = [
        {
            'id': d['id'],
            'name': f"{d['first_name']} {d['last_name']}",
            'city': d['city'] or '',
        }
        for d in drivers
    ]
    return JsonResponse({'results': results})


def yandex_search_teams(request):
    """AJAX: поиск Team по названию"""
    from website.models import Team as WebTeam
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    teams = WebTeam.objects.filter(name__icontains=q).values('id', 'name')[:20]
    return JsonResponse({'results': list(teams)})


@login_required
def yandex_pilot_onboarding(request):
    has_claim = DriverClaim.objects.filter(user=request.user).exists()
    if not request.session.get('yandex_onboarding') and has_claim:
        return redirect('accounts:profile')

    first_name = request.session.get('yandex_first_name', request.user.first_name)
    last_name = request.session.get('yandex_last_name', request.user.last_name)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'select':
            driver_id = request.POST.get('driver_id')
            try:
                driver = Driver.objects.get(pk=driver_id)
            except Driver.DoesNotExist:
                messages.error(request, 'Пилот не найден.')
                return render(request, 'accounts/yandex_pilot_onboarding.html', {
                    'first_name': first_name, 'last_name': last_name,
                })
            if DriverClaim.objects.filter(driver=driver, status='approved').exists():
                messages.error(request, 'Этот профиль уже привязан к другому аккаунту. Обратитесь к администратору.')
                return render(request, 'accounts/yandex_pilot_onboarding.html', {
                    'first_name': first_name, 'last_name': last_name,
                })
            DriverClaim.objects.create(
                user=request.user,
                driver=driver,
                requested_first_name=driver.first_name,
                requested_last_name=driver.last_name,
                status='pending',
            )
            send_admin_notification('пилотом', {
                'user_email': request.user.email,
                'first_name': driver.first_name,
                'last_name': driver.last_name,
                'city': driver.city or '',
                'driver_name': driver.first_name + ' ' + driver.last_name,
            })
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            request.session['active_role'] = 'pilot'
            messages.success(request, 'Заявка на привязку профиля отправлена. Ожидайте подтверждения.')
            return redirect('accounts:profile')

        elif action == 'new':
            fn = request.POST.get('first_name', first_name).strip()
            ln = request.POST.get('last_name', last_name).strip()
            birth_year = request.POST.get('birth_year', '').strip()
            if not fn or not ln:
                messages.error(request, 'Введите имя и фамилию.')
                return render(request, 'accounts/yandex_pilot_onboarding.html', {
                    'first_name': first_name, 'last_name': last_name, 'show_new_form': True,
                })
            from django.utils.text import slugify as dslugify
            import uuid
            base_slug = dslugify(f"{fn}-{ln}", allow_unicode=True) or str(uuid.uuid4())[:8]
            slug = base_slug
            counter = 1
            while Driver.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            driver = Driver(first_name=fn, last_name=ln, slug=slug)
            driver.save()
            DriverClaim.objects.create(
                user=request.user,
                driver=driver,
                requested_first_name=fn,
                requested_last_name=ln,
                status='pending',
            )
            send_admin_notification('пилотом', {
                'user_email': request.user.email,
                'first_name': fn,
                'last_name': ln,
                'city': '',
                'driver_name': f'{fn} {ln} (новый)',
            })
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            request.session['active_role'] = 'pilot'
            messages.success(request, 'Профиль создан, появится в рейтингах после первого этапа.')
            return redirect('accounts:profile')

    return render(request, 'accounts/yandex_pilot_onboarding.html', {
        'first_name': first_name,
        'last_name': last_name,
    })


@login_required
def yandex_team_onboarding(request):
    from teams.models import TeamClaim as _TC
    has_claim = _TC.objects.filter(user=request.user).exists()
    if not request.session.get('yandex_onboarding') and has_claim:
        return redirect('teams:dashboard')

    if request.method == 'POST':
        from website.models import Team as WebTeam
        from teams.models import TeamClaim as TC, TeamManager as TM
        from teams.views import send_team_admin_notification
        action = request.POST.get('action')

        if action == 'select':
            team_id = request.POST.get('team_id')
            try:
                team = WebTeam.objects.get(pk=team_id)
            except WebTeam.DoesNotExist:
                messages.error(request, 'Команда не найдена.')
                return render(request, 'accounts/yandex_team_onboarding.html')
            if TM.objects.filter(team=team, is_active=True).exists():
                messages.error(request, 'У этой команды уже есть менеджер. Обратитесь к администратору.')
                return render(request, 'accounts/yandex_team_onboarding.html')
            TC.objects.create(
                user=request.user,
                team=team,
                requested_team_name=team.name,
                status='pending',
            )
            send_team_admin_notification({'user_email': request.user.email, 'team_name': team.name})
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            request.session['active_role'] = 'team'
            messages.success(request, 'Заявка отправлена, ожидайте подтверждения.')
            return redirect('teams:dashboard')

        elif action == 'new':
            team_name = request.POST.get('team_name', '').strip()
            city = request.POST.get('city', '').strip()
            if not team_name:
                messages.error(request, 'Введите название команды.')
                return render(request, 'accounts/yandex_team_onboarding.html', {'show_new_form': True})
            team = WebTeam(name=team_name)
            team.save()
            TM.objects.create(user=request.user, team=team, role='manager', is_active=True)
            TC.objects.create(
                user=request.user,
                team=team,
                requested_team_name=team_name,
                status='pending',
            )
            send_team_admin_notification({'user_email': request.user.email, 'team_name': team_name})
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            request.session['active_role'] = 'team'
            messages.success(request, 'Команда создана, появится на сайте после проверки.')
            return redirect('teams:dashboard')

    return render(request, 'accounts/yandex_team_onboarding.html')


@login_required
def yandex_organizer_onboarding(request):
    from organizers.models import OrganizerProfile as _OP
    has_profile = _OP.objects.filter(user=request.user).exists()
    if not request.session.get('yandex_onboarding') and has_profile:
        return redirect('organizers:dashboard')
    if request.method == 'POST':
        from organizers.models import OrganizerProfile
        phone = request.POST.get('phone', '').strip()
        telegram = request.POST.get('telegram', '').strip()
        OrganizerProfile.objects.get_or_create(
            user=request.user,
            defaults={'phone': phone, 'telegram': telegram, 'status': 'pending'},
        )
        for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
            request.session.pop(key, None)
        return redirect('organizers:pending')
    return render(request, 'accounts/yandex_organizer_onboarding.html')


@login_required
def yandex_role_switch(request):
    """Страница выбора роли при мультироли (пилот + менеджер команды)"""
    if request.method == 'POST':
        role = request.POST.get('role')
        if role in ('pilot', 'team'):
            request.session['active_role'] = role
        if role == 'team':
            return redirect('teams:dashboard')
        return redirect('accounts:profile')
    return render(request, 'accounts/yandex_role_switch.html')
