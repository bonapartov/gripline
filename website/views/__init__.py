"""Вью сайта по разделам.

Пакет сохраняет прежний импорт `website.views`: все публичные и служебные
имена реэкспортируются из доменных модулей, поэтому URL-маршруты, сервисы и
тесты продолжают работать без изменений.
"""
from .common import *  # noqa: F401,F403
from .public import *  # noqa: F401,F403
from .ratings import *  # noqa: F401,F403
from .stats import *  # noqa: F401,F403
from .staff import *  # noqa: F401,F403
from .snippets import *  # noqa: F401,F403

# Служебные помощники: звёздочный импорт имена с подчёркиванием не переносит.
from .common import (  # noqa: E402
    _compute_driver_current_teams, _get_current_team_driver_ids,
)
from .ratings import (  # noqa: E402
    _career_stat_percentiles, _class_ranking_entries,
    _class_stat_percentiles, _compute_all_track_records,
    _compute_driver_track_records_live, _compute_form_trend,
    _get_driver_best_title, _get_driver_career_highlights,
    _get_driver_class_ratings, _get_driver_track_records,
    _nearby_class_rivals, _quantile, _rating_inactive, _track_record_row,
)
