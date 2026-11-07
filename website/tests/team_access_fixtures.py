"""Explicit artificial consent evidence for access regression fixtures."""
from django.contrib.auth.models import User
from django.utils import timezone
from website.models import TeamMembership


def confirmed_membership(**kwargs):
    actor = kwargs.pop('actor', None) or User.objects.create_user(
        username=f'consent-fixture-{TeamMembership.objects.count()}-{User.objects.count()}')
    return TeamMembership.objects.create(confirmation_state='confirmed',
        confirmed_at=timezone.now(), confirmed_by=actor, confirmation_source='invitation', **kwargs)
