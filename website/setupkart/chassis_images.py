"""Картинки шасси для приложения: подложка под схемой давления/колеи/развала (ТЗ приложения, решение 08.10.2026).

Картинка — на тип шасси (детское, мини, взрослое, KZ…), классы гонок ссылаются на тип. Пользователь
загружает картинку и двумя кликами в предпросмотре отмечает центры левых колёс; правые — зеркально
относительно вертикальной оси картинки. Плашки приложения встают по этим точкам — раскладка ниже
(LAYOUT) одна для предпросмотра в админке и для приложения.
"""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from PIL import Image as PILImage
from wagtail.images import get_image_model
from wagtail.models import Collection

from website.models import AppChassisImage, RaceClass

PERM = 'website.change_appparameter'
MAX_UPLOAD = 8 * 1024 * 1024
RENDITION = 'max-1000x2000|format-webp|webpquality-85'

# Раскладка схемы в приложении для ширины экрана W (dp). Повторяется в JS предпросмотра
# (templates/setupkart/admin/chassis_image_edit.html) и в приложении (kart_top_view.dart).
LAYOUT = {
    'gutter': 0.15,      # поля по бокам картинки под кнопки развала, доля W
    'edge': 4, 'gap': 10, 'chip_h': 56,
    'chip_w': (0.22, 72, 96),     # доля W, мин, макс
    'pill_w': (0.36, 112, 160), 'pill_h': 44,
    'camber_w': (0.16, 56, 68), 'camber_h': 68,
    'tyre_half': 0.055,  # полуширина шины, доля ширины картинки — отступ кнопки развала от центра колеса
}


def _allowed(request):
    return request.user.has_perm(PERM)


class ChassisImageForm(forms.Form):
    name = forms.CharField(label='Тип шасси', max_length=60)
    sort_order = forms.IntegerField(label='Порядок', min_value=0, initial=0)
    image_file = forms.FileField(label='Картинка', required=False,
                                 help_text='PNG или WebP с прозрачным фоном, вид сверху, нос вверху; ширина от 1000 px.')
    classes = forms.ModelMultipleChoiceField(
        label='Классы', queryset=RaceClass.objects.all(), required=False, widget=forms.CheckboxSelectMultiple,
        help_text='Класс может быть только у одного типа: отмеченный здесь уйдёт от другого типа.')
    front_x = forms.FloatField(required=False, min_value=0, max_value=1, widget=forms.HiddenInput)
    front_y = forms.FloatField(required=False, min_value=0, max_value=1, widget=forms.HiddenInput)
    rear_x = forms.FloatField(required=False, min_value=0, max_value=1, widget=forms.HiddenInput)
    rear_y = forms.FloatField(required=False, min_value=0, max_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs = AppChassisImage.objects.filter(name__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Такой тип уже есть')
        return name

    def clean_image_file(self):
        f = self.cleaned_data.get('image_file')
        if not f:
            return None
        if f.size > MAX_UPLOAD:
            raise ValidationError('Файл больше 8 МБ')
        try:
            with PILImage.open(f) as im:
                im.verify()
                fmt = im.format
        except Exception:
            raise ValidationError('Не удалось прочитать картинку')
        if fmt not in ('PNG', 'WEBP', 'JPEG'):
            raise ValidationError('Нужен PNG, WebP или JPEG')
        f.seek(0)
        return f

    def clean(self):
        data = super().clean()
        points = [data.get(k) for k in ('front_x', 'front_y', 'rear_x', 'rear_y')]
        if any(p is not None for p in points) and None in points:
            raise ValidationError('Отметьте оба колеса — переднее и заднее левые')
        if None not in points and data['front_y'] >= data['rear_y']:
            raise ValidationError('Переднее колесо должно быть выше заднего (нос карта — вверху картинки)')
        return data


def image_list(request):
    if not _allowed(request):
        return HttpResponseForbidden()
    items = AppChassisImage.objects.select_related('image').prefetch_related('race_classes')
    return render(request, 'setupkart/admin/chassis_images.html', {
        'items': items,
        'unassigned': RaceClass.objects.filter(app_chassis_image__isnull=True),
    })


def image_edit(request, pk=None):
    if not _allowed(request):
        return HttpResponseForbidden()
    obj = get_object_or_404(AppChassisImage, pk=pk) if pk else None
    if request.method == 'POST':
        form = ChassisImageForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            obj = _save(form, obj, request.user)
            messages.success(request, f'Сохранено: «{obj.name}». В приложение попадёт после публикации справочников.'
                             if obj.ready else f'Сохранено: «{obj.name}». Отметьте колёса — без них картинка не уходит в приложение.')
            return redirect('setupkart_chassis_image_edit', pk=obj.pk)
    else:
        initial = {'sort_order': 0}
        if obj:
            initial = {'name': obj.name, 'sort_order': obj.sort_order, 'classes': list(obj.race_classes.all()),
                       'front_x': obj.front_x, 'front_y': obj.front_y, 'rear_x': obj.rear_x, 'rear_y': obj.rear_y}
        form = ChassisImageForm(initial=initial, instance=obj)
    taken = {rc.pk: rc.app_chassis_image.name for rc in RaceClass.objects.select_related('app_chassis_image')
             if rc.app_chassis_image_id and (obj is None or rc.app_chassis_image_id != obj.pk)}
    class_rows = [(cb, taken.get(int(str(cb.data['value'])))) for cb in form['classes']]
    return render(request, 'setupkart/admin/chassis_image_edit.html', {
        'obj': obj, 'form': form, 'layout': LAYOUT, 'class_rows': class_rows,
        'image_url': obj.image.get_rendition('max-1000x2000').url if obj and obj.image else '',
    })


@transaction.atomic
def _save(form, obj, user):
    d = form.cleaned_data
    obj = obj or AppChassisImage()
    obj.name, obj.sort_order = d['name'], d['sort_order']
    obj.front_x, obj.front_y, obj.rear_x, obj.rear_y = d['front_x'], d['front_y'], d['rear_x'], d['rear_y']
    upload = d.get('image_file')
    if upload:
        image = get_image_model()(title=f'Шасси в приложении: {obj.name}', file=upload, uploaded_by_user=user,
                                  collection=Collection.get_first_root_node())
        image.save()
        obj.image = image
    obj.save()
    selected = {rc.pk for rc in d['classes']}
    RaceClass.objects.filter(app_chassis_image=obj).exclude(pk__in=selected).update(app_chassis_image=None)
    RaceClass.objects.filter(pk__in=selected).update(app_chassis_image=obj)
    return obj


@require_POST
def image_delete(request, pk):
    if not _allowed(request):
        return HttpResponseForbidden()
    obj = get_object_or_404(AppChassisImage, pk=pk)
    name = obj.name
    obj.delete()  # классы: SET_NULL → встроенная схема
    messages.success(request, f'Тип «{name}» удалён. Его классы в приложении получат встроенную схему после публикации.')
    return redirect('setupkart_chassis_images')


def payload():
    """Для справочника приложения: готовые картинки (с отмеченными колёсами) и классы, которые на них ссылаются."""
    out = []
    for c in AppChassisImage.objects.select_related('image').prefetch_related('race_classes'):
        if not c.ready:
            continue
        r = c.image.get_rendition(RENDITION)
        out.append({
            'id': c.pk, 'name': c.name,
            'url': f"{settings.BASE_URL.rstrip('/')}{r.url}",
            'width': r.width, 'height': r.height,
            'front': {'x': round(c.front_x, 4), 'y': round(c.front_y, 4)},
            'rear': {'x': round(c.rear_x, 4), 'y': round(c.rear_y, 4)},
            # Категория в сессии приложения хранится названием класса — отдаём и id, и названия.
            'race_class_ids': sorted(rc.pk for rc in c.race_classes.all()),
            'race_class_names': [rc.name for rc in c.race_classes.all()],
        })
    return out


COMPOUND_RENDITION = 'max-320x320|format-webp|webpquality-85'


def compound_image(compound):
    """Фото состава шины для плитки в приложении: {url, width, height} или None."""
    if not compound.image_id:
        return None
    r = compound.image.get_rendition(COMPOUND_RENDITION)
    return {'url': f"{settings.BASE_URL.rstrip('/')}{r.url}", 'width': r.width, 'height': r.height}


def help_images_payload():
    """Картинки-подсказки к полям: {ключ поля: {url, width, height}}."""
    from website.models import AppHelpImage
    out = {}
    for h in AppHelpImage.objects.select_related('image'):
        r = h.image.get_rendition(RENDITION)
        out[h.key] = {'url': f"{settings.BASE_URL.rstrip('/')}{r.url}", 'width': r.width, 'height': r.height}
    return out


def validation_errors():
    return [f'Картинка шасси «{c.name}»: назначена классам, но ' + ('не загружена' if not c.image_id else 'не отмечены колёса')
            for c in AppChassisImage.objects.prefetch_related('race_classes')
            if c.race_classes.exists() and not c.ready]
