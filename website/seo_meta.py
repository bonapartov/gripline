"""title/description/canonical/og для страниц без Wagtail Page (пилот, команда).

wagtailseo/meta.html выводит теги только для Wagtail-страниц (`self.seo_pagetitle`),
поэтому у Driver/Team (обычные Django-модели) <head> был пустой — Яндекс подставлял
вместо заголовка URL, а в сниппет брал текст меню. Вьюха кладёт в контекст `seo`
(dict из функций ниже), base.html выводит его через includes/seo_meta.html.

Правила заголовка — справки Яндекса и Google (21.10.2026): имя + одно отличающее
уточнение + бренд в конце; без перечислений вида «рейтинг, результаты, фото» —
перечисление фактов уходит в description, и только того, что есть на странице.
"""

from website.schema import _absolute_image_url, _absolute_url

BRAND = "Gripline"


def _plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 10 <= n % 100 < 20:
        return f"{n} {few}"
    return f"{n} {many}"


def _default_image_url(site):
    """Картинка по умолчанию из «Настройки → SEO» (та же, что у Wagtail-страниц)."""
    if not site:
        return None
    from wagtailseo.models import SeoSettings

    return _absolute_image_url(site, SeoSettings.for_site(site).og_image_default)


def _meta(site, title, description, path, image, og_type="profile"):
    return {
        "title": title,
        "description": description,
        "canonical": _absolute_url(site, path),
        "image": image or _default_image_url(site),
        "og_type": og_type,
    }


def driver_seo(driver, site, *, current_class=None, current_team=None,
               total_starts=0, wins=0, podiums=0, titles_count=0, class_rating=None):
    """current_class — класс самого свежего по дате старта; class_rating — карточка
    рейтинга этого класса из _get_driver_class_ratings (место — только если пилот в таблице)."""
    from website.models import Driver

    has_namesake = Driver.objects.filter(
        live=True,
        first_name__iexact=driver.first_name,
        last_name__iexact=driver.last_name,
    ).exclude(pk=driver.pk).exists()

    title = f"{driver.full_name} — пилот картинга"
    if current_class:
        title += f", {current_class}"
    if has_namesake and driver.city:
        # Однофамильцы получили бы одинаковые заголовки — различаем городом
        title += f", {driver.city}"
    title += f" | {BRAND}"

    lead = f"{driver.full_name} — пилот картинга"
    if current_class:
        lead += f", класс {current_class}"
    if current_team:
        lead += f", команда «{current_team.name}»"
    if driver.city:
        lead += f", {driver.city}"
    parts = [lead + "."]

    if total_starts:
        stats = [_plural(total_starts, "старт", "старта", "стартов")]
        if wins:
            stats.append(_plural(wins, "победа", "победы", "побед"))
        if podiums:
            stats.append(_plural(podiums, "подиум", "подиума", "подиумов"))
        if titles_count:
            stats.append(_plural(titles_count, "титул", "титула", "титулов"))
        parts.append(", ".join(stats) + ".")

    if class_rating and class_rating.get("rank") and not class_rating.get("out_reason"):
        # Класс уже назван в первой фразе — карточка рейтинга того же класса
        parts.append(f"{class_rating['rank']}-е место из {class_rating['total']} в рейтинге Gripline.")

    if total_starts:
        parts.append("Результаты по этапам, лучшие круги и история выступлений.")

    return _meta(
        site, title, " ".join(parts), driver.get_absolute_url(),
        _absolute_image_url(site, driver.photo),
    )


def team_seo(team, site, *, classes=(), drivers_count=0, team_stats=None):
    """classes — названия классов текущего состава в порядке регламента."""
    title = f"{team.name} — картинг-команда"
    if team.city:
        title += f", {team.city}"
    title += f" | {BRAND}"

    lead = f"Картинг-команда «{team.name}»"
    if team.city:
        lead += f", {team.city}"
    parts = [lead + "."]

    if drivers_count:
        roster = f"В составе {_plural(drivers_count, 'пилот', 'пилота', 'пилотов')}"
        if classes:
            roster += ": " + ", ".join(classes)
        parts.append(roster + ".")

    starts = (team_stats or {}).get("total_starts") or 0
    if starts:
        stats = [_plural(starts, "старт", "старта", "стартов")]
        if team_stats.get("wins"):
            stats.append(_plural(team_stats["wins"], "победа", "победы", "побед"))
        if team_stats.get("podiums"):
            stats.append(_plural(team_stats["podiums"], "подиум", "подиума", "подиумов"))
        parts.append(", ".join(stats) + ".")
        parts.append("Состав, результаты и история выступлений команды.")

    return _meta(
        site, title, " ".join(parts), team.get_absolute_url(),
        _absolute_image_url(site, team.logo),
    )


def rating_seo(site, *, race_class=None, drivers_count=0, leader=None, is_default=False):
    """Рейтинг /top/drivers/: у каждого класса свой адрес (?class=ID) — свой заголовок.
    is_default — класс, открывающийся без параметра: canonical на /top/drivers/, без дубля."""
    path = "/top/drivers/"
    if race_class and not is_default:
        path += f"?class={race_class.id}"
    if not race_class:
        return _meta(site, f"Рейтинг пилотов картинга | {BRAND}",
                     "Рейтинг пилотов картинга по результатам соревнований.", path, None, "website")

    title = f"Рейтинг пилотов картинга — {race_class.name} | {BRAND}"
    parts = [f"Рейтинг пилотов картинга в классе {race_class.name} по результатам соревнований."]
    if drivers_count:
        parts.append(f"В таблице {_plural(drivers_count, 'пилот', 'пилота', 'пилотов')}"
                     + (f", лидер — {leader.full_name}." if leader else "."))
    parts.append("Места, победы, подиумы и форма; модель Bradley-Terry.")
    return _meta(site, title, " ".join(parts), path, None, "website")


def track_seo(track, site, *, events_count=0, record_classes=0, next_event=None):
    """next_event — ближайшее предстоящее соревнование (dict из track_detail_view)."""
    title = f"{track.name} — картинг-трасса"
    if track.city and track.city.lower() not in track.name.lower():
        title += f", {track.city}"
    title += f" | {BRAND}"

    lead = f"Картинг-трасса «{track.name}»"
    place = ", ".join(x for x in (track.city, track.address) if x)
    if place:
        lead += f": {place}"
    parts = [lead + "."]
    if next_event:
        # У этапа часто безликое название («1 этап») — с чемпионатом
        name = next_event["title"]
        champ = ""
        parent = next_event.get("championship")  # фактически родитель этапа — обычно StagePage
        if parent is not None:
            from website.models import ChampionshipPage

            found = ChampionshipPage.objects.ancestor_of(parent, inclusive=True).first()
            champ = found.title if found else ""
        if champ and champ.lower() not in name.lower():
            name = f"{champ}, {name}"
        parts.append(f"Ближайшее соревнование — {name}, {next_event['start']:%d.%m.%Y}.")
    if events_count:
        parts.append(_plural(events_count, "соревнование", "соревнования", "соревнований")
                     + " на трассе" + (f", рекорды круга в {_plural(record_classes, 'классе', 'классах', 'классах')}"
                                        if record_classes else "") + ".")
    return _meta(site, title, " ".join(parts), track.get_absolute_url(),
                 _absolute_image_url(site, track.photo), "place")


# --- Описания Wagtail-страниц соревнований (21.10.2026) ---------------------------
# Ручное «Описание для поиска» из админки (вкладка «Продвижение») всегда главнее:
# эти функции вызываются из seo_description моделей, только если оно пустое.

def _date(dt):
    return f"{dt:%d.%m.%Y}" if dt else ""


def _with_championship(title, championship):
    """«1 этап» → «1 этап, Зимний кубок …» — если чемпионат ещё не назван в заголовке."""
    if championship and championship.title.lower() not in title.lower():
        return f"{title}, {championship.title}"
    return title


def event_page_description(page):
    """EventPage — класс на этапе: таблица результатов и хронометраж."""
    from website.models import RaceResult

    occurrence = page.occurrences.first()
    groups = list(page.race_class_groups.select_related("race_class"))
    title = page.title
    # Часто заголовок — просто «1 этап»: без класса описание у всех классов этапа одинаковое
    names = list(dict.fromkeys(g.race_class.name for g in groups if g.race_class.name.lower() not in title.lower()))
    if names:
        title += ", " + ", ".join(names)
    lead = _with_championship(title, page.get_championship())
    place = ", ".join(x for x in (
        _date(occurrence.start if occurrence else None),
        f"трасса {page.track.name}" if page.track else "",
    ) if x)
    parts = [lead + (f": {place}." if place else ".")]

    results = RaceResult.objects.filter(group__page=page)
    count = results.values("driver_id").distinct().count()
    if count:
        line = f"Результаты: {_plural(count, 'пилот', 'пилота', 'пилотов')}"
        if len(groups) == 1:
            winner = groups[0].sorted_results().select_related("driver").first()
            if winner and winner.driver:
                line += f", победитель — {winner.driver.full_name}"
        parts.append(line + ".")
    return " ".join(parts)


def stage_page_description(page):
    """StagePage — хаб этапа: даты, трасса, классы."""
    lead = _with_championship(page.title, page.get_parent().specific)
    when = _date(page.start_date)
    if page.end_date and page.start_date and page.end_date.date() != page.start_date.date():
        when = f"{page.start_date:%d.%m}–{page.end_date:%d.%m.%Y}"
    place = ", ".join(x for x in (when, f"трасса {page.track.name}" if page.track else "") if x)
    parts = [lead + (f": {place}." if place else ".")]
    classes = page.get_classes_with_results()
    if classes:
        parts.append("Классы: " + ", ".join(classes) + ".")
    return " ".join(parts)


def championship_page_description(page):
    from website.models import RaceClass, StagePage

    stages = StagePage.objects.child_of(page).live()
    parts = [f"{page.title} — соревнования по картингу."]
    if stages.exists():
        tracks = list(dict.fromkeys(s.track.name for s in stages.select_related("track") if s.track))
        line = _plural(stages.count(), "этап", "этапа", "этапов")
        if tracks:
            line += ", " + ("трасса " if len(tracks) == 1 else "трассы: ") + ", ".join(tracks)
        parts.append(line + ".")
    # Порядок — по регламенту (RaceClass.Meta.ordering)
    class_names = list(RaceClass.objects.filter(
        raceclassresultgroup__page__path__startswith=page.path,
        raceclassresultgroup__class_results__isnull=False,
    ).distinct().values_list("name", flat=True))
    if class_names:
        parts.append("Классы: " + ", ".join(class_names) + ".")
        parts.append("Турнирные таблицы и результаты этапов.")
    return " ".join(parts)
