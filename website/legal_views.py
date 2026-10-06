"""
Публичная форма обращения субъекта персональных данных — /legal/data-request/.

Ссылка на неё стоит в Политике обработки ПД (п. 1.2, 8.2) и в Пользовательском
соглашении (п. 2.4, 3). Обращение сохраняется в DataRequest (админка → «Обращения
по ПД») и дублируется письмом администратору: письмо — удобство, а не гарантия
(исходящий SMTP на проде может быть заблокирован хостингом, см. website/mail.py),
поэтому сбой отправки не ломает приём обращения.

Вынесено в отдельный модуль, не в website/views.py (тот уже слишком большой) —
по образцу mediakit_views.py / balance_views.py.
"""
import logging

from django import forms
from django.conf import settings
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from wagtailcache.cache import nocache_page

from .feedback.notify import notify_data_request
from .mail import admin_notify_email, send_templated_mail
from .models import DataRequest
from .services.balance_limits import balance_ratelimit

logger = logging.getLogger(__name__)

SESSION_KEY = 'data_request_sent'
TEXT_MAX = 5000
# Подробности обращения не дублируем в письме целиком — там только начало, остальное
# в админке (минимизация: почтовый ящик не нужное хранилище ПД заявителя).
EMAIL_TEXT_PREVIEW = 500


class DataRequestForm(forms.Form):
    request_type = forms.ChoiceField(choices=DataRequest.TYPE_CHOICES, label='Тип обращения')
    page_url = forms.CharField(max_length=500, required=False, label='Ссылка на профиль или страницу')
    contact = forms.CharField(max_length=200, label='Контакт для ответа')
    text = forms.CharField(max_length=TEXT_MAX, label='Текст обращения', widget=forms.Textarea)
    confirm = forms.BooleanField(
        label='Подтверждаю, что я субъект персональных данных либо его законный представитель',
        error_messages={'required': 'Нужно подтвердить, что вы субъект данных или его законный представитель.'},
    )
    # Honeypot: настоящий человек поле не видит и не заполняет.
    website = forms.CharField(required=False)

    def clean_contact(self):
        value = self.cleaned_data['contact'].strip()
        if len(value) < 3:
            raise forms.ValidationError('Укажите e-mail или Telegram, куда отправить ответ.')
        return value

    def clean_text(self):
        value = self.cleaned_data['text'].strip()
        if len(value) < 10:
            raise forms.ValidationError('Опишите требование подробнее (хотя бы одной-двумя фразами).')
        return value

    def clean_page_url(self):
        return self.cleaned_data['page_url'].strip()


def _notify_admin(obj):
    base = settings.BASE_URL.rstrip('/')
    preview = obj.text if len(obj.text) <= EMAIL_TEXT_PREVIEW else obj.text[:EMAIL_TEXT_PREVIEW] + '…'
    subject = f'[Gripline] Обращение по персональным данным №{obj.pk}'
    rows = [
        ('Тип', obj.get_request_type_display()),
        ('Страница', obj.page_url),
        ('Контакт', obj.contact),
        ('Текст', preview),
        ('Ответить до', obj.due_date.strftime('%d.%m.%Y')),
    ]
    try:
        send_templated_mail('admin_data_request', subject, [admin_notify_email()], {
            'admin': True,
            'subject': subject,
            'preheader': f'{obj.get_request_type_display()} — ответить до {obj.due_date:%d.%m.%Y}.',
            'title': f'Обращение по персональным данным №{obj.pk}',
            'rows': [(label, value) for label, value in rows if value],
            'admin_url': f'{base}/admin/website/datarequest/edit/{obj.pk}/',
        }, fail_silently=True)
    except Exception:
        logger.exception('data-request #%s: не удалось отправить письмо администратору', obj.pk)


@balance_ratelimit('data_request', limit=5, window_seconds=3600)
def _submit(request, form):
    obj = DataRequest.objects.create(
        request_type=form.cleaned_data['request_type'],
        page_url=form.cleaned_data['page_url'],
        contact=form.cleaned_data['contact'],
        text=form.cleaned_data['text'],
        is_confirmed=True,
    )
    _notify_admin(obj)
    notify_data_request(obj)
    request.session[SESSION_KEY] = {'id': obj.pk, 'due': obj.due_date.strftime('%d.%m.%Y')}
    return redirect('data_request')


# @nocache_page: форма с CSRF-токеном и сессионным «спасибо» — глобальный wagtailcache
# иначе отдал бы один и тот же HTML всем (и чужой токен), см. CLAUDE.md про owner-gated view.
@nocache_page
@require_http_methods(['GET', 'POST'])
def data_request_view(request):
    sent = request.session.pop(SESSION_KEY, None) if request.method == 'GET' else None
    if sent:
        return render(request, 'legal/data_request.html', {'sent': sent})

    if request.method == 'POST':
        form = DataRequestForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['website']:
                # Бот: делаем вид, что приняли, ничего не сохраняя.
                request.session[SESSION_KEY] = {'id': '—', 'due': ''}
                return redirect('data_request')
            return _submit(request, form)
    else:
        form = DataRequestForm(initial={
            'request_type': request.GET.get('type') if request.GET.get('type') in dict(DataRequest.TYPE_CHOICES) else 'deletion',
            'page_url': request.GET.get('url', '')[:500],
        })
    return render(request, 'legal/data_request.html', {'form': form})
