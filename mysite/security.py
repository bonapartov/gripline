"""
Инфраструктурные security-хелперы уровня проекта (не относятся к домену
конкретного Django-приложения — соседствуют с urls.py/wsgi.py).
"""
from django.conf import settings


def build_csp_header_value(directives):
    """dict directive -> [sources] превращается в строку заголовка CSP."""
    return '; '.join(
        f"{name} {' '.join(sources)}" if sources else name
        for name, sources in directives.items()
    )


def get_client_ip(request):
    """
    Определяет реальный IP клиента для django-axes.

    Прод стоит за ЕДИНСТВЕННЫМ обратным прокси (nginx) на том же хосте —
    gunicorn слушает только 127.0.0.1:8000, снаружи недоступен (проверено
    systemd-юнитом + `ss -tlnp` на сервере), так что REMOTE_ADDR для КАЖДОГО
    запроса, дошедшего до Django, — это сам nginx, не реальный клиент.

    nginx настроен с `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`
    (см. /etc/nginx/sites-available/gripline) — эта директива ВСЕГДА дописывает
    реальный IP клиента, которого видит сам nginx, ПОСЛЕДНИМ элементом списка,
    даже если клиент сам прислал поддельный X-Forwarded-For (тогда подделка
    окажется левее, а не на последнем месте). Поэтому последний элемент
    списка — единственное значение, которое клиент не может подделать через
    HTTP-заголовки при данной топологии (ровно один прокси-хоп на одном хосте).

    django-ipware сюда не подходит: его proxy_count/proxy_list рассчитаны на
    список ЗАРАНЕЕ ИЗВЕСТНЫХ доверенных IP прокси-цепочки, а не на простое
    «доверяй последнему хопу» — с proxy_count=1 он требует ≥2 элементов в
    X-Forwarded-For и на обычном запросе без клиентского XFF (когда nginx
    подставляет ровно один элемент) не находит IP вообще (см. разбор в
    коммите, добавляющем django-axes).

    Локальная разработка/тесты (без nginx) — X-Forwarded-For отсутствует,
    используется REMOTE_ADDR как есть.
    """
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR')


class ContentSecurityPolicyReportOnlyMiddleware:
    """
    Наблюдательная фаза CSP (security-аудит, п.5) — только логирует нарушения
    через /csp-report/ (website/csp_views.py), ничего не блокирует. Значение
    заголовка собирается один раз при старте процесса из
    settings.CSP_REPORT_ONLY_DIRECTIVES, не на каждый запрос.

    wagtailcache (глобальный middleware, mysite/settings/base.py) кэширует
    ответы по URL, но заголовок одинаков для всех посетителей — в отличие от
    персонализированных owner-gated вьюх (см. правило @nocache_page в
    mediakit_views.py), тут нет риска утечки чужих данных через кэш.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.header_value = build_csp_header_value(settings.CSP_REPORT_ONLY_DIRECTIVES)

    def __call__(self, request):
        response = self.get_response(request)
        response['Content-Security-Policy-Report-Only'] = self.header_value
        return response
