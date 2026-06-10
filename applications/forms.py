from django import forms
from .models import (
    Application, ApplicationApplicant, ApplicationPilot,
    ApplicationKart, ApplicationMechanic,
)

_text = {'class': 'form-control'}
_date = {'class': 'form-control', 'type': 'date'}


class PilotForm(forms.ModelForm):
    class Meta:
        model = ApplicationPilot
        fields = [
            'last_name', 'first_name', 'middle_name', 'citizenship',
            'birth_date', 'sport_rank', 'license_number',
            'email', 'phone', 'city', 'country',
            'parent_last_name', 'parent_first_name', 'parent_middle_name',
            'parent_relation', 'parent_phone', 'parent_email',
        ]
        widgets = {
            'last_name': forms.TextInput(attrs=_text),
            'first_name': forms.TextInput(attrs=_text),
            'middle_name': forms.TextInput(attrs=_text),
            'citizenship': forms.TextInput(attrs=_text),
            'birth_date': forms.DateInput(attrs=_date, format='%Y-%m-%d'),
            'sport_rank': forms.TextInput(attrs=_text),
            'license_number': forms.TextInput(attrs=_text),
            'email': forms.EmailInput(attrs=_text),
            'phone': forms.TextInput(attrs=_text),
            'city': forms.TextInput(attrs=_text),
            'country': forms.TextInput(attrs=_text),
            'parent_last_name': forms.TextInput(attrs=_text),
            'parent_first_name': forms.TextInput(attrs=_text),
            'parent_middle_name': forms.TextInput(attrs=_text),
            'parent_relation': forms.Select(attrs={'class': 'form-select'}),
            'parent_phone': forms.TextInput(attrs=_text),
            'parent_email': forms.EmailInput(attrs=_text),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['birth_date'].input_formats = ['%Y-%m-%d']


class ApplicantForm(forms.ModelForm):
    class Meta:
        model = ApplicationApplicant
        fields = [
            'type', 'name', 'license_number',
            'rep_last_name', 'rep_first_name', 'rep_email', 'rep_phone',
        ]
        widgets = {
            'type': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs=_text),
            'license_number': forms.TextInput(attrs=_text),
            'rep_last_name': forms.TextInput(attrs=_text),
            'rep_first_name': forms.TextInput(attrs=_text),
            'rep_email': forms.EmailInput(attrs=_text),
            'rep_phone': forms.TextInput(attrs=_text),
        }


class KartForm(forms.ModelForm):
    class Meta:
        model = ApplicationKart
        fields = ['chassis_brand', 'engine_1', 'engine_2', 'tires',
                  'transponder_number', 'ad_consent']
        widgets = {
            'chassis_brand': forms.TextInput(attrs=_text),
            'engine_1': forms.TextInput(attrs=_text),
            'engine_2': forms.TextInput(attrs=_text),
            'tires': forms.TextInput(attrs=_text),
            'transponder_number': forms.TextInput(attrs=_text),
            'ad_consent': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MechanicForm(forms.ModelForm):
    class Meta:
        model = ApplicationMechanic
        fields = ['last_name', 'first_name', 'middle_name', 'license_number', 'phone', 'email']
        widgets = {
            'last_name': forms.TextInput(attrs=_text),
            'first_name': forms.TextInput(attrs=_text),
            'middle_name': forms.TextInput(attrs=_text),
            'license_number': forms.TextInput(attrs=_text),
            'phone': forms.TextInput(attrs=_text),
            'email': forms.EmailInput(attrs=_text),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Механик необязателен — все поля опциональны
        for f in self.fields.values():
            f.required = False


def prefill_from_profile(user):
    """Возвращает dict с начальными данными для форм заявки из профиля пользователя"""
    initial_pilot = {}
    initial_kart = {}

    if not user or not user.is_authenticated:
        return {'pilot': initial_pilot, 'kart': initial_kart}

    profile = getattr(user, 'profile', None)
    driver = profile.driver if profile else None

    # Если profile.driver не привязан — ищем через подтверждённую заявку
    if not driver:
        from accounts.models import DriverClaim
        claim = DriverClaim.objects.filter(
            user=user, status='approved'
        ).order_by('-created_at').first()
        if claim and claim.driver:
            driver = claim.driver

    # Имя/фамилия — из Driver, иначе из User
    if driver:
        initial_pilot['first_name'] = driver.first_name
        initial_pilot['last_name'] = driver.last_name
        initial_pilot['city'] = driver.city or ''
    else:
        initial_pilot['first_name'] = user.first_name
        initial_pilot['last_name'] = user.last_name

    initial_pilot['email'] = user.email

    if profile:
        initial_pilot.setdefault('city', profile.city or '')
        initial_pilot['middle_name'] = profile.middle_name
        initial_pilot['birth_date'] = profile.birth_date
        initial_pilot['citizenship'] = profile.citizenship or 'Россия'
        initial_pilot['phone'] = profile.phone
        initial_pilot['license_number'] = profile.license_number
        initial_pilot['sport_rank'] = profile.sport_rank
        initial_pilot['parent_last_name'] = profile.parent_last_name
        initial_pilot['parent_first_name'] = profile.parent_first_name
        initial_pilot['parent_middle_name'] = profile.parent_middle_name
        initial_pilot['parent_relation'] = profile.parent_relation
        initial_pilot['parent_phone'] = profile.parent_phone
        initial_pilot['parent_email'] = profile.parent_email

        initial_kart['chassis_brand'] = profile.default_chassis_brand
        initial_kart['engine_1'] = profile.default_engine
        initial_kart['transponder_number'] = profile.default_transponder

    return {'pilot': initial_pilot, 'kart': initial_kart}


def save_to_profile(user, pilot_data):
    """Сохраняет данные пилота обратно в профиль пользователя"""
    profile = getattr(user, 'profile', None)
    if not profile:
        return
    mapping = {
        'middle_name': 'middle_name',
        'birth_date': 'birth_date',
        'citizenship': 'citizenship',
        'phone': 'phone',
        'license_number': 'license_number',
        'sport_rank': 'sport_rank',
        'parent_last_name': 'parent_last_name',
        'parent_first_name': 'parent_first_name',
        'parent_middle_name': 'parent_middle_name',
        'parent_relation': 'parent_relation',
        'parent_phone': 'parent_phone',
        'parent_email': 'parent_email',
        'city': 'city',
    }
    for src, dst in mapping.items():
        val = pilot_data.get(src)
        if val:
            setattr(profile, dst, val)
    profile.save()
