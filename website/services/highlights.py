"""Общая логика лесенки «Highlights» — переиспользуется медиа-китом/страницей
пилота И медиа-китом/страницей команды. Все функции работают над плоским
списком `RaceResult` — вызывающая сторона решает, чьи это результаты
(одного пилота или всего ростера команды).

Вынесено из website/services/mediakit.py при добавлении highlights команды
(ТЗ «ЛК команды», раздел 6) — та же иерархия «стабильность» и тот же
фолбэк, дублировать не стали.
"""

# Порог «стабильности» для топ-5 берётся вдвое меньшим, чем для топ-10
# (AnalyticsSettings.mediakit_top10_min_field).
STABILITY_MIN_RACES = 5
STABILITY_MIN_RATE = 0.6


def is_finished(result):
    return result.final_status not in ('DNF', 'DQ')


def stability_highlight(results, settings):
    """«Стабильно топ-5/топ-10» — только если типичное поле достаточно большое
    и доля попаданий высокая, иначе формулировка была бы нечестной."""
    threshold_10 = settings.mediakit_top10_min_field
    threshold_5 = max(threshold_10 // 2, 1)

    def _tier(threshold, top_n):
        qualifying = [
            r for r in results
            if r.group_size and r.group_size >= threshold and is_finished(r)
        ]
        if len(qualifying) < STABILITY_MIN_RACES:
            return None
        hits = sum(1 for r in qualifying if r.position <= top_n)
        rate = hits / len(qualifying)
        if rate < STABILITY_MIN_RATE:
            return None
        return {'top_n': top_n, 'min_field': threshold, 'races': len(qualifying), 'rate': round(rate * 100, 1)}

    return _tier(threshold_5, 5) or _tier(threshold_10, 10)


def fallback_highlights(results):
    """Гарантированный фолбэк — лучший результат и/или лучший круг.
    Используется, только если титул/подиум/стабильность не применимы."""
    import django.utils.timezone as timezone

    items = []

    finished = [r for r in results if is_finished(r)]
    if finished:
        best_position = min(r.position for r in finished)
        best_result = max(
            (r for r in finished if r.position == best_position),
            key=lambda r: getattr(r, 'event_date', None) or r.group.page.last_published_at or r.group.page.first_published_at or timezone.now(),
        )
        items.append({'type': 'best_result', 'position': best_position, 'result': best_result})

    lap_results = [r for r in results if r.best_lap_all_ms]
    if lap_results:
        best_lap_result = min(lap_results, key=lambda r: r.best_lap_all_ms)
        items.append({
            'type': 'best_lap',
            'lap_ms': best_lap_result.best_lap_all_ms,
            'track': getattr(best_lap_result.group.page, 'track', None),
            'class_name': best_lap_result.group.race_class.name,
            'result': best_lap_result,
        })

    return items
