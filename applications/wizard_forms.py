"""Формы шагов мастера подачи заявки на этап (applications/wizard.py)."""
from django import forms
from django.contrib.auth.models import User

from .forms import KartForm, MechanicForm, PilotForm
from .models import Application, ApplicationApplicant

_text = {'class': 'form-control'}


class HighlightErrorsMixin:
    """После проверки помечает поля с ошибками классом is-invalid — красная обводка
    (её же ставит на клиенте static/website/js/custom.js до отправки)."""

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                classes = widget.attrs.get('class', '')
                if 'is-invalid' not in classes:
                    widget.attrs['class'] = f'{classes} is-invalid'.strip()


class StepParticipationForm(HighlightErrorsMixin, forms.Form):
    participation = forms.ChoiceField(label='Участие', widget=forms.RadioSelect)
    race_class = forms.ModelChoiceField(label='Класс', queryset=None, empty_label='— выберите класс —',
                                        widget=forms.Select(attrs={'class': 'form-select'}))
    start_number = forms.IntegerField(label='Стартовый номер', required=False, widget=forms.HiddenInput)

    def __init__(self, *args, stage, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage, self.application = stage, application
        choices = stage.participation_choices()
        self.fields['participation'].choices = choices
        self.fields['participation'].initial = choices[0][0]
        if len(choices) == 1:
            self.fields['participation'].widget = forms.HiddenInput()
        self.fields['race_class'].queryset = stage.championship.race_classes.all()

    def clean(self):
        data = super().clean()
        number = data.get('start_number')
        if number is not None and data.get('race_class'):
            available = set(self.stage.get_available_numbers(race_class=data['race_class'],
                                                             participation=data.get('participation')))
            own = self.application.start_number if self.application else None
            if number not in available and number != own:
                self.add_error('start_number', 'Этот номер уже занят. Выберите другой.')
        return data


class StepPilotForm(HighlightErrorsMixin, PilotForm):
    """Данные пилота. Гостю — email (на него создаётся учётная запись); если имя совпало с
    пилотами в базе и профиль не подтверждён — выбор «это я» или «новый пилот»."""

    email_account = forms.EmailField(label='Ваш email', required=False, widget=forms.EmailInput(attrs=_text),
                                     help_text='Сюда придёт решение по заявке. Пароль можно задать позже через «Забыли пароль?».')
    driver_choice = forms.ChoiceField(label='Вы есть в базе пилотов?', required=False, widget=forms.RadioSelect)
    # Выбор из подсказки при вводе фамилии: id пилота из базы или 'new' («нет в списке»).
    driver_pick = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, need_email=False, candidates=(), lock_names=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.need_email = need_email
        self.fields['email_account'].required = need_email
        if not need_email:
            del self.fields['email_account']
        self.candidates = {str(d.id): d for d in candidates}
        if self.candidates:
            self.fields['driver_choice'].choices = (
                [(i, f'{d.full_name}{", " + d.city if d.city else ""}') for i, d in self.candidates.items()]
                + [('new', 'Нет, я новый пилот')])
            self.fields['driver_choice'].required = True
        else:
            del self.fields['driver_choice']
        if lock_names:
            for name in ('first_name', 'last_name'):
                self.fields[name].widget.attrs['readonly'] = True
        for name in ('first_name', 'last_name'):
            self.fields[name].required = True

    PARENT_REQUIRED = ('parent_last_name', 'parent_first_name', 'parent_phone')

    def clean(self):
        data = super().clean()
        birth = data.get('birth_date')
        if birth:
            from datetime import date
            if (date.today() - birth).days / 365.25 < 18:
                for name in self.PARENT_REQUIRED:
                    if not (data.get(name) or '').strip():
                        self.add_error(name, 'Обязательно для несовершеннолетнего пилота.')
        return data

    def clean_email_account(self):
        email = (self.cleaned_data.get('email_account') or '').strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'Этот email уже зарегистрирован. Войдите — заполненные данные сохранятся.', code='email_taken')
        return email

    def clean_driver_pick(self):
        pick = (self.cleaned_data.get('driver_pick') or '').strip()
        if pick.isdigit():
            from website.models import Driver
            from website.services.demo import without_demo
            driver = without_demo(Driver.objects.filter(pk=pick, live=True)).first()
            if driver is None:
                raise forms.ValidationError('Пилот не найден — выберите из списка ещё раз.')
            self.picked_driver = driver
            return pick
        return 'new' if pick == 'new' else ''

    def chosen_driver(self):
        if getattr(self, 'picked_driver', None):
            return self.picked_driver
        choice = self.cleaned_data.get('driver_choice')
        return self.candidates.get(choice) if choice and choice != 'new' else None


class StepKartForm(HighlightErrorsMixin, KartForm):
    pass


class StepMechanicForm(HighlightErrorsMixin, MechanicForm):
    pass


class StepApplicantForm(HighlightErrorsMixin, forms.Form):
    """Заявитель: физлицо или команда — из списка либо новая (вписать вручную)."""

    TEAM_EXISTING, TEAM_NEW = 'existing', 'new'

    type = forms.ChoiceField(label='Заявитель', choices=ApplicationApplicant.TYPE_CHOICES,
                             widget=forms.Select(attrs={'class': 'form-select'}))
    name = forms.CharField(label='ФИО заявителя', required=False, max_length=255, widget=forms.TextInput(attrs=_text))
    license_number = forms.CharField(label='Лицензия заявителя', required=False, max_length=100,
                                     widget=forms.TextInput(attrs=_text))
    team_mode = forms.ChoiceField(choices=[(TEAM_EXISTING, 'Команда из списка'), (TEAM_NEW, 'Новая команда')],
                                  initial=TEAM_EXISTING, required=False, widget=forms.RadioSelect)
    team = forms.ModelChoiceField(label='Команда', queryset=None, required=False, empty_label='— выберите команду —',
                                  widget=forms.Select(attrs={'class': 'form-select'}))
    new_team_name = forms.CharField(label='Название команды', required=False, max_length=255,
                                    widget=forms.TextInput(attrs=_text))
    new_team_city = forms.CharField(label='Город команды', required=False, max_length=100,
                                    widget=forms.TextInput(attrs=_text))
    rep_last_name = forms.CharField(label='Фамилия представителя', required=False, max_length=100,
                                    widget=forms.TextInput(attrs=_text))
    rep_first_name = forms.CharField(label='Имя представителя', required=False, max_length=100,
                                     widget=forms.TextInput(attrs=_text))
    rep_phone = forms.CharField(label='Телефон представителя', required=False, max_length=30,
                                widget=forms.TextInput(attrs=_text))
    rep_email = forms.EmailField(label='Email представителя', required=False, widget=forms.EmailInput(attrs=_text))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from website.models import Team
        self.fields['team'].queryset = Team.objects.order_by('name')

    def clean(self):
        data = super().clean()
        if data.get('type') == 'team':
            if data.get('team_mode') == self.TEAM_NEW:
                # Представитель новой команды — её контакт: после одобрения он менеджер,
                # на его email приходит решение администратора.
                for name in ('new_team_name', 'rep_last_name', 'rep_first_name', 'rep_email'):
                    if not data.get(name):
                        self.add_error(name, 'Обязательное поле.')
            elif not data.get('team'):
                self.add_error('team', 'Выберите команду или укажите новую.')
        elif not (data.get('name') or '').strip():
            self.add_error('name', 'Обязательное поле.')
        return data

    @classmethod
    def initial_from(cls, applicant):
        if applicant is None:
            return {}
        initial = {f: getattr(applicant, f) for f in (
            'type', 'name', 'license_number', 'new_team_city',
            'rep_last_name', 'rep_first_name', 'rep_phone', 'rep_email')}
        if applicant.type == 'team':
            if applicant.team_id:
                initial.update(team_mode=cls.TEAM_EXISTING, team=applicant.team_id)
            else:
                initial.update(team_mode=cls.TEAM_NEW, new_team_name=applicant.name)
        return initial

    def save_to(self, applicant):
        data = self.cleaned_data
        applicant.type = data['type']
        applicant.license_number = data.get('license_number', '')
        for f in ('rep_last_name', 'rep_first_name', 'rep_phone', 'rep_email'):
            setattr(applicant, f, data.get(f) or '')
        applicant.team, applicant.new_team_city, applicant.new_team_email = None, '', ''
        if data['type'] == 'team':
            if data.get('team_mode') == self.TEAM_NEW:
                applicant.name = data['new_team_name'].strip()
                applicant.new_team_city = data.get('new_team_city', '')
                applicant.new_team_email = data['rep_email']
            else:
                applicant.team = data['team']
                applicant.name = data['team'].name
        else:
            applicant.name = data['name'].strip()
        applicant.save()


def participation_label(stage, code):
    return dict(Application.PARTICIPATION_CHOICES).get(code, '') if stage.has_training else ''
