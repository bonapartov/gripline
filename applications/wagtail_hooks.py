"""Заявки на участие в этапах — в админке Wagtail (группа «Организаторы»).

Заявки создают и заполняют пилоты, команды и организаторы в своих кабинетах, поэтому
здесь они не создаются, а просматриваются целиком (все связанные данные — на странице
просмотра) и меняются только статус, комментарий организатора, стартовый номер и класс.
Полное редактирование со вложенными формами осталось в Django-админке (/django-admin/).
Сама группа меню — organizers/wagtail_hooks.py (OrganizersGroup).
"""
from django.db import models as dj_models
from django.utils.html import format_html
from django.utils.text import capfirst
from wagtail.admin.panels import FieldPanel, ObjectList
from wagtail_modeladmin.helpers import PermissionHelper
from wagtail_modeladmin.options import ModelAdmin
from wagtail_modeladmin.views import InspectView

from .models import Application

STATUS_COLORS = {
    'draft': ('#6c757d', '#fff'),
    'submitted': ('#ffc107', '#000'),
    'confirmed': ('#28a745', '#fff'),
    'rejected': ('#dc3545', '#fff'),
    'cancelled': ('#6c757d', '#fff'),
}
SKIP_FIELDS = {'id', 'application', 'gateway_response'}


def model_rows(obj):
    """[(подпись, значение, ссылка-или-None)] по полям связанной записи."""
    rows = []
    for field in obj._meta.fields:
        if field.name in SKIP_FIELDS:
            continue
        value = getattr(obj, field.name)
        url = None
        if isinstance(field, dj_models.FileField):
            # Только имя файла, без ссылки: файлы заявок отдаются через applications/views.py::
            # serve_document/serve_receipt (доступ — заявитель и организатор этапа; результат
            # security-аудита), а не по публичному /media/. Админу платформы эти вьюхи не
            # открывают файл — расширять доступ без отдельного решения нельзя.
            value = value.name.rsplit('/', 1)[-1] if value else ''
        elif field.choices:
            value = getattr(obj, f'get_{field.name}_display')()
        elif isinstance(field, dj_models.BooleanField):
            value = 'Да' if value else 'Нет'
        elif field.is_relation and value is not None:
            value = str(value)
        if value in (None, ''):
            value = '—'
        rows.append((capfirst(str(field.verbose_name)), value, url))
    return rows


def _related(instance, name):
    """OneToOne-связь или None (обращение к отсутствующей бросает DoesNotExist)."""
    try:
        return getattr(instance, name)
    except Exception:
        return None


class ApplicationInspectView(InspectView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        app = self.instance
        sections = []
        for title, name in (('Заявитель', 'applicant'), ('Пилот', 'pilot'), ('Карт', 'kart'),
                            ('Механик', 'mechanic'), ('Оплата', 'payment')):
            obj = _related(app, name)
            if obj is not None:
                sections.append({'title': title, 'rows': model_rows(obj)})
        for title, manager in (('Документы', app.documents.all()), ('Достижения', app.achievements.all()),
                               ('Выбранные опции', app.selected_options.select_related('option'))):
            items = [model_rows(item) for item in manager]
            if items:
                sections.append({'title': title, 'items': items})
        context['sections'] = sections
        context['total_amount'] = app.get_total_amount()
        return context


class ReadOnlyCreatePermissionHelper(PermissionHelper):
    """Заявку создаёт пользователь в кабинете (со связанными записями) — «Добавить» не нужен."""
    def user_can_create(self, user):
        return False


class ApplicationAdmin(ModelAdmin):
    model = Application
    menu_label = 'Заявки на участие'
    menu_icon = 'form'
    permission_helper_class = ReadOnlyCreatePermissionHelper
    inspect_view_enabled = True
    inspect_view_class = ApplicationInspectView
    inspect_template_name = 'applications/admin/application_inspect.html'
    list_display = ('id', 'pilot_name', 'stage', 'race_class', 'start_number', 'status_badge', 'submitted_by_type', 'created_at')
    list_filter = ('status', 'submitted_by_type', 'stage__championship')
    search_fields = ('pilot__last_name', 'pilot__first_name', 'submitted_by__email', 'stage__title')
    ordering = ('-created_at',)
    list_select_related = ('stage', 'race_class', 'submitted_by')
    edit_handler = ObjectList([
        FieldPanel('status'), FieldPanel('organizer_comment'),
        FieldPanel('start_number'), FieldPanel('race_class'),
    ])

    def pilot_name(self, obj):
        pilot = _related(obj, 'pilot')
        return pilot.full_name if pilot is not None and hasattr(pilot, 'full_name') else obj.submitted_by.email
    pilot_name.short_description = 'Пилот'

    def status_badge(self, obj):
        bg, fg = STATUS_COLORS.get(obj.status, ('#6c757d', '#fff'))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:4px;font-size:0.85em">{}</span>',
            bg, fg, obj.get_status_display(),
        )
    status_badge.short_description = 'Статус'
