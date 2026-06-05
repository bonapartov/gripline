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
    from applications.models import Application
    stages = []
    for champ in championships:
        for stage in champ.stages.all().order_by('start_date'):
            app_qs = Application.objects.filter(stage=stage)
            stages.append({
                'id': stage.id,
                'title': stage.title,
                'championship_title': champ.title,
                'championship_id': champ.id,
                'championship_tyre_mode': champ.tyre_mode,
                'start_date': stage.start_date,
                'end_date': stage.end_date,
                'entry_fee': stage.entry_fee,
                'track': stage.track.name if stage.track else 'не указана',
                'wagtail_page': stage.wagtail_page,
                'is_published': stage.is_published,
                'reg_count': app_qs.exclude(status__in=['cancelled', 'rejected']).count(),
                'reg_pending': app_qs.filter(status='submitted').count(),
                'registration_enabled': stage.registration_enabled,
                'registration_deadline': stage.registration_deadline,
                'max_participants': stage.max_participants,
                'stage_tyres': [str(t) for t in stage.stage_tyres.select_related('brand', 'type').all()],
            })
    
    # Сортируем этапы по дате начала
    stages.sort(key=lambda x: x['start_date'] or datetime.min)

    # Группируем этапы по чемпионату для шаблона
    stages_by_champ = {}
    for s in stages:
        stages_by_champ.setdefault(s['championship_id'], []).append(s)

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
        'stages_by_champ': stages_by_champ,
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

            # Сохраняем классы
            if form.cleaned_data.get('race_classes'):
                championship.race_classes.set(form.cleaned_data['race_classes'])

            # Сохраняем шины
            championship.default_tyres.set(form.cleaned_data.get('default_tyres') or [])

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
            from website.models import ChampionshipPage, SeasonArchivePage
            parent_page = (
                Page.objects.filter(slug="championships").first()
                or SeasonArchivePage.objects.live().first()
                or Page.objects.filter(depth=2).first()  # корневая страница сайта
            )
            if parent_page:
                wagtail_page = ChampionshipPage(
                    title=championship.title,
                    slug=championship.slug,
                    is_completed=False,
                )
                parent_page.add_child(instance=wagtail_page)
                wagtail_page.save_revision().publish()
                championship.wagtail_page = wagtail_page

                specific_page = wagtail_page.specific
                specific_page.championship_competition_types.clear()
                for ct in championship.competition_types.all():
                    specific_page.championship_competition_types.create(competition_type=ct)

                if championship.cover_image:
                    specific_page.cover_image = championship.cover_image
                    specific_page.save_revision().publish()

                championship.save()
            else:
                messages.warning(request, "Чемпионат создан, но страница в публичном каталоге не создана — нет подходящего родителя в дереве страниц.")

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
            stage.stage_tyres.set(form.cleaned_data.get('stage_tyres') or [])

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
            OrganizerProfile.objects.get_or_create(
                user=user,
                defaults={
                    'phone': form.cleaned_data.get('phone', ''),
                    'telegram': form.cleaned_data.get('telegram', ''),
                }
            )
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
        if user is None:
            for candidate in User.objects.filter(email__iexact=email):
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
        OrganizerProfile.objects.get_or_create(user=user)
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


def _sync_event_pages_for_classes(championship, old_class_ids, new_class_ids):
    """Создаёт EventPages для новых классов и удаляет для убранных."""
    from django.utils.text import slugify
    from website.models import EventPage, EventOccurrence, RaceClassResultGroup, RaceClass

    added = new_class_ids - old_class_ids
    removed = old_class_ids - new_class_ids

    for stage in championship.stages.all():
        if not stage.wagtail_page:
            continue
        stage_page = stage.wagtail_page.specific

        # Удаляем EventPages для убранных классов
        if removed:
            groups_to_delete = RaceClassResultGroup.objects.filter(
                page__in=EventPage.objects.child_of(stage_page),
                race_class_id__in=removed,
            )
            for group in groups_to_delete:
                group.page.delete()

        # Создаём EventPages для новых классов
        existing_class_ids = set(
            RaceClassResultGroup.objects.filter(
                page__in=EventPage.objects.child_of(stage_page)
            ).values_list('race_class_id', flat=True)
        )
        for class_id in added - existing_class_ids:
            race_class = RaceClass.objects.get(id=class_id)
            base_slug = slugify(f"{stage.title}-{race_class.name}")
            slug = base_slug
            counter = 1
            while EventPage.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            event_page = EventPage(
                title=stage.title,
                admin_title=f"{stage.title} - {race_class.name}",
                slug=slug,
                track=stage.track,
            )
            stage_page.add_child(instance=event_page)
            event_page.save_revision().publish()
            EventOccurrence.objects.create(
                event=event_page,
                start=stage.start_date,
                end=stage.end_date,
            )
            RaceClassResultGroup.objects.create(
                page=event_page,
                race_class=race_class,
            )


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

            # Обновляем классы
            old_class_ids = set(championship.race_classes.values_list('id', flat=True))
            if form.cleaned_data.get('race_classes'):
                championship.race_classes.set(form.cleaned_data['race_classes'])
            else:
                championship.race_classes.clear()
            new_class_ids = set(championship.race_classes.values_list('id', flat=True))

            # Синхронизируем EventPages: создаём новые, удаляем убранные классы
            _sync_event_pages_for_classes(championship, old_class_ids, new_class_ids)

            # Обновляем шины
            new_tyre_mode = form.cleaned_data.get('tyre_mode', Championship.TYRE_MODE_ALL)
            old_tyre_mode = Championship.objects.get(pk=championship.pk).tyre_mode if championship.pk else None

            if new_tyre_mode == Championship.TYRE_MODE_PER_STAGE:
                # Сбрасываем шины чемпионата
                championship.default_tyres.clear()
                # Если переключились с 'all' — предупреждаем
                if old_tyre_mode == Championship.TYRE_MODE_ALL:
                    from datetime import date
                    future_stages = championship.stages.filter(end_date__date__gte=date.today())
                    if future_stages.exists():
                        messages.warning(request, f'Выберите шины для этапов в «{championship.title}»')
            else:
                championship.default_tyres.set(form.cleaned_data.get('default_tyres') or [])

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
            stage.stage_tyres.set(form.cleaned_data.get('stage_tyres') or [])
            messages.success(request, f'Этап "{stage.title}" обновлён!')
            return redirect('organizers:dashboard')
    else:
        form = StageForm(instance=stage)

    return render(request, 'organizers/stage_form.html', {'form': form, 'championship': stage.championship, 'stage': stage})
    





@login_required
def stage_delete(request, pk):
    stage = get_object_or_404(Stage, pk=pk, championship__organizer__user=request.user)
    title = stage.title
    stage.delete()
    messages.success(request, f'Этап "{title}" удалён!')
    return redirect('organizers:dashboard')


@login_required
def stage_settings(request, pk):
    """Настройка регистрации этапа: документы, доп. опции, зарезервированные номера"""
    from .forms import StageDocumentForm, StageOptionForm
    from applications.models import StageDocument, StageOption

    stage = get_object_or_404(Stage, pk=pk, championship__organizer__user=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_document':
            form = StageDocumentForm(request.POST)
            if form.is_valid():
                doc = form.save(commit=False)
                doc.stage = stage
                doc.order = stage.required_documents.count()
                doc.save()
                messages.success(request, f'Документ «{doc.name}» добавлен.')
            return redirect('organizers:stage_settings', pk=stage.id)

        if action == 'delete_document':
            StageDocument.objects.filter(id=request.POST.get('doc_id'), stage=stage).delete()
            messages.success(request, 'Документ удалён.')
            return redirect('organizers:stage_settings', pk=stage.id)

        if action == 'add_option':
            form = StageOptionForm(request.POST)
            if form.is_valid():
                opt = form.save(commit=False)
                opt.stage = stage
                opt.order = stage.options.count()
                opt.save()
                messages.success(request, f'Опция «{opt.name}» добавлена.')
            return redirect('organizers:stage_settings', pk=stage.id)

        if action == 'delete_option':
            StageOption.objects.filter(id=request.POST.get('option_id'), stage=stage).delete()
            messages.success(request, 'Опция удалена.')
            return redirect('organizers:stage_settings', pk=stage.id)

        if action == 'save_reserved':
            raw = request.POST.get('reserved_numbers', '')
            numbers = []
            for part in raw.replace(';', ',').split(','):
                part = part.strip()
                if part.isdigit():
                    numbers.append(int(part))
            stage.reserved_start_numbers = sorted(set(numbers))
            stage.save(update_fields=['reserved_start_numbers'])
            messages.success(request, 'Зарезервированные номера сохранены.')
            return redirect('organizers:stage_settings', pk=stage.id)

    return render(request, 'organizers/stage_settings.html', {
        'stage': stage,
        'documents': stage.required_documents.all(),
        'options': stage.options.all(),
        'document_form': StageDocumentForm(),
        'option_form': StageOptionForm(),
        'reserved_str': ', '.join(str(n) for n in (stage.reserved_start_numbers or [])),
    })


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
    """Список заявок на этап (только для организатора)."""
    from .models import Stage
    from applications.models import Application
    stage = get_object_or_404(Stage, pk=stage_id, championship__organizer__user=request.user)

    applications = Application.objects.filter(stage=stage).exclude(
        status='cancelled'
    ).select_related('race_class', 'pilot', 'pilot__driver', 'payment').prefetch_related(
        'documents'
    ).order_by('race_class__name', 'start_number', 'created_at')

    by_class = {}
    for app in applications:
        # Считаем готовность документов
        docs = list(app.documents.all())
        app.docs_total = len(docs)
        app.docs_verified = sum(1 for d in docs if d.status == 'verified')
        cls_name = app.race_class.name if app.race_class else 'Без класса'
        by_class.setdefault(cls_name, []).append(app)

    return render(request, 'organizers/stage_registrations.html', {
        'stage': stage,
        'by_class': by_class,
        'total': applications.count(),
        'pending_count': applications.filter(status='submitted').count(),
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

@login_required
def stage_numbers(request, stage_id):
    from .models import Stage
    from applications.models import Application

    stage = get_object_or_404(Stage, pk=stage_id, championship__organizer__user=request.user)

    applications = Application.objects.filter(
        stage=stage, start_number__isnull=False
    ).exclude(status__in=['cancelled', 'rejected']).select_related('race_class', 'pilot', 'pilot__driver')

    # Приоритет активной заявки при совпадении номера
    numbers_map = {}
    STATUS_PRIORITY = {'confirmed': 0, 'submitted': 1, 'draft': 2}
    for app in applications:
        n = app.start_number
        if n not in numbers_map or STATUS_PRIORITY.get(app.status, 9) < STATUS_PRIORITY.get(numbers_map[n].status, 9):
            numbers_map[n] = app

    if stage.start_number_digits == 2:
        all_numbers = list(range(10, 100))
    else:
        all_numbers = list(range(100, 1000))

    reserved = set(stage.reserved_start_numbers or [])

    grid_data = []
    for n in all_numbers:
        grid_data.append({
            'number': n,
            'app': numbers_map.get(n),
            'reserved': n in reserved and n not in numbers_map,
        })

    total_taken = len(numbers_map)
    total_reserved = len([n for n in reserved if n not in numbers_map])
    total_free = len(all_numbers) - total_taken - total_reserved

    return render(request, 'organizers/stage_numbers.html', {
        'stage': stage,
        'grid_data': grid_data,
        'total_all': len(all_numbers),
        'total_taken': total_taken,
        'total_free': total_free,
    })


@login_required
def reassign_number(request, stage_id):
    from django.http import JsonResponse
    from .models import Stage
    from applications.models import Application

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    stage = get_object_or_404(Stage, pk=stage_id, championship__organizer__user=request.user)

    app_id = request.POST.get('app_id')
    new_number = request.POST.get('new_number')

    try:
        new_number = int(new_number)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Некорректный номер'})

    app = get_object_or_404(Application, pk=app_id, stage=stage)

    taken = set(
        Application.objects.filter(stage=stage, start_number__isnull=False)
        .exclude(status__in=['cancelled'])
        .exclude(pk=app.pk)
        .values_list('start_number', flat=True)
    )
    reserved = set(stage.reserved_start_numbers or [])

    if new_number in taken or new_number in reserved:
        return JsonResponse({'success': False, 'error': 'Номер занят или зарезервирован'})

    if stage.start_number_digits == 2 and not (10 <= new_number <= 99):
        return JsonResponse({'success': False, 'error': 'Номер вне диапазона'})
    if stage.start_number_digits == 3 and not (100 <= new_number <= 999):
        return JsonResponse({'success': False, 'error': 'Номер вне диапазона'})

    app.start_number = new_number
    app.save()
    return JsonResponse({'success': True, 'new_number': new_number})


@login_required
def stage_finance(request, stage_id):
    from .models import Stage
    from applications.models import Application, ApplicationPayment
    from django.db.models import Sum, Count, Q

    stage = get_object_or_404(Stage, pk=stage_id, championship__organizer__user=request.user)

    apps = Application.objects.filter(stage=stage).exclude(
        status__in=['cancelled', 'draft']
    ).select_related('race_class', 'pilot', 'pilot__driver', 'payment').prefetch_related('selected_options')

    # Считаем итог по каждой заявке
    rows = []
    total_expected = 0
    total_confirmed = 0
    total_pending = 0
    total_rejected_amount = 0

    for app in apps:
        options_total = sum(o.price_at_time for o in app.selected_options.all())
        app_total = app.entry_fee_amount + options_total

        try:
            pay = app.payment
            pay_status = pay.status
            pay_amount = pay.amount
        except Exception:
            pay = None
            pay_status = 'pending'
            pay_amount = app_total

        rows.append({
            'app': app,
            'options_total': options_total,
            'app_total': app_total,
            'pay': pay,
            'pay_status': pay_status,
            'pay_amount': pay_amount,
        })

        total_expected += app_total
        if pay_status == 'verified':
            total_confirmed += pay_amount
        elif pay_status in ('pending', 'uploaded'):
            total_pending += app_total
        elif pay_status == 'rejected':
            total_rejected_amount += app_total

    # Сводка по классам
    by_class = {}
    for row in rows:
        cls = row['app'].race_class.name if row['app'].race_class else 'Без класса'
        if cls not in by_class:
            by_class[cls] = {'count': 0, 'expected': 0, 'confirmed': 0}
        by_class[cls]['count'] += 1
        by_class[cls]['expected'] += row['app_total']
        if row['pay_status'] == 'verified':
            by_class[cls]['confirmed'] += row['pay_amount']

    return render(request, 'organizers/stage_finance.html', {
        'stage': stage,
        'rows': rows,
        'by_class': by_class,
        'total_expected': total_expected,
        'total_confirmed': total_confirmed,
        'total_pending': total_pending,
        'total_rejected_amount': total_rejected_amount,
        'total_apps': len(rows),
    })


@login_required
def championship_toggle_publish(request, pk):
    championship = get_object_or_404(Championship, pk=pk, organizer__user=request.user)
    championship.is_published = not championship.is_published
    championship.save()
    return redirect('organizers:dashboard')


@login_required
def stage_toggle_publish(request, pk):
    stage = get_object_or_404(Stage, pk=pk, championship__organizer__user=request.user)
    stage.is_published = not stage.is_published
    stage.save()

    # Авто-каскад: обновляем статус чемпионата
    championship = stage.championship
    all_stages = championship.stages.all()
    total = all_stages.count()
    published_count = all_stages.filter(is_published=True).count()

    if total == 1:
        # Единственный этап — чемпионат повторяет его статус
        championship.is_published = stage.is_published
        championship.save()
    elif published_count == 0:
        # Все этапы — черновики → чемпионат тоже черновик
        championship.is_published = False
        championship.save()
    elif not championship.is_published and published_count > 0:
        # Есть опубликованные этапы → авто-публикуем чемпионат
        championship.is_published = True
        championship.save()

    return redirect('organizers:dashboard')


@login_required
def championship_set_color(request, pk):
    if request.method == 'POST':
        import re
        championship = get_object_or_404(Championship, pk=pk, organizer__user=request.user)
        color = request.POST.get('color', '#ffc107')
        if re.match(r'^#[0-9a-fA-F]{6}$', color):
            championship.color = color
            championship.save()
    return redirect('organizers:dashboard')
