"""
Приёмник отчётов Content-Security-Policy-Report-Only (security-аудит, п.5 —
наблюдательная фаза перед включением настоящего enforce-заголовка).
"""
import json
import logging

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger('gripline.csp')

# Реальный отчёт браузера — компактный JSON (несколько полей: blocked-uri,
# violated-directive, document-uri...), с большим запасом укладывается в
# несколько сотен байт. Лимит — просто защита от переполнения лога, а не
# ожидаемый размер.
_MAX_REPORT_BYTES = 8192


@csrf_exempt
@require_POST
def csp_report(request):
    """
    report-uri для CSP. @csrf_exempt здесь — не повтор находки прошлого
    аудита (см. коммит 16d0b90, где exempt сняли с process_claim_api): та
    вьюха меняла состояние приложения по запросу авторизованного пользователя
    и нуждалась в CSRF-защите. Эта — только пишет в лог, а POST шлёт сам
    браузер по спецификации CSP, без доступа к CSRF-токену страницы
    (это не форма и не fetch с нашего JS).
    """
    if len(request.body) > _MAX_REPORT_BYTES:
        return HttpResponse(status=413)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)
    logger.warning('CSP-VIOLATION %s', json.dumps(payload, ensure_ascii=False))
    return HttpResponse(status=204)
