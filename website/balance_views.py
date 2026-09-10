"""
Views калькулятора развесовки (/balance/). Отдельный модуль, не website/views.py
(тот уже 3000+ строк) — тот же паттерн, что у website/mediakit_views.py.

Блок 0 (инфраструктура): app-shell + PWA manifest. Блок 2 (этот файл) —
базовый калькулятор, анонимный, ничего не сохраняет. Авторизация/сохранение
— Блок 3.
"""
from django.contrib.staticfiles import finders
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from wagtail.models import Site
from wagtailcache.cache import nocache_page

from website.models import Chassis, Kart, KartClass
from website.schema import balance_webapp_dict, render_json_ld
from website.services.balance_calc import load_diagnostic_rules, load_thresholds
from website.services.balance_permissions import get_balance_identity


def _calculator_reference_context():
    """
    Справочный контекст калькулятора — классы/пороги/диагностика. Не
    зависит от пользователя или конкретного сетапа, поэтому вынесен из
    balance_home (Этап 4 плана Блока 3 —
    /home/v/.claude/plans/smooth-snacking-spindle.md): setup_edit
    (balance_setup_views.py) рендерит тот же home.html и должен получить
    ровно те же справочники, без повторного похода в БД за тем же самым.
    """
    kart_classes = []
    for kc in KartClass.objects.filter(is_active=True):
        geometry = kc.effective_geometry()
        kart_classes.append({
            "id": kc.id,
            "name": kc.name,
            "chassis_type": kc.chassis_type,
            "min_weight_kg": str(kc.min_weight_kg) if kc.min_weight_kg is not None else None,
            "wheelbase_mm": geometry["wheelbase_mm"],
            "track_front_mm": geometry["track_front_mm"],
            "track_rear_mm": geometry["track_rear_mm"],
        })
    thresholds = {
        metric: {
            "green_min": str(t.green_min),
            "green_max": str(t.green_max),
            "yellow_min": str(t.yellow_min),
            "yellow_max": str(t.yellow_max),
        }
        for metric, t in load_thresholds().items()
    }

    diagnostic_rules = {}
    why_43_57 = None
    for condition, rule in load_diagnostic_rules().items():
        entry = {
            "text": rule.text,
            "article_url": rule.article.url if rule.article else None,
            "article_title": rule.article.title if rule.article else None,
        }
        if condition == "why_43_57_target":
            why_43_57 = entry
        else:
            diagnostic_rules[condition] = entry

    return {
        "kart_classes": kart_classes,
        "kart_classes_json": kart_classes,
        "thresholds_json": thresholds,
        "diagnostic_rules_json": diagnostic_rules,
        "why_43_57": why_43_57,
    }


def user_karts_context(user):
    """
    Identity-производный контекст (пилотские карты + справочник шасси для
    инлайн-создания нового карта) — общий для balance_home и setup_edit
    (та же причина выноса, что у _calculator_reference_context выше).
    Без подчёркивания — вызывается из balance_setup_views.py.
    """
    identity = get_balance_identity(user)
    driver = identity["driver"]
    has_balance_access = driver is not None or identity["managed_teams"].exists()

    user_karts = []
    if driver is not None:
        user_karts = [
            {"id": k.id, "name": k.name}
            for k in Kart.objects.filter(owner_driver=driver, is_archived=False).order_by("-updated_at")
        ]
    chassis_choices = [
        {"id": c.id, "name": c.name}
        for c in Chassis.objects.filter(live=True).order_by("name")
    ]
    return {
        "has_driver_identity": driver is not None,
        "has_balance_access": has_balance_access,
        "user_karts": user_karts,
        "chassis_choices": chassis_choices,
    }


def balance_seo_context(request):
    """OG/canonical/schema — общие для home и setup_edit: setup_edit рендерит
    ту же страницу с конкретным сетапом внутри, а не отдельный индексируемый
    URL (см. robots_content в home.html — noindex для editing_setup)."""
    site = Site.find_for_request(request)
    root_url = site.root_url if site else "https://gripline.ru"
    canonical_url = root_url.rstrip("/") + reverse("balance:home")
    og_image_url = root_url.rstrip("/") + static("website/images/balance/og-card.png")
    return {
        "canonical_url": canonical_url,
        "og_image_url": og_image_url,
        "schema_json_ld": render_json_ld(balance_webapp_dict(site, canonical_url)),
    }


@nocache_page
def balance_home(request):
    """
    @nocache_page здесь не про авторизацию (страница анонимная, публичная) —
    про свежесть данных. KartClass/BalanceThreshold правятся в админке
    («Развесовка») без какого-либо хука инвалидации wagtailcache; без этого
    декоратора первый закэшированный ответ (например, ещё пустые справочники)
    отдавался бы всем следующим посетителям до истечения TTL/ручного
    clear_wagtail_cache — тот же класс бага, что уже ловили на медиа-ките
    пилота (см. CLAUDE.md), только там дело было в авторизации, здесь — в
    актуальности регламентных цифр. С Блока 3 у декоратора появилась и
    вторая причина: страница теперь несёт персонализированный список
    картов пилота (user_karts) — без @nocache_page первый закэшированный
    ответ (даже анонимный) отдавался бы всем следующим посетителям в обход
    личных данных, тот же класс бага, что уже ловили на медиа-ките пилота."""
    context = _calculator_reference_context()
    context.update(user_karts_context(request.user))
    context.update(balance_seo_context(request))
    context["active_tab"] = "home"
    return render(request, "balance/home.html", context)


def balance_manifest(request):
    return render(request, "balance/manifest.json", content_type="application/manifest+json")


def balance_service_worker(request):
    """
    Отдаётся ровно с /balance/sw.js (не из /static/) — область действия
    service worker'а по умолчанию равна каталогу, где лежит файл, поэтому
    только так scope естественно совпадает с '/balance/' (как в manifest.json).
    finders.find() работает и при DEBUG=False — ищет по исходным static-
    каталогам приложений, не зависит от того, выполнен ли collectstatic.
    """
    path = finders.find("website/js/balance-sw.js")
    if not path:
        return HttpResponseNotFound()
    with open(path, "rb") as f:
        content = f.read()
    return HttpResponse(content, content_type="application/javascript")
