from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.conf import settings

from wagtailcache.cache import nocache_page

from website.mail import send_templated_mail
from website.services.balance_limits import ratelimit_post
from organizers.models import Stage
from . import health_consent, vault
from .models import Application, ApplicationDocument, ApplicationPayment


_NOTICES = {
    'app_confirmed': dict(
        subject='Заявка #{id} одобрена — {stage}', status='ok', title='Заявка одобрена',
        preheader='Организатор одобрил вашу заявку на {stage}. Детали и комментарий — внутри.',
        lead='Организатор одобрил вашу заявку на участие в этапе.',
        comment_label='Комментарий организатора', championship=True),
    'app_rejected': dict(
        subject='Заявка #{id} отклонена — {stage}', status='bad', title='Заявка отклонена',
        preheader='Организатор отклонил заявку на {stage}. Причина — внутри письма.',
        lead='Организатор отклонил вашу заявку на участие в этапе. Подробности — на странице заявки.',
        comment_label='Причина'),
    'doc_verified': dict(
        subject='Документ проверен — {stage}', status='ok', status_label='Принят', title='Документ проверен',
        preheader='Организатор принял документ «{document}» по заявке №{id}.',
        lead='Организатор проверил и принял загруженный документ.'),
    'doc_rejected': dict(
        subject='Документ отклонён — {stage}', status='bad', title='Документ отклонён',
        preheader='Документ «{document}» нужно загрузить заново. Причина — внутри.',
        lead='Организатор отклонил загруженный документ. Загрузите исправленный на странице заявки.',
        comment_label='Причина', button='Загрузить документ'),
    'pay_verified': dict(
        subject='Оплата подтверждена — {stage}', status='ok', status_label='Оплачено', title='Оплата подтверждена',
        preheader='Стартовый взнос по заявке №{id} получен и подтверждён.',
        lead='Организатор подтвердил оплату стартового взноса.'),
    'pay_rejected': dict(
        subject='Оплата отклонена — {stage}', status='bad', title='Оплата отклонена',
        preheader='Квитанцию по заявке №{id} нужно загрузить заново. Причина — внутри.',
        lead='Организатор не принял квитанцию об оплате стартового взноса. Загрузите корректную квитанцию на странице заявки.',
        comment_label='Причина', button='Загрузить квитанцию'),
}


def _notice(application, kind, comment='', document=None):
    """Тема и контекст письма участнику об изменении статуса заявки (макет «Gripline Emails», 09–14)."""
    from website.templatetags.email_tags import STATUS

    spec = _NOTICES[kind]
    stage = application.stage
    fmt = {'id': application.id, 'stage': stage.title, 'document': document.name if document else ''}
    rows = [('Документ', document.name)] if document else []
    rows += [('Заявка', f'№{application.id}'), ('Этап', stage.title)]
    if spec.get('championship'):
        rows.append(('Чемпионат', stage.championship.title))
    pilot = getattr(application, 'pilot', None)
    subject = spec['subject'].format(**fmt)
    context = {
        'subject': subject,
        'preheader': spec['preheader'].format(**fmt),
        'status': spec['status'],
        'status_label': spec.get('status_label', ''),
        'status_text': spec.get('status_label') or STATUS[spec['status']][2],
        'title': spec['title'],
        'lead': spec['lead'],
        'pilot_name': pilot.full_name if pilot else application.submitted_by.email,
        'rows': rows,
        'comment': comment if spec.get('comment_label') else '',
        'comment_label': spec.get('comment_label', ''),
        'button': spec.get('button', 'Открыть заявку'),
        'link': _app_link(application),
    }
    return subject, context


def _notify(application, kind, comment='', document=None):
    """Письмо участнику; сбой почты не должен ломать действие организатора."""
    try:
        subject, context = _notice(application, kind, comment, document)
        send_templated_mail('application_update', subject, [_participant_email(application)],
                            context, fail_silently=True)
    except Exception:
        pass


def _participant_email(application):
    return application.submitted_by.email


def _app_link(application):
    base = getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')
    return f"{base}/applications/{application.id}/"


def _duplicate_application(stage, user, submitted_by_type, race_class_id):
    """Активная заявка этого пилота на этап в том же классе. Организатор подаёт
    за разных пилотов, поэтому для него проверки нет."""
    if submitted_by_type == 'organizer' or not str(race_class_id or '').isdigit():
        return None
    from django.db.models import Q
    # Заявки, поданные пользователем как менеджером команды, — за других пилотов.
    who = Q(submitted_by=user) & ~Q(submitted_by_type='team')
    driver = getattr(getattr(user, 'profile', None), 'driver', None)
    if driver:
        who |= Q(pilot__driver=driver)
    return (Application.objects.filter(who, stage=stage, race_class_id=race_class_id)
            .exclude(status__in=['rejected', 'cancelled']).first())


def _notify_organizer_submitted(application):
    """Письмо организатору этапа о новой поданной заявке; сбой почты не мешает подаче."""
    try:
        stage = application.stage
        organizer = stage.championship.organizer.user
        pilot = getattr(application, 'pilot', None)
        pilot_name = pilot.full_name if pilot else application.submitted_by.email
        rows = [('Заявка', f'№{application.id}'), ('Пилот', pilot_name), ('Этап', stage.title),
                ('Чемпионат', stage.championship.title)]
        if application.race_class:
            rows.append(('Класс', application.race_class.name))
        subject = f'Новая заявка #{application.id} — {stage.title}'
        send_templated_mail('application_update', subject, [organizer.email], {
            'subject': subject,
            'preheader': f'{pilot_name} подал заявку на {stage.title}. Проверьте документы и оплату.',
            'status': 'wait', 'status_label': 'Новая заявка', 'status_text': 'Новая заявка',
            'title': 'Новая заявка на этап',
            'lead': 'Участник отправил заявку. Проверьте документы и оплату и примите решение.',
            'pilot_name': organizer.get_full_name() or organizer.email,
            'rows': rows, 'comment': '', 'comment_label': '',
            'button': 'Открыть заявку', 'link': _app_link(application),
        }, fail_silently=True)
    except Exception:
        pass


def _stage_classes(stage):
    return stage.championship.race_classes.all()


def _participation(stage, value):
    """Вариант участия из формы; недопустимый для этапа — «только этап»."""
    allowed = {c[0] for c in stage.participation_choices()}
    return value if value in allowed else Application.PARTICIPATION_RACE


@login_required
def detail(request, application_id):
    """Просмотр своей заявки + загрузка документов и квитанции"""
    application = get_object_or_404(Application, pk=application_id)

    from . import team_notify
    is_owner = can_manage(request.user, application)
    is_organizer = (hasattr(request.user, 'organizer_profile')
                    and application.stage.championship.organizer == request.user.organizer_profile)
    is_pilot = not is_owner and team_notify.is_team_pilot(request.user, application)
    if not (is_owner or is_organizer or is_pilot):
        messages.error(request, 'У вас нет доступа к этой заявке.')
        return redirect('/')

    if is_owner and application.status == 'draft' and application.team_entry_id:
        # Черновик заявки команды заполняется в мастере команды, не здесь.
        return redirect('teams:team_entry_pilot', entry_id=application.team_entry_id, application_id=application.id)

    in_wizard = application.status == 'draft' and application.submitted_by_type != 'team'
    return render(request, 'applications/detail.html', {
        'application': application,
        'is_owner': is_owner,
        'is_organizer': is_organizer,
        'can_withdraw': is_owner and can_withdraw(application),
        'vault_on': vault.vault_profile(application) is not None,
        'health_text': health_consent.text_for(application),
        'is_team_pilot': is_pilot,
        'decline_url': (team_notify.decline_url(application)
                        if is_pilot and application.status != 'cancelled' and can_withdraw(application) else ''),
        'in_wizard': in_wizard,
        'wizard_url': reverse('applications:apply', args=[application.stage_id])
                      + (f'?app={application.id}' if application.submitted_by_type == 'organizer' else ''),
        'documents': application.documents.select_related('stage_document'),
        'payment': getattr(application, 'payment', None),
    })


def _parse_date(value):
    from datetime import datetime
    try:
        return datetime.strptime((value or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _back(request, application):
    """Куда вернуться после загрузки: next со своего сайта (страница заявки команды) или заявка."""
    from django.utils.http import url_has_allowed_host_and_scheme
    nxt = request.POST.get('next') or ''
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return redirect(nxt)
    return redirect('applications:detail', application_id=application.id)


@login_required
def upload_document(request, document_id):
    """Загрузка файла документа участником (поддерживает AJAX)"""
    doc = get_object_or_404(ApplicationDocument, pk=document_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not can_manage(request.user, doc.application):
        if is_ajax:
            return JsonResponse({'error': 'Нет доступа.'}, status=403)
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    if request.method == 'POST' and request.FILES.get('file'):
        expiry = _parse_date(request.POST.get('expiry_date'))
        if doc.stage_document.is_fixed_kind and expiry is None:
            error = 'Укажите срок действия документа — по нему придёт напоминание.'
            if is_ajax:
                return JsonResponse({'error': error}, status=400)
            messages.error(request, error)
            return _back(request, doc.application)
        if health_consent.needed(doc.stage_document.kind):
            if not health_consent.given(request.POST):
                if is_ajax:
                    return JsonResponse({'error': health_consent.ERROR}, status=400)
                messages.error(request, health_consent.ERROR)
                return _back(request, doc.application)
            health_consent.stamp(doc, request.user)
        doc.file = request.FILES['file']
        if expiry:
            doc.expiry_date = expiry
        doc.status = 'uploaded'
        doc.uploaded_at = timezone.now()
        doc.organizer_comment = ''
        doc.vault_document = None
        doc.save()
        vault.save_from_application(doc)
        if is_ajax:
            return JsonResponse({
                'success': True,
                'status': doc.status,
                'status_display': doc.get_status_display(),
                'file_url': reverse('applications:serve_document', args=[doc.id]),
            })
        messages.success(request, f'Документ «{doc.stage_document.name}» загружен.')
        return _back(request, doc.application)

    if is_ajax:
        return JsonResponse({'error': 'Файл не выбран.'}, status=400)
    return redirect('applications:detail', application_id=doc.application.id)


@login_required
def upload_payment(request, application_id):
    """Загрузка квитанции об оплате участником (поддерживает AJAX)"""
    application = get_object_or_404(Application, pk=application_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not can_manage(request.user, application):
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
                'file_url': reverse('applications:serve_receipt', args=[application.id]),
            })
        messages.success(request, 'Квитанция загружена. Ожидайте подтверждения.')
        return _back(request, application)

    if is_ajax:
        return JsonResponse({'error': 'Файл не выбран.'}, status=400)
    return redirect('applications:detail', application_id=application.id)


def can_manage(user, application):
    """Участник-заявитель: подавший заявку, а у заявки команды — любой действующий менеджер
    этой команды (у команды бывает несколько менеджеров, пакет у них общий)."""
    if not user.is_authenticated:
        return False
    if application.submitted_by_id == user.id:
        return True
    if application.team_entry_id:
        from teams.models import TeamManager
        return TeamManager.objects.filter(user=user, team_id=application.team_entry.team_id,
                                          is_active=True).exists()
    return False


def is_platform_admin(user):
    """Администратор сайта (решение владельца 17.10.2026): видит файлы любых заявок из Wagtail-админки
    («Заявки на участие»). Право — то же, что на редактирование заявок в админке."""
    return user.is_authenticated and (user.is_superuser or user.has_perm('applications.change_application'))


def _can_view_application(request, application):
    from .team_notify import is_team_pilot
    return (can_manage(request.user, application) or _check_organizer(request, application)
            or is_platform_admin(request.user) or is_team_pilot(request.user, application))


@login_required
def serve_document(request, document_id):
    """
    Отдаёт файл документа заявки (ApplicationDocument) только участнику-
    заявителю или организатору этапа. Раньше detail.html ссылался прямо на
    doc.file.url — публичный /media/ путь без какой-либо проверки прав (см.
    accounts/views.py::serve_pilot_document — тот же класс проблемы найден
    и закрыт для личных документов пилота, здесь то же самое для документов
    заявки на этап и квитанций об оплате).

    as_attachment=True — иначе Content-Disposition: inline и браузер
    попытается отрендерить файл в контексте origin gripline.ru по
    Content-Type, угаданному по имени файла: участник мог бы назвать
    загружаемый "документ" evil.html со скриптом — организатор, открывающий
    его на проверку заявки, получил бы XSS в своей сессии.
    """
    doc = get_object_or_404(ApplicationDocument, pk=document_id)
    if not _can_view_application(request, doc.application):
        return JsonResponse({'error': 'Нет доступа.'}, status=403)
    return FileResponse(
        doc.file.open('rb'), filename=doc.file.name.rsplit('/', 1)[-1], as_attachment=True,
    )


@login_required
def serve_receipt(request, application_id):
    """Отдаёт квитанцию об оплате только заявителю или организатору этапа
    (as_attachment=True — см. serve_document выше, тот же риск)."""
    application = get_object_or_404(Application, pk=application_id)
    if not _can_view_application(request, application):
        return JsonResponse({'error': 'Нет доступа.'}, status=403)
    payment = getattr(application, 'payment', None)
    if not payment or not payment.receipt_file:
        return JsonResponse({'error': 'Квитанция не найдена.'}, status=404)
    return FileResponse(
        payment.receipt_file.open('rb'),
        filename=payment.receipt_file.name.rsplit('/', 1)[-1],
        as_attachment=True,
    )


def _notify_organizer_withdrawn(application):
    """Письмо организатору: участник отозвал заявку (номер освобождён)."""
    try:
        stage = application.stage
        organizer = stage.championship.organizer.user
        pilot = getattr(application, 'pilot', None)
        pilot_name = pilot.full_name if pilot else application.submitted_by.email
        rows = [('Заявка', f'№{application.id}'), ('Пилот', pilot_name), ('Этап', stage.title)]
        if application.start_number:
            rows.append(('Освобождён номер', str(application.start_number)))
        paid = getattr(getattr(application, 'payment', None), 'status', '') == 'verified'
        subject = f'Заявка #{application.id} отозвана — {stage.title}'
        send_templated_mail('application_update', subject, [organizer.email], {
            'subject': subject,
            'preheader': f'{pilot_name} отозвал заявку на {stage.title}.',
            'status': 'bad', 'status_label': 'Отозвана', 'status_text': 'Отозвана',
            'title': 'Участник отозвал заявку',
            'lead': 'Стартовый номер освобождён и доступен другим участникам.'
                    + (' Взнос по заявке был подтверждён — участник может обратиться к вам за возвратом.' if paid else ''),
            'pilot_name': organizer.get_full_name() or organizer.email,
            'rows': rows, 'comment': application.withdraw_reason, 'comment_label': 'Причина',
            'button': 'Открыть заявку', 'link': _app_link(application),
        }, fail_silently=True)
    except Exception:
        pass


def can_withdraw(application):
    """Отозвать можно активную заявку до начала этапа (после старта снимает только организатор)."""
    return (application.status in ('draft', 'submitted', 'confirmed')
            and application.stage.start_date > timezone.now())


@login_required
def cancel(request, application_id):
    """Отзыв заявки участником (или удаление черновика): номер сразу освобождается."""
    application = get_object_or_404(Application, pk=application_id)
    if not can_manage(request.user, application):
        messages.error(request, 'Нет доступа.')
        return redirect('/')
    if request.method != 'POST':
        return redirect('applications:detail', application_id=application.id)
    if not can_withdraw(application):
        messages.error(request, 'Эту заявку уже нельзя отозвать — этап начался. Свяжитесь с организатором.')
        return redirect('applications:detail', application_id=application.id)

    was_draft = application.status == 'draft'
    application.status = 'cancelled'
    application.withdrawn_at = timezone.now()
    application.withdraw_reason = request.POST.get('reason', '').strip()[:1000]
    application.save()
    if was_draft:
        messages.success(request, 'Черновик заявки удалён.')
    else:
        _notify_organizer_withdrawn(application)
        messages.success(request, 'Заявка отозвана, стартовый номер освобождён. '
                                  'По возврату взноса свяжитесь с организатором.')
    return redirect('applications:detail', application_id=application.id)


@nocache_page
@ratelimit_post('team_decline', limit=30, window_seconds=3600)
def team_decline(request, application_id, token):
    """Отказ пилота от заявки, поданной командой, — по подписанной ссылке из письма, без входа
    (у многих пилотов нет аккаунта). Отказ = отзыв заявки: номер освобождается, менеджеры
    команды и организатор получают письмо."""
    from . import team_notify
    application = get_object_or_404(Application.objects.select_related('team_entry__team', 'stage', 'pilot'),
                                    pk=application_id)
    if not application.team_entry_id or not team_notify.check_token(application, token):
        raise Http404
    allowed = can_withdraw(application) and application.status != 'cancelled'
    if request.method == 'POST' and allowed:
        reason = (request.POST.get('reason') or '').strip()[:900]
        application.status = 'cancelled'
        application.withdrawn_at = timezone.now()
        application.withdraw_reason = 'Пилот отказался от участия' + (f': {reason}' if reason else '')
        application.save()
        team_notify.notify_declined(application)
        allowed = False
    return render(request, 'applications/team_decline.html', {
        'application': application, 'allowed': allowed, 'declined': application.status == 'cancelled'})


# ---------------------------------------------------------------------------
# Действия организатора
# ---------------------------------------------------------------------------

def _check_organizer(request, application):
    """True если текущий пользователь — организатор этого чемпионата"""
    profile = getattr(request.user, 'organizer_profile', None)
    return (profile is not None and profile.status == 'active'
            and application.stage.championship.organizer == profile)


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
        if action == 'confirm':
            application.status = 'confirmed'
            application.organizer_comment = comment
            application.save()
            messages.success(request, 'Заявка подтверждена.')
            _notify(application, 'app_confirmed', comment)
        elif action == 'reject':
            application.status = 'rejected'
            application.organizer_comment = comment
            application.save()
            messages.warning(request, 'Заявка отклонена.')
            _notify(application, 'app_rejected', comment)

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
        if action == 'verify':
            doc.status = 'verified'
            doc.verified_at = timezone.now()
            doc.verified_by = request.user
            doc.organizer_comment = ''
            doc.save()
            _notify(application, 'doc_verified', document=doc.stage_document)
        elif action == 'reject':
            comment = request.POST.get('comment', '').strip()
            doc.status = 'rejected'
            doc.organizer_comment = comment
            doc.save()
            vault.mark_rejected(doc, comment)
            _notify(application, 'doc_rejected', comment, document=doc.stage_document)

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
        if action == 'verify':
            payment.status = 'verified'
            payment.verified_at = timezone.now()
            payment.verified_by = request.user
            payment.organizer_comment = ''
            payment.save()
            messages.success(request, 'Оплата подтверждена. Уведомление отправлено участнику.')
            _notify(application, 'pay_verified')
        elif action == 'reject':
            payment.status = 'rejected'
            payment.organizer_comment = comment
            payment.save()
            messages.warning(request, 'Оплата отклонена. Уведомление отправлено участнику.')
            _notify(application, 'pay_rejected', comment)

    return redirect('applications:detail', application_id=application.id)


@login_required
def submit_application(request, application_id):
    """Пилот подтверждает заявку: draft → submitted"""
    application = get_object_or_404(Application, pk=application_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not can_manage(request.user, application):
        if is_ajax:
            return JsonResponse({'error': 'Нет доступа.'}, status=403)
        messages.error(request, 'Нет доступа.')
        return redirect('/')

    if application.status != 'draft':
        if is_ajax:
            return JsonResponse({'error': 'Заявка уже отправлена.'}, status=400)
        return redirect('applications:detail', application_id=application.id)

    if request.method != 'POST':
        return redirect('applications:detail', application_id=application.id)

    # Проверяем обязательные документы
    missing = []
    for doc in application.documents.select_related('stage_document'):
        if doc.stage_document.required and doc.stage_document.is_active and doc.status == 'pending':
            missing.append(doc.stage_document.name)

    if missing:
        if is_ajax:
            return JsonResponse({'error': 'missing_docs', 'missing': missing}, status=400)
        messages.error(request, 'Загрузите все обязательные документы перед отправкой.')
        return redirect('applications:detail', application_id=application.id)

    application.status = 'submitted'
    application.submitted_at = timezone.now()
    application.save()
    _notify_organizer_submitted(application)

    if is_ajax:
        return JsonResponse({'success': True})
    messages.success(request, 'Заявка отправлена! Ожидайте решения организатора.')
    return redirect('applications:detail', application_id=application.id)


def driver_search_api(request):
    """JSON для мастера заявки: пилоты из базы по фамилии/имени (подсказка при вводе)."""
    from website.services.demo import search_drivers
    drivers = search_drivers(request.GET.get('q', '').strip())
    return JsonResponse({'drivers': [{'id': d.pk, 'name': f'{d.last_name} {d.first_name}', 'first_name': d.first_name,
                                      'last_name': d.last_name, 'city': d.city or ''} for d in drivers]})


def available_numbers_api(request, stage_id):
    """JSON: доступные стартовые номера для этапа и класса"""
    stage = get_object_or_404(Stage, pk=stage_id)
    race_class_id = request.GET.get('class_id')
    race_class = None
    if race_class_id:
        from website.models import RaceClass
        race_class = RaceClass.objects.filter(pk=race_class_id).first()
    participation = _participation(stage, request.GET.get('participation'))
    numbers = stage.get_available_numbers(race_class=race_class, participation=participation)
    return JsonResponse({'numbers': numbers})
