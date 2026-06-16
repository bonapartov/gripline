from django.shortcuts import redirect, render
from django.contrib.auth import login
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from .models import DemoSlot


def choose_role(request):
    from accounts.models import SocialAuthSettings
    social_auth = SocialAuthSettings.get()
    return render(request, 'demo/choose_role.html', {'social_auth': social_auth})


REDIRECT_MAP = {
    'organizer': 'organizers:dashboard',
    'pilot': 'accounts:profile',
    'team': 'teams:dashboard',
}

LOGIN_MAP = {
    'organizer': 'organizers:login',
    'pilot': 'accounts:login',
    'team': 'teams:login',
}


def demo_login(request, slot_type):
    if slot_type not in REDIRECT_MAP:
        return redirect('/')

    slots = DemoSlot.objects.filter(slot_type=slot_type).select_related('user').order_by('slot_number')
    free_slot = None
    for slot in slots:
        if slot.is_free():
            free_slot = slot
            break

    if not free_slot:
        messages.error(request, 'Все демо-слоты заняты. Попробуйте через несколько минут.')
        return redirect(LOGIN_MAP[slot_type])

    free_slot.occupy()
    user = free_slot.user

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session.save()

    return HttpResponseRedirect(reverse(REDIRECT_MAP[slot_type]))
