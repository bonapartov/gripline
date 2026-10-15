"""Мастер подачи заявки на этап: ① участие и класс → ② пилот → ③ карт, механик, заявитель →
④ опции → ⑤ проверка и отправка.

Черновик (Application в статусе draft) привязан к учётной записи и сохраняется после
каждого шага — к нему можно вернуться. Гость проходит шаг ① без входа (данные в сессии),
на шаге ② оставляет email: создаётся учётная запись без известного ему пароля (задаёт
через «Забыли пароль?»), занятый email — просим войти. Заявки на профиль пилота и на
новую команду (DriverClaim/TeamClaim → уведомление админу в Telegram и письма) создаются
только при отправке на шаге ⑤, чтобы брошенные черновики не засыпали модерацию.
"""
import os
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from wagtailcache.cache import nocache_page

from organizers.models import Stage
from website.services.balance_limits import ratelimit_post

from .forms import prefill_from_profile, save_to_profile
from .models import (
    Application, ApplicationApplicant, ApplicationDocument, ApplicationOption, ApplicationPayment,
)
from .wizard_forms import (
    StepApplicantForm, StepKartForm, StepMechanicForm, StepParticipationForm, StepPilotForm,
)

STEPS = [(1, 'Участие и класс'), (2, 'Пилот'), (3, 'Карт и заявитель'), (4, 'Опции'), (5, 'Проверка')]
LAST_STEP = len(STEPS)
SESSION_KEY = 'apply_wizard_{}'


def _related(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _step_url(stage, step, application=None):
    url = reverse('applications:wizard_step', args=[stage.id, step])
    return f'{url}?app={application.id}' if application and application.submitted_by_type == 'organizer' else url


def _is_organizer(user):
    profile = getattr(user, 'organizer_profile', None)
    return profile is not None and profile.status == 'active'


def _confirmed_driver(user):
    """Подтверждённый пилот пользователя (одобренная заявка на профиль) или None."""
    if not user.is_authenticated:
        return None
    from accounts.models import DriverClaim
    claim = (DriverClaim.objects.filter(user=user, status='approved', driver__isnull=False)
             .select_related('driver').first())
    return claim.driver if claim else None


def _find_draft(request, stage):
    """Черновик текущего пользователя на этап. Организатор подаёт за разных пилотов —
    его черновики различаются по ?app=<id> (без него — новый)."""
    if not request.user.is_authenticated:
        return None
    drafts = Application.objects.filter(stage=stage, submitted_by=request.user, status='draft')
    if _is_organizer(request.user):
        app_id = request.GET.get('app') or request.POST.get('app')
        return drafts.filter(pk=app_id).first() if str(app_id or '').isdigit() else None
    return drafts.order_by('-updated_at').first()


def _create_account(email, first_name, last_name):
    """Учётная запись по email из мастера. Пароль случайный (Django не шлёт письмо сброса
    пользователю без пароля) — человек задаёт свой через «Забыли пароль?», и сброс
    подтверждает email (accounts.views.VerifyingPasswordResetConfirmView)."""
    from accounts.verification import mark_unverified
    user = User(username=email, email=email, first_name=first_name, last_name=last_name, is_active=True)
    user.set_password(secrets.token_urlsafe(32))
    user.save()
    mark_unverified(user)
    return user


def _draft_from_session(request, stage):
    data = request.session.get(SESSION_KEY.format(stage.id)) or {}
    return data if data.get('race_class') else None


def _save_participation(stage, application, data, user, submitted_by_type):
    """Шаг ①: создаёт черновик или обновляет участие, класс, номер и взнос."""
    if application is None:
        application = Application(stage=stage, submitted_by=user, submitted_by_type=submitted_by_type,
                                  status='draft')
    application.participation = data['participation']
    application.race_class = data['race_class']
    application.start_number = data.get('start_number')
    application.entry_fee_amount = stage.fee_for(data['participation'])
    application.wizard_step = max(application.wizard_step, 1)
    application.save()
    return application


def _submitted_by_type(user):
    return 'organizer' if user.is_authenticated and _is_organizer(user) else 'pilot'


@nocache_page
@ratelimit_post('apply_wizard', limit=60, window_seconds=3600)
def wizard_step(request, stage_id, step):
    stage = get_object_or_404(Stage, pk=stage_id)
    closed = stage.registration_closed_reason()
    if closed:
        messages.error(request, closed)
        return redirect((stage.wagtail_page and stage.wagtail_page.url) or '/')
    if step < 1 or step > LAST_STEP:
        return redirect('applications:apply', stage_id=stage.id)

    application = _find_draft(request, stage)
    done = application.wizard_step if application else (1 if _draft_from_session(request, stage) else 0)
    if step > done + 1:
        return redirect(_step_url(stage, done + 1, application))
    if step > 2 and application is None:
        return redirect(_step_url(stage, 2))

    handler = {1: _step_participation, 2: _step_pilot, 3: _step_kart_applicant, 4: _step_options,
               5: _step_review}[step]
    return handler(request, stage, application)


@nocache_page
def wizard_start(request, stage_id):
    """Вход в мастер: продолжить черновик с первого незавершённого шага."""
    stage = get_object_or_404(Stage, pk=stage_id)
    closed = stage.registration_closed_reason()
    if closed:
        messages.error(request, closed)
        return redirect((stage.wagtail_page and stage.wagtail_page.url) or '/')
    application = _find_draft(request, stage)
    if application:
        return redirect(_step_url(stage, min(application.wizard_step + 1, LAST_STEP), application))
    return redirect(_step_url(stage, 1))


def _render(request, stage, application, step, context):
    context.update({
        'stage': stage, 'application': application, 'step': step, 'steps': STEPS,
        'done': application.wizard_step if application else 0,
        'app_query': f'?app={application.id}' if application and application.submitted_by_type == 'organizer' else '',
    })
    return render(request, 'applications/wizard.html', context)


# ── ① участие и класс ────────────────────────────────────────────────────────

def _step_participation(request, stage, application):
    initial = {}
    if application:
        initial = {'participation': application.participation, 'race_class': application.race_class_id,
                   'start_number': application.start_number}
        if (request.method == 'GET' and application.start_number and not application.is_number_reserved()
                and application.start_number not in stage.get_available_numbers(
                    race_class=application.race_class, participation=application.participation)):
            messages.warning(request, f'Номер {application.start_number} заняли, пока черновик ждал '
                                      'больше 12 часов. Выберите другой.')
            initial['start_number'] = None
    elif not request.user.is_authenticated:
        initial = _draft_from_session(request, stage) or {}

    form = StepParticipationForm(request.POST or None, stage=stage, application=application, initial=initial)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        from .views import _duplicate_application
        if request.user.is_authenticated:
            duplicate = _duplicate_application(stage, request.user, _submitted_by_type(request.user), data['race_class'].id)
            if duplicate and duplicate != application and duplicate.status != 'draft':
                messages.warning(request, 'Вы уже подали заявку на этот этап в этом классе.')
                return redirect('applications:detail', application_id=duplicate.id)
            application = _save_participation(stage, application, data, request.user,
                                              _submitted_by_type(request.user))
        else:
            request.session[SESSION_KEY.format(stage.id)] = {
                'participation': data['participation'], 'race_class': data['race_class'].id,
                'start_number': data.get('start_number'),
            }
        return redirect(_step_url(stage, 2, application))

    race_class = form['race_class'].value() or (stage.championship.race_classes.values_list('id', flat=True).first())
    participation = form['participation'].value() or stage.participation_choices()[0][0]
    from website.models import RaceClass
    numbers = stage.get_available_numbers(race_class=RaceClass.objects.filter(pk=race_class).first(),
                                          participation=participation) if race_class else []
    # Свой номер черновик держит только DRAFT_HOLD; брошенный — наравне со всеми, если свободен.
    own = application.start_number if application and application.is_number_reserved() else None
    if own and own not in numbers:
        numbers = sorted([*numbers, own])
    return _render(request, stage, application, 1, {
        'form': form, 'numbers': numbers,
        'fees': {code: stage.fee_for(code) for code, _ in stage.participation_choices()},
    })


# ── ② пилот ──────────────────────────────────────────────────────────────────

def _pilot_candidates(user, first_name, last_name):
    from website.models import Driver
    if not first_name or not last_name or _confirmed_driver(user):
        return Driver.objects.none()
    return Driver.objects.filter(first_name__iexact=first_name.strip(), last_name__iexact=last_name.strip())


def _step_pilot(request, stage, application):
    user = request.user
    is_guest = not user.is_authenticated
    organizer = not is_guest and _is_organizer(user)
    confirmed = None if (is_guest or organizer) else _confirmed_driver(user)
    pilot = _related(application, 'pilot') if application else None

    if pilot is not None:
        initial = {}
    elif organizer or is_guest:
        initial = {'citizenship': 'Россия', 'country': 'Россия'}
    else:
        initial = prefill_from_profile(user)['pilot']

    data = request.POST if request.method == 'POST' else None
    names = (data.get('last_name', ''), data.get('first_name', '')) if data else (None, None)
    # Пилот выбран в подсказке (или «нет в списке») — переспрашивать «это вы?» не нужно.
    picked = bool(data and (data.get('driver_pick') or '').strip())
    candidates = _pilot_candidates(user, names[1], names[0]) if (data and not organizer and not picked) else []
    if pilot is not None and not data:
        initial = {**initial, 'driver_pick': str(pilot.requested_driver_id or pilot.driver_id or '')}
    form = StepPilotForm(data, instance=pilot, initial=initial, need_email=is_guest,
                         candidates=candidates, lock_names=bool(confirmed))
    if pilot is not None and pilot.requested_driver_id and not data:
        form.fields.pop('driver_choice', None)

    if data and form.is_valid():
        with transaction.atomic():
            if application is None:
                # Шаг ① пройден без входа (данные в сессии): гостю создаём учётную запись,
                # вошедшему посреди мастера (email был занят) — просто черновик.
                session_data = _draft_from_session(request, stage)
                if not session_data:
                    return redirect(_step_url(stage, 1))
                if is_guest:
                    user = _create_account(form.cleaned_data['email_account'], form.cleaned_data['first_name'],
                                           form.cleaned_data['last_name'])
                    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                from website.models import RaceClass
                session_data = {**session_data, 'race_class': RaceClass.objects.get(pk=session_data['race_class'])}
                application = _save_participation(stage, None, session_data, user, _submitted_by_type(user))
                request.session.pop(SESSION_KEY.format(stage.id), None)
            pilot = form.save(commit=False)
            pilot.application = application
            if confirmed:
                pilot.driver = confirmed
            elif organizer:
                # Организатор подаёт за пилота из базы — привязываем сразу.
                pilot.driver = form.chosen_driver() or pilot.driver
            elif form.cleaned_data.get('driver_pick') or 'driver_choice' in form.fields:
                pilot.requested_driver = form.chosen_driver()
            if not pilot.email:
                pilot.email = user.email if not organizer else ''
            pilot.save()
            application.wizard_step = max(application.wizard_step, 2)
            application.save(update_fields=['wizard_step', 'updated_at'])
        return redirect(_step_url(stage, 3, application))

    taken_email = is_guest and data is not None and any(
        e.code == 'email_taken' for e in form.errors.as_data().get('email_account', []))
    return _render(request, stage, application, 2, {
        'form': form, 'is_guest': is_guest, 'confirmed_driver': confirmed, 'taken_email': taken_email,
        'pilot_fields': ['last_name', 'first_name', 'middle_name', 'birth_date', 'citizenship', 'sport_rank',
                         'license_number', 'email', 'phone', 'city', 'country'],
        'login_url': f"{reverse('accounts:login')}?next={_step_url(stage, 2)}",
    })


# ── ③ карт, механик, заявитель ───────────────────────────────────────────────

def _last_application(user, exclude):
    return (Application.objects.filter(submitted_by=user).exclude(pk=exclude.pk)
            .exclude(status='draft').order_by('-created_at').first())


def _step_kart_applicant(request, stage, application):
    kart, mechanic, applicant = (_related(application, n) for n in ('kart', 'mechanic', 'applicant'))
    kart_initial, mech_initial, app_initial = {}, {}, StepApplicantForm.initial_from(applicant)
    if kart is None and application.submitted_by_type != 'organizer':
        kart_initial = prefill_from_profile(request.user)['kart']
        last = _last_application(request.user, application)
        last_mech = _related(last, 'mechanic') if last else None
        if last_mech:
            mech_initial = {f: getattr(last_mech, f) for f in
                            ('last_name', 'first_name', 'middle_name', 'license_number', 'phone', 'email')}
    if applicant is None:
        pilot = _related(application, 'pilot')
        app_initial = {'type': 'individual', 'name': pilot.full_name if pilot else ''}
    # Шины задаёт организатор: на весь чемпионат или на каждый этап отдельно.
    from organizers.models import Championship
    tyre_source = (stage.stage_tyres if stage.championship.tyre_mode == Championship.TYRE_MODE_PER_STAGE
                   else stage.championship.default_tyres)
    tyres = list(tyre_source.select_related('brand', 'type'))
    if tyres:
        kart_initial['tires'] = ', '.join(str(t) for t in tyres)

    data = request.POST if request.method == 'POST' else None
    kart_form = StepKartForm(data, instance=kart, initial=kart_initial, prefix='kart')
    mech_form = StepMechanicForm(data, instance=mechanic, initial=mech_initial, prefix='mechanic')
    applicant_form = StepApplicantForm(data, initial=app_initial, prefix='applicant')

    if data and all([kart_form.is_valid(), mech_form.is_valid(), applicant_form.is_valid()]):
        with transaction.atomic():
            k = kart_form.save(commit=False)
            k.application = application
            k.save()
            if mech_form.cleaned_data.get('last_name'):
                m = mech_form.save(commit=False)
                m.application = application
                m.save()
            elif mechanic is not None:
                mechanic.delete()
            applicant_form.save_to(applicant or ApplicationApplicant(application=application))
            application.wizard_step = max(application.wizard_step, 3)
            application.save(update_fields=['wizard_step', 'updated_at'])
        return redirect(_step_url(stage, 4, application))

    from website.models import Chassis
    return _render(request, stage, application, 3, {
        'kart_form': kart_form, 'mech_form': mech_form, 'applicant_form': applicant_form,
        'chassis_list': list(Chassis.objects.filter(live=True).values_list('name', flat=True).order_by('name')),
        'tyres_fixed': bool(tyres),
    })


# ── ④ опции ──────────────────────────────────────────────────────────────────

def _step_options(request, stage, application):
    options = list(stage.options.filter(is_active=True))
    selected = set(application.selected_options.values_list('option_id', flat=True))
    if request.method == 'POST':
        chosen = {o.id for o in options if o.is_mandatory or request.POST.get(f'option_{o.id}')}
        with transaction.atomic():
            application.selected_options.exclude(option_id__in=chosen).delete()
            for opt in options:
                if opt.id in chosen and opt.id not in selected:
                    ApplicationOption.objects.create(application=application, option=opt, price_at_time=opt.price)
            application.wizard_step = max(application.wizard_step, 4)
            application.save(update_fields=['wizard_step', 'updated_at'])
        return redirect(_step_url(stage, 5, application))
    return _render(request, stage, application, 4, {
        'options': [(o, o.is_mandatory or o.id in selected) for o in options],
    })


# ── ⑤ проверка и отправка ────────────────────────────────────────────────────

def _create_document_rows(application, user, is_minor):
    """Строки требуемых документов; подходящие документы из хранилища пилота — сразу загружены."""
    if application.documents.exists():
        return
    vault = {}
    profile = getattr(user, 'profile', None) if application.submitted_by_type == 'pilot' else None
    if profile is not None:
        vault = {d.name.lower(): d for d in profile.documents.all() if not d.is_expired}
    for doc in application.stage.required_documents.filter(is_active=True):
        if doc.minors_only and not is_minor:
            continue
        match = vault.get(doc.name.lower())
        row = ApplicationDocument(application=application, stage_document=doc)
        if match:
            match.file.seek(0)
            row.file.save(os.path.basename(match.file.name), ContentFile(match.file.read()), save=False)
            row.status, row.uploaded_at, row.expiry_date = 'uploaded', timezone.now(), match.expiry_date
        row.save()


def _claim_pilot(application, user):
    """Пилот без подтверждённого профиля → заявка на профиль (новый или «это я»)."""
    from accounts.models import DriverClaim
    pilot = application.pilot
    if application.submitted_by_type != 'pilot' or pilot.driver_id:
        return
    claim = DriverClaim.objects.filter(user=user, status__in=['pending', 'approved']).order_by('-created_at').first()
    if claim is None:
        claim = DriverClaim.objects.create(
            user=user, driver=pilot.requested_driver,
            requested_first_name=pilot.first_name, requested_last_name=pilot.last_name,
            requested_city=pilot.city, status='pending')
    pilot.driver_claim = claim
    if claim.status == 'approved' and claim.driver_id:
        pilot.driver_id = claim.driver_id
    pilot.save(update_fields=['driver_claim', 'driver'])


def _claim_team(application, user):
    """Команда вписана вручную → заявка на новую команду от контакта (после одобрения — менеджер)."""
    from teams.models import TeamClaim
    applicant = _related(application, 'applicant')
    if applicant is None or applicant.type != 'team' or applicant.team_id or not applicant.new_team_email:
        return
    email = applicant.new_team_email.strip()
    contact = user if user.email.lower() == email.lower() else User.objects.filter(email__iexact=email).first()
    if contact is None:
        contact = _create_account(email, applicant.rep_first_name, applicant.rep_last_name)
    claim = TeamClaim.objects.filter(user=contact, requested_team_name__iexact=applicant.name,
                                     status='pending').first()
    if claim is None:
        claim = TeamClaim.objects.create(user=contact, requested_team_name=applicant.name,
                                         requested_city=applicant.new_team_city, status='pending')
    applicant.team_claim = claim
    applicant.save(update_fields=['team_claim'])


def _notify_participant_submitted(application):
    from website.mail import send_templated_mail
    from .views import _app_link
    try:
        stage, user = application.stage, application.submitted_by
        reset = f"{getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')}{reverse('password_reset')}"
        subject = f'Заявка #{application.id} отправлена — {stage.title}'
        send_templated_mail('application_update', subject, [user.email], {
            'subject': subject,
            'preheader': f'Заявка на {stage.title} отправлена организатору. Документы можно догрузить на странице заявки.',
            'status': 'wait', 'status_label': 'Отправлена', 'status_text': 'Отправлена',
            'title': 'Заявка отправлена организатору',
            'lead': ('Организатор рассмотрит заявку и сообщит решение. Документы и квитанцию можно '
                     f'догрузить на странице заявки. Если вы ещё не задали пароль — задайте его здесь: {reset}'),
            'pilot_name': user.get_full_name() or user.email,
            'rows': [('Заявка', f'№{application.id}'), ('Этап', stage.title),
                     ('Чемпионат', stage.championship.title)],
            'comment': '', 'comment_label': '', 'button': 'Открыть заявку', 'link': _app_link(application),
        }, fail_silently=True)
    except Exception:
        pass


def _step_review(request, stage, application):
    if request.method == 'POST':
        if application.wizard_step < LAST_STEP - 1:
            return redirect(_step_url(stage, application.wizard_step + 1, application))
        from .views import _duplicate_application, _notify_organizer_submitted
        duplicate = _duplicate_application(stage, request.user, application.submitted_by_type,
                                           application.race_class_id)
        if duplicate and duplicate != application and duplicate.status != 'draft':
            messages.warning(request, 'Вы уже подали заявку на этот этап в этом классе.')
            return redirect('applications:detail', application_id=duplicate.id)
        if application.start_number and stage.active_applications().filter(
                race_class=application.race_class, start_number=application.start_number,
        ).exclude(pk=application.pk).exists():
            messages.error(request, 'Пока вы заполняли заявку, номер заняли. Выберите другой.')
            return redirect(_step_url(stage, 1, application))
        with transaction.atomic():
            pilot = application.pilot
            _create_document_rows(application, request.user, pilot.is_minor)
            ApplicationPayment.objects.update_or_create(
                application=application,
                defaults={'amount': application.get_total_amount(), 'method': 'manual'})
            _claim_pilot(application, request.user)
            _claim_team(application, request.user)
            application.status = 'submitted'
            application.submitted_at = timezone.now()
            application.wizard_step = LAST_STEP
            application.save()
            if application.submitted_by_type == 'pilot':
                save_to_profile(request.user, {f: getattr(pilot, f) for f in (
                    'middle_name', 'birth_date', 'citizenship', 'phone', 'license_number', 'sport_rank',
                    'parent_last_name', 'parent_first_name', 'parent_middle_name', 'parent_relation',
                    'parent_phone', 'parent_email', 'city')})
        _notify_organizer_submitted(application)
        _notify_participant_submitted(application)
        messages.success(request, 'Заявка отправлена организатору. Документы и квитанцию можно догрузить ниже.')
        return redirect('applications:detail', application_id=application.id)

    return _render(request, stage, application, 5, {
        'pilot': _related(application, 'pilot'), 'kart': _related(application, 'kart'),
        'mechanic': _related(application, 'mechanic'), 'applicant': _related(application, 'applicant'),
        'selected_options': application.selected_options.select_related('option'),
        'total': application.get_total_amount(),
        'documents_required': [d for d in stage.required_documents.filter(is_active=True)],
    })
