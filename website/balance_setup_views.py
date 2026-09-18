"""
Views сохранения/управления сетапами развесовки (/balance/) — Блок 3 ТЗ
«Сервис расчёта развесовки карта». Отдельный модуль, не website/views.py
(тот уже 3000+ строк) и не website/balance_views.py (тот остаётся
анонимным калькулятором, Блок 2) — тот же паттерн, что у
website/mediakit_views.py.

Этап 1 (см. /home/v/.claude/plans/smooth-snacking-spindle.md): пилотский
Kart CRUD — kart_create/kart_archive. Этап 2: setup_save (создание). Этап 3:
setups_list — список сохранённых сетапов. Этап 4: setup_edit (загрузка
сетапа в тот же калькулятор — home.html, не отдельный шаблон) + update-путь
setup_save (kart_id сменить нельзя — см. can_edit_setup). Этап 5: setup_copy
(только владелец — получателю шера копия была бы бессмысленна, копия того
же карта того же владельца). Этап 6: setup_archive (setup-уровня, отдельно
от kart_archive) + setup_share (валидирует, что цель шеринга вообще
применима к типу владения картом — см. visible_setups_for_user: shared_with_team
работает только для личного карта пилота, shared_with_driver — только для
карта команды с закреплённым в ростере пилотом).

Все мутирующие эндпоинты: @nocache_page (owner-gated — см. предупреждение
в website/mediakit_views.py про wagtailcache как глобальный middleware),
@login_required, проверка через website/services/balance_permissions.py
(никогда не инлайн), rate limit через website/services/balance_limits.py.
setups_list — та же пара @login_required/@nocache_page, но без rate-limit
(GET, ничего не меняет) и с robots noindex,nofollow (приватные данные).

Блок 7 (ТЗ §8.1, сравнение сетапов): setups_compare — та же пара GET-view
без rate-limit, что и setups_list. Сама математика (дельты, значимость
изменений) — в website/services/balance_calc.py::compare_setups, не здесь.
"""
import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from wagtailcache.cache import nocache_page

from website.balance_views import (
    _calculator_reference_context,
    balance_seo_context,
    user_karts_context,
)
from website.models import Ballast, Chassis, Kart, KartClass, Setup
from website.services.balance_calc import compare_setups, validate_corners
from website.services.balance_limits import (
    MAX_BALLASTS_PER_SETUP,
    MAX_KARTS_PER_OWNER,
    MAX_SETUPS_PER_KART,
    balance_ratelimit,
)
from website.services.balance_permissions import (
    can_edit_kart,
    can_edit_setup,
    get_balance_identity,
    visible_karts_for_user,
    visible_setups_for_user,
)


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


@login_required
@require_POST
@nocache_page
@balance_ratelimit("kart_create", limit=20, window_seconds=60)
def kart_create(request):
    """Только карт пилота (owner_driver) — командный карт создаётся из
    /teams/, см. teams/balance_roster_views.py::team_kart_save (там же
    поле "закреплён за", которого у пилотского карта в принципе нет)."""
    identity = get_balance_identity(request.user)
    driver = identity["driver"]
    if driver is None:
        return JsonResponse(
            {"error": "Сохранение доступно только подтверждённым пилотам."}, status=403,
        )

    existing = visible_karts_for_user(request.user, include_archived=True).filter(
        owner_driver=driver,
    ).count()
    if existing >= MAX_KARTS_PER_OWNER:
        return JsonResponse({"error": "Достигнут лимит количества картов."}, status=400)

    data = _json_body(request)
    name = str(data.get("name") or "").strip()
    chassis_id = data.get("chassis_id")
    chassis_type = str(data.get("chassis_type") or "").strip()

    if not name:
        return JsonResponse({"error": "Укажите название карта."}, status=400)
    chassis = get_object_or_404(Chassis, pk=chassis_id) if chassis_id else None
    if chassis is None:
        return JsonResponse({"error": "Выберите шасси."}, status=400)

    kart = Kart(
        name=name,
        chassis=chassis,
        chassis_type=chassis_type,
        model=str(data.get("model") or "").strip(),
        year=data.get("year") or None,
        owner_driver=driver,
    )
    try:
        kart.full_clean()
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
    kart.save()

    return JsonResponse({"id": kart.id, "name": kart.name})


@login_required
@require_POST
@nocache_page
@balance_ratelimit("kart_archive", limit=30, window_seconds=60)
def kart_archive(request, pk):
    kart = get_object_or_404(Kart, pk=pk)
    if not can_edit_kart(request.user, kart):
        return JsonResponse({"error": "Нет прав на этот карт."}, status=404)

    data = _json_body(request)
    kart.is_archived = bool(data.get("archived", True))
    kart.save(update_fields=["is_archived", "updated_at"])
    return JsonResponse({"id": kart.id, "is_archived": kart.is_archived})


def _to_decimal(raw):
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _to_int(raw):
    if raw is None or raw == "":
        return None
    try:
        return int(Decimal(str(raw).strip().replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


@login_required
@require_POST
@nocache_page
@balance_ratelimit("setup_save", limit=30, window_seconds=60)
def setup_save(request):
    """
    Создание (Этап 2) и обновление (Этап 4) одним эндпоинтом — различаются
    по наличию setup_id в теле. Update никогда не трогает kart (план Блока 3,
    решение "kart_id менять нельзя" — передача карта между командами
    сознательно вне скоупа, см. раздел "Явно вне скоупа" плана) и не
    затрагивает is_archived/shared_with_*/parent_setup — это поля других
    этапов (6), setup_save их не касается ни при create, ни при update.
    """
    data = _json_body(request)
    setup_id = data.get("setup_id")
    is_create = not setup_id

    if is_create:
        kart = get_object_or_404(Kart, pk=data.get("kart_id")) if data.get("kart_id") else None
        if kart is None or not can_edit_kart(request.user, kart):
            return JsonResponse({"error": "Нет прав на этот карт."}, status=404)
        setup = Setup(kart=kart)
    else:
        setup = get_object_or_404(visible_setups_for_user(request.user, include_archived=True), pk=setup_id)
        if not can_edit_setup(request.user, setup):
            return JsonResponse({"error": "Нет прав на этот сетап."}, status=404)
        kart = setup.kart

    kart_class = KartClass.objects.filter(pk=data.get("class_id"), is_active=True).first()
    if kart_class is None:
        return JsonResponse({"error": "Выберите класс, чтобы сохранить сетап."}, status=400)

    if is_create and Setup.objects.filter(kart=kart).count() >= MAX_SETUPS_PER_KART:
        return JsonResponse({"error": "Достигнут лимит количества сетапов на этот карт."}, status=400)

    ballasts_raw = data.get("ballasts") or []
    if len(ballasts_raw) > MAX_BALLASTS_PER_SETUP:
        return JsonResponse({"error": "Слишком много грузов в одном сетапе."}, status=400)

    corners_raw = data.get("corners") or {}
    lf = _to_decimal(corners_raw.get("lf"))
    rf = _to_decimal(corners_raw.get("rf"))
    lr = _to_decimal(corners_raw.get("lr"))
    rr = _to_decimal(corners_raw.get("rr"))
    validation = validate_corners(lf, rf, lr, rr, kart_class=kart_class)
    if validation["errors"]:
        return JsonResponse({"error": "; ".join(validation["errors"])}, status=400)

    # Вес пилота: явно переданный клиентом → (только при СОЗДАНИИ) закреплённый
    # в ростере или последний несархивный сетап на этом же карте (план Блока 3,
    # раздел "setup_save"). При UPDATE пустое значение — это пилот осознанно
    # очистил поле, не повод подставлять туда старое/чужое число обратно.
    driver_weight = _to_decimal(data.get("driver_weight_kg"))
    if driver_weight is None and is_create:
        if kart.roster_entry_id and kart.roster_entry.gear_weight_kg is not None:
            driver_weight = kart.roster_entry.gear_weight_kg
        else:
            last_setup = Setup.objects.filter(kart=kart, is_archived=False).order_by("-created_at").first()
            if last_setup is not None and last_setup.driver_weight_kg is not None:
                driver_weight = last_setup.driver_weight_kg

    name = str(data.get("name") or "").strip()[:150]
    if not name:
        name = setup.name if not is_create else f"Сетап {timezone.now():%d.%m.%Y}"

    weather = data.get("weather")
    if weather not in dict(Setup.WEATHER_CHOICES):
        weather = setup.weather if not is_create else "dry"

    setup.name = name
    setup.kart_class = kart_class
    setup.weight_lf, setup.weight_rf, setup.weight_lr, setup.weight_rr = lf, rf, lr, rr
    setup.driver_weight_kg = driver_weight
    setup.weather = weather
    setup.wheelbase_mm = _to_int(data.get("wheelbase_mm"))
    setup.track_front_mm = _to_int(data.get("track_front_mm"))
    setup.track_rear_mm = _to_int(data.get("track_rear_mm"))
    try:
        setup.full_clean()
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
    setup.save()

    if not is_create:
        # Грузы не идентифицированы по id на клиенте (GripBalanceCalc.getState
        # отдаёт весь список заново) — простая замена целиком проще и надёжнее
        # частичного diff'а по неизменяемым позициям.
        setup.ballasts.all().delete()
    for index, raw in enumerate(ballasts_raw):
        weight_kg = _to_decimal(raw.get("weight_kg"))
        pos_x_mm = _to_decimal(raw.get("pos_x_mm"))
        pos_y_mm = _to_decimal(raw.get("pos_y_mm"))
        if weight_kg is None or pos_x_mm is None or pos_y_mm is None:
            continue  # неполная запись груза — молча пропускаем, не блокируем сохранение сетапа
        Ballast.objects.create(
            setup=setup, weight_kg=weight_kg, pos_x_mm=pos_x_mm, pos_y_mm=pos_y_mm,
            label=str(raw.get("label") or "").strip()[:100], sort_order=index,
        )

    return JsonResponse({"id": setup.id, "name": setup.name})


@login_required
@nocache_page
def setup_edit(request, pk):
    """
    Этап 4 плана — рендерит ТОТ ЖЕ home.html (не отдельный шаблон), заполнив
    его контекстом конкретного сетапа. Доступ — через visible_setups_for_user
    (никогда не голый Setup.objects.get), чтобы чужой pk не отличался от
    несуществующего. can_edit=False (расшаренный только для чтения сетап)
    долетает в шаблон — тот прячет форму сохранения (см. home.html).
    """
    setup = get_object_or_404(
        visible_setups_for_user(request.user, include_archived=True)
        .select_related("kart", "kart_class", "kart__roster_entry", "parent_setup")
        .prefetch_related("ballasts"),
        pk=pk,
    )
    can_edit = can_edit_setup(request.user, setup)

    loaded_setup = {
        "setup_id": setup.id,
        "kart_name": setup.kart.name,
        "can_edit": can_edit,
        "parent_setup_name": setup.parent_setup.name if setup.parent_setup_id else None,
        "state": {
            "corners": {
                "lf": str(setup.weight_lf), "rf": str(setup.weight_rf),
                "lr": str(setup.weight_lr), "rr": str(setup.weight_rr),
            },
            "class_id": setup.kart_class_id,
            "weather": setup.weather,
            "driver_weight": str(setup.driver_weight_kg) if setup.driver_weight_kg is not None else "",
            "wheelbase_mm": str(setup.wheelbase_mm) if setup.wheelbase_mm else "",
            "track_front_mm": str(setup.track_front_mm) if setup.track_front_mm else "",
            "track_rear_mm": str(setup.track_rear_mm) if setup.track_rear_mm else "",
            "ballasts": [
                {
                    "weight_kg": str(b.weight_kg), "pos_x_mm": str(b.pos_x_mm),
                    "pos_y_mm": str(b.pos_y_mm), "label": b.label,
                }
                for b in sorted(setup.ballasts.all(), key=lambda b: (b.sort_order, b.id))
            ],
        },
    }

    context = _calculator_reference_context()
    context.update(user_karts_context(request.user))
    context.update(balance_seo_context(request))
    context.update({
        "active_tab": "setups",
        "editing_setup": setup,
        "can_edit_loaded_setup": can_edit,
        "loaded_setup_json": loaded_setup,
    })
    return render(request, "balance/home.html", context)


@login_required
@nocache_page
def setups_list(request):
    """
    Этап 3 плана — весь видимый датасет считается здесь и уходит на клиент
    одним JSON-блобом (json_script в шаблоне), группировка по карту/
    фильтрация по классу-погоде-трассе/переключатель архива — целиком на
    клиенте (balance-setups.js), без похода на сервер. Тот же паттерн, что
    «История выступлений» на странице пилота (website/views.py::driver_detail_view).

    include_archived=True — переключатель "показать архивные" в UI работает
    без повторного запроса, значит архивные тоже должны быть в блобе,
    просто по умолчанию скрыты на клиенте.
    """
    identity = get_balance_identity(request.user)
    has_balance_access = identity["driver"] is not None or identity["managed_teams"].exists()

    setups = list(
        visible_setups_for_user(request.user, include_archived=True)
        .select_related("kart", "kart_class", "track")
        .order_by("-created_at")
    )

    weather_labels = dict(Setup.WEATHER_CHOICES)
    available_classes = {}
    available_tracks = {}
    setups_data = []
    for s in setups:
        available_classes[s.kart_class_id] = s.kart_class.name
        if s.track_id:
            available_tracks[s.track_id] = s.track.name
        setups_data.append({
            "id": s.id,
            "name": s.name,
            "kart_id": s.kart_id,
            "kart_name": s.kart.name,
            "class_id": s.kart_class_id,
            "class_name": s.kart_class.name,
            "weather": s.weather,
            "weather_label": weather_labels.get(s.weather, ""),
            "track_id": s.track_id,
            "track_name": s.track.name if s.track_id else None,
            "corners": {
                "lf": str(s.weight_lf), "rf": str(s.weight_rf),
                "lr": str(s.weight_lr), "rr": str(s.weight_rr),
            },
            "total_kg": str(s.total_weight_kg),
            "shared_with_team": s.shared_with_team,
            "shared_with_driver": s.shared_with_driver,
            "is_archived": s.is_archived,
            "can_edit": can_edit_setup(request.user, s),
            "created_at": s.created_at.isoformat(),
            "created_at_display": s.created_at.strftime("%d.%m.%Y"),
        })

    return render(request, "balance/setups_list.html", {
        "setups_data": setups_data,
        "available_classes": sorted(available_classes.items(), key=lambda kv: kv[1]),
        "available_tracks": sorted(available_tracks.items(), key=lambda kv: kv[1]),
        "has_balance_access": has_balance_access,
        "active_tab": "setups",
    })


@login_required
@require_POST
@nocache_page
@balance_ratelimit("setup_copy", limit=30, window_seconds=60)
def setup_copy(request, pk):
    """
    Этап 6 плана — только владелец источника (can_edit_setup): получателю
    шера копия была бы бессмысленна (осталась бы на том же kart, у того же
    владельца, см. план Блока 3, решение 2). Семантика полей — по таблице
    плана "setup_copy": погода/температура/трасса/заметки сбрасываются на
    дефолты, шеринг снят, is_archived=False независимо от источника
    (копия архивного сетапа — не архивная копия), parent_setup = источник.
    """
    source = get_object_or_404(
        visible_setups_for_user(request.user, include_archived=True).select_related("kart", "kart_class"),
        pk=pk,
    )
    if not can_edit_setup(request.user, source):
        return JsonResponse({"error": "Нет прав на этот сетап."}, status=404)

    if Setup.objects.filter(kart=source.kart).count() >= MAX_SETUPS_PER_KART:
        return JsonResponse({"error": "Достигнут лимит количества сетапов на этот карт."}, status=400)

    copy = Setup(
        kart=source.kart,
        kart_class=source.kart_class,
        name=f"{source.name} — копия"[:150],
        weight_lf=source.weight_lf, weight_rf=source.weight_rf,
        weight_lr=source.weight_lr, weight_rr=source.weight_rr,
        driver_weight_kg=source.driver_weight_kg,
        wheelbase_mm=source.wheelbase_mm,
        track_front_mm=source.track_front_mm,
        track_rear_mm=source.track_rear_mm,
        weather="dry",
        temp_air_c=None,
        temp_track_c=None,
        temp_source="manual",
        track=None,
        notes="",
        shared_with_team=False,
        shared_with_driver=False,
        parent_setup=source,
        is_archived=False,
    )
    try:
        copy.full_clean()
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
    copy.save()

    for b in source.ballasts.all():
        Ballast.objects.create(
            setup=copy, weight_kg=b.weight_kg, pos_x_mm=b.pos_x_mm, pos_y_mm=b.pos_y_mm,
            label=b.label, sort_order=b.sort_order,
        )

    return JsonResponse({"id": copy.id, "name": copy.name})


@login_required
@require_POST
@nocache_page
@balance_ratelimit("setup_archive", limit=30, window_seconds=60)
def setup_archive(request, pk):
    """Setup-уровня — отдельно от kart_archive (тот архивирует физический
    карт целиком, этот — один снимок развесовки на нём)."""
    setup = get_object_or_404(visible_setups_for_user(request.user, include_archived=True), pk=pk)
    if not can_edit_setup(request.user, setup):
        return JsonResponse({"error": "Нет прав на этот сетап."}, status=404)

    data = _json_body(request)
    setup.is_archived = bool(data.get("archived", True))
    setup.save(update_fields=["is_archived", "updated_at"])
    return JsonResponse({"id": setup.id, "is_archived": setup.is_archived})


@login_required
@require_POST
@nocache_page
@balance_ratelimit("setup_share", limit=30, window_seconds=60)
def setup_share(request, pk):
    """
    {"target": "team"|"driver", "shared": bool}. Валидирует, что цель вообще
    применима к типу владения картом — иначе флаг сохранился бы, но
    visible_setups_for_user (website/services/balance_permissions.py) его
    никогда бы не проверил: shared_with_team резолвится только через
    kart.owner_driver (личный карт → команды владельца-пилота),
    shared_with_driver — только через kart.owner_team + roster_entry
    (карт команды → закреплённый в ростере пилот). Без этой проверки
    получился бы "рабочий" на вид переключатель, который молча ничего
    не делает — хуже отсутствия переключателя вовсе.
    """
    setup = get_object_or_404(
        visible_setups_for_user(request.user, include_archived=True).select_related("kart"),
        pk=pk,
    )
    if not can_edit_setup(request.user, setup):
        return JsonResponse({"error": "Нет прав на этот сетап."}, status=404)

    data = _json_body(request)
    target = data.get("target")
    shared = bool(data.get("shared", True))

    if target == "team":
        if not setup.kart.owner_driver_id:
            return JsonResponse({"error": "Открыть команде можно только личный карт пилота."}, status=400)
        field_name = "shared_with_team"
    elif target == "driver":
        if not setup.kart.owner_team_id or not setup.kart.roster_entry_id:
            return JsonResponse(
                {"error": "Открыть пилоту можно только карт команды, закреплённый за пилотом в ростере."},
                status=400,
            )
        field_name = "shared_with_driver"
    else:
        return JsonResponse({"error": "Некорректная цель шеринга."}, status=400)

    setattr(setup, field_name, shared)
    setup.save(update_fields=[field_name, "updated_at"])
    return JsonResponse({"id": setup.id, field_name: shared})


@login_required
@nocache_page
def setups_compare(request):
    """
    Блок 7 ТЗ (§8.1) — «два сетапа рядом» + дельты. GET, ничего не мутирует —
    тот же паттерн прав/кэша, что setups_list (без rate-limit).

    Пикер (два <select>, group by карт) работает и как единственный вход
    (без query-параметров показывает только выбор), и как способ поменять
    одну из сторон, не возвращаясь на список сетапов.

    a/b — необязательные query-параметры id сетапа. Недоступный/несуществующий
    id тихо игнорируется (не 404): это read-only страница выбора из СВОЕГО
    же списка видимых сетапов (id никогда не попадёт в picker_groups, если
    недоступен), а не прямой доступ к чужим данным по произвольному pk —
    мягкая деградация здесь уместнее hard-fail.
    """
    visible = list(
        visible_setups_for_user(request.user, include_archived=True)
        .select_related("kart", "kart_class")
        .order_by("kart__name", "-created_at")
    )
    by_id = {s.id: s for s in visible}

    def _pick(param):
        raw = request.GET.get(param)
        if raw and raw.isdigit():
            return by_id.get(int(raw))
        return None

    setup_a = _pick("a")
    setup_b = _pick("b")

    picker_groups = []
    groups_by_kart = {}
    for s in visible:
        group = groups_by_kart.get(s.kart_id)
        if group is None:
            group = {"kart_name": s.kart.name, "options": []}
            groups_by_kart[s.kart_id] = group
            picker_groups.append(group)
        group["options"].append({"id": s.id, "label": f"{s.name} · {s.kart_class.name}"})

    comparison = None
    if setup_a is not None and setup_b is not None:
        comparison = compare_setups(setup_a, setup_b)

    context = user_karts_context(request.user)
    context.update({
        "active_tab": "setups",
        "picker_groups": picker_groups,
        "setup_a": setup_a,
        "setup_b": setup_b,
        "comparison": comparison,
    })
    return render(request, "balance/compare.html", context)
