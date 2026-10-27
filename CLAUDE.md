# Gripline — документация проекта

## Что это

Сайт карт-федерации на Django 5.2 + Wagtail 7.3. Публикует новости, статьи (матчасть), события, результаты соревнований и рейтинги пилотов/шасси.

**Живой сайт:** https://gripline.ru  
**Админка:** https://gripline.ru/admin/

---

## Структура репозитория

```
gripline/
├── mysite/               # Конфиг Django (settings/, urls.py, wsgi.py)
│   └── settings/
│       ├── base.py       # Общие настройки
│       ├── dev.py        # Локальная разработка
│       └── prod.py       # Продакшн
├── website/              # Главное приложение
│   ├── models.py         # Все модели: страницы, пилоты, классы, рейтинг
│   ├── views.py          # Все вью: рейтинг, сравнения, API
│   ├── urls.py           # URL-маршруты приложения
│   ├── wagtail_hooks.py  # Регистрация моделей в Wagtail admin
│   ├── management/commands/
│   │   └── update_ratings.py   # Команда пересчёта рейтингов
│   ├── migrations/       # Миграции БД
│   └── templates/        # HTML-шаблоны
│       └── coderedcms/
│           ├── pages/    # Шаблоны страниц (home_page.html, rating_info_page_ld.html, …)
│           └── snippets/ # Частичные шаблоны (top_drivers_page.html, driver_page.html, …)
├── analytics/            # Модели рейтинга (независимый Python-пакет)
│   ├── core/
│   │   └── data_loader.py      # Загрузка данных из БД в DataFrame
│   ├── bradley_terry/
│   │   └── model.py            # BT с Lasso-регуляризацией
│   ├── pagerank/
│   │   └── model.py            # PageRank
│   ├── ensemble/               # Ансамблевая модель BT+PR
│   └── context/                # Контекстная модель (погода, шины)
├── organizers/           # Организаторы соревнований
├── accounts/             # Пользователи
├── teams/                # Команды
├── tg_bot/               # Telegram-бот
├── templates/            # Глобальные шаблоны (navbar, footer, base)
├── fastapi/              # FastAPI сервис (мобильный API, порт 8001)
│   ├── main.py           # Точка входа, CORS, роутеры
│   ├── database.py       # SQLAlchemy engine + get_db()
│   ├── requirements.txt
│   ├── .env.example
│   ├── auth/             # JWT-авторизация
│   │   ├── jwt.py        # verify_password, create_access_token, decode_token
│   │   └── router.py     # POST /auth/login
│   ├── models/           # SQLAlchemy-модели (только чтение, без миграций)
│   │   ├── user.py       # AuthUser, UserProfile
│   │   └── driver.py     # Driver
│   └── routers/
│       └── pilots.py     # GET /pilot/me, GET /pilot/profile
├── flutter_app/          # Flutter мобильное приложение
│   ├── pubspec.yaml
│   ├── lib/
│   │   ├── main.dart         # Точка входа, Firebase init
│   │   ├── router.dart       # GoRouter + auth redirect
│   │   ├── theme.dart        # Тёмная тема
│   │   ├── config.dart       # baseUrl, константы
│   │   ├── models/           # AuthUser, DriverProfile
│   │   ├── services/         # api_client, auth_service, push_service
│   │   ├── screens/          # auth/, feed/, pilots/, profile/
│   │   └── widgets/          # main_shell.dart (bottom nav)
│   ├── android/app/google-services.json.example
│   └── ios/Runner/GoogleService-Info.plist.example
├── DESIGN_SYSTEM.md      # Дизайн-система (токены CSS, правила)
└── manage.py
```

---

## Git-ветки

Одна ветка — `main`. Это единственная ветка. Сервер работает на `main`.

**Workflow разработки:**
1. Работаем локально в `main` (или в feature-ветке если фича большая)
2. Коммит → `git push origin main`
3. Деплой: `./deploy.sh` (запускает pull + collectstatic + migrate + restart на сервере)

**Деплой вручную (если deploy.sh недоступен):**
```bash
ssh root@92.63.192.42
cd /www/wwwroot/gripline.ru
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
systemctl restart gripline
```

**Важно:** никогда не редактировать файлы напрямую на сервере — только через git. Если потребовалось исправить что-то напрямую — сразу коммитить изменение локально и пушить.

---

## Сервер

**Хост:** `cleantogo` (root@cleantogo)  
**Путь:** `/www/wwwroot/gripline.ru`  
**Сервис Django:** `gripline` (gunicorn, 3 воркера, порт 8000)  
**Сервис FastAPI:** `gripline-api` (uvicorn, 2 воркера, порт 8001) — **задеплоен и работает**  
**Сервис API приложения SetupKart:** `gripline-setupkart` (gunicorn, 1 воркер × 4 потока, порт 8002) — nginx отдаёт ему `/api/setupkart/`, чтобы приложение не занимало воркеры сайта. Юнит — `deploy/systemd/gripline-setupkart.service`, location — `deploy/nginx/setupkart.conf`; `deploy.sh` перезапускает оба. Второй воркер не помещается в память (воркер ~220 МБ, сервер 1,8 ГБ)  
**Python venv Django:** `/www/wwwroot/gripline.ru/venv`  
**Python venv FastAPI:** `/www/wwwroot/gripline.ru/fastapi/venv`  
**nginx конфиг:** `/etc/nginx/sites-available/gripline`  
**SSH:** `root@92.63.192.42`

### Основные команды на сервере

```bash
# Перезапуск Django
systemctl restart gripline

# Логи Django
journalctl -u gripline -f

# Активировать venv Django
cd /www/wwwroot/gripline.ru && source venv/bin/activate

# Пересчёт рейтингов (запускать вручную после ввода новых результатов)
python manage.py update_ratings --entity driver --model bt

# Миграции
python manage.py migrate

# Django shell
python manage.py shell

# Запуск FastAPI (локально / dev)
cd fastapi && venv/bin/uvicorn main:app --reload --port 8001

# Перезапуск FastAPI
systemctl restart gripline-api

# Логи FastAPI
journalctl -u gripline-api -f
```

Первичная настройка FastAPI на новом сервере (venv, systemd, nginx) — `docs/claude/platform-fastapi-flutter.md`. В `fastapi/main.py` обязателен `root_path="/api/mobile"`, иначе Swagger за nginx грузит `/openapi.json` не по тому адресу.

### Деплой обновлений FastAPI

```bash
# После cherry-pick на сервере
systemctl restart gripline-api
```

---

## База данных

PostgreSQL. Настройки через переменные окружения:
- `POSTGRES_DB` — имя БД
- `POSTGRES_HOST` — хост (по умолчанию localhost)
- `POSTGRES_USER`, `POSTGRES_PASSWORD`

---

## Ключевые модели (`website/models.py`)

| Модель | Описание |
|--------|---------|
| `Driver` | Пилот. Поле `rating_by_class` (JSON) хранит BT-рейтинг по классам |
| `RaceClass` | Класс карта. Поле `sort_order` задаёт порядок по регламенту дисциплин (не алфавит) везде на сайте — см. `docs/claude/raceclass-order.md` |
| `RaceResult` | **Один пилот на одном этапе в одном классе.** Хранит данные всех сессий: квалификация, предфинал, финал |
| `RaceClassResultGroup` | Класс на этапе. Содержит погоду, шины, двигатель. Связан с `EventPage` |
| `AnalyticsSettings` | Singleton с параметрами аналитики. Доступ: `AnalyticsSettings.get()` |
| `HomePage` | Главная страница. Блоки: герой, новости, топ пилотов, предстоящие события, матчасть |
| `ArticlePage` | Статья/новость |
| `ArticleIndexPage` | Индекс новостей |
| `TechArticleIndexPage` | Индекс матчасти (`/matchast/`, page id=378) |
| `StagePage` | Этап чемпионата |
| `ChampionshipPage` | Чемпионат |

### Поля RaceResult (хронометраж)

Одна запись = один пилот на этапе. Все сессии внутри одной записи:

| Группа | Поля |
|--------|------|
| **Финал** | `position`, `start_position`, `best_lap_ms`, `best_s1_ms`, `best_s2_ms`, `best_s3_ms` |
| **Квалификация** | `qual_position`, `qual_best_lap_ms`, `qual_s1_ms`, `qual_s2_ms`, `qual_s3_ms` |
| **Предфинал** | `pre_final_position`, `pre_final_start_pos`, `pre_final_best_lap_ms`, `pre_final_s1_ms`, `pre_final_s2_ms`, `pre_final_s3_ms` |

Все временны́е поля в **миллисекундах** (integer). Конвертация в шаблоне: фильтр `laptime` из `website/templatetags/website_tags.py`.

---

## AnalyticsSettings (настройки аналитики)

Единственная запись в таблице, редактируется через Wagtail admin.

| Параметр | Умолчание | Описание |
|----------|-----------|---------|
| `lambda_active` | 0.8 | Скорость затухания веса гонки — одна для всех гонок (с 18.10.2026) |
| `lambda_inactive` | 2.0 | Не используется с 18.10.2026 (поле оставлено в БД, в админке скрыто) |
| `inactive_threshold_days` | 365 | Дней без стартов в классе → пилот не показывается в таблице рейтинга |
| `bayes_c` | 4 | Вес байесовского сглаживания C; действует сразу, без пересчёта |
| `class_transfer_weight` | 0.5 | Учёт прошлого класса при переходе: опора сглаживания сдвинута от медианы к месту пилота в прошлом классе на эту долю; действует сразу |
| `min_races_per_class` | 5 | Мин. гонок в классе для расчёта BT |
| `min_comparisons` | 10 | Мин. парных сравнений |
| `min_starts_display` | 3 | Мин. стартов для показа ⚠️ |
| `bt_alpha` | 0.1 | Lasso-регуляризация BT |
| `pagerank_damping` | 0.85 | Демпфирование PageRank |
| `trend_window` | 5 | Гонок для расчёта тренда формы |

---

## Рейтинговая система

### Как считается

1. Все результаты разбиваются на парные сравнения (каждый с каждым внутри заезда)
2. Каждая пара получает вес: `exp(-λ × дней / 365)` — старые гонки весят меньше; λ одна для всех гонок (до 18.10.2026 гонки старше порога неактивности затухали с `lambda_inactive` — скачок веса 45% → 14% на отметке года)
3. Пилоты, **не приехавшие на этап**, получают виртуальное последнее место и проигрывают всем участникам — только этапы **после первого старта пилота в этом классе** (18.10.2026: до перехода в класс он ехал в другом, а не пропускал)
4. Место на странице пилота, в таблице `/top/drivers/`, на главной и в сравнении считается по одной выборке (`rating_out_reason` + `_class_ranking_entries`): без пилотов, не выступавших в классе дольше `inactive_threshold_days`, и без пилотов с числом стартов меньше `min_starts_display` — порог стартов действует, только если его набрали хотя бы 5 пилотов класса (`class_min_starts`), иначе в небольших классах таблица пустела. Пилоту вне таблицы на его странице — «вне рейтинга: давно не выступал / мало стартов». Правило пропусков (п. 3) — по всем этапам класса, независимо от чемпионата: решение владельца 18.10.2026 («у всех этот пропуск есть»)
5. BT-модель с Lasso обучается на взвешенных сравнениях
6. Байесовское сглаживание: `(N × BT + C × медиана) / (N + C)`, C = `AnalyticsSettings.bayes_c` (с 18.10.2026 — 4 вместо 15: пилот проводит в классе обычно 3–9 этапов, 15 стартов набирают единицы). У пилота, перешедшего из другого класса, вместо медианы — опора `медиана + class_transfer_weight × (квантиль нового класса на prior_pct − медиана)` (`views.ClassSmoother`, единственное место формулы — таблица, главная, страница пилота, сравнение). `prior_pct` (0 — последний, 1 — первый) и `prior_class` кладёт `update_ratings` (`transfer_priors`): прошлый класс — где пилот закончил выступать раньше первого старта в новом, 2+ старта; место — по отдельной BT-модели только реальных гонок (`_create_class_comparisons(level_only=True)`: без виртуальных поражений и затухания — иначе пропуски после ухода обваливали уровень, 18.10.2026)
7. Нормировка 0–100 внутри каждого класса

### Структура `rating_by_class`

```json
{
  "1": {
    "score": 0.847,
    "starts": 12,
    "updated": "2026-06-04T12:00:00",
    "last_race_date": "2026-05-15"
  }
}
```

Ключ — `id` класса (`RaceClass`).

### Запуск пересчёта

**В админке (рекомендуется для организатора):** `/admin/analytics/` → кнопка «🚀 Запустить обновление». Асинхронно запускает `update_all_analytics` — обёртку, которая по очереди вызывает все три команды ниже (см. `website/admin_views.py`), с прогрессом в лог-боксе на странице.

**Вручную (SSH):**
```bash
python manage.py update_ratings --entity driver --model bt
python manage.py update_championship_standings
python manage.py update_track_records
# или всё сразу той же обёрткой, что и кнопка:
python manage.py update_all_analytics --entity all --model all
```

Запускается **вручную** после каждого ввода новых результатов соревнований. Вторая команда — турнирные таблицы чемпионатов (`ChampionshipPage.standings_cache`), используется Career highlights на странице пилота и `/api/v2/pulse/`. Третья — рекорды трасс (`Track.records_cache`), используется блоком «Рекорды трасс» на странице пилота. Обе — см. `docs/claude/driver-page.md`.

---

## Основные URL

| URL | Описание |
|-----|---------|
| `/` | Главная |
| `/top/drivers/` | Рейтинг пилотов |
| `/rating-info/` | Методология рейтинга |
| `/matchast/` | Матчасть |
| `/news/` | Новости |
| `/compare/` | Сравнение шасси |
| `/compare-drivers/` | Сравнение пилотов |
| `/api/rating-stats/` | JSON: статистика рейтинга и настройки |
| `/api/home-top-drivers/` | JSON: топ пилотов для главной (AJAX) |
| `/api/v2/pulse/` | JSON: пульс данных |
| `/admin/` | Wagtail CMS admin |

---

## Шаблоны — важные файлы

| Файл | Описание |
|------|---------|
| `templates/coderedcms/snippets/navbar.html` | Навигация |
| `website/templates/coderedcms/pages/home_page.html` | Главная страница |
| `website/templates/coderedcms/pages/rating_info_page_ld.html` | Страница методологии |
| `website/templates/coderedcms/snippets/top_drivers_page.html` | Рейтинг пилотов |
| `website/templates/coderedcms/snippets/driver_page.html` | Профиль пилота |
| `website/templates/coderedcms/pages/tech_article_index_page.html` | Матчасть |

---

## Локальная разработка

Для локальной разработки используется `mysite/settings/local.py` (в `.gitignore` не попадает, но закоммичен как шаблон).

Файл `local.py` обязан начинаться с:
```python
from .base import *

SECRET_KEY = "..."  # любой непустой ключ для локалки
```

Затем переопределяет `DATABASES` под локальный PostgreSQL.

Запуск:

```bash
source venv/bin/activate
python manage.py runserver --settings=mysite.settings.local
python manage.py migrate --settings=mysite.settings.local
```

Или один раз установить переменную:
```bash
export DJANGO_SETTINGS_MODULE=mysite.settings.local
```

> **Важно:** `base.py` не содержит `SECRET_KEY` — он должен быть в `local.py` (для локалки) или в `prod.py` через `os.getenv('SECRET_KEY')` (для прода). Без него Django упадёт с `ImproperlyConfigured`.

---

## Миграции

**Актуальная история (website):**

| № | Название | Суть |
|---|----------|------|
| 0001–0009 | — | Базовые модели, аналитика, команды |
| 0010 | `add_session_type_and_timing_fields` | Финальные поля хронометража в `RaceResult` (`start_position`, `best_lap_ms`, секторы) |
| 0011 | `techarticleindexpage_alter_articlepage_body` | Страница матчасти |
| 0012 | `remove_session_type` | Удаление колонки `session_type` из `RaceClassResultGroup` (через `RunSQL`) |
| 0013 | `add_qual_and_prefinal_fields` | Поля квалификации и предфинала в `RaceResult` (11 колонок) |
| 0014 | `add_roles_team_pushtoken` | Согласование `verbose_name` полей `RaceResult` с состоянием миграций |
| 0029 | `alter_articlepage_body` | Локальная копия блока `"text"` для `ArticlePage.body` с фичами `pilot_mention`/`team_mention` (см. `docs/claude/mentions.md`) |

**Актуальная история (accounts):**

| № | Название | Суть |
|---|----------|------|
| 0001–0009 | — | UserProfile, документы, соц. авторизация |
| 0010 | `add_roles_team_pushtoken` | `roles` (ArrayField), `verified`, `team` FK в `UserProfile`; новая модель `PushToken` |

Сервер может иметь миграции которых нет в ветке разработки (если они создавались прямо на сервере). При конфликте запускать:

```bash
python manage.py makemigrations --merge --no-input
python manage.py migrate
```

---

## Дизайн-система

Все цвета — через CSS-токены (`var(--gl-*)`). Файл `website/static/website/css/tokens.css`.  
Подробнее: `DESIGN_SYSTEM.md`.

Не писать hex-значения напрямую в шаблонах. Не писать inline-стили если есть токен.

---

## Сквозные правила (нарушение = баг на проде)

- **Персональный или owner-gated Django-view** (не Wagtail `Page.serve`) — обязательно `@nocache_page` (`from wagtailcache.cache import nocache_page`). `wagtailcache` кэширует любой ответ по URL без учёта пользователя и пробивает авторизацию. В `dev.py` кэш выключен, локально этого не видно.
- **После правок, влияющих на закэшированные страницы,** на проде — `python manage.py clear_wagtail_cache` (рестарт его не чистит).
- **Публичные списки классов** — только `RaceClass.objects.for_site()`, не `.all()` (скрывает классы «Только для приложения»). Порядок — `sort_order`, не алфавит.
- **Шаблон, переопределяющий `{% block custom_scripts %}`,** обязан вызывать `{{ block.super }}`, иначе пропадают плашка cookie и Метрика.
- **Пользовательский HTML** (`description`, `biography`) выводится через `|safe_html`, никогда не через `|safe`. Это сторожит тест.
- **Яндекс Метрика и Google Analytics** загружаются только из `cookie-consent.js` после согласия. Тег Метрики в шаблоны напрямую не вставлять.
- **Уведомления о заявках пилота или команды** шлются из `post_save`-сигналов через `on_commit`, во views их не дублировать.
- **ORM из процесса бота** — только через `website/feedback/db.py::run_sync`, не через голый `sync_to_async`.
- **Импорт `website.mediakit_views` внутри `website/views.py`** — только локальный (внутри функции), иначе циклический импорт.
- **Скрипты в блоке `extra_js` админки Wagtail** подключать с `defer` (блок выводится в `<head>`).
- **Тренировки из приложения** (`AppSyncRecord`) никогда не попадают в рейтинг, рекорды и статистику, только `RaceResult`.
- **Дублированные формулы меняются синхронно:** развесовка — `balance_calc.py` + `balance-calculator.js` + Dart в приложении (эталон `website/tests/fixtures/balance_vectors.json`); геометрия схемы трассы — `track_scheme.py` + `track_scheme_geom.js`.
- **Data-миграции:** `ParentalManyToManyField.add()` в БД не пишется, писать через `.through`. Миграции, удаляющие данные, — только после бэкапа и явного «да» владельца.
- **Команды, которые что-то отправляют** (сводка, напоминания), на проде запускать только с `--dry-run`.
- **Тесты:** `pytest` с `--no-migrations`, Wagtail `Site` в БД нет. Логин — `force_login` (django-axes). Для бота — `transactional_db`.
- **Django `{# #}`** — только однострочный; многострочный комментарий — `{% comment %}`.

---

## Документация по фичам (`docs/claude/`)

Подробности по каждой фиче вынесены в отдельные файлы. **Перед работой над фичей прочитать её файл.** Новую крупную фичу документировать в новом файле там же и добавлять строку сюда, а не дописывать в этот файл.

| Файл | Когда читать |
|------|-------------|
| `docs/claude/driver-page.md` | Страница пилота: вкладки, Career highlights, рекорды трасс, «Ход гонки», порядок карточек рейтинга, редизайн 20.09, `standings_cache`/`records_cache` |
| `docs/claude/mentions.md` | @-упоминания пилотов и команд в статьях (Draftail, markdown) |
| `docs/claude/platform-fastapi-flutter.md` | Роли пользователей, `UserProfile`/`PushToken`, сигналы ролей, хронометраж и импорт CSV, FastAPI (эндпоинты, деплой), Flutter, дорожная карта |
| `docs/claude/mediakit-team.md` | PDF медиа-киты пилота и команды (WeasyPrint), ЛК команды, highlights, история команды |
| `docs/claude/balance.md` | Развесовка: удалена с сайта 17.10.2026, справочники и формулы оставлены для приложения |
| `docs/claude/raceclass-order.md` | Порядок классов (`sort_order`), в том числе клиентская сортировка на `/pulse/` |
| `docs/claude/seo.md` | title/description/canonical для Django-страниц, sitemap.xml |
| `docs/claude/legal-cookies.md` | `/legal/*`, форма обращения по ПД, cookie-согласие, согласие на медсправку |
| `docs/claude/feedback-bot.md` | Telegram-бот обратной связи, виджет на сайте, `/feedback/`, статистика |
| `docs/claude/admin-dashboard.md` | «Пульт Gripline» на `/admin/`, утренняя сводка, cron-задачи (`JOBS`) |
| `docs/claude/registration-applications.md` | Заявки пилотов и команд, подтверждение email, мастер регистрации на этап, УТС, заявка команды, документы пилота и напоминания |
| `docs/claude/setupkart.md` | Серверная часть приложения GripLine SetupKart: справочник, публикация, API, Pro, вход и синхронизация, карбюраторы |
| `docs/claude/track-page.md` | Страница трассы: статистика, секторы, редактор схемы, 3D, PDF |
| `docs/claude/weather.md` | Погода этапов: снимки по cron, Open-Meteo через VPN |

---

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
