from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from website.models import Team, TeamStaff, TeamSocialLink, TeamStaffSocialLink
import uuid

class TeamRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email")
    team_name = forms.CharField(max_length=255, required=True, label="Название команды")

    class Meta:
        model = User
        fields = ('email', 'team_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        # Используем email как username, но если такой уже есть - добавляем случайный суффикс
        base_username = self.cleaned_data['email'].split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        user.username = username
        user.email = self.cleaned_data['email']

        if commit:
            user.save()
        return user


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['logo', 'description', 'manager_name', 'manager_photo', 'manager_email', 'manager_phone', 'manager_social']
        widgets = {
            'logo': forms.FileInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': 'Расскажите о команде...'}),
            'manager_photo': forms.FileInput(attrs={'class': 'form-control'}),
            'manager_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Иванов Иван Иванович'}),
            'manager_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'manager@team.ru'}),
            'manager_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+7 999 123-45-67'}),
            'manager_social': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://vk.com/id...'}),
        }


class TeamSocialLinkForm(forms.ModelForm):
    class Meta:
        model = TeamSocialLink
        fields = ['network_name', 'link_url']
        widgets = {
            'network_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ВК, Instagram...'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
        }


TeamSocialLinkFormSet = forms.inlineformset_factory(
    Team,
    TeamSocialLink,
    form=TeamSocialLinkForm,
    extra=3,
    can_delete=True,
)


class TeamStaffForm(forms.ModelForm):
    # Добавляем поле для загрузки файла
    photo_upload = forms.ImageField(
        label="Фото сотрудника",
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = TeamStaff
        fields = ['last_name', 'first_name', 'middle_name', 'position', 'biography', 'phone', 'email']
        widgets = {
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Фамилия'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Имя'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Отчество'}),
            'position': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Должность'}),
            'biography': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Краткая информация...'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+7 999 123-45-67'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Если редактируем существующего сотрудника, показываем текущее фото
        if self.instance and self.instance.pk and self.instance.photo:
            self.fields['photo_upload'].help_text = f'Текущее фото: {self.instance.photo.title}'


class TeamStaffSocialLinkForm(forms.ModelForm):
    class Meta:
        model = TeamStaffSocialLink
        fields = ['network_name', 'link_url']
        widgets = {
            'network_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ВК, Instagram...'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
        }


TeamStaffSocialLinkFormSet = forms.inlineformset_factory(
    TeamStaff,
    TeamStaffSocialLink,
    form=TeamStaffSocialLinkForm,
    extra=3,
    can_delete=True,
)
