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

from website.models import KartClass
from website.schema import balance_webapp_dict, render_json_ld
from website.services.balance_calc import load_diagnostic_rules, load_thresholds


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
    актуальности регламентных цифр."""
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
    reading_links = []
    seen_article_urls = set()
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
            # Несколько условий делят одну статью (ТЗ 7.1: front_high/front_low
            # — «та же», cross_diagonal/cross_mechanical — тоже) — не дублируем
            # ссылку в списке для чтения на лендинге.
            if entry["article_url"] and entry["article_url"] not in seen_article_urls:
                seen_article_urls.add(entry["article_url"])
                reading_links.append(entry)

    site = Site.find_for_request(request)
    root_url = site.root_url if site else "https://gripline.ru"
    canonical_url = root_url.rstrip("/") + reverse("balance:home")
    og_image_url = root_url.rstrip("/") + static("website/images/balance/og-card.png")

    return render(request, "balance/home.html", {
        "kart_classes": kart_classes,
        "kart_classes_json": kart_classes,
        "thresholds_json": thresholds,
        "diagnostic_rules_json": diagnostic_rules,
        "why_43_57": why_43_57,
        "reading_links": reading_links,
        "canonical_url": canonical_url,
        "og_image_url": og_image_url,
        "schema_json_ld": render_json_ld(balance_webapp_dict(site, canonical_url)),
    })


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
