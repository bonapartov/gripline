"""Демо-пилоты (demo/management/commands/setup_demo_accounts.py) — карточки Driver со slug
`demo-pilot-N`. Они нужны только внутри демо-режима (демо-команда приглашает демо-пилотов), в
публичный поиск, сравнение и списки попадать не должны."""

DEMO_DRIVER_SLUG_PREFIX = 'demo-pilot-'


def without_demo(queryset):
    """Убирает демо-пилотов из queryset Driver для публичных списков и поиска."""
    return queryset.exclude(slug__startswith=DEMO_DRIVER_SLUG_PREFIX)


def search_drivers(query, limit=10):
    """Поиск опубликованных (не демо) пилотов по фамилии/имени: каждое слово запроса должно
    встретиться в фамилии или имени. full_name у Driver — свойство, по нему фильтровать нельзя."""
    from django.db.models import Q
    from website.models import Driver
    words = (query or '').split()[:3]
    if not words or len(' '.join(words)) < 2:
        return Driver.objects.none()
    qs = without_demo(Driver.objects.filter(live=True))
    for word in words:
        qs = qs.filter(Q(last_name__icontains=word) | Q(first_name__icontains=word))
    return qs.order_by('last_name', 'first_name')[:limit]
