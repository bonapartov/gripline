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
    
    default_tyre = forms.ModelChoiceField(
        queryset=Tyre.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Шины по умолчанию"
    )
    
    class Meta:
        model = Championship
        fields = ['title', 'budget', 'competition_types', 'race_classes', 'default_tyre']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название чемпионата'}),
            'budget': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Опишите чемпионат...'}),
        }
        labels = {
            'title': 'Название чемпионата',
            'budget': 'Описание',
        }

class StageForm(forms.ModelForm):
    class Meta:
        model = Stage
        fields = ['title', 'start_date', 'end_date', 'track', 'entry_fee', 'schedule']
        widgets = {
            'start_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'end_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),  # Убрал placeholder
            'track': forms.Select(attrs={'class': 'form-control'}),
            'entry_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'min': '0'}),
            'schedule': forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': 'Расписание этапа...'}),
        }
        labels = {
            'title': 'Название этапа',
            'start_date': 'Дата и время начала',
            'end_date': 'Дата и время окончания',
            'track': 'Трасса',
            'entry_fee': 'Стартовый взнос (₽)',
            'schedule': 'Расписание этапа',
        }
        help_texts = {
            'title': 'Используйте формат: "1 этап", "2 этап" и т.д. Название будет отображаться в итоговой таблице',
        }
    
    def clean_entry_fee(self):
        entry_fee = self.cleaned_data.get('entry_fee')
        if entry_fee is not None and entry_fee < 0:
            raise forms.ValidationError('Стартовый взнос не может быть отрицательным')
        return entry_fee

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