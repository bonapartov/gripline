"""title/description пилота и команды (21.10.2026).

Страницы Driver/Team не Wagtail Page — wagtailseo для них ничего не выводил, в выдаче
Яндекса вместо заголовка был URL, а в сниппете — текст меню «О проекте. Вход.».
"""
import pytest
from django.template.loader import render_to_string

from website.models import Driver, Team
from website.seo_meta import driver_seo, team_seo

pytestmark = pytest.mark.django_db


def test_driver_title_is_name_class_brand_without_listing():
    d = Driver.objects.create(first_name="Михаил", last_name="Твердохлебов", city="Москва")
    seo = driver_seo(d, None, current_class="Rotax Max Junior", total_starts=12, wins=1, podiums=5)
    assert seo["title"] == "Михаил Твердохлебов — пилот картинга, Rotax Max Junior | Gripline"
    assert "12 стартов, 1 победа, 5 подиумов." in seo["description"]


def test_namesakes_get_different_titles_by_city():
    a = Driver.objects.create(first_name="Иван", last_name="Петров", city="Москва")
    b = Driver.objects.create(first_name="Иван", last_name="Петров", city="Казань", slug="ivan-petrov-2")
    ta = driver_seo(a, None, current_class="OK")["title"]
    tb = driver_seo(b, None, current_class="OK")["title"]
    assert ta != tb
    assert "Москва" in ta and "Казань" in tb


def test_driver_without_starts_has_no_empty_stats():
    d = Driver.objects.create(first_name="Пётр", last_name="Новиков")
    seo = driver_seo(d, None)
    assert seo["title"] == "Пётр Новиков — пилот картинга | Gripline"
    assert seo["description"] == "Пётр Новиков — пилот картинга."


def test_rank_hidden_when_driver_out_of_rating():
    d = Driver.objects.create(first_name="Анна", last_name="Смирнова")
    card = {"rank": 3, "total": 20, "class_name": "OK", "out_reason": "inactive"}
    assert "место" not in driver_seo(d, None, current_class="OK", total_starts=4, class_rating=card)["description"]
    card["out_reason"] = None
    assert "3-е место из 20" in driver_seo(d, None, current_class="OK", total_starts=4, class_rating=card)["description"]


def test_team_title_and_roster():
    t = Team.objects.create(name="Liberty RS Team", city="Тула")
    seo = team_seo(t, None, classes=["Rotax Max DD2"], drivers_count=2,
                   team_stats={"total_starts": 3, "wins": 0, "podiums": 1})
    assert seo["title"] == "Liberty RS Team — картинг-команда, Тула | Gripline"
    assert "В составе 2 пилота: Rotax Max DD2." in seo["description"]
    assert "3 старта, 1 подиум." in seo["description"]


def test_meta_template_escapes_quotes():
    t = Team.objects.create(name='Команда "X"')
    html = render_to_string("includes/seo_meta.html", {"seo": team_seo(t, None)})
    assert 'content="Команда &quot;X&quot;' in html



def test_sitemap_skips_drivers_without_results():
    from website.sitemaps import DriverSitemap

    Driver.objects.create(first_name="Пустой", last_name="Профиль", slug="empty")
    assert list(DriverSitemap().items()) == []


def test_sitemap_teams_with_roster_or_results_only():
    from website.models import TeamMembership
    from website.sitemaps import TeamSitemap

    driver = Driver.objects.create(first_name="Гонщик", last_name="Команды", slug="team-driver")
    team = Team.objects.create(name="Команда с составом")
    Team.objects.create(name="Пустая команда")
    Team.objects.create(name="Черновик", live=False)
    TeamMembership.objects.create(driver=driver, team=team, is_active=True)
    assert [t.name for t in TeamSitemap().items()] == ["Команда с составом"]


def test_rating_title_per_class_and_canonical():
    from website.models import RaceClass
    from website.seo_meta import rating_seo

    rc = RaceClass.objects.create(name="RM Mini")
    leader = Driver(first_name="Михаил", last_name="Твердохлебов")
    seo = rating_seo(None, race_class=rc, drivers_count=32, leader=leader)
    assert seo["title"] == "Рейтинг пилотов картинга — RM Mini | Gripline"
    assert "В таблице 32 пилота, лидер — Михаил Твердохлебов." in seo["description"]
    assert seo["canonical"] == f"/top/drivers/?class={rc.id}"
    # Класс, открывающийся без параметра, — без дубля адреса
    assert rating_seo(None, race_class=rc, is_default=True)["canonical"] == "/top/drivers/"


def test_track_title_skips_city_already_in_name():
    from datetime import datetime
    from website.models import Track
    from website.seo_meta import track_seo

    t = Track.objects.create(name="Картодром Тула", slug="tula", city="Тула", address="ул. Мира, 1")
    seo = track_seo(t, None, events_count=5, record_classes=3,
                    next_event={"title": "Кубок Тулы", "start": datetime(2026, 11, 7)})
    assert seo["title"] == "Картодром Тула — картинг-трасса | Gripline"
    assert seo["description"] == (
        "Картинг-трасса «Картодром Тула»: Тула, ул. Мира, 1. Ближайшее соревнование — Кубок Тулы, 07.11.2026. "
        "5 соревнований на трассе, рекорды круга в 3 классах."
    )
    assert seo["og_type"] == "place"


def test_empty_twitter_site_not_rendered():
    """Без аккаунта в «Настройки → SEO» wagtail-seo выводил twitter:site content="@"."""
    from django.template.loader import get_template

    src = get_template("wagtailseo/meta.html").template.source
    assert "{% if settings.wagtailseo.SeoSettings.twitter_site %}" in src


def test_with_championship_not_repeated():
    from types import SimpleNamespace
    from website.seo_meta import _with_championship

    champ = SimpleNamespace(title="Зимний кубок")
    assert _with_championship("1 этап", champ) == "1 этап, Зимний кубок"
    assert _with_championship("1 этап Зимний кубок", champ) == "1 этап Зимний кубок"
