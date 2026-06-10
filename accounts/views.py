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
        fail_silently=False,
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
            return render(request, 'accounts/profile_pending.html')

    except DriverClaim.DoesNotExist:
        pending = DriverClaim.objects.filter(user=request.user, status='pending').first()
        if pending:
            return render(request, 'accounts/profile_pending.html')
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


def _redirect_by_role(user):
    if hasattr(user, 'organizer_profile'):
        return redirect('organizers:dashboard')
    from teams.models import TeamManager
    if TeamManager.objects.filter(user=user).exists():
        return redirect('teams:dashboard')
    if DriverClaim.objects.filter(user=user).exists():
        return redirect('accounts:profile')
    # Нет ни одной роли — отправляем на выбор роли
    if YandexSocialAuth.objects.filter(user=user).exists():
        return redirect('accounts:yandex_choose_role')
    return redirect('accounts:profile')


def yandex_login(request):
    settings_obj = SocialAuthSettings.get()
    if not settings_obj.yandex_enabled:
        messages.error(request, 'Вход через Яндекс временно недоступен.')
        return redirect('accounts:login')
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
        return _redirect_by_role(user)
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
        return _redirect_by_role(user)
    except User.DoesNotExist:
        pass

    # Шаг 3: новый пользователь — создаём и редиректим на выбор роли
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
    YandexSocialAuth.objects.create(user=user, yandex_uid=yandex_uid, yandex_login=yandex_login_name)
    request.session['yandex_first_name'] = first_name
    request.session['yandex_last_name'] = last_name
    request.session['yandex_onboarding'] = True
    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)
    return redirect('accounts:yandex_choose_role')


@login_required
def yandex_choose_role(request):
    return render(request, 'accounts/yandex_choose_role.html')


@login_required
def yandex_pilot_onboarding(request):
    if not request.session.get('yandex_onboarding'):
        return redirect('accounts:profile')
    first_name = request.session.get('yandex_first_name', request.user.first_name)
    last_name = request.session.get('yandex_last_name', request.user.last_name)
    drivers = Driver.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name)
    if drivers.exists():
        request.session['found_drivers'] = [
            {'id': d.id, 'name': d.full_name, 'city': d.city or ''}
            for d in drivers
        ]
        request.session['user_id'] = request.user.id
        request.session['first_name'] = first_name
        request.session['last_name'] = last_name
        request.session['city'] = ''
        for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
            request.session.pop(key, None)
        return redirect('accounts:select_driver')
    DriverClaim.objects.create(
        user=request.user,
        requested_first_name=first_name,
        requested_last_name=last_name,
        status='pending',
    )
    send_admin_notification('пилотом', {
        'user_email': request.user.email,
        'first_name': first_name,
        'last_name': last_name,
        'city': '',
        'driver_name': 'новый пилот',
    })
    for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
        request.session.pop(key, None)
    messages.success(request, 'Аккаунт пилота создан! Ожидайте привязки к профилю.')
    return redirect('accounts:profile')


@login_required
def yandex_team_onboarding(request):
    if not request.session.get('yandex_onboarding'):
        return redirect('teams:dashboard')
    if request.method == 'POST':
        from teams.models import Team, TeamClaim
        from teams.views import send_team_admin_notification
        team_name = request.POST.get('team_name', '').strip()
        if not team_name:
            messages.error(request, 'Введите название команды.')
            return render(request, 'accounts/yandex_team_onboarding.html')
        teams_qs = Team.objects.filter(name__icontains=team_name)
        if teams_qs.exists():
            request.session['found_teams'] = [{'id': t.id, 'name': t.name} for t in teams_qs]
            request.session['user_id'] = request.user.id
            request.session['requested_team_name'] = team_name
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            return redirect('teams:select_team')
        from teams.models import TeamClaim as TC
        TC.objects.create(user=request.user, requested_team_name=team_name, status='pending')
        send_team_admin_notification({'user_email': request.user.email, 'team_name': team_name})
        for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
            request.session.pop(key, None)
        return redirect('accounts:yandex_claim_sent')
    return render(request, 'accounts/yandex_team_onboarding.html')


@login_required
def yandex_claim_sent(request):
    return render(request, 'accounts/yandex_claim_sent.html')


@login_required
def yandex_organizer_onboarding(request):
    if not request.session.get('yandex_onboarding'):
        return redirect('organizers:dashboard')
    if request.method == 'POST':
        from organizers.models import OrganizerProfile
        phone = request.POST.get('phone', '').strip()
        telegram = request.POST.get('telegram', '').strip()
        OrganizerProfile.objects.get_or_create(
            user=request.user,
            defaults={'phone': phone, 'telegram': telegram},
        )
        for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
            request.session.pop(key, None)
        messages.success(request, 'Профиль организатора создан!')
        return redirect('organizers:dashboard')
    return render(request, 'accounts/yandex_organizer_onboarding.html')
