"""
ЛК менеджера команды — ростер и карты для калькулятора развесовки
(/balance/), Блок 3 ТЗ «Сервис расчёта развесовки карта». Отдельный модуль,
не teams/views.py (тот уже 1400+ строк) — по образцу website/mediakit_views.py.

TeamRosterEntry/командный Kart живут здесь, а не под /balance/ — право-
проверка "TeamManager.objects.filter(user=..., is_active=True)" уже
используется ~10 раз в teams/views.py, переиспользуем идиому дословно
вместо новой. Пилотский Kart — website/balance_setup_views.py::kart_create.

Этап 1 (см. /home/v/.claude/plans/smooth-snacking-spindle.md): создание и
мягкая архивация записи ростера/карта. Редактирование задним числом — не
в этом этапе (нужно — заархивировать и создать заново).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from wagtailcache.cache import nocache_page

from website.models import ROSTER_PRIVACY_NOTICE, Chassis, Kart, TeamRosterEntry
from website.services.balance_limits import (
    MAX_KARTS_PER_OWNER,
    balance_ratelimit,
)
from .models import TeamManager


def _active_manager(request):
    return TeamManager.objects.filter(
        user=request.user, is_active=True,
    ).select_related("team").first()


@login_required
@nocache_page
def balance_roster(request):
    """Страница ростера и командных картов — та же гейтинг-идиома, что
    teams/views.py::dashboard."""
    manager = _active_manager(request)
    if not manager:
        messages.error(request, "У вас нет прав на управление командой")
        return redirect("/")

    team = manager.team
    roster_entries = TeamRosterEntry.objects.filter(team=team).select_related("driver")
    karts = Kart.objects.filter(owner_team=team).select_related("chassis", "roster_entry")

    return render(request, "teams/balance_roster.html", {
        "team": team,
        "roster_entries": roster_entries,
        "roster_entries_active": roster_entries.filter(is_archived=False),
        "karts": karts,
        "karts_active": karts.filter(is_archived=False),
        "chassis_choices": Chassis.objects.filter(live=True).order_by("name"),
        "roster_privacy_notice": ROSTER_PRIVACY_NOTICE,
    })


@login_required
@nocache_page
@balance_ratelimit("roster_entry_save", limit=30, window_seconds=60)
def roster_entry_save(request):
    manager = _active_manager(request)
    if not manager or request.method != "POST":
        messages.error(request, "У вас нет прав на управление командой")
        return redirect("/")

    last_name = request.POST.get("last_name", "").strip()
    first_name = request.POST.get("first_name", "").strip()
    if not last_name or not first_name:
        messages.error(request, "Укажите фамилию и имя.")
        return redirect("teams:balance_roster")

    TeamRosterEntry.objects.create(
        team=manager.team,
        last_name=last_name,
        first_name=first_name,
        label=request.POST.get("label", "").strip(),
        gear_weight_kg=request.POST.get("gear_weight_kg") or None,
    )
    messages.success(request, "Пилот добавлен в ростер.")
    return redirect("teams:balance_roster")


@login_required
@nocache_page
@balance_ratelimit("roster_entry_archive", limit=30, window_seconds=60)
def roster_entry_archive(request, pk):
    manager = _active_manager(request)
    if not manager or request.method != "POST":
        messages.error(request, "У вас нет прав на управление командой")
        return redirect("/")

    entry = get_object_or_404(TeamRosterEntry, pk=pk, team=manager.team)
    entry.is_archived = not entry.is_archived
    entry.save(update_fields=["is_archived", "updated_at"])
    messages.success(request, "Запись ростера в архиве." if entry.is_archived else "Запись ростера возвращена из архива.")
    return redirect("teams:balance_roster")


@login_required
@nocache_page
@balance_ratelimit("team_kart_save", limit=20, window_seconds=60)
def team_kart_save(request):
    manager = _active_manager(request)
    if not manager or request.method != "POST":
        messages.error(request, "У вас нет прав на управление командой")
        return redirect("/")

    existing = Kart.objects.filter(owner_team=manager.team).count()
    if existing >= MAX_KARTS_PER_OWNER:
        messages.error(request, "Достигнут лимит количества картов команды.")
        return redirect("teams:balance_roster")

    name = request.POST.get("name", "").strip()
    chassis_id = request.POST.get("chassis_id")
    chassis_type = request.POST.get("chassis_type", "").strip()
    if not name or not chassis_id or not chassis_type:
        messages.error(request, "Укажите название, шасси и тип шасси.")
        return redirect("teams:balance_roster")

    chassis = get_object_or_404(Chassis, pk=chassis_id)
    roster_entry_id = request.POST.get("roster_entry_id") or None
    roster_entry = None
    if roster_entry_id:
        roster_entry = get_object_or_404(TeamRosterEntry, pk=roster_entry_id, team=manager.team)

    kart = Kart(
        name=name,
        chassis=chassis,
        chassis_type=chassis_type,
        model=request.POST.get("model", "").strip(),
        year=request.POST.get("year") or None,
        owner_team=manager.team,
        roster_entry=roster_entry,
    )
    try:
        kart.full_clean()
    except Exception as exc:
        messages.error(request, f"Ошибка: {exc}")
        return redirect("teams:balance_roster")
    kart.save()
    messages.success(request, "Карт добавлен.")
    return redirect("teams:balance_roster")


@login_required
@nocache_page
@balance_ratelimit("team_kart_archive", limit=30, window_seconds=60)
def team_kart_archive(request, pk):
    manager = _active_manager(request)
    if not manager or request.method != "POST":
        messages.error(request, "У вас нет прав на управление командой")
        return redirect("/")

    kart = get_object_or_404(Kart, pk=pk, owner_team=manager.team)
    kart.is_archived = not kart.is_archived
    kart.save(update_fields=["is_archived", "updated_at"])
    messages.success(request, "Карт в архиве." if kart.is_archived else "Карт возвращён из архива.")
    return redirect("teams:balance_roster")
