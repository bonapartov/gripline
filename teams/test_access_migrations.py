"""Apply and reverse the new migrations on an isolated synthetic schema.

Existing migration history cannot replay website.0011 on a blank DB. This test
uses historical migration states with real schema operations against the isolated
pytest database, not --fake or a production connection.
"""
import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from website.models import Driver, Team, TeamMembership


@pytest.mark.django_db(transaction=True)
def test_new_schema_forward_backward_preserves_legacy_without_confirming(settings):
    settings.MIGRATION_MODULES = {}
    loader = MigrationLoader(connection)
    website_key = ('website', '0111_teammembership_confirmation_reason_and_more')
    teams_key = ('teams', '0004_membershipconfirmation')
    website_migration = loader.get_migration(*website_key)
    teams_migration = loader.get_migration(*teams_key)
    before_website = loader.project_state(website_key, at_end=False)
    before_teams = loader.project_state(teams_key, at_end=False)
    driver = Driver.objects.create(first_name='Migration', last_name='Synthetic')
    team = Team.objects.create(name='Migration team')
    member = TeamMembership.objects.create(driver=driver, team=team)
    # Existing rows cannot be inferred from invitations or is_active.
    with connection.schema_editor() as editor:
        teams_migration.unapply(before_teams, editor)
        website_migration.unapply(before_website, editor)
    try:
        with connection.schema_editor() as editor:
            website_migration.apply(before_website.clone(), editor)
            teams_migration.apply(before_teams.clone(), editor)
        member.refresh_from_db()
        assert member.is_active and member.confirmation_state == 'legacy'
        assert member.confirmed_at is None and member.confirmed_by_id is None
        assert member.confirmation_source == ''
        from django.utils import timezone
        actor = User.objects.create_user('migration-actor')
        member.confirmation_state = 'confirmed'
        member.confirmed_at = timezone.now()
        member.confirmed_by = actor
        member.confirmation_source = 'invitation'
        member.save()
        fresh = TeamMembership.objects.create(driver=driver, team=Team.objects.create(name='New'))
        assert fresh.confirmation_state == 'unconfirmed'
        from teams.models import MembershipConfirmation
        MembershipConfirmation.objects.create(membership=member, actor=actor, source='invitation',
            driver_id_at_confirmation=driver.pk, team_id_at_confirmation=team.pk)
        assert MembershipConfirmation.objects.count() == 1
        # Schema rollback removes evidence; data and active flags survive.
        with connection.schema_editor() as editor:
            teams_migration.unapply(before_teams, editor)
            website_migration.unapply(before_website, editor)
        with connection.cursor() as cursor:
            cursor.execute('SELECT is_active FROM website_teammembership WHERE id=%s', [member.pk])
            assert cursor.fetchone() == (True,)
    finally:
        with connection.cursor() as cursor:
            columns = {c.name for c in connection.introspection.get_table_description(
                cursor, 'website_teammembership')}
        if 'confirmation_state' not in columns:
            with connection.schema_editor() as editor:
                website_migration.apply(before_website.clone(), editor)
                teams_migration.apply(before_teams.clone(), editor)
