from django import forms
from django.core.exceptions import ValidationError
from website.models import TeamMembership


class MembershipAdminForm(forms.ModelForm):
    confirm_no_account = forms.BooleanField(label='Подтвердить пилота без аккаунта', required=False)
    exception_reason = forms.CharField(label='Основание исключения', required=False, widget=forms.Textarea)

    class Meta:
        model = TeamMembership
        fields = ['driver', 'team', 'race_class', 'is_active', 'left_at']

    def clean(self):
        data = super().clean()
        if data.get('confirm_no_account'):
            from accounts.models import DriverClaim, UserProfile
            driver = data.get('driver')
            if not data.get('exception_reason', '').strip():
                raise ValidationError('Укажите основание подтверждения.')
            if driver and (DriverClaim.objects.filter(driver=driver, status='approved').exists()
                           or UserProfile.objects.filter(driver=driver, verified=True).exists()):
                raise ValidationError('Пилот с аккаунтом должен принять приглашение.')
            if not data.get('is_active') or data.get('left_at'):
                raise ValidationError('Подтверждение возможно только для действующего состава.')
        return data
