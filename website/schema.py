"""
Утилиты для генерации структурированных данных Schema.org (JSON-LD).

Не собираем JSON строковой конкатенацией — строим dict в Python и
сериализуем через json.dumps(), см. gripline_matchast_TZ / Schema.org ТЗ, раздел 9.
"""
import json

from django.utils.safestring import mark_safe


class StructuredDataJSONEncoder(json.JSONEncoder):
    """date/datetime -> ISO 8601, остальное — стандартно."""

    def default(self, o):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return super().default(o)


def render_json_ld(data):
    """dict -> <script type="application/ld+json">...</script> (mark_safe)."""
    if not data:
        return ""
    payload = json.dumps(data, ensure_ascii=False, cls=StructuredDataJSONEncoder)
    return mark_safe(f'<script type="application/ld+json">{payload}</script>')


def build_breadcrumb_items(page):
    """
    Цепочка хлебных крошек для Wagtail-страницы: [{'name': ..., 'url': ...}, ...].
    Пустой список для главной страницы (или если ancestors <= 1) — крошки не нужны.
    """
    if page is None or not hasattr(page, "get_ancestors"):
        return []

    site = page.get_site() if hasattr(page, "get_site") else None
    root_depth = site.root_page.depth if site and site.root_page else None

    ancestors = list(
        page.get_ancestors(inclusive=True).live().public().specific()
    )
    if root_depth is not None:
        ancestors = [a for a in ancestors if a.depth >= root_depth]

    if len(ancestors) <= 1:
        return []

    items = []
    for anc in ancestors:
        url = getattr(anc, "full_url", None) or anc.url
        if not url:
            continue
        items.append({"name": anc.title, "url": url})
    return items


def _absolute_url(site, path):
    if not site or not path:
        return path or ""
    return site.root_url.rstrip("/") + path


def _absolute_image_url(site, image, filter_spec="width-800"):
    if not image:
        return None
    from wagtail.images.shortcuts import get_rendition_or_not_found

    rendition = get_rendition_or_not_found(image, filter_spec)
    return _absolute_url(site, rendition.url)


def driver_person_dict(driver, site, current_team=None):
    """Person structured data для страницы пилота."""
    data = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": driver.full_name,
        "url": _absolute_url(site, driver.get_absolute_url()),
    }

    image_url = _absolute_image_url(site, driver.photo)
    if image_url:
        data["image"] = image_url

    same_as = []
    if driver.telegram:
        same_as.append(driver.telegram)
    if driver.instagram:
        same_as.append(driver.instagram)
    same_as.extend(
        link.link_url for link in driver.social_links.all() if link.link_url
    )
    if same_as:
        data["sameAs"] = same_as

    if current_team:
        data["affiliation"] = {
            "@type": "SportsTeam",
            "name": current_team.name,
            "url": _absolute_url(site, current_team.get_absolute_url()),
        }

    return data


def team_sportsteam_dict(team, site, members=None):
    """SportsTeam structured data для страницы команды."""
    data = {
        "@context": "https://schema.org",
        "@type": "SportsTeam",
        "name": team.name,
        "url": _absolute_url(site, team.get_absolute_url()),
        "sport": "Karting",
    }

    logo_url = _absolute_image_url(site, team.logo)
    if logo_url:
        data["logo"] = logo_url

    same_as = [
        link.link_url for link in team.social_links.all() if link.link_url
    ]
    if same_as:
        data["sameAs"] = same_as

    if members:
        data["member"] = [
            {
                "@type": "Person",
                "name": driver.full_name,
                "url": _absolute_url(site, driver.get_absolute_url()),
            }
            for driver in members
        ]

    return data


def track_place_dict(track, site):
    """SportsActivityLocation structured data для страницы трассы."""
    data = {
        "@context": "https://schema.org",
        "@type": "SportsActivityLocation",
        "name": track.name,
        "url": _absolute_url(site, track.get_absolute_url()),
    }

    image_url = _absolute_image_url(site, track.photo)
    if image_url:
        data["image"] = image_url

    if track.address or track.city:
        data["address"] = {
            "@type": "PostalAddress",
            "streetAddress": track.address or "",
            "addressLocality": track.city or "",
            "addressRegion": track.region or "",
            "addressCountry": "RU",
        }

    # Координаты — только реальные, из базы. Не проставлять "на глаз".
    if track.latitude is not None and track.longitude is not None:
        data["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": track.latitude,
            "longitude": track.longitude,
        }

    return data


def breadcrumb_list_dict(items):
    """[{'name', 'url'}, ...] -> dict структуры BreadcrumbList, либо None."""
    if not items or len(items) < 2:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": item["name"],
                "item": item["url"],
            }
            for i, item in enumerate(items)
        ],
    }
