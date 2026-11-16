"""Общие помощники: актуальная команда пилота по последнему старту."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from website.models import Ad, AdCategory, AdResponse
from django.db.models import Q
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path
from wagtail.snippets.views.snippets import SnippetViewSet
from website.models import (
    Driver, Team, RaceResult, RaceClass, Track, Chassis, TyreBrand, TyreType,
    Tyre, Engine,
)
from django.utils.timezone import now
# Определение текущего сайта нужно для Header/Footer.
from wagtail.models import Site
from django.db.models import F, OuterRef, Subquery, Avg
from website.models import EventOccurrence
from django.db import models
from django.utils import timezone
import zoneinfo
from website.models import AnalyticsMetadata, AnalyticsSettings
from datetime import timedelta
from django.db.models import Max
from website.models import TeamStaff, TeamStaffMembership
from django.http import JsonResponse
from django.db.models import Count


def _compute_driver_current_teams():
    """{driver_id: team_id} — команда каждого пилота на его самой свежей по дате гонке.

    Дата гонки: конец последнего EventOccurrence этапа, либо (если Occurrence нет)
    last_published_at/first_published_at страницы этапа. Считается двумя запросами
    на весь сайт разом — чтобы не пересчитывать каждого пилота заново на каждую команду.
    """
    occurrence_ends = {}
    for event_id, end in EventOccurrence.objects.values_list('event_id', 'end'):
        if end is None:
            continue
        if event_id not in occurrence_ends or end > occurrence_ends[event_id]:
            occurrence_ends[event_id] = end

    rows = RaceResult.objects.values(
        'driver_id', 'team_id',
        'group__page_id', 'group__page__last_published_at', 'group__page__first_published_at',
    )

    latest_by_driver = {}  # driver_id -> (event_date, team_id)
    for row in rows:
        event_date = (
            occurrence_ends.get(row['group__page_id'])
            or row['group__page__last_published_at']
            or row['group__page__first_published_at']
        )
        if event_date is None:
            continue
        current = latest_by_driver.get(row['driver_id'])
        if current is None or event_date > current[0]:
            latest_by_driver[row['driver_id']] = (event_date, row['team_id'])

    return {driver_id: team_id for driver_id, (_, team_id) in latest_by_driver.items()}


def _get_current_team_driver_ids(team, current_team_map=None):
    """ID пилотов, у которых команда team — актуальная на публичной странице.

    Актуальность определяется по факту последнего старта пилота (RaceResult.team
    на самой свежей по дате гонке пилота, среди вообще всех его результатов —
    не только за эту команду). Пилот, ни разу не стартовавший, остаётся по
    ручной записи TeamMembership (например, только что подписанный новичок).
    """
    if current_team_map is None:
        current_team_map = _compute_driver_current_teams()

    raced_current = {
        driver_id for driver_id, current_team_id in current_team_map.items()
        if current_team_id == team.id
    }

    never_raced_signed = set(
        Driver.objects.filter(
            team_memberships__team=team,
            team_memberships__is_active=True,
        ).exclude(id__in=current_team_map.keys()).values_list('id', flat=True)
    )

    return raced_current | never_raced_signed
