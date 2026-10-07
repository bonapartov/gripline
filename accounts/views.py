from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode, url_has_allowed_host_and_scheme
from django.utils.encoding import force_bytes, force_str
from django.conf import settings
from django.db.models import Q
from .forms import RegistrationForm, DriverProfileForm, SocialLinkFormSet
from website.models import Driver
from website.mail import send_templated_mail
from website.services.balance_limits import ratelimit_post
from .verification import (NEUTRAL_RESEND_MESSAGE, confirm_email, is_email_verified, mark_unverified,
                           handle_existing_email, resend_verification_emails, user_from_token)
from .models import DriverClaim, PilotDocument, SocialAuthSettings
from wagtail.images.models import Image
from django.db import transaction
from django.utils import timezone
from django.http import JsonResponse, FileResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
import json

import logging
logger = logging.getLogger(__name__)


def send_verification_email(user, request):
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verification_url = request.build_absolute_uri(f'/accounts/verify-email/{uid}/{token}/')
    send_templated_mail('verification_email', 'Подтверждение регистрации на Gripline', [user.email], {
        'user': user,
        'verification_url': verification_url,
        'expiry_minutes': 30,
    })


@ratelimit_post('register_pilot', limit=20, window_seconds=3600)
def register(request):
    """Регистрация пилота по email: аккаунт создаётся сразу, но войти и подать заявку
    можно только после перехода по ссылке из письма (см. verify_email)."""
    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            if handle_existing_email(form.cleaned_data['email'], request):
                return redirect('accounts:verification_sent')   # тот же ответ, что и для нового адреса
            user = form.save(commit=False)
            user.is_active = True
            user.save()
            mark_unverified(user, city=form.cleaned_data.get('city', ''))

            try:
                send_verification_email(user, request)
            except Exception:
                logger.exception('pilot register: письмо подтверждения не отправлено')
                user.delete()
                messages.error(request, 'Не удалось отправить письмо. Попробуйте позже.')
                return render(request, 'accounts/register.html', {'form': form})
            return redirect('accounts:verification_sent')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


def verification_sent(request):
    """Страница «Письмо отправлено»"""
    return render(request, 'accounts/verification_sent.html')


def _pilot_candidates(user):
    return Driver.objects.filter(first_name__iexact=user.first_name, last_name__iexact=user.last_name)


def verify_email(request, uidb64, token):
    """Ссылка из письма: подтверждает email и продолжает регистрацию пилота — заявка (и уведомление
    админу) появляется только теперь. Данные берутся из БД, а не из сессии: ссылку можно открыть
    в другом браузере. Заблокированный аккаунт ссылкой не оживляется."""
    user = user_from_token(uidb64, token)
    if user is None:
        return render(request, 'accounts/verification_failed.html')

    first_time = confirm_email(user)
    profile = user.profile

    if DriverClaim.objects.filter(user=user).exists() or not (user.first_name and user.last_name):
        messages.success(request, 'Email подтверждён! Теперь вы можете войти.')
        return redirect('accounts:login')

    candidates = _pilot_candidates(user)
    if candidates.exists():
        if first_time:
            from website.claim_notify import notify_admins_registration_without_claim
            transaction.on_commit(lambda: notify_admins_registration_without_claim(
                user, user.first_name, user.last_name, profile.city, candidates.count()))
        messages.success(request, 'Email подтверждён! Теперь выберите своего пилота.')
        target = reverse('accounts:select_driver')
        if request.user.is_authenticated and request.user.pk == user.pk:
            return redirect(target)
        return redirect(f"{reverse('accounts:login')}?next={target}")

    DriverClaim.objects.create(
        user=user, requested_first_name=user.first_name, requested_last_name=user.last_name,
        requested_city=profile.city, status='pending',
    )
    messages.success(request, 'Email подтверждён! Заявка отправлена администратору.')
    return redirect('accounts:login')


@ratelimit_post('resend_verification', limit=10, window_seconds=3600)
def resend_verification(request):
    """Повторная отправка письма с подтверждением (ответ одинаковый для любого адреса)."""
    if request.method == 'POST':
        resend_verification_emails(request.POST.get('email'), request)
        messages.success(request, NEUTRAL_RESEND_MESSAGE)
        return redirect('accounts:verification_sent')
    return render(request, 'accounts/verification_resend.html')


@login_required
def select_driver(request):
    """Выбор своего пилота среди однофамильцев. Список считается по БД для request.user —
    ничего из сессии не доверяем, выбрать можно только пилота из этого списка."""
    user = request.user
    if not is_email_verified(user):
        messages.error(request, 'Сначала подтвердите email — письмо со ссылкой отправлено при регистрации.')
        return redirect('accounts:resend_verification')
    if DriverClaim.objects.filter(user=user).exists():
        return redirect('accounts:profile')

    found = _pilot_candidates(user)
    if not found.exists():
        return redirect('accounts:profile')
    city = user.profile.city

    if request.method == 'POST':
        selected_id = request.POST.get('driver_id')
        allowed = {str(d.id): d for d in found}

        if selected_id != 'none' and selected_id not in allowed:
            messages.error(request, 'Выберите пилота из списка.')
            return redirect('accounts:select_driver')

        driver = None if selected_id == 'none' else allowed[selected_id]
        DriverClaim.objects.create(
            user=user, driver=driver,
            requested_first_name=user.first_name, requested_last_name=user.last_name,
            requested_city=city, status='pending',
        )
        if driver:
            messages.success(request, f'Заявка на привязку к {driver.full_name} отправлена администратору.')
        else:
            messages.success(request, 'Ваша заявка отправлена администратору.')
        return redirect('accounts:profile')

    return render(request, 'accounts/select_driver.html', {
        'drivers': [{'id': d.id, 'name': d.full_name, 'city': d.city or ''} for d in found],
        'first_name': user.first_name,
        'last_name': user.last_name,
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
            if not is_email_verified(user):
                messages.error(request, 'Подтвердите email: мы отправляли письмо со ссылкой. Можно запросить новое.')
                return redirect('accounts:resend_verification')
            if user.is_active:
                login(request, user)
                next_url = request.GET.get('next') or request.POST.get('next')
                if next_url and url_has_allowed_host_and_scheme(
                        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
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
    # Блок 3 (/balance/) — возврат после входа через Яндекс, если пользователь
    # пришёл со страницы калькулятора (см. accounts/pipeline.py::setup_onboarding).
    # Проверяется здесь, а не только в _redirect_by_role — у пилота с уже
    # одобренной заявкой (самый частый повторный вход) этот код вообще не
    # добирается до _redirect_by_role, он рендерит профиль напрямую ниже.
    # Попап всегда снимается из сессии (одноразовый), но редирект срабатывает
    # только вне свежего онбординга — у нового юзера ещё нет Driver/TeamManager,
    # /balance/ ему рано (см. план Блока 3, решение 4).
    balance_next = request.session.pop('yandex_balance_next', None)
    if balance_next and not request.session.get('yandex_onboarding'):
        return redirect(balance_next)

    try:
        claim = DriverClaim.objects.filter(
            user=request.user,
            status='approved'
        ).latest('created_at')

        if claim.driver:
            driver = claim.driver

            profile = getattr(request.user, 'profile', None)

            if request.method == 'POST':
                form = DriverProfileForm(request.POST, request.FILES, instance=driver, profile=profile)
                formset = SocialLinkFormSet(request.POST, instance=driver)

                if form.is_valid() and formset.is_valid():
                    driver = form.save(commit=False)

                    if 'photo_file' in request.FILES:
                        photo_file = request.FILES['photo_file']
                        wagtail_image = Image.objects.create(
                            title=f"{driver.full_name} - фото профиля",
                            file=photo_file
                        )
                        driver.photo = wagtail_image

                    driver.save()
                    formset.save()

                    # Сохраняем поля UserProfile
                    if profile:
                        if driver.city is not None:
                            profile.city = driver.city
                        # Отчество — только если ещё не было заполнено
                        new_middle = form.cleaned_data.get('middle_name', '').strip()
                        if new_middle and not profile.middle_name:
                            profile.middle_name = new_middle
                        # Дата рождения и галочка публикации
                        profile.birth_date = form.cleaned_data.get('birth_date')
                        profile.birth_date_public = form.cleaned_data.get('birth_date_public', False)
                        profile.save()

                    messages.success(request, 'Профиль обновлён')
                    return redirect('accounts:profile')
            else:
                form = DriverProfileForm(instance=driver, profile=profile)
                formset = SocialLinkFormSet(instance=driver)

            pilot_docs = profile.documents.all() if profile else []
            from teams.models import TeamInvitation
            from organizers.models import Stage as OrgStage
            from applications.models import Application
            pending_invitations = TeamInvitation.objects.filter(
                driver=driver, status='pending'
            ).select_related('team', 'race_class')
            from django.utils import timezone
            has_registrable_stages = OrgStage.objects.filter(
                is_published=True,
                championship__is_published=True,
                wagtail_page__isnull=False,
                end_date__gte=timezone.now(),
            ).exists()
            my_applications = Application.objects.filter(
                submitted_by=request.user
            ).select_related('stage', 'stage__championship', 'race_class').order_by('-created_at')[:10]
            return render(request, 'accounts/profile.html', {
                'driver': driver,
                'claim': claim,
                'form': form,
                'formset': formset,
                'pilot_docs': pilot_docs,
                'pending_invitations': pending_invitations,
                'has_registrable_stages': has_registrable_stages,
                'my_applications': my_applications,
            })
        else:
            messages.warning(request, 'Ваша заявка ещё не подтверждена администратором.')
            return render(request, 'accounts/profile_pending.html', {'claim': claim})

    except DriverClaim.DoesNotExist:
        pending = DriverClaim.objects.filter(user=request.user, status='pending').first()
        if pending:
            return render(request, 'accounts/profile_pending.html', {'claim': pending})
        # OAuth users (social_django) → onboarding
        has_social = request.user.social_auth.exists() if hasattr(request.user, 'social_auth') else False
        if has_social:
            return _redirect_by_role(request.user, request)
        messages.warning(request, 'У вас нет активной заявки. Зарегистрируйтесь как пилот.')
        return redirect('accounts:register')


def logout_view(request):
    """Выход пользователя"""
    logout(request)
    return redirect('choose_role')


@staff_member_required
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
    doc_number = request.POST.get('doc_number', '').strip()
    file = request.FILES.get('file')
    expiry_date_str = request.POST.get('expiry_date') or None

    expiry_date = None
    if expiry_date_str:
        from datetime import datetime as dt
        try:
            expiry_date = dt.strptime(expiry_date_str, '%Y-%m-%d').date()
        except ValueError:
            expiry_date = None

    if not name or not file:
        return JsonResponse({'error': 'Название и файл обязательны'}, status=400)

    try:
        doc = PilotDocument.objects.create(
            profile=profile,
            name=name,
            doc_number=doc_number,
            file=file,
            expiry_date=expiry_date,
        )
        return JsonResponse({
            'success': True,
            'id': doc.id,
            'name': doc.name,
            'doc_number': doc.doc_number,
            'file_url': reverse('accounts:serve_pilot_document', args=[doc.id]),
            'expiry_date': expiry_date.strftime('%d.%m.%Y') if expiry_date else '',
            'is_expired': doc.is_expired,
            'expires_soon': doc.expires_soon,
        })
    except Exception as e:
        import traceback
        return JsonResponse({'error': f'{type(e).__name__}: {e}', 'trace': traceback.format_exc()}, status=500)


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


@login_required
def serve_pilot_document(request, doc_id):
    """
    Отдаёт файл личного документа пилота (паспорт, лицензия и т.д.) только
    владельцу. Раньше шаблон ссылался прямо на doc.file.url — это публичный
    /media/ путь, который nginx отдаёт БЕЗ какой-либо проверки прав (см.
    /etc/nginx/sites-available/gripline: location /media/ — голый alias).
    Оригинальное имя файла на первой загрузке nginx/Django не рандомизирует
    (суффикс добавляется только при коллизии имён), поэтому URL вида
    /media/pilot_documents/passport_ivanov.jpg был предсказуем и полностью
    публичен — любой, кто узнал или угадал имя файла, мог скачать чужой
    паспорт без авторизации. Прод-nginx закрыт на уровне location (deny),
    единственный путь к файлу теперь — через эту вьюху.

    as_attachment=True обязателен: без него FileResponse отдаёт
    Content-Disposition: inline, и браузер откроет файл в контексте origin
    gripline.ru согласно Content-Type, угаданному по расширению загруженного
    файла (mimetypes.guess_type по имени, а не по фактическому содержимому).
    Ничто не мешает пилоту назвать файл "паспорт.html" со скриптом внутри —
    это был бы хранимый XSS с сессией того, кто открыл "документ" (в
    applications-версии этой же вьюхи — сессией организатора, который
    проверяет заявку). С attachment браузер всегда скачивает файл, не
    выполняет его содержимое.
    """
    profile = getattr(request.user, 'profile', None)
    doc = get_object_or_404(PilotDocument, pk=doc_id, profile=profile)
    return FileResponse(
        doc.file.open('rb'), filename=doc.file.name.rsplit('/', 1)[-1], as_attachment=True,
    )


# ─── Яндекс OAuth ────────────────────────────────────────────────────────────

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
    """Thin wrapper: store role in session then delegate to social-auth-app-django."""
    settings_obj = SocialAuthSettings.get()
    if not settings_obj.yandex_enabled:
        messages.error(request, 'Вход через Яндекс временно недоступен.')
        return redirect('accounts:login')
    role = request.GET.get('role', 'pilot')
    if role not in ('pilot', 'team', 'organizer'):
        role = 'pilot'
    # social-auth stores SOCIAL_AUTH_FIELDS_STORED_IN_SESSION fields from GET params
    from django.urls import reverse as _rev
    return redirect(_rev('social:begin', args=['yandex-oauth2']) + f'?role={role}')


@csrf_exempt
def vk_id_widget_complete(request):
    """
    Завершение входа для виджета VK ID SDK (OneTap).

    VK ID требует официальный SDK-виджет вместо прямого редиректа на
    id.vk.ru/authorize (иначе платформа блокирует вход: «Сервис заблокирован»).
    Виджет сам обменивает code на access_token в браузере (VKID.Auth.exchangeCode) —
    сервер code_verifier не видит и участвовать в обмене не может, поэтому
    здесь запускается только вторая половина стандартного pipeline
    python-social-auth: access_token → user_data() (проверка токена на стороне VK)
    → SOCIAL_AUTH_PIPELINE (создание/связывание пользователя) → login().
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    settings_obj = SocialAuthSettings.get()
    if not settings_obj.vk_enabled:
        return JsonResponse({'error': 'Вход через VK ID временно недоступен.'}, status=403)

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Некорректный запрос.'}, status=400)

    access_token = payload.get('access_token')
    if not access_token:
        return JsonResponse({'error': 'Не получен access_token.'}, status=400)

    role = payload.get('role', 'pilot')
    if role not in ('pilot', 'team', 'organizer'):
        role = 'pilot'
    request.session['role'] = role
    for field in ('pilot_id', 'team_id', 'team_name'):
        value = payload.get(field)
        if value:
            request.session[field] = value

    from social_django.utils import load_strategy, load_backend
    strategy = load_strategy(request)
    backend = load_backend(strategy, 'vk-id', redirect_uri=None)

    try:
        user = backend.do_auth(access_token, request=request)
    except Exception as e:
        return JsonResponse({'error': f'Ошибка VK ID: {e}'}, status=400)

    if not isinstance(user, User) or not user.is_active:
        return JsonResponse({'error': 'Не удалось войти через VK ID.'}, status=400)

    user.backend = f'{backend.__module__}.{backend.__class__.__name__}'
    login(request, user)
    return JsonResponse({'success': True, 'redirect': '/accounts/profile/'})


def vk_id_redirect_landing(request):
    """
    Landing-страница для redirectUrl VK ID SDK (https://gripline.ru/auth/complete/vk-id/).

    Для уже узнанной VK-сессии («Продолжить как …») виджет не отдаёт code
    через LOGIN_SUCCESS в исходной вкладке — вместо этого открывает окно
    с полноценным OAuth-редиректом сюда (?code=...&device_id=...). Здесь тот же
    VK ID SDK довершает обмен кода на access_token (code_verifier PKCE хранится
    в sessionStorage самим SDK и переживает переход в пределах одного окна),
    а дальше — тот же POST в vk_id_widget_complete, что и у обычного клика.

    Путь перехватывает social_django-роут auth/complete/vk-id/ раньше
    (см. mysite/urls.py) — сервер туда больше не заходит, code/device_id
    обрабатываются только в браузере.
    """
    settings_obj = SocialAuthSettings.get()
    return render(request, 'accounts/vk_id_redirect.html', {'social_auth': settings_obj})


def yandex_search_drivers(request):
    """AJAX: поиск Driver по имени/фамилии"""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    from django.db.models import Q as DQ
    from website.services.demo import without_demo
    drivers = without_demo(Driver.objects.filter(
        DQ(first_name__icontains=q) | DQ(last_name__icontains=q)
    )).values('id', 'first_name', 'last_name', 'city')[:20]
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

    # Auto-select pre-chosen pilot from choose-role modal
    preselected_id = request.session.pop('yandex_preselected_pilot_id', None)
    if preselected_id and request.method == 'GET':
        try:
            driver = Driver.objects.get(pk=preselected_id)
            if not DriverClaim.objects.filter(driver=driver, status='approved').exists():
                DriverClaim.objects.create(
                    user=request.user,
                    driver=driver,
                    requested_first_name=driver.first_name,
                    requested_last_name=driver.last_name,
                    status='pending',
                )
                for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                    request.session.pop(key, None)
                request.session['active_role'] = 'pilot'
                messages.success(request, 'Заявка на привязку профиля отправлена. Ожидайте подтверждения.')
                return redirect('accounts:profile')
        except Driver.DoesNotExist:
            pass

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
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            request.session['active_role'] = 'pilot'
            messages.success(request, 'Заявка на привязку профиля отправлена. Ожидайте подтверждения.')
            return redirect('accounts:profile')

        elif action == 'new':
            fn = request.POST.get('first_name', first_name).strip()
            ln = request.POST.get('last_name', last_name).strip()
            if not fn or not ln:
                messages.error(request, 'Введите имя и фамилию.')
                return render(request, 'accounts/yandex_pilot_onboarding.html', {
                    'first_name': first_name, 'last_name': last_name, 'show_new_form': True,
                })
            # Профиль пилота создаст сигнал при подтверждении заявки админом (accounts/signals.py)
            DriverClaim.objects.create(
                user=request.user,
                requested_first_name=fn,
                requested_last_name=ln,
                status='pending',
            )
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            request.session['active_role'] = 'pilot'
            messages.success(request, 'Заявка отправлена. Профиль пилота появится на сайте после подтверждения администратором.')
            return redirect('accounts:profile')

    return render(request, 'accounts/yandex_pilot_onboarding.html', {
        'first_name': first_name,
        'last_name': last_name,
    })


@login_required
def yandex_team_onboarding(request):
    from teams.models import TeamClaim as _TC, TeamManager as _TM
    has_claim = _TC.objects.filter(user=request.user).exists()
    if not request.session.get('yandex_onboarding') and has_claim:
        return redirect('teams:dashboard')

    # Auto-create team from name entered in choose-role modal before OAuth
    preselected_team_name = request.session.pop('yandex_preselected_team_name', None)
    if preselected_team_name and request.method == 'GET':
        from website.models import Team as WebTeam
        from teams.models import TeamClaim as TC, TeamManager as TM
        # Команду и менеджера создаст сигнал при подтверждении заявки админом (teams/signals.py)
        TC.objects.create(
            user=request.user,
            requested_team_name=preselected_team_name,
            status='pending',
        )
        for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
            request.session.pop(key, None)
        request.session['active_role'] = 'team'
        messages.success(request, 'Заявка отправлена. Команда появится на сайте после проверки администратором.')
        return redirect('teams:dashboard')

    # Auto-select pre-chosen team from choose-role modal
    preselected_team_id = request.session.pop('yandex_preselected_team_id', None)
    if preselected_team_id and request.method == 'GET':
        from website.models import Team as WebTeam
        try:
            team = WebTeam.objects.get(pk=preselected_team_id)
            if not _TM.objects.filter(team=team, is_active=True).exists():
                _TC.objects.create(
                    user=request.user,
                    team=team,
                    requested_team_name=team.name,
                    status='pending',
                )
                for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                    request.session.pop(key, None)
                request.session['active_role'] = 'team'
                messages.success(request, 'Заявка отправлена. Ожидайте подтверждения.')
                return redirect('teams:dashboard')
        except WebTeam.DoesNotExist:
            pass

    if request.method == 'POST':
        from website.models import Team as WebTeam
        from teams.models import TeamClaim as TC, TeamManager as TM
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
            # Команду и менеджера создаст сигнал при подтверждении заявки админом (teams/signals.py)
            TC.objects.create(
                user=request.user,
                requested_team_name=team_name,
                requested_city=city,
                status='pending',
            )
            for key in ('yandex_onboarding', 'yandex_first_name', 'yandex_last_name'):
                request.session.pop(key, None)
            request.session['active_role'] = 'team'
            messages.success(request, 'Заявка отправлена. Команда появится на сайте после проверки администратором.')
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
