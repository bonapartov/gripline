"""Artificial-data acceptance matrix for team access spec v0.2."""
import json
from itertools import product
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.utils import timezone

from accounts.models import DriverClaim, PilotDocument
from applications import vault
from applications.models import Application, ApplicationPilot, StageDocument, TeamStageEntry
from applications.test_wizard import WizardFixture
from teams.access import (can_manage_driver, confirm_membership, end_membership,
                          managed_driver_ids, operational_memberships)
from teams.audit import audit_memberships
from teams.models import MembershipConfirmation, TeamInvitation, TeamManager
from website.models import AppSyncRecord, Driver, RaceResult, Team, TeamMembership
from website.setupkart.auth import account_payload
from website.setupkart.session_views import can_view, team_sessions_qs
from website.setupkart.sync import allowed_driver_ids
from website.tests.team_access_fixtures import confirmed_membership
from website.tests.test_setupkart_sync import make_user, push, session_row, token_for


@pytest.fixture
def roster(db, settings):
    settings.TEAM_ACCESS_LEGACY_ENABLED = False
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    from wagtail.models import Locale, Page, Site
    Locale.objects.get_or_create(language_code='ru')
    Site.objects.create(hostname='testserver', root_page=Page.add_root(title='Root', slug='root'), is_default_site=True)
    driver = Driver.objects.create(first_name='Pilot', last_name='Synthetic')
    pilot = make_user('pilot@example.test', driver)
    pilot.refresh_from_db()
    manager = make_user('manager@example.test')
    team = Team.objects.create(name='Synthetic Team')
    tm = TeamManager.objects.create(user=manager, team=team)
    membership = TeamMembership.objects.create(driver=driver, team=team)
    invitation = TeamInvitation.objects.create(driver=driver, team=team, invited_by=manager)
    return driver, pilot, manager, team, tm, membership, invitation


def accept(client, roster):
    client.force_login(roster[1])
    return client.post(f'/teams/invitation/{roster[6].pk}/accept/')


def test_active_unconfirmed_denies_all_scopes(roster):
    driver, pilot, manager, team, _, m, _ = roster
    assert not can_manage_driver(manager, team.pk, driver.pk)
    assert driver.pk not in allowed_driver_ids(manager)
    assert account_payload(manager)['team_pilots'] == []
    assert driver.pk in allowed_driver_ids(pilot)
    rec = AppSyncRecord.objects.create(user=pilot, driver=driver, table='sessions', uuid='private', data={}, client_updated_at=1, server_updated_at=timezone.now())
    assert not can_view(manager, rec)
    assert can_view(pilot, rec)


def test_get_safe_and_post_idempotent(client, roster):
    client.force_login(roster[1])
    url = f'/teams/invitation/{roster[6].pk}/accept/'
    assert client.get(url).status_code == 200
    roster[5].refresh_from_db()
    assert roster[5].confirmation_state == 'unconfirmed'
    assert not MembershipConfirmation.objects.exists()
    assert client.post(url).status_code == 302
    assert client.post(url).status_code == 302
    assert MembershipConfirmation.objects.count() == 1
    assert TeamMembership.objects.count() == 1
    m = TeamMembership.objects.get()
    assert m.confirmed_by == roster[1] and m.confirmation_source == 'invitation'
    assert can_manage_driver(roster[2], roster[3].pk, roster[0].pk)


def test_invitation_wrong_user_or_unapproved_claim(client, roster):
    client.force_login(roster[2])
    url = f'/teams/invitation/{roster[6].pk}/accept/'
    assert client.post(url).status_code == 404
    DriverClaim.objects.filter(user=roster[1]).update(status='pending')
    client.force_login(roster[1])
    assert client.post(url).status_code == 404
    assert not MembershipConfirmation.objects.exists()


def test_invitation_requires_csrf(roster):
    client = Client(enforce_csrf_checks=True)
    client.force_login(roster[1])
    assert client.post(f'/teams/invitation/{roster[6].pk}/accept/').status_code == 403


@pytest.mark.parametrize('visible,global_visible', list(product([False, True], repeat=2)))
def test_visibility_both_flags_and_owner(client, roster, visible, global_visible):
    accept(client, roster)
    driver, pilot, manager, *_ = roster
    pilot.profile.app_sessions_team = global_visible
    pilot.profile.save()
    rec = AppSyncRecord.objects.create(user=pilot, driver=driver, table='sessions', uuid='s', data={}, client_updated_at=1, server_updated_at=timezone.now(), visible_to_team=visible)
    assert can_view(manager, rec) == (visible and global_visible)
    assert can_view(pilot, rec)
    client.force_login(manager)
    assert client.get('/accounts/app-sessions/s/').status_code == (200 if visible and global_visible else 404)


@pytest.mark.parametrize('revoke', ['membership', 'manager'])
def test_revocation_next_request_and_cache(client, roster, settings, revoke):
    settings.WAGTAIL_CACHE = True
    from django.core.cache import cache
    cache.clear()
    accept(client, roster)
    driver, pilot, manager, _, tm, m, _ = roster
    rec = AppSyncRecord.objects.create(user=pilot, driver=driver, table='sessions', uuid='warm', data={}, client_updated_at=1, server_updated_at=timezone.now())
    client.force_login(manager)
    assert client.get('/accounts/app-sessions/warm/').status_code == 200
    assert 'no-cache' in client.get('/accounts/app-sessions/warm/')['Cache-Control']
    if revoke == 'membership':
        end_membership(m)
    else:
        tm.is_active = False
        tm.save()
    assert client.get('/accounts/app-sessions/warm/').status_code == 404
    assert driver.pk not in allowed_driver_ids(manager)
    assert not can_view(manager, rec)
    client.logout()
    assert client.get('/accounts/app-sessions/warm/').status_code == 302
    client.force_login(pilot)
    assert client.get('/accounts/app-sessions/warm/').status_code == 200


def test_decline_leave_reinvite_requires_fresh_consent(client, roster):
    driver, pilot, manager, team, _, m, inv = roster
    client.force_login(pilot)
    assert client.get(f'/teams/invitation/{inv.pk}/decline/').status_code == 405
    assert client.post(f'/teams/invitation/{inv.pk}/decline/').status_code == 302
    assert not operational_memberships().exists()
    inv.status = 'pending'
    inv.save()
    accept(client, roster)
    assert client.get(f'/teams/membership/{m.pk}/leave/').status_code == 405
    client.post(f'/teams/membership/{m.pk}/leave/')
    assert not operational_memberships().exists()
    # Replaying an old accepted invitation cannot restore access.
    accept(client, roster)
    assert not operational_memberships().exists()
    client.force_login(manager)
    with patch('teams.views._send_team_invitation_email'):
        client.post('/teams/invite-driver/', {'driver_id':driver.pk, 'team_id':team.pk})
    inv.refresh_from_db()
    assert inv.status == 'pending'
    accept(client, roster)
    assert operational_memberships().count() == 1
    assert MembershipConfirmation.objects.count() == 2


def test_multiteam_scope_and_remove(client, roster):
    driver, _, manager, team, _, m, _ = roster
    accept(client, roster)
    other = Team.objects.create(name='Other')
    foreign = Driver.objects.create(first_name='Foreign', last_name='Pilot')
    confirmed_membership(driver=foreign, team=other)
    assert foreign.pk not in managed_driver_ids(manager)
    assert not can_manage_driver(manager, other.pk, driver.pk)
    TeamManager.objects.create(user=manager, team=other)
    assert foreign.pk in managed_driver_ids(manager)
    assert not can_manage_driver(manager, other.pk, driver.pk)
    client.force_login(manager)
    assert client.post(f'/teams/remove-driver/{driver.pk}/').status_code == 403
    assert client.post(f'/teams/remove-driver/{driver.pk}/', {'team_id': other.pk}).status_code == 302
    assert can_manage_driver(manager, team.pk, driver.pk)
    client.post(f'/teams/remove-driver/{driver.pk}/', {'team_id': team.pk})
    assert not can_manage_driver(manager, team.pk, driver.pk)


def test_admin_exception_and_log(roster):
    driver, _, manager, team, _, m, _ = roster
    admin = User.objects.create_superuser('admin', 'admin@example.test', 'x')
    with pytest.raises(ValidationError):
        confirm_membership(m, admin, 'admin_exception', 'Documented exception')
    DriverClaim.objects.filter(driver=driver).delete()
    profile = roster[1].profile
    profile.driver = None
    profile.verified = False
    profile.save()
    with pytest.raises(PermissionDenied):
        confirm_membership(m, manager, 'admin_exception', 'Reason')
    with pytest.raises(ValidationError):
        confirm_membership(m, admin, 'admin_exception')
    confirm_membership(m, admin, 'admin_exception', 'Synthetic no-account verification')
    event = MembershipConfirmation.objects.get()
    assert event.actor == admin and event.reason == 'Synthetic no-account verification'
    assert can_manage_driver(manager, team.pk, driver.pk)


def test_manual_deactivate_reactivate_cannot_restore_evidence(client, roster):
    accept(client, roster)
    m = TeamMembership.objects.get()
    m.is_active = False
    m.save(update_fields=['is_active'])
    m.is_active = True
    m.left_at = None
    m.save()
    assert m.confirmation_state == 'unconfirmed'
    assert not operational_memberships().exists()
    assert MembershipConfirmation.objects.count() == 1


def test_sync_forgery_keeps_record_without_driver(client, roster):
    driver, _, manager, *_ = roster
    auth = token_for(manager)
    assert push(client, auth, sessions=[session_row('forged',driver_id=driver.pk)]).json()['accepted'] == 1
    assert AppSyncRecord.objects.get(uuid='forged').driver_id is None
    accept(client, roster)
    push(client, auth, sessions=[session_row('allowed',driver_id=driver.pk)])
    assert AppSyncRecord.objects.get(uuid='allowed').driver_id == driver.pk


def test_legacy_compatibility_is_separate_explicit_risk(roster, settings):
    m = roster[5]
    m.confirmation_state = 'legacy'
    m.save()
    assert not operational_memberships().exists()
    settings.TEAM_ACCESS_LEGACY_ENABLED = True
    assert operational_memberships().count() == 1
    assert TeamMembership.objects.get().confirmed_at is None
    TeamMembership.objects.create(driver=roster[0], team=Team.objects.create(name='New'))
    assert operational_memberships().count() == 1


@pytest.mark.django_db(transaction=True)
def test_audit_readonly_and_conservative(client, roster):
    from io import StringIO
    m, inv = roster[5:]
    inv.status = 'accepted'
    inv.responded_at = timezone.now()
    inv.save()
    initial = list(TeamMembership.objects.values())
    out = StringIO()
    call_command('audit_team_access', '--dry-run', stdout=out)
    result = json.loads(out.getvalue())
    assert result['dry_run'] and result['counts']['ambiguous'] == 1
    assert result['memberships'][0]['classification'] == 'ambiguous'
    assert initial == list(TeamMembership.objects.values())
    m.is_active = False
    m.left_at = timezone.localdate()
    m.save()
    assert 'ended_membership' in audit_memberships()['memberships'][0]['reasons']


class VaultBoundaryTests(WizardFixture):
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user('mgr', 'mgr@example.test')
        self.team = Team.objects.create(name='Team')
        self.tm = TeamManager.objects.create(user=self.manager, team=self.team)
        self.driver = Driver.objects.create(first_name='Pilot', last_name='Synthetic')
        self.pilot = make_user('pilot@example.test', self.driver)
        self.membership = confirmed_membership(driver=self.driver, team=self.team, actor=self.pilot)
        self.entry = TeamStageEntry.objects.create(team=self.team, stage=self.stage, created_by=self.manager)
        self.app = Application.objects.create(stage=self.stage, team_entry=self.entry,
            submitted_by=self.manager, submitted_by_type='team', race_class=self.mini, status='submitted')
        ApplicationPilot.objects.create(application=self.app, driver=self.driver,
            first_name='Pilot', last_name='Synthetic', birth_date='2000-01-01')

    def test_vault_and_application_copies_have_different_lifetimes(self):
        import tempfile
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            license = StageDocument.objects.create(stage=self.stage, kind='license')
            personal = PilotDocument.objects.create(profile=self.pilot.profile, kind='license',
                file=SimpleUploadedFile('license.pdf', b'%PDF-1.4 synthetic'), expiry_date='2035-01-01')
            vault.create_document_rows(self.app, False, actor=self.manager)
            doc = self.app.documents.get(stage_document=license)
            assert doc.file and vault.team_pilot_profile(self.app, actor=self.manager)
            self.client.force_login(self.manager)
            # Use URL reverse so this is tied to the repository's actual direct endpoint.
            from django.urls import reverse
            response = self.client.get(reverse('applications:serve_document', args=[doc.pk]))
            assert response.status_code == 200
            for closer in response._resource_closers:
                closer()
            end_membership(self.membership)
            assert vault.team_pilot_profile(self.app, actor=self.manager) is None
            response = self.client.get(reverse('applications:serve_document', args=[doc.pk]))
            assert response.status_code == 200
            for closer in response._resource_closers:
                closer()
            assert PilotDocument.objects.filter(pk=personal.pk).exists()
            # Replacement of an old application copy must not write into current vault.
            assert vault.save_from_application(doc, actor=self.manager) is None
            assert self.client.get(reverse('accounts:serve_pilot_document', args=[personal.pk])).status_code == 404
            self.tm.is_active = False
            self.tm.save()
            assert self.client.get(reverse('applications:serve_document', args=[doc.pk])).status_code == 403
            self.client.force_login(self.organizer.user)
            response = self.client.get(reverse('applications:serve_document', args=[doc.pk]))
            assert response.status_code == 200
            for closer in response._resource_closers:
                closer()

    def test_unconfirmed_membership_has_no_vault_even_if_active(self):
        TeamMembership.objects.filter(pk=self.membership.pk).update(confirmation_state='unconfirmed')
        assert vault.team_pilot_profile(self.app, actor=self.manager) is None

    def test_other_active_manager_can_use_vault_after_submitter_deactivation(self):
        other = User.objects.create_user('colleague', 'colleague@example.test')
        TeamManager.objects.create(user=other, team=self.team)
        self.tm.is_active = False
        self.tm.save()
        assert vault.team_pilot_profile(self.app, actor=self.manager) is None
        assert vault.team_pilot_profile(self.app, actor=other) is not None

    def test_wrong_team_even_when_manager_manages_both(self):
        other = Team.objects.create(name='Other')
        TeamManager.objects.create(user=self.manager, team=other)
        self.entry.team = other
        self.entry.save()
        assert vault.team_pilot_profile(self.app, actor=self.manager) is None

    def test_old_result_never_creates_or_reactivates_membership(self):
        from wagtail.models import Page
        from website.models import EventPage, RaceClassResultGroup
        page = Page.get_first_root_node().add_child(instance=EventPage(title='Synthetic race', slug='race'))
        group = RaceClassResultGroup.objects.create(page=page, race_class=self.mini)
        end_membership(self.membership)
        result = RaceResult.objects.create(group=group, driver=self.driver, team=self.team, position=1)
        result.save()
        self.membership.refresh_from_db()
        assert not self.membership.is_active
        stranger = Driver.objects.create(first_name='Another', last_name='Pilot')
        RaceResult.objects.create(group=group, driver=stranger, team=self.team, position=2)
        assert not TeamMembership.objects.filter(driver=stranger).exists()


def test_legacy_can_be_reinvited_before_strict_rollout(client, roster, settings):
    settings.TEAM_ACCESS_LEGACY_ENABLED = True
    m, inv = roster[5:]
    m.confirmation_state = 'legacy'
    m.save()
    inv.status = 'accepted'
    inv.responded_at = timezone.now()
    inv.save()
    client.force_login(roster[2])
    with patch('teams.views._send_team_invitation_email'):
        client.post('/teams/invite-driver/', {'driver_id': roster[0].pk, 'team_id': roster[3].pk})
    inv.refresh_from_db()
    assert inv.status == 'pending'
    assert not MembershipConfirmation.objects.exists()
    accept(client, roster)
    assert MembershipConfirmation.objects.count() == 1


@pytest.mark.parametrize('scenario', ['only_membership', 'accepted', 'left', 'readded', 'no_account', 'bad_dates'])
def test_audit_never_infers_confirmation(roster, scenario):
    from datetime import timedelta
    driver, pilot, _, team, _, m, inv = roster
    if scenario in ('accepted', 'left', 'readded', 'bad_dates'):
        inv.status = 'accepted'
        inv.responded_at = timezone.now()
        inv.save()
    if scenario == 'left':
        end_membership(m)
    if scenario == 'readded':
        TeamMembership.objects.filter(pk=m.pk).update(joined_at=timezone.localdate()-timedelta(days=2),
                                                     is_active=False, left_at=timezone.localdate())
        TeamMembership.objects.create(driver=driver, team=team)
    if scenario == 'no_account':
        DriverClaim.objects.filter(driver=driver).delete()
        pilot.profile.driver = None
        pilot.profile.verified = False
        pilot.profile.save()
    if scenario == 'bad_dates':
        inv.responded_at = timezone.now()-timedelta(days=30)
        inv.save()
    result = audit_memberships()
    assert all(row['classification'] == 'ambiguous' for row in result['memberships'])
    assert not MembershipConfirmation.objects.exists()
    assert all(row['state'] != 'confirmed' for row in result['memberships'])
    if scenario == 'readded':
        assert all('multiple_membership_periods' in r['reasons'] for r in result['memberships'])
    if scenario == 'bad_dates':
        assert 'inconsistent_chronology' in result['memberships'][0]['reasons']


def test_admin_form_actual_wagtail_flow(client, roster):
    from django.urls import reverse
    driver, pilot, _, team, _, m, _ = roster
    DriverClaim.objects.filter(driver=driver).delete()
    pilot.profile.driver = None
    pilot.profile.verified = False
    pilot.profile.save()
    admin = User.objects.create_superuser('admin-form', 'admin-form@example.test', 'x')
    client.force_login(admin)
    url = reverse('website_teammembership_modeladmin_edit', args=[m.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert 'exception_reason' in response.content.decode()
    data = {'driver':driver.pk, 'team':team.pk, 'is_active':'on', 'confirm_no_account':'on'}
    assert client.post(url, data).status_code == 200
    assert not MembershipConfirmation.objects.exists()
    response = client.post(url, {**data, 'exception_reason':'Synthetic admin verification'})
    assert response.status_code == 302
    assert MembershipConfirmation.objects.get().actor == admin
    m.refresh_from_db()
    assert m.confirmation_state == 'confirmed'


def test_invitation_metadata_not_editable_from_admin(client, roster):
    from django.urls import reverse
    admin = User.objects.create_superuser('editor', 'editor@example.test', 'x')
    client.force_login(admin)
    url = reverse('website_teammembership_modeladmin_edit', args=[roster[5].pk])
    response = client.post(url, {'driver':roster[0].pk, 'team':roster[3].pk, 'is_active':'on',
        'confirmation_state':'confirmed', 'confirmation_source':'invitation',
        'confirmed_by':roster[1].pk, 'confirmed_at':timezone.now().isoformat()})
    assert response.status_code == 302
    roster[5].refresh_from_db()
    assert roster[5].confirmation_state == 'unconfirmed'
    assert not MembershipConfirmation.objects.exists()


def test_compare_and_list_do_not_expand_team_scope(client, roster):
    driver, pilot, manager, *_ = roster
    accept(client, roster)
    rec = AppSyncRecord.objects.create(user=pilot, driver=driver, table='sessions', uuid='compare',
        data={'name':'Synthetic private session'}, client_updated_at=1, server_updated_at=timezone.now())
    client.force_login(manager)
    response = client.get('/accounts/app-sessions/compare/', {'a':rec.uuid, 'b':rec.uuid})
    assert response.status_code == 200 and response.context['a']['record'] == rec
    end_membership(roster[5])
    response = client.get('/accounts/app-sessions/compare/', {'a':rec.uuid, 'b':rec.uuid})
    assert response.status_code == 200 and 'a' not in response.context
    assert 'Synthetic private session' not in client.get('/teams/app-sessions/').content.decode()
    assert 'Synthetic private session' not in client.get('/accounts/app-sessions/analytics/').content.decode()


def test_confirmation_service_rechecks_invitation_and_records_target(client, roster):
    driver, pilot, _, team, _, membership, inv = roster
    accept(client, roster)
    # The fixture object still says pending; service must read current DB state.
    assert inv.status == 'pending'
    with pytest.raises(PermissionDenied):
        confirm_membership(membership, pilot, 'invitation', invitation=inv)
    event = MembershipConfirmation.objects.get()
    assert (event.driver_id_at_confirmation, event.team_id_at_confirmation) == (driver.pk, team.pk)
    membership = TeamMembership.objects.get(pk=membership.pk)
    membership.team = Team.objects.create(name='Moved target')
    membership.save()
    assert membership.confirmation_state == 'unconfirmed'
    event.refresh_from_db()
    assert event.team_id_at_confirmation == team.pk
