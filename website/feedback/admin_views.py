"""Админ-эндпоинты бота обратной связи (регистрируются в wagtail_hooks.py)."""
import os
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from website.feedback import tg_sync
from website.models import FeedbackAttachment, FeedbackBotSettings

HEARTBEAT_OK_SEC = 90


def _can_change(user):
    return user.has_perm('website.change_feedbackbotsettings')


@login_required
def bot_status(request):
    if not _can_change(request.user):
        return HttpResponseForbidden()
    cfg = FeedbackBotSettings.get()
    age = None
    if cfg.heartbeat_at:
        age = int((timezone.now() - cfg.heartbeat_at).total_seconds())
    return JsonResponse({
        'heartbeat_age_sec': age,
        'alive': age is not None and age <= HEARTBEAT_OK_SEC,
        'enabled': cfg.is_enabled,
        'has_token': bool(cfg.get_token()),
    })


def _action(request, fn):
    if not _can_change(request.user):
        return JsonResponse({'ok': False, 'message': 'Нет прав'}, status=403)
    cfg = FeedbackBotSettings.get()
    try:
        return JsonResponse({'ok': True, 'message': fn(cfg)})
    except tg_sync.TelegramApiError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)})
    except Exception as exc:  # в т.ч. CryptoConfigError — без трейсбека с токеном
        return JsonResponse({'ok': False, 'message': f'Ошибка: {type(exc).__name__}: {str(exc)[:200]}'})


@login_required
@require_POST
def bot_check(request):
    def run(cfg):
        me = tg_sync.check_connection(cfg)
        return f'Подключено: @{me.get("username")} (id {me.get("id")})'
    return _action(request, run)


@login_required
@require_POST
def bot_test_chat(request):
    def run(cfg):
        tg_sync.send_test_message(cfg)
        return 'Тестовое сообщение отправлено в админ-чат.'
    return _action(request, run)


@login_required
@require_POST
def bot_restart(request):
    def run(cfg):
        cfg.restart_requested_at = timezone.now()
        cfg.save(update_fields=['restart_requested_at'])
        return 'Перезапуск запрошен: бот перезапустится в течение периода перечитывания настроек.'
    return _action(request, run)


@login_required
@require_POST
def bot_create_topics(request):
    def run(cfg):
        created, errors = tg_sync.create_category_topics(cfg)
        msg = f'Создано тем: {created}.'
        if errors:
            msg += ' Ошибки: ' + '; '.join(errors)
        return msg
    return _action(request, run)


@login_required
def attachment_download(request, pk):
    """Вложения лежат вне публичного MEDIA_ROOT; отдаём только тем, у кого
    есть право просмотра обращений."""
    if not request.user.has_perm('website.view_feedback'):
        return HttpResponseForbidden()
    att = FeedbackAttachment.objects.filter(pk=pk).first()
    if att is None or not att.file:
        raise Http404
    try:
        handle = att.file.open('rb')
    except FileNotFoundError:
        raise Http404
    name = att.original_name or os.path.basename(att.file.name)
    response = FileResponse(handle, content_type=att.mime or 'application/octet-stream')
    response['Content-Disposition'] = f'inline; filename*=UTF-8\'\'{quote(name)}'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
