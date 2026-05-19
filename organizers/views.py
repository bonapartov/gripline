from django.shortcuts import render, redirect, get_object_or_404
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.contrib.auth.models import User
from wagtail.models import Page
from website.models import ChampionshipPage, StagePage, EventPage, RaceClass
from .models import OrganizerProfile, Championship, Stage, OrganizerSettings
from .forms import ChampionshipForm, StageForm, OrganizerRegistrationForm
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.http import HttpResponseRedirect
from django.urls import reverse
from wagtail.models import Collection
from wagtail.images.models import Image as WagtailImage
from wagtail.documents.models import Document as WagtailDocument
from django.utils.text import slugify
import time

@login_required
def dashboard(request):
    try:
        profile = request.user.organizer_profile
    except OrganizerProfile.DoesNotExist:
        messages.error(request, 'У вас нет прав организатора.')
        return redirect('/')
    
    championships = Championship.objects.filter(organizer=profile)
    
    # Собираем все этапы для чемпионатов организатора
    from .models import Registration
    stages = []
    for champ in championships:
        for stage in champ.stages.all().order_by('start_date'):
            reg_qs = stage.registrations
            stages.append({
                'id': stage.id,
                'title': stage.title,
                'championship_title': champ.title,
                'championship_id': champ.id,
                'start_date': stage.start_date,
                'end_date': stage.end_date,
                'entry_fee': stage.entry_fee,
                'track': stage.track.name if stage.track else 'не указана',
                'wagtail_page': stage.wagtail_page,
                'reg_count': reg_qs.exclude(status__in=['cancelled', 'rejected']).count(),
                'reg_pending': reg_qs.filter(status='draft').count(),
            })
    
    # Сортируем этапы по дате начала
    stages.sort(key=lambda x: x['start_date'] or datetime.min)
    
    # Получаем глобальные настройки
    settings_obj = OrganizerSettings.objects.first()
    default_commission = settings_obj.commission_default if settings_obj else 10
    default_payer = getattr(settings_obj, 'commission_payer', 'participant')
    
    # Комиссия организатора
    organizer_commission = profile.commission_percent
    organizer_payer = profile.commission_payer
    
    # Для отображения в блоке условий (берём первый чемпионат)
    first_champ = championships.first()
    championship_commission = first_champ.commission_percent if first_champ and first_champ.commission_percent else None
    championship_payer = first_champ.commission_payer if first_champ and first_champ.commission_payer else None
    
    support_phone = settings_obj.support_phone if settings_obj else ""
    support_email = settings_obj.support_email if settings_obj else ""
    terms_text = settings_obj.terms_text if settings_obj else ""
    
    return render(request, 'organizers/dashboard.html', {
        'championships': championships,
        'stages': stages,
        'default_commission': default_commission,
        'default_payer': default_payer,
        'organizer_commission': organizer_commission,
        'organizer_payer': organizer_payer,
        'championship_commission': championship_commission,
        'championship_payer': championship_payer,
        'support_phone': support_phone,
        'support_email': support_email,
        'terms_text': terms_text,
    })

@login_required
def championship_create(request):
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        profile = request.user.organizer_profile
    except OrganizerProfile.DoesNotExist:
        messages.error(request, "Доступ запрещён.")
        return redirect("/")
    
    if request.method == "POST":
        form = ChampionshipForm(request.POST, request.FILES)
        
        if form.is_valid():
            championship = form.save(commit=False)
            championship.organizer = profile
            
            # Slug
            from django.utils.text import slugify
            base_slug = slugify(championship.title)
            if not base_slug:
                base_slug = "championship"
            slug = base_slug
            counter = 1
            while Championship.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            championship.slug = slug
            
            championship.save()
            
            # Сохраняем типы соревнований
            if form.cleaned_data.get('competition_types'):
                championship.competition_types.set(form.cleaned_data['competition_types'])
            
            # Обработка фото
            if 'cover_image' in request.FILES:
                from wagtail.images.models import Image as WagtailImage
                wagtail_image = WagtailImage.objects.create(
                    title=championship.title,
                    file=request.FILES['cover_image']
                )
                championship.cover_image = wagtail_image
                championship.save()
            
            # Создание Wagtail страницы
            parent_page = Page.objects.filter(slug="championships").first()
            if parent_page:
                from website.models import ChampionshipPage
                wagtail_page = ChampionshipPage(
                    title=championship.title,
                    slug=championship.slug,
                    is_completed=False,
                )
                parent_page.add_child(instance=wagtail_page)
                wagtail_page.save_revision().publish()
                championship.wagtail_page = wagtail_page
                
                # Синхронизация типов
                specific_page = wagtail_page.specific
                specific_page.championship_competition_types.clear()
                for ct in championship.competition_types.all():
                    specific_page.championship_competition_types.create(competition_type=ct)
                
                # Синхронизация картинки
                if championship.cover_image:
                    specific_page.cover_image = championship.cover_image
                    specific_page.save_revision().publish()
                
                championship.save()
            
            messages.success(request, f"Чемпионат '{championship.title}' создан!")
            return redirect("organizers:dashboard")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = ChampionshipForm()
    
    return render(request, "organizers/championship_form.html", {"form": form})

@login_required
def stage_create(request, championship_id):
    championship = get_object_or_404(Championship, id=championship_id, organizer__user=request.user)
    
    if request.method == 'POST':
        form = StageForm(request.POST)
        if form.is_valid():
            stage = form.save(commit=False)
            stage.championship = championship
            stage.save()  # Сигнал сам создаст StagePage и EventPage
            
            messages.success(request, f'Этап "{stage.title}" создан!')
            return redirect('organizers:dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = StageForm()
    
    return render(request, 'organizers/stage_form.html', {'form': form, 'championship': championship})
    
def organizer_register(request):
    if request.method == 'POST':
        form = OrganizerRegistrationForm(request.POST)
        if form.is_valid():
            email = request.POST.get('email')
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Пользователь с таким email уже зарегистрирован.')
                return render(request, 'organizers/register.html', {'form': form})
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            try:
                send_organizer_verification_email(user, request)
                messages.success(request, 'Регистрация почти завершена! Проверьте почту.')
                return redirect('organizers:organizer_verification_sent')
            except Exception as e:
                user.delete()
                messages.error(request, f'Ошибка отправки письма: {str(e)}')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = OrganizerRegistrationForm()
    return render(request, 'organizers/register.html', {'form': form})

def organizer_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, username=email, password=password)
        if user is not None:
            if user.is_active:
                login(request, user)
                return redirect('organizers:dashboard')
            else:
                messages.error(request, 'Аккаунт не активирован. Проверьте почту.')
                return redirect('organizers:organizer_resend_verification')
        else:
            messages.error(request, 'Неверный email или пароль')
    return render(request, 'organizers/login.html')

def send_organizer_verification_email(user, request):
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verification_url = request.build_absolute_uri(f'/organizers/verify-email/{uid}/{token}/')
    subject = 'Подтверждение регистрации организатора на Gripline'
    html_message = render_to_string('emails/organizer_verification_email.html', {
        'user': user,
        'verification_url': verification_url,
        'expiry_minutes': 30,
    })
    send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message, fail_silently=False)

def organizer_verification_sent(request):
    return render(request, 'organizers/verification_sent.html')

def organizer_verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except:
        user = None
    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, 'Email подтверждён! Теперь вы можете войти.')
        return redirect('organizers:login')
    else:
        return render(request, 'organizers/verification_failed.html')

def organizer_resend_verification(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email, is_active=False)
            send_organizer_verification_email(user, request)
            messages.success(request, 'Письмо отправлено повторно.')
            return redirect('organizers:organizer_verification_sent')
        except User.DoesNotExist:
            messages.error(request, 'Пользователь с таким email не найден или уже активирован.')
    return render(request, 'organizers/verification_resend.html')

@login_required
def championship_edit(request, pk):
    championship = get_object_or_404(Championship, pk=pk, organizer__user=request.user)
    
    if request.method == 'POST':
        form = ChampionshipForm(request.POST, request.FILES, instance=championship)
        if form.is_valid():
            championship = form.save(commit=False)
            championship.save()
            
            # Обновляем типы соревнований (ManyToMany)
            if form.cleaned_data.get('competition_types'):
                championship.competition_types.set(form.cleaned_data['competition_types'])
            else:
                championship.competition_types.clear()
            
            # Обработка cover_image
            if 'cover_image' in request.FILES:
                from wagtail.images.models import Image as WagtailImage
                wagtail_image = WagtailImage.objects.create(
                    title=championship.title,
                    file=request.FILES['cover_image']
                )
                championship.cover_image = wagtail_image
                championship.save()
            
            # Обновляем Wagtail страницу, если есть
            if championship.wagtail_page:
                # ВАЖНО: используем .specific для доступа к полям ChampionshipPage
                wagtail_page = championship.wagtail_page.specific
                wagtail_page.title = championship.title
                wagtail_page.slug = championship.slug
                wagtail_page.save()
                
                # Синхронизация типов соревнований
                wagtail_page.championship_competition_types.clear()
                for ct in championship.competition_types.all():
                    wagtail_page.championship_competition_types.create(competition_type=ct)
            
            messages.success(request, 'Чемпионат обновлён!')
            return redirect('organizers:dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = ChampionshipForm(instance=championship)
    
    return render(request, 'organizers/championship_form.html', {'form': form})

@login_required
def championship_delete(request, pk):
    championship = get_object_or_404(Championship, pk=pk, organizer__user=request.user)
    title = championship.title
    
    if championship.wagtail_page:
        championship.wagtail_page.delete()
    championship.delete()
    
    messages.success(request, f'Чемпионат "{title}" удалён!')
    return redirect('organizers:dashboard')

@login_required
def stage_edit(request, pk):
    stage = get_object_or_404(Stage, pk=pk, championship__organizer__user=request.user)
    
    if request.method == 'POST':
        form = StageForm(request.POST, instance=stage)
        if form.is_valid():
            stage = form.save()
            messages.success(request, f'Этап "{stage.title}" обновлён!')
            return redirect('organizers:dashboard')
    else:
        form = StageForm(instance=stage)
    
    return render(request, 'organizers/stage_form.html', {'form': form, 'championship': stage.championship})
    





@login_required
def stage_delete(request, pk):
    stage = get_object_or_404(Stage, pk=pk, championship__organizer__user=request.user)
    title = stage.title
    stage.delete()
    messages.success(request, f'Этап "{title}" удалён!')
    return redirect('organizers:dashboard')


def stage_register(request, stage_id):
    """Регистрация участника на этап через страницу этапа."""
    from .models import Registration, Stage
    stage = get_object_or_404(Stage, pk=stage_id)

    if not request.user.is_authenticated:
        messages.error(request, 'Войдите в аккаунт для регистрации на этап.')
        stage_url = stage.wagtail_page.url if stage.wagtail_page else '/'
        return redirect(f'/accounts/login/?next={stage_url}')

    if request.method != 'POST':
        stage_url = stage.wagtail_page.url if stage.wagtail_page else '/'
        return redirect(stage_url)

    race_class_id = request.POST.get('race_class_id')
    if not race_class_id:
        messages.error(request, 'Выберите класс для регистрации.')
        stage_url = stage.wagtail_page.url if stage.wagtail_page else '/'
        return redirect(stage_url)

    race_class = get_object_or_404(RaceClass, pk=race_class_id)

    try:
        driver = request.user.profile.driver
    except Exception:
        driver = None

    if Registration.objects.filter(stage=stage, user=request.user, race_class=race_class,
                                   status__in=['draft', 'paid', 'confirmed']).exists():
        messages.warning(request, f'Вы уже зарегистрированы на этот этап в классе {race_class.name}.')
        stage_url = stage.wagtail_page.url if stage.wagtail_page else '/'
        return redirect(stage_url)

    team = driver.current_team if driver and hasattr(driver, 'current_team') else None

    Registration.objects.create(
        stage=stage,
        user=request.user,
        race_class=race_class,
        driver=driver,
        team=team,
        status='draft',
        amount=stage.entry_fee,
    )
    messages.success(request, f'Вы зарегистрированы на этап «{stage.title}» в классе {race_class.name}!')
    stage_url = stage.wagtail_page.url if stage.wagtail_page else '/'
    return redirect(stage_url)


@login_required
def registration_cancel(request, registration_id):
    """Участник отменяет свою регистрацию."""
    from .models import Registration
    reg = get_object_or_404(Registration, pk=registration_id, user=request.user)

    if reg.status not in ('draft', 'paid'):
        messages.error(request, 'Эту регистрацию уже нельзя отменить.')
    else:
        reg.status = 'cancelled'
        reg.save()
        messages.success(request, 'Регистрация отменена.')

    stage_url = reg.stage.wagtail_page.url if reg.stage.wagtail_page else '/'
    return redirect(stage_url)


@login_required
def stage_registrations(request, stage_id):
    """Список регистраций на этап (только для организатора)."""
    from .models import Registration, Stage
    stage = get_object_or_404(Stage, pk=stage_id, championship__organizer__user=request.user)
    registrations = stage.registrations.select_related(
        'user', 'race_class', 'driver', 'team'
    ).order_by('race_class__name', 'created_at')

    by_class = {}
    for reg in registrations:
        cls_name = reg.race_class.name
        by_class.setdefault(cls_name, []).append(reg)

    return render(request, 'organizers/stage_registrations.html', {
        'stage': stage,
        'by_class': by_class,
        'total': registrations.count(),
    })


@login_required
def registration_action(request, registration_id):
    """Организатор подтверждает или отклоняет регистрацию."""
    from .models import Registration
    reg = get_object_or_404(
        Registration, pk=registration_id,
        stage__championship__organizer__user=request.user
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'confirm':
            reg.status = 'confirmed'
            reg.save()
            messages.success(request, f'Регистрация {reg.user.email} подтверждена.')
        elif action == 'reject':
            reg.status = 'rejected'
            reg.save()
            messages.warning(request, f'Регистрация {reg.user.email} отклонена.')

    return redirect('organizers:stage_registrations', stage_id=reg.stage.pk)