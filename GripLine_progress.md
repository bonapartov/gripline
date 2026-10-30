# GripLine — точка продолжения

Обновлено: 2026-10-30 (Europe/Moscow)

## Код и выкладка

- Коммит `375014cfb1c1b9d815525251f5abc491dd3604fa` (`Fix race result status and rating eligibility`) находится в `main` и опубликован в `origin/main`.
- Этот коммит развёрнут на production штатным `deploy.sh`.
- Миграция `website.0110_analytics_min_class_races` применена. Порог `min_races_per_class` в production сейчас равен 3.
- После выкладки подтверждены SHA коммита на сервере, чистое Git-дерево, активные сервисы `gripline` и `gripline-setupkart`, HTTP 200.
- В изолированной тестовой среде прошли 133 теста; результаты прогона: `diagnostics/data_fixes_20261030/results.xml`.

## Production-пересчёт

- 2026-10-30 на сервере выполнена команда `python manage.py update_ratings --entity all --model all`.
- В последнем `UpdateLog`: статус `success`, сообщение «Пересчёт завершён успешно», `race_results_count=2763`; метка `AnalyticsMetadata.last_updated` обновлена.
- В выводе команды: BT и PageRank обновили по 27 шасси; BT создал записи для 426 пилотов. Для части классов BT указал «Недостаточно данных» — это ожидаемое следствие порога и имеющихся результатов.
- Рейтинги рассчитывались по моделям BT, PageRank, ансамбль и Context-Aware для пилотов; BT и PageRank для шасси.
- После рейтингов 2026-10-30 выполнена production-команда `python manage.py update_track_records`. Обновлены кэши всех 10 трасс; проверка подтвердила 46 записей рекордов, без ссылок на неопубликованные/несоответствующие результаты.

## Резервные копии production БД

Перед миграцией создан и проверен `pg_dump`:

- `/var/backups/gripline/gripline_db_before_375014c_20261030T205139Z.dump`
- Размер 10,400,083 байта; SHA256 `3117d3e776de6d713dd20d85237744c5eefa0895662c245e06606366a2ad4b3d`; `pg_restore --list` прошёл.

Перед пересчётом рейтингов создан отдельный дамп уже после миграции:

- `/var/backups/gripline/gripline_db_before_ratings_recalc_375014c_20261030T205348Z.dump`
- Размер 10,400,111 байт; SHA256 `7d55c3cb950d7ac581d3664d399bea6fe1de9a08ff85a71549a13722a38fd468`; `pg_restore --list` прошёл.

Оба дампа оставлены на сервере; восстановление не выполнялось.

Перед пересчётом кэша рекордов создан и проверен отдельный дамп:

- `/var/backups/gripline/gripline_db_before_track_records_20261030T211814Z.dump`
- Размер 10,397,133 байта; SHA256 `59963b1362244bd0babd952c1a285a8a576325630abcfc01b1f29af7530842e8`; `pg_restore --list` прошёл.

## Локальное состояние и продолжение

- Локальная ветка `main` синхронизирована с `origin/main`; коммитов сверх удалённой ветки нет.
- В рабочем дереве остались незакоммиченные материалы исследования: `GripLine_code_research.md`, `GripLine_data_checks.md`, `diagnostics/`. Они не входили в production-коммит.
- Подробные правила исправленной цепочки: `docs/claude/result-data-rules.md`.
- При продолжении не запускать повторные пересчёты без отдельной необходимости: рейтинги и кэш рекордов уже обновлены. Если потребуется менять production БД, сначала создать отдельный проверенный бэкап.
