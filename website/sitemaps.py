"""Пилоты и команды в sitemap.xml (21.10.2026).

Driver/Team — не Wagtail Page: штатный Wagtail-sitemap (coderedcms.urls) строит его
только из Page.objects.live() и их не видит. Подключены рядом с ним в mysite/urls.py.
"""
from django.contrib.sitemaps import Sitemap
from django.db.models import Max, Q

from website.models import Driver, Team
from website.services.demo import without_demo


class DriverSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        # Только пилоты с результатами: пустой профиль без стартов в выдаче не нужен.
        # lastmod — конец последнего этапа, где пилот стартовал.
        return (
            without_demo(Driver.objects.filter(live=True))
            .annotate(last_race=Max("raceresult__group__page__occurrences__end"))
            .filter(raceresult__isnull=False)
            .exclude(slug="")
            .order_by("id")
        )

    def lastmod(self, driver):
        return driver.last_race


class TeamSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        # С результатами или с действующим составом (новая команда ещё не стартовала)
        ids = Team.objects.filter(
            Q(race_results__isnull=False) | Q(memberships__is_active=True),
            live=True,
        ).exclude(slug__isnull=True).exclude(slug="").values("id")
        return (
            Team.objects.filter(id__in=ids)
            .annotate(last_race=Max("race_results__group__page__occurrences__end"))
            .order_by("id")
        )

    def lastmod(self, team):
        return team.last_race
