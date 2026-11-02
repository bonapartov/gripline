# Проверка ТЗ team-access v0.2

## Интеграция с main — 02.11.2026

В ветку PR №3 включён `main` на `526fadb3bd59379fa65322cbef34cbf192d72b8f`:
квитанции SetupKart `1eef330`, представление DNS/DQ `2720010` и документация
импортов `526fadb`. Merge прошёл без текстовых конфликтов. История обеих веток
сохранена; force push и слияние PR в main не выполнялись.

Добавлена `.github/workflows/team-access.yml`: расширенный набор ниже плюс
`website/tests/test_result_presentation.py` запускается на отдельной PostgreSQL 16.2
в GitHub Actions. Настройки `mysite.settings.test_team_access_ci` фиксируют loopback,
искусственную БД и тестовые учётные данные; production DSN не используется.
Workflow имеет только `contents: read`, не выполняет деплой и не использует secrets.
Четыре дополнительных сценария проверяют квитанции v2 вместе с неподтверждённым
составом, принятием приглашения и отзывом членства/прав менеджера в обоих режимах
legacy. Квитанция accepted подтверждает сохранение строки, а не доступ к пилоту.

В облачной рабочей среде: Python 3.12.14, зависимости из requirements.txt;
`manage.py check`, compileall и обе whitespace-проверки прошли.
`makemigrations --check --dry-run` не нашёл изменений моделей, но выдал предупреждение
о недоступности локальной БД: это не проверка её истории. Собрано **355 тестов**
(`--collect-only`), что само по себе не означает успешный прогон.
Запуск локальной PostgreSQL через pgserver остановился на невозможности создать
системного пользователя; тесты с БД перенесены в CI. Актуальный результат выполнения
и точный SHA нужно брать из check **Team access integration / synthetic-postgres**
в PR №3, а не из исторического числа 341 ниже.

Подтверждённый прогон объединённого кода `07db0ef25d034017e9db5a88b5b2909158e3ad2f`:
[GitHub Actions #41392675508](https://github.com/bonapartov/gripline/actions/runs/41392675508)
— **355 passed, 13 warnings, 49.58 s**, без skipped. Python 3.12.15, Django 5.2.17,
PostgreSQL 16.2. Django check и makemigrations --check также прошли в CI с доступной БД.
Предупреждения тестов прежние: URLField в Django 6 и defusedxml.cElementTree.
Реальные операции новых миграций прошли внутри набора; это по-прежнему не полный replay.

### Условия решения о слиянии и выпуске

1. Успешный CI на актуальном коде объединённой ветки и review итогового diff.
2. До production-миграций — проверенный бэкап, восстановление в закрытое изолированное
   окружение и проверка обновления этой копии. В этой сессии копии production нет;
   данный этап не выполнен. Искусственные миграционные тесты его не заменяют.
3. На обновлённой копии выполнить `audit_team_access --dry-run --summary` и подробный
   аудит. Команда требует полей website.0111; на старой схеме её запускать нельзя.
   Не помещать production-вывод и персональные данные в репозиторий/CI.
4. Отдельно согласовать подготовительный production-выпуск с временным
   `TEAM_ACCESS_LEGACY_ENABLED=true`, окно, резервную копию и сценарий отката.
   После обновления схемы повторить read-only аудит на production.
5. Разобрать активные legacy-связи, получить новые подтверждения или оформить
   обоснованные исключения. Строгий режим включать отдельным решением после
   классификации; затем проверить HTTP-матрицу доступа и сбросить page-cache.

PR остаётся draft до отдельного решения. Production, рабочие данные и кэш не
менялись; аудит production и проверка его копии не выполнены. Полный replay старой
истории, браузерный QA и HTTP-проверка FastAPI остаются отдельными ограничениями.
Импорт очков, аналитические пересчёты, выпуск APK и доработка конфликтов SetupKart
не входят в эту интеграцию.

## Исторический прогон 31.10.2026

31.10.2026. Исходный SHA после `git fetch origin`:
`889f6718f0297613f4bca2b6ffb1cbd16094af79`. Ветка `feat/confirmed-team-access`.
ТЗ версии 0.2 прочитано, правила A–C учтены. Исходная рабочая папка была чистой.

Окружение: Python 3.12.14, Django 5.2.17, PostgreSQL 16.2 (локальный pgserver 0.1.4),
Unix socket `/tmp/gripline-test-pg`; искусственная БД `test_gripline_synthetic`.
Настройки `mysite.settings.test_team_access` фиксируют отдельную локальную БД и не используют
production DSN. Все файлы тестов искусственные, почта locmem. Production не подключался.

## Выполнено

```bash
git fetch origin
python manage.py check --settings=mysite.settings.test_team_access
python manage.py makemigrations --check --dry-run --settings=mysite.settings.test_team_access
python -m pytest teams/test_access.py teams/test_access_migrations.py applications accounts \
  website/tests/test_registration_flows.py website/tests/test_claim_notify.py \
  website/tests/test_setupkart_auth.py website/tests/test_setupkart_sync.py \
  website/tests/test_setupkart_records.py website/tests/test_result_data_rules.py \
  website/tests/test_seo_meta.py website/tests/test_schema.py website/tests/test_demo_pilots.py \
  --ds=mysite.settings.test_team_access --no-cov -q
git diff --check
```

Исполняемый Python — `.venv/bin/python` (для pytest — `python -m pytest`).
Последний расширенный прогон: **341 passed, 13 warnings, 42.93 s**, без skipped.
Предупреждения: URLField default scheme в Django 6 и deprecated defusedxml.cElementTree.
Django check: без ошибок. Проверка схемы: новых незаписанных изменений моделей нет.
Whitespace-проверка: без ошибок.

Первоначальные проверки (до уточнения владельца): отсутствие writer из результата; неподтверждённый активный состав; GET/CSRF,
владелец approved-привязки, идемпотентность; отказ/выход/повторное приглашение; stale accepted
не возвращает права; два менеджера и точная команда ресурса; четыре комбинации видимости;
владелец сессии; списки/detail/compare/analytics; запрещённая sync-привязка сохраняется без Driver;
отзыв прав с включённым и прогретым page-cache; текущий ЛК отдельно от копий поданной заявки;
доступ организатора; actual Wagtail form и запрет подделать метаданные; исключение администратора
с основанием/автором; снимок цели подтверждения; read-only аудит и неоднозначная хронология.
Регрессионные фикстуры теперь явно задают искусственное подтверждение.

## Миграции отдельно от no-migrations

Основной pytest использует установленный в репозитории `--no-migrations`.
`teams/test_access_migrations.py` отдельно исполняет **реальные schema operations**
`website.0111` и `teams.0004` вперёд/назад с историческими migration states на тестовой БД.
Проверены: маркировка старой связи legacy без подтверждения/деактивации, default новых строк
unconfirmed, запись журнала, обратимость схемы и сохранность членств/active-флагов.
Это не полный replay всей истории.

Полный replay также запускался на отдельной пустой локальной БД командой
`python manage.py migrate --settings=gripline_test_settings --noinput`.
Временные настройки указывали только на локальную искусственную БД `gripline_synthetic`.
Результат: **ошибка существующей website.0011_techarticleindexpage** —
`relation "website_techarticleindexpage" already exists`, до новых миграций.
Этот дефект истории указан в `pyproject.toml`; его исправление не включено в PR.

## Воспроизведение локального окружения

Установить requirements и pytest/pytest-django/pytest-cov. Для такого же изолированного
PostgreSQL можно дополнительно установить `pgserver==0.1.4`, затем:

```python
from pathlib import Path
import pgserver
import psycopg
server = pgserver.get_server(Path('/tmp/gripline-test-pg'), cleanup_mode=None)
with psycopg.connect(server.get_uri(), autocommit=True) as conn:
    conn.execute('CREATE DATABASE gripline_synthetic')
```

После этого выполнить команды с `mysite.settings.test_team_access` выше.
Не запускать параллельные pytest-процессы с одним именем тестовой БД.

## Ограничения выпуска

- Production-аудит **не выполнен**; готов `audit_team_access --dry-run [--summary]`.
  Ни production-вывод, ни файлы пилотов не сохранялись в репозиторий.
- Старые связи не подтверждаются автоматически и не деактивируются массово.
  Сохранён **временный риск legacy-доступа** при `TEAM_ACCESS_LEGACY_ENABLED=true`.
  Строгий режим протестирован; его выпуск требует отдельного аудита и согласованной
  классификации. Подробный план и ручные проверки — `team-access.md`.
- Полный replay старых миграций с нуля не проходит по указанной причине.
- Весь репозиторий целиком и браузерный визуальный QA не запускались; выполнен указанный
  расширенный набор. FastAPI публичные readers проверены статически, отдельный HTTP-прогон
  FastAPI не выполнялся.
- Деплой, миграции production, очистка production-кэша, рабочие пересчёты и merge PR
  не выполнялись. В тестах рекорды/результаты проверялись только на искусственных данных.
- Откат только кода сохраняет метаданные схемы, но возвращает прежние уязвимые проверки.
  Schema rollback удаляет журнал/метаданные: перед ним нужен отдельный проверенный бэкап.

## Уточнение владельца после первоначального PR

Результат гонки снова автоматически создаёт активное членство без обязательного приглашения.
Новая связь остаётся `unconfirmed`: автоматическое членство не подтверждает доступ к документам,
личным сессиям и новой sync-привязке. Повторный импорт не дублирует связь, не подтверждает её и
не восстанавливает прекращённые права. Приглашение остаётся отдельным способом подтверждения
личных прав, а не условием попадания в состав. Тест результата обновлён под это разделение.

Актуальный расширенный прогон после уточнения: та же команда выше —
**341 passed, 13 warnings, 43.25 s**, без skipped. Проверены автоматическое активное
членство из результата без приглашения, отсутствие подтверждения личных прав, повторный
импорт без дублей и сохранение прекращённого членства. `compileall` и `git diff --check`
также прошли. Production и рабочие пересчёты не выполнялись.
