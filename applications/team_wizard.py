"""Заявка команды на этап: менеджер заявляет несколько пилотов (разные классы) одним пакетом.

① Состав — пилоты команды галочками, у каждого класс, участие и номер; можно добавить пилота
  не из состава (из базы или нового) — только в эту заявку, в команду он не записывается.
② Пилоты — карточка на каждого: личные данные, родитель несовершеннолетнего, карт, механик.
③ Проверка и отправка — всех готовых сразу; остальных можно дозаполнить и отправить позже.

Пакет — TeamStageEntry (одна на команду и этап), каждый пилот — Application(submitted_by_type=
'team', status='draft'); черновик держит номер DRAFT_HOLD, как у одиночной заявки. Отправка —
та же finalize_submission, что в мастере пилота (applications/wizard.py).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from wagtailcache.cache import nocache_page

from organizers.models import Stage
from website.services.balance_limits import ratelimit_post

from .models import Application, ApplicationApplicant, ApplicationOption, ApplicationPilot, TeamStageEntry
from .wizard import _related, finalize_submission
from .wizard_forms import StepKartForm, StepMechanicForm, StepPilotForm

STEPS = [(1, 'Состав'), (2, 'Пилоты'), (3, 'Проверка')]
PILOT_FIELDS = ['last_name', 'first_name', 'middle_name', 'birth_date', 'citizenship', 'sport_rank',
                'license_number', 'email', 'phone', 'city', 'country']
# Личные данные пилота, которые подставляются из прошлых заявок этой же команды.
CARRY_PILOT_FIELDS = ['middle_name', 'birth_date', 'citizenship', 'sport_rank', 'license_number', 'email',
                      'phone', 'city', 'country', 'parent_last_name', 'parent_first_name', 'parent_middle_name',
                      'parent_relation', 'parent_phone', 'parent_email']
KART_FIELDS = ['chassis_brand', 'engine_1', 'engine_2', 'tires', 'transponder_number', 'ad_consent']
MECH_FIELDS = ['last_name', 'first_name', 'middle_name', 'license_number', 'phone', 'email']
READY_STEP = 2   # wizard_step черновика: 1 — класс выбран, 2 — данные пилота и карт заполнены


# ── права и общее ────────────────────────────────────────────────────────────

def manager_teams(user):
    from website.models import Team
    return Team.objects.filter(managers__user=user, managers__is_active=True).distinct().order_by('name')


def _entry_or_redirect(request, entry_id):
    """Пакет, если пользователь — действующий менеджер его команды, иначе None."""
    entry = get_object_or_404(TeamStageEntry.objects.select_related('stage__championship', 'team'), pk=entry_id)
    if not manager_teams(request.user).filter(pk=entry.team_id).exists():
        messages.error(request, 'У вас нет прав менеджера этой команды.')
        return None
    return entry


def closed_reason(stage):
    """Причина, по которой команде нельзя подавать: регистрация выключена или срок истёк.
    Лимит мест проверяется отдельно — свои же черновики его уже занимают."""
    if not stage.registration_enabled:
        return 'Регистрация на этот этап закрыта.'
    if (stage.registration_deadline and timezone.now() > stage.registration_deadline
            and not stage.late_registration_allowed):
        return 'Срок регистрации истёк.'
    return None


def _render(request, entry, step, context):
    context.update({'entry': entry, 'stage': entry.stage, 'team': entry.team, 'step': step, 'steps': STEPS})
    return render(request, 'applications/team_wizard.html', context)


def is_ready(application):
    return application.wizard_step >= READY_STEP and _related(application, 'kart') is not None


def _stage_classes(stage):
    return list(stage.championship.race_classes.all())


def _previous_team_pilot(team, driver, exclude_entry=None):
    """Последний «Пилот в заявке» этого пилота, поданный этой же командой: из него
    подставляются личные данные (свои же данные команды, без доступа к профилю пилота)."""
    if driver is None:
        return None
    qs = (ApplicationPilot.objects.filter(driver=driver, application__team_entry__team=team)
          .exclude(application__status='draft'))
    if exclude_entry is not None:
        qs = qs.exclude(application__team_entry=exclude_entry)
    return qs.order_by('-application__created_at').first()


def _default_class(stage, team, driver, classes):
    """Класс по умолчанию: из состава команды, иначе класс последней заявки пилота."""
    ids = {c.id for c in classes}
    from website.models import TeamMembership
    m = TeamMembership.objects.filter(team=team, driver=driver, is_active=True).first()
    if m and m.race_class_id in ids:
        return m.race_class_id
    last = (Application.objects.filter(pilot__driver=driver, race_class__in=classes)
            .exclude(status__in=('draft', 'cancelled')).order_by('-created_at').first())
    return last.race_class_id if last else None


def _default_number(stage, driver):
    """Прошлый стартовый номер пилота в этом чемпионате (стартовые листы публичны)."""
    last = (Application.objects.filter(pilot__driver=driver, stage__championship=stage.championship,
                                       start_number__isnull=False)
            .exclude(status__in=('draft', 'cancelled', 'rejected')).order_by('-created_at').first())
    return last.start_number if last else None


# ── вход ─────────────────────────────────────────────────────────────────────

@login_required
@nocache_page
def start(request, stage_id):
    """Кнопка «Зарегистрировать от команды»: выбор команды (если их несколько) → пакет."""
    stage = get_object_or_404(Stage, pk=stage_id)
    teams = list(manager_teams(request.user))
    if not teams:
        messages.error(request, 'У вас нет прав менеджера команды.')
        return redirect('/')
    reason = closed_reason(stage)
    if reason:
        messages.error(request, reason)
        return redirect('teams:dashboard')
    team_id = request.GET.get('team') or request.POST.get('team')
    team = next((t for t in teams if str(t.id) == str(team_id)), None)
    if team is None and len(teams) == 1:
        team = teams[0]
    if team is None:
        return render(request, 'applications/team_wizard.html', {
            'stage': stage, 'teams': teams, 'step': 0, 'steps': STEPS})
    user = request.user
    entry, _ = TeamStageEntry.objects.get_or_create(stage=stage, team=team, defaults={
        'created_by': user, 'rep_last_name': user.last_name, 'rep_first_name': user.first_name,
        'rep_email': user.email})
    return redirect('teams:team_entry', entry_id=entry.id)


# ── ① состав ─────────────────────────────────────────────────────────────────

class _Row:
    """Строка таблицы состава: пилот команды или добавленный в эту заявку."""

    def __init__(self, key, name, driver=None, application=None, in_roster=True):
        self.key, self.name, self.driver, self.application, self.in_roster = key, name, driver, application, in_roster
        self.picked = application is not None
        self.class_id = application.race_class_id if application else None
        self.participation = application.participation if application else Application.PARTICIPATION_RACE
        self.number = application.start_number if application else None
        self.locked = application is not None and application.status != 'draft'
        self.errors = []


def _rows(entry):
    from website.models import TeamMembership
    apps = list(entry.applications.exclude(status='cancelled').select_related('pilot', 'race_class')
                .order_by('created_at'))
    by_driver = {a.pilot.driver_id: a for a in apps if _related(a, 'pilot') and a.pilot.driver_id}
    classes = _stage_classes(entry.stage)
    rows, seen = [], set()
    members = (TeamMembership.objects.filter(team=entry.team, is_active=True).select_related('driver')
               .order_by('driver__last_name', 'driver__first_name'))
    for m in members:
        if m.driver_id in seen:
            continue
        seen.add(m.driver_id)
        app = by_driver.get(m.driver_id)
        row = _Row(f'd{m.driver_id}', m.driver.full_name, driver=m.driver, application=app)
        if app is None:
            row.class_id = _default_class(entry.stage, entry.team, m.driver, classes)
            row.number = _default_number(entry.stage, m.driver)
        rows.append(row)
    for app in apps:
        pilot = _related(app, 'pilot')
        if pilot and pilot.driver_id in seen:
            continue
        rows.append(_Row(f'a{app.id}', pilot.full_name if pilot else f'Заявка №{app.id}',
                         driver=pilot.driver if pilot else None, application=app, in_roster=False))
    return rows


def _own_number(app, class_id):
    if app is None or app.race_class_id != class_id or not app.is_number_reserved():
        return None
    return app.start_number


def _validate_rows(entry, rows, data):
    """Разбирает POST таблицы состава. Возвращает выбранные строки (с ошибками в row.errors)."""
    stage = entry.stage
    classes = {c.id: c for c in _stage_classes(stage)}
    allowed = {c[0] for c in stage.participation_choices()}
    picked, used = [], set()
    for row in rows:
        if row.locked:
            continue
        row.picked = bool(data.get(f'pick_{row.key}'))
        raw_class, raw_number = data.get(f'class_{row.key}', ''), (data.get(f'num_{row.key}') or '').strip()
        row.class_id = int(raw_class) if raw_class.isdigit() else None
        part = data.get(f'part_{row.key}')
        row.participation = part if part in allowed else Application.PARTICIPATION_RACE
        row.number = int(raw_number) if raw_number.isdigit() else None
        if not row.picked:
            continue
        picked.append(row)
        if row.class_id not in classes:
            row.errors.append('Выберите класс.')
            continue
        if row.driver is not None and Application.objects.filter(
                stage=stage, race_class_id=row.class_id, pilot__driver=row.driver,
        ).exclude(status__in=('rejected', 'cancelled')).exclude(team_entry=entry).exists():
            row.errors.append('Пилот уже заявлен на этот этап в этом классе.')
        if row.number is None:
            continue
        separate = stage.separate_training_numbers() and row.participation == Application.PARTICIPATION_TRAINING
        slot = (row.class_id, separate, row.number)
        if slot in used:
            row.errors.append(f'Номер {row.number} уже выбран для другого пилота в этом классе.')
            continue
        used.add(slot)
        free = stage.get_available_numbers(race_class=classes[row.class_id], participation=row.participation)
        if row.number not in free and row.number != _own_number(row.application, row.class_id):
            row.errors.append(f'Номер {row.number} занят. Выберите другой.')
    return picked


def _capacity_error(entry, picked):
    stage = entry.stage
    if not stage.max_participants:
        return None
    holding = set(stage.race_applications().values_list('id', flat=True))
    new = sum(1 for r in picked if r.participation != Application.PARTICIPATION_TRAINING
              and not (r.application and r.application.id in holding))
    free = stage.max_participants - len(holding)
    if new > free:
        return f'Мест осталось {max(free, 0)}, а новых пилотов в заявке {new}. Уберите лишних.'
    return None


def _save_row(entry, row, user):
    stage = entry.stage
    app = row.application or Application(stage=stage, submitted_by=user, submitted_by_type='team',
                                         team_entry=entry, status='draft')
    app.participation = row.participation
    app.race_class_id = row.class_id
    app.start_number = row.number
    app.entry_fee_amount = stage.fee_for(row.participation)
    app.wizard_step = max(app.wizard_step, 1)
    app.save()
    if _related(app, 'pilot') is None:
        driver = row.driver
        prev = _previous_team_pilot(entry.team, driver, exclude_entry=entry)
        pilot = ApplicationPilot(application=app, driver=driver,
                                 first_name=driver.first_name, last_name=driver.last_name,
                                 city=driver.city or '')
        if prev is not None:
            for f in CARRY_PILOT_FIELDS:
                setattr(pilot, f, getattr(prev, f))
        pilot.save()
    if _related(app, 'applicant') is None:
        ApplicationApplicant.objects.create(application=app, type='team', team=entry.team, name=entry.team.name)
    return app


@login_required
@nocache_page
@ratelimit_post('team_apply', limit=120, window_seconds=3600)
def roster(request, entry_id):
    entry = _entry_or_redirect(request, entry_id)
    if entry is None:
        return redirect('/')
    stage = entry.stage
    reason = closed_reason(stage)
    rows = _rows(entry)

    if request.method == 'POST':
        if reason:
            messages.error(request, reason)
            return redirect('teams:team_entry', entry_id=entry.id)
        for f in ('rep_last_name', 'rep_first_name', 'rep_phone', 'rep_email'):
            setattr(entry, f, (request.POST.get(f) or '').strip()[:100])
        picked = _validate_rows(entry, rows, request.POST)
        capacity = _capacity_error(entry, picked)
        has_errors = any(r.errors for r in rows) or capacity
        if not picked:
            messages.error(request, 'Отметьте хотя бы одного пилота.')
        elif capacity:
            messages.error(request, capacity)
        if picked and not has_errors:
            with transaction.atomic():
                entry.save()
                for row in rows:
                    if row.locked:
                        continue
                    if row.picked:
                        _save_row(entry, row, request.user)
                    elif row.application is not None:
                        row.application.delete()
            return redirect('teams:team_entry_pilots', entry_id=entry.id)

    return _render(request, entry, 1, {
        'rows': rows, 'classes': _stage_classes(stage), 'closed_reason': reason,
        'participation_choices': stage.participation_choices(),
        'fees': {code: stage.fee_for(code) for code, _ in stage.participation_choices()},
    })


@login_required
@nocache_page
@ratelimit_post('team_apply_add', limit=60, window_seconds=3600)
def add_pilot(request, entry_id):
    """Пилот не из состава — только в эту заявку: из базы (по id) или новый (по ФИО).
    В команду не записывается: состав меняется только приглашением, с согласием пилота."""
    entry = _entry_or_redirect(request, entry_id)
    if entry is None:
        return redirect('/')
    if request.method != 'POST' or closed_reason(entry.stage):
        return redirect('teams:team_entry', entry_id=entry.id)
    from website.models import Driver
    from website.services.demo import without_demo
    driver_id = (request.POST.get('driver_id') or '').strip()
    first, last = (request.POST.get('first_name') or '').strip(), (request.POST.get('last_name') or '').strip()
    driver = None
    if driver_id.isdigit():
        driver = without_demo(Driver.objects.filter(pk=driver_id, live=True)).first()
        if driver is None:
            messages.error(request, 'Пилот не найден.')
            return redirect('teams:team_entry', entry_id=entry.id)
        if entry.applications.filter(pilot__driver=driver).exclude(status='cancelled').exists():
            messages.warning(request, f'{driver.full_name} уже в этой заявке.')
            return redirect('teams:team_entry', entry_id=entry.id)
        first, last = driver.first_name, driver.last_name
    elif not (first and last):
        messages.error(request, 'Укажите фамилию и имя пилота.')
        return redirect('teams:team_entry', entry_id=entry.id)
    classes = _stage_classes(entry.stage)
    with transaction.atomic():
        app = Application.objects.create(
            stage=entry.stage, submitted_by=request.user, submitted_by_type='team', team_entry=entry,
            status='draft', race_class_id=_default_class(entry.stage, entry.team, driver, classes) if driver else None,
            entry_fee_amount=entry.stage.fee_for(Application.PARTICIPATION_RACE))
        pilot = ApplicationPilot(application=app, driver=driver, first_name=first[:100], last_name=last[:100],
                                 city=(driver.city or '') if driver else '')
        prev = _previous_team_pilot(entry.team, driver)
        if prev is not None:
            for f in CARRY_PILOT_FIELDS:
                setattr(pilot, f, getattr(prev, f))
        pilot.save()
        ApplicationApplicant.objects.create(application=app, type='team', team=entry.team, name=entry.team.name)
    messages.success(request, f'{last} {first} добавлен в заявку — выберите класс и номер.')
    return redirect('teams:team_entry', entry_id=entry.id)


# ── ② пилоты ─────────────────────────────────────────────────────────────────

def _drafts(entry):
    return (entry.applications.filter(status='draft').select_related('pilot', 'race_class')
            .order_by('race_class__sort_order', 'pilot__last_name'))


@login_required
@nocache_page
def pilots(request, entry_id):
    entry = _entry_or_redirect(request, entry_id)
    if entry is None:
        return redirect('/')
    drafts = list(_drafts(entry))
    if not drafts:
        return redirect('teams:team_entry', entry_id=entry.id)
    return _render(request, entry, 2, {
        'drafts': [(a, is_ready(a)) for a in drafts],
        'all_ready': all(is_ready(a) for a in drafts),
    })


def _sibling_initial(entry, application):
    """Карт и механик по образцу уже заполненного пилота этой заявки — у команды обычно
    одно шасси и общий механик; поля можно поправить."""
    sibling = (entry.applications.exclude(pk=application.pk).filter(kart__isnull=False)
               .select_related('kart').order_by('-updated_at').first())
    kart = {f: getattr(sibling.kart, f) for f in ('chassis_brand', 'ad_consent')} if sibling else {}
    mech = _related(sibling, 'mechanic') if sibling else None
    return kart, ({f: getattr(mech, f) for f in MECH_FIELDS} if mech else {})


@login_required
@nocache_page
@ratelimit_post('team_apply_pilot', limit=240, window_seconds=3600)
def pilot(request, entry_id, application_id):
    entry = _entry_or_redirect(request, entry_id)
    if entry is None:
        return redirect('/')
    application = get_object_or_404(Application, pk=application_id, team_entry=entry)
    if application.status != 'draft':
        return redirect('applications:detail', application_id=application.id)
    stage = entry.stage
    pilot_obj, kart, mechanic = (_related(application, n) for n in ('pilot', 'kart', 'mechanic'))

    kart_initial, mech_initial = ({}, {}) if kart else _sibling_initial(entry, application)
    from organizers.models import Championship
    tyre_source = (stage.stage_tyres if stage.championship.tyre_mode == Championship.TYRE_MODE_PER_STAGE
                   else stage.championship.default_tyres)
    tyres = list(tyre_source.select_related('brand', 'type'))
    if tyres:
        kart_initial['tires'] = ', '.join(str(t) for t in tyres)

    data = request.POST if request.method == 'POST' else None
    form = StepPilotForm(data, instance=pilot_obj, lock_names=bool(pilot_obj and pilot_obj.driver_id))
    form.fields.pop('driver_pick', None)
    kart_form = StepKartForm(data, instance=kart, initial=kart_initial, prefix='kart')
    mech_form = StepMechanicForm(data, instance=mechanic, initial=mech_initial if not mechanic else {},
                                 prefix='mechanic')

    if data and all([form.is_valid(), kart_form.is_valid(), mech_form.is_valid()]):
        with transaction.atomic():
            p = form.save(commit=False)
            p.application = application
            if pilot_obj and pilot_obj.driver_id:
                p.driver_id = pilot_obj.driver_id
            p.save()
            k = kart_form.save(commit=False)
            k.application = application
            k.save()
            if mech_form.cleaned_data.get('last_name'):
                m = mech_form.save(commit=False)
                m.application = application
                m.save()
            elif mechanic is not None:
                mechanic.delete()
            application.wizard_step = max(application.wizard_step, READY_STEP)
            application.save(update_fields=['wizard_step', 'updated_at'])
        nxt = next((a for a in _drafts(entry) if not is_ready(a)), None)
        if nxt is not None:
            messages.success(request, f'{p.full_name}: сохранено. Следующий — {nxt.pilot.full_name}.')
            return redirect('teams:team_entry_pilot', entry_id=entry.id, application_id=nxt.id)
        return redirect('teams:team_entry_review', entry_id=entry.id)

    from website.models import Chassis
    return _render(request, entry, 2, {
        'application': application, 'form': form, 'kart_form': kart_form, 'mech_form': mech_form,
        'pilot_fields': PILOT_FIELDS, 'tyres_fixed': bool(tyres),
        'chassis_list': list(Chassis.objects.filter(live=True).values_list('name', flat=True).order_by('name')),
        'drafts': [(a, is_ready(a)) for a in _drafts(entry)],
    })


# ── ③ проверка и отправка ────────────────────────────────────────────────────

def _add_mandatory_options(application):
    have = set(application.selected_options.values_list('option_id', flat=True))
    for opt in application.stage.options.filter(is_active=True, is_mandatory=True):
        if opt.id not in have:
            ApplicationOption.objects.create(application=application, option=opt, price_at_time=opt.price)


def _number_taken(application):
    return bool(application.start_number) and application.stage.active_applications().filter(
        race_class=application.race_class, start_number=application.start_number,
    ).exclude(pk=application.pk).exists()


@login_required
@nocache_page
@ratelimit_post('team_apply_submit', limit=30, window_seconds=3600)
def review(request, entry_id):
    entry = _entry_or_redirect(request, entry_id)
    if entry is None:
        return redirect('/')
    stage = entry.stage
    apps = list(entry.applications.exclude(status='cancelled').select_related('pilot', 'race_class', 'kart')
                .order_by('race_class__sort_order', 'pilot__last_name'))
    drafts = [a for a in apps if a.status == 'draft']
    ready = [a for a in drafts if is_ready(a)]

    if request.method == 'POST':
        reason = closed_reason(stage)
        if reason:
            messages.error(request, reason)
            return redirect('teams:team_entry_review', entry_id=entry.id)
        if not ready:
            messages.error(request, 'Нет пилотов, готовых к отправке: заполните данные пилота и карта.')
            return redirect('teams:team_entry_pilots', entry_id=entry.id)
        taken = [a for a in ready if _number_taken(a)]
        if taken:
            names = ', '.join(f'{a.pilot.full_name} (№{a.start_number})' for a in taken)
            messages.error(request, f'Пока заявка заполнялась, номера заняли: {names}. Выберите другие.')
            return redirect('teams:team_entry', entry_id=entry.id)
        if stage.max_participants:
            holding = set(stage.race_applications().values_list('id', flat=True))
            new = [a for a in ready if a.participation != Application.PARTICIPATION_TRAINING and a.id not in holding]
            if len(holding) + len(new) > stage.max_participants:
                messages.error(request, 'Мест на этапе не хватает на всех отмеченных пилотов: часть черновиков '
                                        'потеряла бронь (прошло больше 12 часов). Уберите лишних в «Составе».')
                return redirect('teams:team_entry', entry_id=entry.id)
        with transaction.atomic():
            for app in ready:
                applicant = app.applicant
                for f in ('rep_last_name', 'rep_first_name', 'rep_phone', 'rep_email'):
                    setattr(applicant, f, getattr(entry, f))
                applicant.save()
                _add_mandatory_options(app)
                finalize_submission(app, request.user)
            entry.status = 'submitted'
            entry.submitted_at = timezone.now()
            entry.save(update_fields=['status', 'submitted_at', 'updated_at'])
        notify_team_submitted(entry, ready, request.user)
        left = len(drafts) - len(ready)
        messages.success(request, f'Отправлено пилотов: {len(ready)}.'
                         + (f' Не отправлено (не заполнены): {left}.' if left else ''))
        return redirect('teams:team_entry_review', entry_id=entry.id)

    return _render(request, entry, 3, {
        'apps': [(a, is_ready(a)) for a in apps],
        'ready_count': len(ready), 'draft_count': len(drafts),
        'ready_total': sum(a.get_total_amount() for a in ready),
    })


def notify_team_submitted(entry, applications, user):
    """Одно письмо организатору и одно менеджеру на всю отправку, а не по письму на пилота."""
    from website.mail import send_templated_mail
    from .views import _app_link
    stage = entry.stage
    rows = [('Команда', entry.team.name), ('Этап', stage.title), ('Чемпионат', stage.championship.title)]
    rows += [(f'№{a.id}', f'{a.pilot.full_name} · {a.race_class.name if a.race_class else "—"}'
              + (f' · №{a.start_number}' if a.start_number else '')) for a in applications]
    from django.conf import settings
    from django.urls import reverse
    base = getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')
    link = (_app_link(applications[0]) if len(applications) == 1
            else f"{base}{reverse('organizers:stage_registrations', args=[stage.id])}")
    try:
        organizer = stage.championship.organizer.user
        subject = f'Заявка команды {entry.team.name}: {len(applications)} пил. — {stage.title}'
        send_templated_mail('application_update', subject, [organizer.email], {
            'subject': subject,
            'preheader': f'Команда {entry.team.name} заявила пилотов на {stage.title}. Проверьте документы и оплату.',
            'status': 'wait', 'status_label': 'Новые заявки', 'status_text': 'Новые заявки',
            'title': 'Заявка команды на этап',
            'lead': 'Команда отправила заявки пилотов. Проверьте документы и оплату и примите решение по каждой.',
            'pilot_name': organizer.get_full_name() or organizer.email,
            'rows': rows, 'comment': '', 'comment_label': '',
            'button': 'Открыть заявки', 'link': link,
        }, fail_silently=True)
    except Exception:
        pass
    try:
        subject = f'Заявка команды отправлена — {stage.title}'
        send_templated_mail('application_update', subject, [user.email], {
            'subject': subject,
            'preheader': f'Пилотов отправлено: {len(applications)}. Документы и квитанции можно догрузить.',
            'status': 'wait', 'status_label': 'Отправлена', 'status_text': 'Отправлена',
            'title': 'Заявка команды отправлена организатору',
            'lead': 'Организатор рассмотрит заявку каждого пилота. Документы и квитанции можно догрузить '
                    'на странице заявки команды.',
            'pilot_name': user.get_full_name() or user.email,
            'rows': rows, 'comment': '', 'comment_label': '', 'button': 'Открыть заявку команды',
            'link': f"{base}{reverse('teams:team_entry_review', args=[entry.id])}",
        }, fail_silently=True)
    except Exception:
        pass
