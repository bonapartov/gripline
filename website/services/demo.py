"""Демо-пилоты (demo/management/commands/setup_demo_accounts.py) — карточки Driver со slug
`demo-pilot-N`. Они нужны только внутри демо-режима (демо-команда приглашает демо-пилотов), в
публичный поиск, сравнение и списки попадать не должны."""

DEMO_DRIVER_SLUG_PREFIX = 'demo-pilot-'


def without_demo(queryset):
    """Убирает демо-пилотов из queryset Driver для публичных списков и поиска."""
    return queryset.exclude(slug__startswith=DEMO_DRIVER_SLUG_PREFIX)
