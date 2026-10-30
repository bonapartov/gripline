"""Shared published-result, session and event-date rules for sporting data."""
from django.utils import timezone


SESSIONS = (
    ('qual', 'квалификация', 'qual_best_lap_ms', ('qual_s1_ms', 'qual_s2_ms', 'qual_s3_ms'), 'qual_status'),
    ('pre_final', 'предфинал', 'pre_final_best_lap_ms',
     ('pre_final_s1_ms', 'pre_final_s2_ms', 'pre_final_s3_ms'), 'pre_final_status'),
    ('final', 'финал', 'best_lap_ms', ('best_s1_ms', 'best_s2_ms', 'best_s3_ms'), 'final_status'),
)


def published_results():
    from website.models import RaceResult
    return RaceResult.objects.filter(group__page__live=True)


def result_datetime(page):
    """Last occurrence end in site timezone; legacy undated pages use publication.

    Iterate the prefetched relation rather than issuing one order_by query per row.
    """
    ends = [o.end for o in page.occurrences.all() if o.end is not None]
    value = max(ends) if ends else (page.last_published_at or page.first_published_at)
    if value is not None and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value


def valid_sessions(result):
    """DQ/DNS sessions cannot supply a lap. DNF may have a valid timed lap."""
    return [s for s in SESSIONS if getattr(result, s[4], '') not in ('DQ', 'DNS')]


def best_session_lap(result):
    candidates = [(getattr(result, s[2]), s[0]) for s in valid_sessions(result)
                  if getattr(result, s[2]) is not None and getattr(result, s[2]) > 0]
    return min(candidates, key=lambda x: x[0]) if candidates else (None, None)


def session_sectors(result):
    return {s[0]: tuple(getattr(result, f) for f in s[3]) for s in valid_sessions(result)}
