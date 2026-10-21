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
