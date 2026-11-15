"""Правила доступа команды: подтверждённый состав, результат, приглашения и менеджеры.

Решение владельца 15.11.2026: результат пилота за команду подтверждает членство
автоматически. При этом активная, но неподтверждённая связь (ручной/исторический
состав) остаётся видимой, но не даёт операционного доступа к личным данным.
"""
import datetime as dt

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Locale, Page, Site

from accounts.models import DriverClaim
from website.models import (Driver, EventPage, RaceClass, RaceClassResultGroup,
                            RaceResult, Team, TeamMembership, Track)
from website.services.team_access import (allowed_driver_ids, can_access_team_vault,
                                         confirmed_memberships, has_confirmed_membership,
                                         is_team_manager)

from .models import TeamInvitation, TeamJoinRequest, TeamManager


def make_user(email='mgr@example.com'):
    return User.objects.create_user(email, email, 'pw')


def make_driver(first='Анна', last='Иванова', slug=None):
    return Driver.objects.create(first_name=first, last_name=last,
                                 slug=slug or first.lower() + last.lower())


def make_membership(driver, team, *, active=True, confirmed=True, source='legacy'):
    return TeamMembership.objects.create(
        driver=driver, team=team, is_active=active,
        confirmed_at=timezone.now() if confirmed else None,
        confirmation_source=source if confirmed else '',
    )


def make_site():
    """--no-migrations: шаблоны coderedcms читают Site и LayoutSettings."""
    Locale.objects.get_or_create(language_code='ru')
    root = Page.get_first_root_node() or Page.add_root(title='Root', slug='root')
    return Site.objects.get_or_create(hostname='testserver', defaults={
        'root_page': root, 'is_default_site': True})


def make_event_group(title, slug):
    Locale.objects.get_or_create(language_code='ru')
    root = Page.get_first_root_node() or Page.add_root(title='Root', slug='root')
    track = Track.objects.create(name='Трасса', slug='trassa-' + slug, live=True)
    klass = RaceClass.objects.create(name='Мини')
    page = root.add_child(instance=EventPage(
        title=title, slug=slug, track=track, live=True,
        first_published_at=timezone.now()))
    return RaceClassResultGroup.objects.create(page=page, race_class=klass)


class TeamAccessServiceTests(TestCase):
    def setUp(self):
        self.team_a = Team.objects.create(name='Альфа', slug='alfa')
        self.team_b = Team.objects.create(name='Бета', slug='beta')
        self.driver = make_driver()

    def test_only_confirmed_active_membership_grants_access(self):
        membership = make_membership(self.driver, self.team_a, confirmed=False)
        self.assertFalse(has_confirmed_membership(self.driver.id, self.team_a.id))
        self.assertFalse(confirmed_memberships(team_ids=[self.team_a.id]).exists())

        membership.confirm(source='admin')
        membership.save()
        self.assertTrue(has_confirmed_membership(self.driver.id, self.team_a.id))

        membership.is_active = False
        membership.save()
        self.assertFalse(has_confirmed_membership(self.driver.id, self.team_a.id))

    def test_inactive_membership_is_not_granted(self):
        make_membership(self.driver, self.team_a, active=False)
        self.assertFalse(has_confirmed_membership(self.driver.id, self.team_a.id))
        self.assertEqual(confirmed_memberships(team_ids=[self.team_a.id]).count(), 0)

    def test_manager_sees_only_own_team_roster(self):
        manager_a = make_user('a@example.com')
        TeamManager.objects.create(user=manager_a, team=self.team_a, is_active=True)
        make_membership(self.driver, self.team_a)
        other_driver = make_driver('Борис', 'Смирнов', 'boris')
        make_membership(other_driver, self.team_b)

        self.assertTrue(is_team_manager(manager_a, self.team_a.id))
        self.assertFalse(is_team_manager(manager_a, self.team_b.id))
        self.assertTrue(can_access_team_vault(manager_a, self.team_a.id, self.driver.id))
        self.assertFalse(can_access_team_vault(manager_a, self.team_b.id, self.driver.id))

    def test_setupkart_allowed_drivers_exclude_unconfirmed_members(self):
        manager = make_user('mgr@example.com')
        TeamManager.objects.create(user=manager, team=self.team_a, is_active=True)
        membership = make_membership(self.driver, self.team_a, confirmed=False)

        self.assertNotIn(self.driver.id, allowed_driver_ids(manager))
        membership.confirm(source='admin')
        membership.save()
        self.assertIn(self.driver.id, allowed_driver_ids(manager))

    def test_setupkart_allowed_drivers_include_own_verified_driver(self):
        user = make_user('pilot@example.com')
        driver = make_driver('Пётр', 'Петров', 'petr')
        profile = user.profile
        profile.driver = driver
        profile.verified = True
        profile.save()
        self.assertIn(driver.id, allowed_driver_ids(user))
        profile.verified = False
        profile.save()
        self.assertNotIn(driver.id, allowed_driver_ids(user))


class RaceResultConfirmationTests(TestCase):
    def setUp(self):
        self.group = make_event_group('Этап', 'etap')
        self.team = Team.objects.create(name='Альфа', slug='alfa')
        self.driver = make_driver()

    def result(self):
        return RaceResult.objects.create(group=self.group, driver=self.driver,
                                         team=self.team, position=1)

    def test_result_creates_confirmed_membership(self):
        self.result()
        membership = TeamMembership.objects.get(driver=self.driver, team=self.team)
        self.assertTrue(membership.is_active)
        self.assertTrue(membership.is_confirmed)
        self.assertEqual(membership.confirmation_source, 'result')
        self.assertIn('результатом', membership.confirmation_note)

    def test_result_confirms_existing_unconfirmed_membership(self):
        membership = make_membership(self.driver, self.team, confirmed=False)
        self.result()
        membership.refresh_from_db()
        self.assertTrue(membership.is_confirmed)
        self.assertEqual(membership.confirmation_source, 'result')
        self.assertEqual(TeamMembership.objects.count(), 1)

    def test_result_returns_excluded_membership_to_roster(self):
        membership = make_membership(self.driver, self.team, active=False)
        membership.left_at = timezone.now().date()
        membership.save()
        self.result()
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)
        self.assertIsNone(membership.left_at)
        self.assertEqual(membership.confirmation_source, 'result')

    def test_result_does_not_overwrite_existing_confirmation(self):
        confirmed_at = timezone.now() - dt.timedelta(days=10)
        membership = make_membership(self.driver, self.team, source='admin')
        TeamMembership.objects.filter(pk=membership.pk).update(confirmed_at=confirmed_at)
        self.result()
        membership.refresh_from_db()
        self.assertEqual(membership.confirmed_at, confirmed_at)
        self.assertEqual(membership.confirmation_source, 'admin')


class InvitationFlowTests(TestCase):
    def setUp(self):
        make_site()
        self.team = Team.objects.create(name='Альфа', slug='alfa')
        self.manager = make_user('mgr@example.com')
        TeamManager.objects.create(user=self.manager, team=self.team, is_active=True)
        self.driver = make_driver()
        self.pilot = make_user('pilot@example.com')
        DriverClaim.objects.create(user=self.pilot, driver=self.driver, status='approved',
                                  requested_first_name='Анна', requested_last_name='Иванова')
        self.invitation = TeamInvitation.objects.create(
            team=self.team, driver=self.driver, invited_by=self.manager, status='pending')

    def test_get_accept_only_shows_confirmation(self):
        self.client.force_login(self.pilot)
        resp = self.client.get(reverse('teams:accept_invitation', args=[self.invitation.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'teams/invitation_confirm.html')
        self.assertFalse(TeamMembership.objects.exists())
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, 'pending')

    def test_post_accept_confirms_membership(self):
        self.client.force_login(self.pilot)
        resp = self.client.post(reverse('teams:accept_invitation', args=[self.invitation.pk]))
        self.assertRedirects(resp, reverse('accounts:profile'), fetch_redirect_response=False)
        membership = TeamMembership.objects.get(driver=self.driver, team=self.team)
        self.assertTrue(membership.is_active and membership.is_confirmed)
        self.assertEqual(membership.confirmation_source, 'invitation')
        self.assertEqual(membership.confirmed_by, self.pilot)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, 'accepted')
        self.assertIsNotNone(self.invitation.responded_at)

    def test_get_decline_only_shows_confirmation(self):
        self.client.force_login(self.pilot)
        resp = self.client.get(reverse('teams:decline_invitation', args=[self.invitation.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'teams/invitation_confirm.html')
        self.assertFalse(TeamMembership.objects.exists())
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, 'pending')

    def test_post_decline_does_not_create_membership(self):
        self.client.force_login(self.pilot)
        resp = self.client.post(reverse('teams:decline_invitation', args=[self.invitation.pk]))
        self.assertRedirects(resp, reverse('accounts:profile'), fetch_redirect_response=False)
        self.assertFalse(TeamMembership.objects.exists())
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, 'declined')

    def test_other_user_cannot_accept_invitation(self):
        stranger = make_user('stranger@example.com')
        self.client.force_login(stranger)
        resp = self.client.post(reverse('teams:accept_invitation', args=[self.invitation.pk]))
        self.assertRedirects(resp, reverse('accounts:profile'), fetch_redirect_response=False)
        self.assertFalse(TeamMembership.objects.exists())
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, 'pending')

    def test_processed_invitation_is_not_changed_again(self):
        TeamInvitation.objects.filter(pk=self.invitation.pk).update(status='accepted')
        self.client.force_login(self.pilot)
        self.client.post(reverse('teams:accept_invitation', args=[self.invitation.pk]))
        self.assertFalse(TeamMembership.objects.exists())


class JoinRequestTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name='Альфа', slug='alfa')
        self.manager = make_user('mgr@example.com')
        TeamManager.objects.create(user=self.manager, team=self.team, is_active=True)
        self.driver = make_driver()
        self.join_request = TeamJoinRequest.objects.create(
            team=self.team, driver=self.driver, status='pending')
        self.client.force_login(self.manager)

    def test_approval_creates_confirmed_membership(self):
        resp = self.client.post(reverse('teams:approve_request', args=[self.join_request.pk]))
        self.assertRedirects(resp, reverse('teams:dashboard'), fetch_redirect_response=False)
        membership = TeamMembership.objects.get(driver=self.driver, team=self.team)
        self.assertTrue(membership.is_active and membership.is_confirmed)
        self.assertEqual(membership.confirmation_source, 'join_request')
        self.assertEqual(membership.confirmed_by, self.manager)
        self.join_request.refresh_from_db()
        self.assertEqual(self.join_request.status, 'approved')
        self.assertEqual(self.join_request.reviewed_by, self.manager)

    def test_wrong_manager_cannot_approve(self):
        other_team = Team.objects.create(name='Бета', slug='beta')
        stranger = make_user('stranger@example.com')
        TeamManager.objects.create(user=stranger, team=other_team, is_active=True)
        self.client.force_login(stranger)
        self.client.post(reverse('teams:approve_request', args=[self.join_request.pk]))
        self.assertFalse(TeamMembership.objects.exists())
        self.join_request.refresh_from_db()
        self.assertEqual(self.join_request.status, 'pending')


class TeamScopedManagerTests(TestCase):
    def setUp(self):
        make_site()
        self.team_a = Team.objects.create(name='Альфа', slug='alfa')
        self.team_b = Team.objects.create(name='Бета', slug='beta')
        self.manager = make_user('mgr@example.com')
        TeamManager.objects.create(user=self.manager, team=self.team_a, is_active=True)
        TeamManager.objects.create(user=self.manager, team=self.team_b, is_active=True)
        self.driver = make_driver()
        self.membership = make_membership(self.driver, self.team_a)
        self.client.force_login(self.manager)

    def test_multiteam_dashboard_offers_choice(self):
        resp = self.client.get(reverse('teams:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'teams/choose_team.html')
        self.assertContains(resp, 'Альфа')
        self.assertContains(resp, 'Бета')

    def test_selected_team_is_remembered(self):
        resp = self.client.get(reverse('teams:dashboard') + f'?team={self.team_a.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'teams/dashboard.html')
        self.assertEqual(resp.context['team'], self.team_a)

        resp = self.client.get(reverse('teams:dashboard'))
        self.assertTemplateUsed(resp, 'teams/dashboard.html')
        self.assertEqual(resp.context['team'], self.team_a)

    def test_action_without_selected_team_is_rejected(self):
        self.client.post(reverse('teams:remove_driver', args=[self.driver.id]))
        self.membership.refresh_from_db()
        self.assertTrue(self.membership.is_active)

    def test_action_cannot_target_another_team(self):
        self.client.post(reverse('teams:remove_driver', args=[self.driver.id]),
                         {'team_id': self.team_b.id})
        self.membership.refresh_from_db()
        self.assertTrue(self.membership.is_active)

    def test_action_applies_to_selected_own_team(self):
        self.client.post(reverse('teams:remove_driver', args=[self.driver.id]),
                         {'team_id': self.team_a.id})
        self.membership.refresh_from_db()
        self.assertFalse(self.membership.is_active)

    def test_dashboard_marks_unconfirmed_member(self):
        TeamMembership.objects.filter(pk=self.membership.pk).update(
            confirmed_at=None, confirmation_source='')
        resp = self.client.get(reverse('teams:dashboard') + f'?team={self.team_a.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Доступ не подтверждён')

    def test_invite_allows_active_unconfirmed_membership(self):
        TeamMembership.objects.filter(pk=self.membership.pk).update(
            confirmed_at=None, confirmation_source='')
        DriverClaim.objects.create(
            user=make_user('pilot@example.com'), driver=self.driver, status='approved',
            requested_first_name='Анна', requested_last_name='Иванова')
        self.client.post(reverse('teams:invite_driver'), {
            'team_id': self.team_a.id, 'driver_id': self.driver.id})
        self.assertTrue(TeamInvitation.objects.filter(
            team=self.team_a, driver=self.driver, status='pending').exists())


class TeamVaultAccessTests(TestCase):
    def test_unconfirmed_roster_is_not_operational(self):
        team = Team.objects.create(name='Альфа', slug='alfa')
        driver = make_driver()
        make_membership(driver, team, confirmed=False)
        manager = make_user()
        TeamManager.objects.create(user=manager, team=team, is_active=True)
        self.assertFalse(can_access_team_vault(manager, team.id, driver.id))
