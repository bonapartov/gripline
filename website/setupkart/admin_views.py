"""Админка «Приложение»: обзор, предложения пользователей, публикация справочников."""
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from website.models import (
    AppCatalogVersion, AppEngineSparkPlug, AppParameter, AppSuggestion, Chassis, Engine, Track, TyreBrand,
)
from . import catalog
from .api import tracks_payload
from .spec import expand

PERM = 'website.change_appparameter'


def _allowed(request):
    return request.user.has_perm(PERM)


def overview(request):
    if not _allowed(request):
        return HttpResponseForbidden()
    engines = list(catalog.app_engines())
    return render(request, 'setupkart/admin/overview.html', {
        'engines': engines,
        'engines_off': Engine.objects.filter(show_in_app=False).order_by('name'),
        'tyre_brands': TyreBrand.objects.filter(show_in_app=True).order_by('name'),
        'chassis': Chassis.objects.filter(show_in_app=True).order_by('name'),
        'tracks': tracks_payload()['tracks'],
        'tracks_without_coords': Track.objects.filter(show_in_app=True).filter(latitude__isnull=True).count(),
        'params': AppParameter.objects.all(),
        'errors': catalog.validation_errors(),
        'latest': catalog.latest_version(),
        'unpublished': catalog.has_unpublished_changes(),
        'new_suggestions': AppSuggestion.objects.filter(status=AppSuggestion.STATUS_NEW).count(),
    })


def publication(request):
    if not _allowed(request):
        return HttpResponseForbidden()
    if request.method == 'POST':
        try:
            v = catalog.publish(user=request.user, note=request.POST.get('note', '').strip()[:200])
        except catalog.PublishError as exc:
            for e in exc.errors:
                messages.error(request, e)
        else:
            messages.success(request, f'Опубликована версия {v.version}. Приложения получат её при следующем обновлении справочников.')
        return redirect('setupkart_publication')
    return render(request, 'setupkart/admin/publication.html', {
        'errors': catalog.validation_errors(),
        'latest': catalog.latest_version(),
        'unpublished': catalog.has_unpublished_changes(),
        'versions': AppCatalogVersion.objects.select_related('published_by')[:30],
    })


def suggestions(request):
    if not _allowed(request):
        return HttpResponseForbidden()
    status = request.GET.get('status', AppSuggestion.STATUS_NEW)
    qs = AppSuggestion.objects.select_related('engine')
    if status in dict(AppSuggestion.STATUS_CHOICES):
        qs = qs.filter(status=status)
    return render(request, 'setupkart/admin/suggestions.html', {
        'items': qs[:300], 'status': status, 'statuses': AppSuggestion.STATUS_CHOICES,
    })


def add_to_catalog(s):
    """Добавляет значение в справочник. Возвращает (ok, сообщение)."""
    if s.field_key == 'spark_plug':
        if not s.engine:
            return False, 'Свеча прислана без двигателя — добавьте вручную в карточку нужного двигателя.'
        AppEngineSparkPlug.objects.get_or_create(engine=s.engine, name=s.value)
        return True, f'Свеча «{s.value}» добавлена в «{s.engine}».'
    if s.field_key == 'tyre_make':
        brand, _ = TyreBrand.objects.get_or_create(name=s.value)
        TyreBrand.objects.filter(pk=brand.pk).update(show_in_app=True)
        return True, f'Производитель шин «{s.value}» добавлен (проверьте карточку: он появится и на сайте).'
    if s.field_key == 'track':
        existing = Track.objects.filter(name__iexact=s.value).first()
        if existing:
            return False, (f'Трасса «{existing.name}» уже есть на сайте. Если это она — проверьте у неё координаты '
                           f'и галочку «Показывать в приложении»; если другая — создайте вручную с уточнённым названием.')
        track = Track(name=s.value, latitude=s.latitude, longitude=s.longitude, show_in_app=True, live=False)
        track.save()
        track.save_revision()
        return True, (f'Трасса «{s.value}» создана черновиком. Проверьте название, город и координаты и опубликуйте — '
                      f'после этого она появится на сайте и в приложении (публиковать справочник не нужно).')
    if s.field_key == 'chassis':
        ch, _ = Chassis.objects.get_or_create(name=s.value)
        Chassis.objects.filter(pk=ch.pk).update(show_in_app=True)
        return True, f'Шасси «{s.value}» добавлено (проверьте карточку: оно появится и на сайте).'
    spec = None
    if s.engine:
        spec = s.engine.app_fields.filter(key=s.field_key).first()
    if spec is None:
        spec = AppParameter.objects.filter(key=s.field_key).first()
    if spec is None:
        return False, 'Это поле не настроено в справочнике — добавьте значение вручную.'
    if spec.mode == spec.MODE_RANGE:
        return False, ('Поле задано диапазоном (минимум, максимум, шаг) — расширьте диапазон вручную '
                       'или переключите поле на список.')
    if s.value not in expand(spec):
        spec.options_text = (spec.options_text.rstrip('\n') + '\n' + s.value).strip('\n')
        spec.save(update_fields=['options_text'])
    return True, f'Значение «{s.value}» добавлено.'


@require_POST
def suggestion_action(request, pk, action):
    if not _allowed(request):
        return HttpResponseForbidden()
    s = get_object_or_404(AppSuggestion, pk=pk)
    if action == 'hide':
        s.status = AppSuggestion.STATUS_HIDDEN
        s.save(update_fields=['status'])
        messages.info(request, f'«{s.value}» скрыто.')
    elif action == 'add':
        ok, msg = add_to_catalog(s)
        if ok:
            s.status = AppSuggestion.STATUS_ADDED
            s.save(update_fields=['status'])
            messages.success(request, msg + ' Не забудьте опубликовать справочники.')
        else:
            messages.warning(request, msg)
    nxt = request.POST.get('next')
    if not nxt or not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = reverse('setupkart_suggestions')
    return redirect(nxt)
