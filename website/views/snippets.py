"""ViewSet'ы Wagtail для сниппетов: пилоты, команды, трассы и техника."""

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
from .public import (
    chassis_detail_view, driver_detail_view, engine_detail_view,
    team_detail_view, track_detail_view, tyre_detail_view,
    tyrebrand_detail_view, tyretype_detail_view,
)


# Классы для админки (Wagtail Snippets)
class DriverViewSet(SnippetViewSet):
    model = Driver
    icon = "user"
    menu_label = "Пилоты"
    menu_name = "drivers_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        # Локальный импорт: website.mediakit_views -> services.mediakit ->
        # website.views (этот же модуль) — на уровне модуля был бы цикл,
        # get_urlpatterns() вызывается уже после полной загрузки views.py.
        from website.mediakit_views import driver_mediakit_pdf_view

        return super().get_urlpatterns() + [
            path("<slug:slug>/mediakit/", driver_mediakit_pdf_view, name="mediakit"),
            path("<slug:slug>/", driver_detail_view, name="details"),
        ]

class TeamViewSet(SnippetViewSet):
    model = Team
    icon = "group"
    menu_label = "Команды"
    menu_name = "teams_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        # Локальный импорт — тот же циклический импорт, что и у DriverViewSet
        # (см. комментарий там): website.team_mediakit_views -> services.team_mediakit
        # -> services.team_stats -> website.views (этот же модуль).
        from website.team_mediakit_views import team_mediakit_pdf_view

        return super().get_urlpatterns() + [
            path("<slug:slug>/mediakit/", team_mediakit_pdf_view, name="mediakit"),
            path("<slug:slug>/", team_detail_view, name="details"),
        ]
class TrackViewSet(SnippetViewSet):
    model = Track
    icon = "site"  # Иконка для админки
    menu_label = "Трассы"
    menu_name = "tracks_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", track_detail_view, name="details"),
        ]
class ChassisViewSet(SnippetViewSet):
    model = Chassis
    icon = "cog"
    menu_label = "Шасси"
    menu_name = "chassis_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", chassis_detail_view, name="details"),
        ]

class TyreBrandViewSet(SnippetViewSet):
    model = TyreBrand
    icon = "fa-brands"
    menu_label = "Производители шин"
    menu_name = "tyrebrand_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", tyrebrand_detail_view, name="details"),
        ]

class TyreTypeViewSet(SnippetViewSet):
    model = TyreType
    icon = "fa-type"
    menu_label = "Типы шин"
    menu_name = "tyretype_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", tyretype_detail_view, name="details"),
        ]

class TyreViewSet(SnippetViewSet):
    model = Tyre
    icon = "fa-tyre"
    menu_label = "Шины"
    menu_name = "tyre_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", tyre_detail_view, name="details"),
        ]

class EngineViewSet(SnippetViewSet):
    model = Engine
    icon = "fa-engine"
    menu_label = "Двигатели"
    menu_name = "engine_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", engine_detail_view, name="details"),
        ]
