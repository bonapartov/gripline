from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from website.models import Driver, DriverSocialLink
from wagtail.images.models import Image
from PIL import Image as PILImage
import os

def validate_image_file(value):
    """Проверяет, что файл является изображением допустимого формата"""
    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
    if ext not in valid_extensions:
        raise ValidationError(f'Неподдерживаемый формат файла. Разрешены: {", ".join(valid_extensions)}')

    try:
        image = PILImage.open(value)
        image.verify()
        value.seek(0)
    except Exception:
        raise ValidationError('Файл повреждён или не является изображением')

class DriverProfileForm(forms.ModelForm):
    photo_file = forms.ImageField(
        required=False,
        validators=[validate_image_file],
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        label='Фото профиля'
    )

    class Meta:
        model = Driver
        fields = ['biography']  # Убираем photo из полей
        widgets = {
            'biography': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Если у пилота уже есть фото, показываем его название
        if self.instance and self.instance.photo:
            self.fields['photo_file'].help_text = f'Текущее фото: {self.instance.photo.title}'

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email")
    first_name = forms.CharField(max_length=100, required=True, label="Имя")
    last_name = forms.CharField(max_length=100, required=True, label="Фамилия")
    city = forms.CharField(max_length=100, required=False, label="Город")

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'password1', 'password2', 'city')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']

        if commit:
            user.save()
            profile = user.profile
            profile.city = self.cleaned_data.get('city', '')
            profile.save()

        return user

class DriverSocialLinkForm(forms.ModelForm):
    class Meta:
        model = DriverSocialLink
        fields = ['network_name', 'link_url']
        widgets = {
            'network_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: ВК'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
        }

SocialLinkFormSet = forms.inlineformset_factory(
    Driver,
    DriverSocialLink,
    form=DriverSocialLinkForm,
    extra=3,
    can_delete=True,
)
