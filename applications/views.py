from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from decimal import Decimal

from organizers.models import Stage
from .models import (
    Application, ApplicationApplicant, ApplicationPilot, ApplicationKart,
    ApplicationMechanic, ApplicationOption, ApplicationDocument, ApplicationPayment,
    StageOption, StageDocument,
)
from .forms import (
    PilotForm, ApplicantForm, KartForm, MechanicForm,
    prefill_from_profile, save_to_profile,
)


def _notify(to_email, subject, body_html):
    """Отправляет email-уведомление, не падает при ошибке"""
    try:
        send_mail(
            subject, '', settings.EMAIL_HOST_USER, [to_email],
            html_message=body_html, fail_silently=True,
        )
    except Exception:
        pass


def _participant_email(application):
    return application.submitted_by.email


def _app_link(application):
    base = getattr(settings, 'BASE_URL', 'http://gripline.ru')
    return f"{base}/applications/{application.id}/"


def _stage_classes(stage):
    return stage.championship.race_classes.all()


def _effective_entry_fee(stage):
    """Учитывает поздний взнос если дедлайн прошёл"""
    fee = stage.entry_fee
    if (stage.late_registration_allowed and stage.registration_deadline
            and timezone.now() > stage.registration_deadline):
        fee = fee * stage.late_registration_fee_multiplier
    return fee


@login_required
def apply(request, stage_id):
    """Подача заявки на этап — универсальная для пилота/команды/организатора"""
    stage = get_object_or_404(Stage, pk=stage_id)

    if not stage.registration_enabled:
        messages.error(request, 'Регистрация на этот этап закрыта.')
        return redirect('/')

    # Определяем тип подающего
    submitted_by_type = 'pilot'
    if hasattr(request.user, 'organizer_profile'):
        submitted_by_type = 'organizer'

    from website.models import Team, Chassis, RaceClass
    stage_options = stage.options.filter(is_active=True)
    classes = list(_stage_classes(stage))
    entry_fee = _effective_entry_fee(stage)
    # Начальные номера для первого класса (или все если класс не выбран)
    first_class = classes[0] if classes else None
    available_numbers = stage.get_available_numbers(race_class=first_class)
    teams = list(Team.objects.values_list('name', flat=True).order_by('name'))
    chassis_list = list(Chassis.objects.values_list('name', flat=True).order_by('name'))
    default_tyre = stage.championship.default_tyre

    if request.method == 'POST':
        pilot_form = PilotForm(request.POST, prefix='pilot')
        applicant_form = ApplicantForm(request.POST, prefix='applicant')
        kart_form = KartForm(request.POST, prefix='kart')
        mechanic_form = MechanicForm(request.POST, prefix='mechanic')

        race_class_id = request.POST.get('race_class')
        start_number = request.POST.get('start_number')

        forms_valid = (pilot_form.is_valid() and applicant_form.is_valid()
                       and kart_form.is_valid() and mechanic_form.is_valid())

        # Валидация стартового номера
        number_error = None
        chosen_number = None
        if start_number:
            try:
                chosen_number = int(start_number)
                if chosen_number not in available_numbers:
                    number_error = 'Этот номер уже занят. Выберите другой.'
            except ValueError:
                number_error = 'Некорректный номер.'

        if not race_class_id:
            messages.error(request, 'Выберите класс.')
            forms_valid = False

        if number_error:
            messages.error(request, number_error)
            forms_valid = False

        if forms_valid:
            application = Application.objects.create(
                stage=stage,
                submitted_by=request.user,
                submitted_by_type=submitted_by_type,
                race_class_id=race_class_id,
                start_number=chosen_number,
                status='submitted',
                entry_fee_amount=entry_fee,
                submitted_at=timezone.now(),
            )

            pilot = pilot_form.save(commit=False)
            pilot.application = application
            profile = getattr(request.user, 'profile', None)
            if profile and profile.driver:
                pilot.driver = profile.driver
            pilot.save()

            applicant = applicant_form.save(commit=False)
            applicant.application = application
            applicant.save()

            kart = kart_form.save(commit=False)
            kart.application = application
            kart.save()

            # Механик — только если заполнена фамилия
            if mechanic_form.cleaned_data.get('last_name'):
                mechanic = mechanic_form.save(commit=False)
                mechanic.application = application
                mechanic.save()

            # Доп. опции
            for opt in stage_options:
                selected = request.POST.get(f'option_{opt.id}')
                if opt.is_mandatory or selected:
                    ApplicationOption.objects.create(
                        application=application,
                        option=opt,
                        price_at_time=opt.price,
                    )

            # Создаём строки документов
            is_minor = pilot.is_minor
            for doc in stage.required_documents.all():
                if doc.minors_only and not is_minor:
                    continue
                ApplicationDocument.objects.create(
                    application=application,
                    stage_document=doc,
                    status='pending',
                )

            # Создаём запись об оплате
            ApplicationPayment.objects.create(
                application=application,
                amount=application.get_total_amount(),
                method='manual',
                status='pending',
            )

            # Сохраняем данные обратно в профиль
            save_to_profile(request.user, pilot_form.cleaned_data)

            messages.success(request, 'Заявка подана! Теперь загрузите документы и подтверждение оплаты.')
            return redirect('applications:detail', application_id=application.id)
    else:
        initial = prefill_from_profile(request.user)
        pilot_form = PilotForm(prefix='pilot', initial=initial['pilot'])
        applicant_form = ApplicantForm(prefix='applicant')
        kart_form = KartForm(prefix='kart', initial=initial['kart'])
        mechanic_form = MechanicForm(prefix='mechanic')

    return render(request, 'applications/apply.html', {
        'stage': stage,
        'classes': classes,
        'available_numbers': available_numbers,
        'stage_options': stage_options,
        'entry_fee': entry_fee,
        'pilot_form': pilot_form,
        'applicant_form': applicant_form,
        'kart_form': kart_form,
        'mechanic_form': mechanic_form,
        'teams': teams,
        'chassis_list': chassis_list,
        'default_tyre': default_tyre,
        'first_class_id': first_class.id if first_class else '',
    })


@login_required
def detail(request, application_id):
    """Просмотр своей заявки + загрузка документов и квитанции"""
    application = get_object_or_404(Application, pk=application_id)

    is_owner = application.submitted_by == request.user
    is_organizer = (hasattr(request.user, 'organizer_profile')
                    and application.stage.championship.organizer == request.user.organizer_profile)
    if not (is_owner or is_organizer):
        messages.error(request, 'У вас нет доступа к этой заявке.')
        return redirect('/')

    return render(request, 'applications/detail.html', {
        'application': application,
        'is_owner': is_owner,
        'is_organizer': is_organizer,
        'documents': application.documents.select_related('stage_document'),
        'payment': getattr(application, 'payment', None),
    })


@login_required
def upload_document(request, document_id):
    """Загрузка файла документа участником (поддерживает AJAX)"""
    doc = get_object_or_404(ApplicationDocument, pk=document_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if doc.application.submitted_by != request.user:
        if is_ajax:
            return JsonResponse({'error': 'Нет доступа.'}, status=403)
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    if request.method == 'POST' and request.FILES.get('file'):
        doc.file = request.FILES['file']
        expiry = request.POST.get('expiry_date')
        if expiry:
            doc.expiry_date = expiry
        doc.status = 'uploaded'
        doc.uploaded_at = timezone.now()
        doc.organizer_comment = ''
        doc.save()
        if is_ajax:
            return JsonResponse({
                'success': True,
                'status': doc.status,
                'status_display': doc.get_status_display(),
                'file_url': doc.file.url,
            })
        messages.success(request, f'Документ «{doc.stage_document.name}» загружен.')
        return redirect('applications:detail', application_id=doc.application.id)

    if is_ajax:
        return JsonResponse({'error': 'Файл не выбран.'}, status=400)
    return redirect('applications:detail', application_id=doc.application.id)


@login_required
def upload_payment(request, application_id):
    """Загрузка квитанции об оплате участником (поддерживает AJAX)"""
    application = get_object_or_404(Application, pk=application_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if application.submitted_by != request.user:
        if is_ajax:
            return JsonResponse({'error': 'Нет доступа.'}, status=403)
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    payment, _ = ApplicationPayment.objects.get_or_create(
        application=application,
        defaults={'amount': application.get_total_amount()},
    )

    if request.method == 'POST' and request.FILES.get('receipt'):
        payment.receipt_file = request.FILES['receipt']
        payment.status = 'uploaded'
        payment.save()
        if is_ajax:
            return JsonResponse({
                'success': True,
                'status': payment.status,
                'status_display': payment.get_status_display(),
                'file_url': payment.receipt_file.url,
            })
        messages.success(request, 'Квитанция загружена. Ожидайте подтверждения.')
        return redirect('applications:detail', application_id=application.id)

    if is_ajax:
        return JsonResponse({'error': 'Файл не выбран.'}, status=400)
    return redirect('applications:detail', application_id=application.id)


@login_required
def cancel(request, application_id):
    """Отмена заявки участником — освобождает стартовый номер"""
    application = get_object_or_404(Application, pk=application_id)
    if application.submitted_by != request.user:
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    if application.status in ('submitted', 'draft', 'confirmed'):
        application.status = 'cancelled'
        application.save()
        messages.success(request, 'Заявка отменена. Стартовый номер освобождён.')

    return redirect('applications:detail', application_id=application.id)


# ---------------------------------------------------------------------------
# Действия организатора
# ---------------------------------------------------------------------------

def _check_organizer(request, application):
    """True если текущий пользователь — организатор этого чемпионата"""
    return (hasattr(request.user, 'organizer_profile')
            and application.stage.championship.organizer == request.user.organizer_profile)


@login_required
def org_action(request, application_id):
    """Организатор подтверждает или отклоняет заявку"""
    application = get_object_or_404(Application, pk=application_id)
    if not _check_organizer(request, application):
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    if request.method == 'POST':
        action = request.POST.get('action')
        comment = request.POST.get('comment', '').strip()
        link = _app_link(application)
        pilot_name = application.pilot.full_name if hasattr(application, 'pilot') else application.submitted_by.email
        if action == 'confirm':
            application.status = 'confirmed'
            application.organizer_comment = comment
            application.save()
            messages.success(request, 'Заявка подтверждена.')
            _notify(
                _participant_email(application),
                f'Заявка #{application.id} одобрена — {application.stage.title}',
                f'<p>Здравствуйте, {pilot_name}!</p>'
                f'<p>Ваша заявка на <b>{application.stage.title}</b> (<b>{application.stage.championship.title}</b>) <b style="color:green">одобрена</b>. Вы допущены к соревнованиям.</p>'
                + (f'<p>Комментарий организатора: {comment}</p>' if comment else '')
                + f'<p><a href="{link}">Открыть заявку</a></p>',
            )
        elif action == 'reject':
            application.status = 'rejected'
            application.organizer_comment = comment
            application.save()
            messages.warning(request, 'Заявка отклонена.')
            _notify(
                _participant_email(application),
                f'Заявка #{application.id} отклонена — {application.stage.title}',
                f'<p>Здравствуйте, {pilot_name}!</p>'
                f'<p>Ваша заявка на <b>{application.stage.title}</b> <b style="color:red">отклонена</b>.</p>'
                + (f'<p>Причина: {comment}</p>' if comment else '')
                + f'<p><a href="{link}">Открыть заявку</a></p>',
            )

    return redirect('applications:detail', application_id=application.id)


@login_required
def org_verify_document(request, document_id):
    """Организатор проверяет или отклоняет документ"""
    doc = get_object_or_404(ApplicationDocument, pk=document_id)
    if not _check_organizer(request, doc.application):
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    if request.method == 'POST':
        action = request.POST.get('action')
        application = doc.application
        link = _app_link(application)
        pilot_name = application.pilot.full_name if hasattr(application, 'pilot') else application.submitted_by.email
        if action == 'verify':
            doc.status = 'verified'
            doc.verified_at = timezone.now()
            doc.verified_by = request.user
            doc.organizer_comment = ''
            doc.save()
            _notify(
                _participant_email(application),
                f'Документ проверен — {application.stage.title}',
                f'<p>Здравствуйте, {pilot_name}!</p>'
                f'<p>Документ <b>«{doc.stage_document.name}»</b> по заявке #{application.id} <b style="color:green">принят</b>.</p>'
                f'<p><a href="{link}">Открыть заявку</a></p>',
            )
        elif action == 'reject':
            comment = request.POST.get('comment', '').strip()
            doc.status = 'rejected'
            doc.organizer_comment = comment
            doc.save()
            _notify(
                _participant_email(application),
                f'Документ отклонён — {application.stage.title}',
                f'<p>Здравствуйте, {pilot_name}!</p>'
                f'<p>Документ <b>«{doc.stage_document.name}»</b> по заявке #{application.id} <b style="color:red">отклонён</b>.</p>'
                + (f'<p>Причина: {comment}</p>' if comment else '')
                + f'<p>Пожалуйста, загрузите исправленный документ. <a href="{link}">Открыть заявку</a></p>',
            )

    return redirect('applications:detail', application_id=doc.application.id)


@login_required
def org_verify_payment(request, application_id):
    """Организатор подтверждает или отклоняет оплату"""
    application = get_object_or_404(Application, pk=application_id)
    if not _check_organizer(request, application):
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    payment = getattr(application, 'payment', None)
    if payment and request.method == 'POST':
        action = request.POST.get('action')
        comment = request.POST.get('comment', '').strip()
        link = _app_link(application)
        pilot_name = application.pilot.full_name if hasattr(application, 'pilot') else application.submitted_by.email
        if action == 'verify':
            payment.status = 'verified'
            payment.verified_at = timezone.now()
            payment.verified_by = request.user
            payment.organizer_comment = ''
            payment.save()
            messages.success(request, 'Оплата подтверждена. Уведомление отправлено участнику.')
            _notify(
                _participant_email(application),
                f'Оплата подтверждена — {application.stage.title}',
                f'<p>Здравствуйте, {pilot_name}!</p>'
                f'<p>Оплата по заявке #{application.id} на <b>{application.stage.title}</b> <b style="color:green">подтверждена</b>.</p>'
                f'<p><a href="{link}">Открыть заявку</a></p>',
            )
        elif action == 'reject':
            payment.status = 'rejected'
            payment.organizer_comment = comment
            payment.save()
            messages.warning(request, 'Оплата отклонена. Уведомление отправлено участнику.')
            _notify(
                _participant_email(application),
                f'Оплата отклонена — {application.stage.title}',
                f'<p>Здравствуйте, {pilot_name}!</p>'
                f'<p>Оплата по заявке #{application.id} на <b>{application.stage.title}</b> <b style="color:red">отклонена</b>.</p>'
                + (f'<p>Причина: {comment}</p>' if comment else '')
                + f'<p>Пожалуйста, загрузите корректную квитанцию. <a href="{link}">Открыть заявку</a></p>',
            )

    return redirect('applications:detail', application_id=application.id)


def available_numbers_api(request, stage_id):
    """JSON: доступные стартовые номера для этапа и класса"""
    stage = get_object_or_404(Stage, pk=stage_id)
    race_class_id = request.GET.get('class_id')
    race_class = None
    if race_class_id:
        from website.models import RaceClass
        race_class = RaceClass.objects.filter(pk=race_class_id).first()
    numbers = stage.get_available_numbers(race_class=race_class)
    return JsonResponse({'numbers': numbers})
