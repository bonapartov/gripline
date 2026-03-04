from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .forms import RegistrationForm, DriverProfileForm, SocialLinkFormSet
from website.models import Driver
from .models import DriverClaim
from wagtail.images.models import Image  # Важно!
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
import json

def register(request):
    """Регистрация нового пользователя"""
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()

            # Ищем похожих пилотов
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            city = form.cleaned_data.get('city', '')

            # Поиск по точному совпадению имени и фамилии
            drivers = Driver.objects.filter(
                first_name__iexact=first_name,
                last_name__iexact=last_name
            )

            # Если есть совпадения, сохраняем их в сессию
            if drivers.exists():
                request.session['found_drivers'] = [
                    {'id': d.id, 'name': d.full_name, 'city': d.city or ''}
                    for d in drivers
                ]
                request.session['user_id'] = user.id
                request.session['first_name'] = first_name
                request.session['last_name'] = last_name
                request.session['city'] = city

                return redirect('accounts:select_driver')
            else:
                # Если пилот не найден, создаем заявку без привязки
                DriverClaim.objects.create(
                    user=user,
                    requested_first_name=first_name,
                    requested_last_name=last_name,
                    requested_city=city,
                    status='pending'
                )
                messages.success(request, 'Регистрация завершена. Ваша заявка отправлена администратору.')
                return redirect('accounts:login')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})

def select_driver(request):
    """Страница выбора пилота из найденных"""
    found_drivers = request.session.get('found_drivers', [])
    user_id = request.session.get('user_id')

    if not found_drivers or not user_id:
        return redirect('accounts:register')

    if request.method == 'POST':
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=user_id)

        selected_id = request.POST.get('driver_id')

        if selected_id == 'none':
            # Пользователь не нашел себя
            DriverClaim.objects.create(
                user=user,
                requested_first_name=request.session['first_name'],
                requested_last_name=request.session['last_name'],
                requested_city=request.session.get('city', ''),
                status='pending'
            )
            messages.success(request, 'Ваша заявка отправлена администратору.')

        elif selected_id:
            # Пользователь выбрал пилота
            driver = Driver.objects.get(id=selected_id)
            DriverClaim.objects.create(
                user=user,
                driver=driver,
                requested_first_name=request.session['first_name'],
                requested_last_name=request.session['last_name'],
                requested_city=request.session.get('city', ''),
                status='pending'
            )
            messages.success(request, f'Заявка на привязку к {driver.full_name} отправлена администратору.')

        # Очищаем сессию
        for key in ['found_drivers', 'user_id', 'first_name', 'last_name', 'city']:
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

        if user is not None:
            login(request, user)
            return redirect('accounts:profile')
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

            return render(request, 'accounts/profile.html', {
                'driver': driver,
                'claim': claim,
                'form': form,
                'formset': formset,
            })
        else:
            messages.warning(request, 'Ваша заявка ещё не подтверждена администратором.')
            return render(request, 'accounts/profile_pending.html')

    except DriverClaim.DoesNotExist:
        messages.warning(request, 'У вас нет активной заявки. Зарегистрируйтесь как пилот.')
        return redirect('accounts:register')

def logout_view(request):
    """Выход пользователя"""
    logout(request)
    return redirect('accounts:login')
# Create your views here.
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
