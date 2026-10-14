"""Заявки на участие в этапах — в админке Wagtail (группа «Организаторы»).

Заявки создают и заполняют пилоты, команды и организаторы в своих кабинетах, поэтому
здесь они не создаются. Карточка редактирования (ApplicationEditView) содержит все поля
регистрации: саму заявку, заявителя, пилота, карт, механика, оплату, статусы документов,
достижения и выбранные опции. Файлы документов и квитанций здесь не показываются и не
меняются — их отдают только serve_document/serve_receipt (см. model_rows).
Сама группа меню — organizers/wagtail_hooks.py (OrganizersGroup).
"""
from django.db import models as dj_models
from django.utils.html import format_html
from django.utils.text import capfirst
from wagtail.admin.panels import FieldPanel, ObjectList
from wagtail_modeladmin.helpers import PermissionHelper
from wagtail_modeladmin.options import ModelAdmin
from django import forms
from django.contrib import messages
from django.db import transaction
from django.forms import inlineformset_factory
from wagtail_modeladmin.views import EditView, InspectView

from .forms import ApplicantForm, KartForm, MechanicForm, PilotForm
from .models import (
    Application, ApplicationAchievement, ApplicationDocument, ApplicationOption, ApplicationPayment,
)

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


class PaymentForm(forms.ModelForm):
    class Meta:
        model = ApplicationPayment
        fields = ['amount', 'method', 'status', 'organizer_comment']


class DocumentStatusForm(forms.ModelForm):
    class Meta:
        model = ApplicationDocument
        fields = ['status', 'expiry_date', 'organizer_comment']
        widgets = {'expiry_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'organizer_comment': forms.Textarea(attrs={'rows': 2})}


DocumentFormSet = inlineformset_factory(Application, ApplicationDocument, form=DocumentStatusForm,
                                        extra=0, can_delete=False)
AchievementFormSet = inlineformset_factory(Application, ApplicationAchievement,
                                           fields=['competition_name', 'year', 'achievement', 'order'],
                                           extra=1, can_delete=True)


class ApplicationEditView(EditView):
    """Карточка заявки со всеми полями регистрации. Связанные записи (OneToOne) —
    отдельные формы рядом с основной; сохраняется всё вместе или ничего."""

    # (имя связи, заголовок, форма, обязательна ли запись). Необязательную пустую
    # запись не создаём: у командных заявок, например, нет карта и заявителя-лица.
    # Пилот обязателен — заявка без пилота не подаётся.
    RELATED = (
        ('applicant', 'Заявитель', ApplicantForm, False),
        ('pilot', 'Пилот', PilotForm, True),
        ('kart', 'Карт', KartForm, False),
        ('mechanic', 'Механик (необязательно)', MechanicForm, False),
        ('payment', 'Оплата', PaymentForm, True),
    )

    def _data(self):
        return self.request.POST if self.request.method == 'POST' else None

    def build_related(self):
        if hasattr(self, '_related_forms'):
            return self._related_forms
        app, data = self.instance, self._data()
        sections = []
        for name, title, form_class, required in self.RELATED:
            obj = _related(app, name)
            initial = {'amount': app.get_total_amount()} if name == 'payment' and obj is None else None
            form = form_class(data, prefix=name, instance=obj, initial=initial)
            form.use_required_attribute = False
            sections.append({'name': name, 'title': title, 'form': form, 'required': required, 'exists': obj is not None})
        self._related_forms = {
            'sections': sections,
            'documents': DocumentFormSet(data, instance=app, prefix='docs',
                                         queryset=app.documents.select_related('stage_document')),
            'achievements': AchievementFormSet(data, instance=app, prefix='ach'),
        }
        return self._related_forms

    def stage_options(self):
        selected = set(self.instance.selected_options.values_list('option_id', flat=True))
        return [(opt, opt.id in selected) for opt in self.instance.stage.options.all()]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['related'] = self.build_related()
        context['stage_options'] = self.stage_options()
        return context

    def _section_valid(self, section):
        form = section['form']
        # Пустую необязательную запись (механик) не создаём и не проверяем.
        if not section['required'] and not section['exists'] and not any(
                (form.data.get(f'{form.prefix}-{f}') or '').strip() for f in form.fields):
            section['skip'] = True
            return True
        return form.is_valid()

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        related = self.build_related()
        valid = form.is_valid()
        valid = all([self._section_valid(s) for s in related['sections']]) and valid
        valid = related['documents'].is_valid() and valid
        valid = related['achievements'].is_valid() and valid
        if not valid:
            return self.form_invalid(form)
        with transaction.atomic():
            response = self.form_valid(form)
            app = self.instance
            for section in related['sections']:
                if section.get('skip'):
                    continue
                obj = section['form'].save(commit=False)
                obj.application = app
                obj.save()
            related['documents'].save()
            related['achievements'].instance = app
            related['achievements'].save()
            self._save_options(app, request.POST.getlist('options'))
        return response

    def _save_options(self, app, chosen_ids):
        chosen = {int(i) for i in chosen_ids if str(i).isdigit()}
        current = {o.option_id: o for o in app.selected_options.all()}
        for option_id, row in current.items():
            if option_id not in chosen:
                row.delete()
        for opt in app.stage.options.filter(id__in=chosen - set(current)):
            ApplicationOption.objects.create(application=app, option=opt, price_at_time=opt.price)


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
    edit_view_class = ApplicationEditView
    edit_template_name = 'applications/admin/application_edit.html'
    list_display = ('id', 'pilot_name', 'stage', 'race_class', 'start_number', 'status_badge', 'submitted_by_type', 'created_at')
    list_filter = ('status', 'submitted_by_type', 'stage__championship')
    search_fields = ('pilot__last_name', 'pilot__first_name', 'submitted_by__email', 'stage__title')
    ordering = ('-created_at',)
    list_select_related = ('stage', 'race_class', 'submitted_by')
    edit_handler = ObjectList([
        FieldPanel('status'), FieldPanel('participation'), FieldPanel('race_class'), FieldPanel('start_number'),
        FieldPanel('entry_fee_amount'), FieldPanel('submitted_by_type'), FieldPanel('organizer_comment'),
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
