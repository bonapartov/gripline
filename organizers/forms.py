from django import forms
from .models import Championship, Stage
from website.models import CompetitionType, RaceClass, Tyre 

# organizers/forms.py
class ChampionshipForm(forms.ModelForm):
    competition_types = forms.ModelMultipleChoiceField(
        queryset=CompetitionType.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Типы соревнований"
    )
    
    race_classes = forms.ModelMultipleChoiceField(
        queryset=RaceClass.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Классы гонок"
    )
    
    default_tyres = forms.ModelMultipleChoiceField(
        queryset=Tyre.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Разрешённые шины",
    )

    class Meta:
        model = Championship
        fields = ['title', 'budget', 'competition_types', 'race_classes', 'tyre_mode', 'default_tyres']
        widgets = {
            'tyre_mode': forms.RadioSelect,
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название чемпионата'}),
            'budget': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Опишите чемпионат...'}),
        }
        labels = {
            'title': 'Название чемпионата',
            'budget': 'Описание',
        }

class StageForm(forms.ModelForm):
    stage_tyres = forms.ModelMultipleChoiceField(
        queryset=Tyre.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Шины для этапа",
    )

    class Meta:
        model = Stage
        fields = [
            'title', 'start_date', 'end_date', 'track', 'entry_fee', 'schedule',
            'registration_enabled', 'registration_deadline',
            'late_registration_allowed', 'late_registration_fee_multiplier',
            'max_participants', 'start_number_digits', 'stage_tyres',
        ]
        widgets = {
            'start_date': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'end_date': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'track': forms.Select(attrs={'class': 'form-control'}),
            'entry_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'min': '0'}),
            'schedule': forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': 'Расписание этапа...'}),
            'registration_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'registration_deadline': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'late_registration_allowed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'late_registration_fee_multiplier': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '1'}),
            'max_participants': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'start_number_digits': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'title': 'Название этапа',
            'start_date': 'Дата и время начала',
            'end_date': 'Дата и время окончания',
            'track': 'Трасса',
            'entry_fee': 'Стартовый взнос (₽)',
            'schedule': 'Расписание этапа',
            'registration_enabled': 'Регистрация открыта',
            'registration_deadline': 'Дедлайн регистрации',
            'late_registration_allowed': 'Допустить позднюю регистрацию',
            'late_registration_fee_multiplier': 'Множитель позднего взноса',
            'max_participants': 'Макс. участников (пусто = без лимита)',
            'start_number_digits': 'Формат стартовых номеров',
        }
        help_texts = {
            'title': 'Используйте формат: "1 этап", "2 этап" и т.д. Название будет отображаться в итоговой таблице',
            'late_registration_fee_multiplier': 'Во сколько раз увеличивается взнос после дедлайна (например, 2 = двойной)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['registration_deadline'].required = False
        self.fields['max_participants'].required = False
        self.fields['track'].required = False

    def clean_entry_fee(self):
        entry_fee = self.cleaned_data.get('entry_fee')
        if entry_fee is not None and entry_fee < 0:
            raise forms.ValidationError('Стартовый взнос не может быть отрицательным')
        return entry_fee


class StageDocumentForm(forms.ModelForm):
    class Meta:
        from applications.models import StageDocument
        model = StageDocument
        fields = ['name', 'description', 'required', 'minors_only', 'has_expiry_date']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Напр. Медицинская справка'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Пояснение (необязательно)'}),
            'required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'minors_only': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_expiry_date': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class StageOptionForm(forms.ModelForm):
    class Meta:
        from applications.models import StageOption
        model = StageOption
        fields = ['name', 'description', 'price', 'is_mandatory', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Напр. Комплект слик'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Описание (необязательно)'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'min': '0'}),
            'is_mandatory': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django import forms as django_forms

class OrganizerRegistrationForm(UserCreationForm):
    email = django_forms.EmailField(required=True)
    first_name = django_forms.CharField(max_length=100, required=True)
    last_name = django_forms.CharField(max_length=100, required=True)
    phone = django_forms.CharField(max_length=30, required=False)
    telegram = django_forms.CharField(max_length=100, required=False)

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
            from .models import OrganizerProfile
            OrganizerProfile.objects.create(
                user=user,
                phone=self.cleaned_data.get('phone', ''),
                telegram=self.cleaned_data.get('telegram', ''),
            )
        return user