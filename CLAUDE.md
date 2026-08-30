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

### Деплой FastAPI на сервер (первый раз)

> **Уже выполнено 2026-06-19.** Раздел оставлен для воспроизведения на другом сервере.

```bash
# 1. Создать venv и установить зависимости (сервер использует Python 3.12)
cd /www/wwwroot/gripline.ru/fastapi
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 2. Добавить FASTAPI_SECRET_KEY в /www/wwwroot/gripline.ru/.env
python3 -c "import secrets; print('FASTAPI_SECRET_KEY=' + secrets.token_hex(32))" >> /www/wwwroot/gripline.ru/.env

# 3. Создать systemd-юнит (User=root — пользователя www на сервере нет)
# Файл: /etc/systemd/system/gripline-api.service
# Содержимое — см. fastapi/gripline-api.service, но с User=root, Group=root
systemctl daemon-reload
systemctl enable --now gripline-api

# 4. Добавить nginx location в /etc/nginx/sites-available/gripline
# Вставить внутрь server { ... } блока (см. fastapi/nginx_snippet.conf):
#   location /api/mobile/ {
#       proxy_pass http://127.0.0.1:8001/;
#       ...
#   }
nginx -t && nginx -s reload
```

**Важно:** в `fastapi/main.py` установлен `root_path="/api/mobile"` — это обязательно для корректной работы Swagger UI за nginx-прокси с префиксом. Без него Swagger пытается загрузить `/openapi.json` вместо `/api/mobile/openapi.json`.

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
| `RaceClass` | Класс карта (Micro, Mini, Junior, Senior, DD2, DD2 Masters) |
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
| `lambda_active` | 0.8 | Скорость затухания для активных пилотов |
| `lambda_inactive` | 2.0 | Скорость затухания для неактивных |
| `inactive_threshold_days` | 365 | Дней без гонок → режим неактивный |
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
2. Каждая пара получает вес: `exp(-λ × дней / 365)` — старые гонки весят меньше
3. Пилоты, **не приехавшие на этап**, получают виртуальное последнее место и проигрывают всем участникам
4. BT-модель с Lasso обучается на взвешенных сравнениях
5. Байесовское сглаживание: `(N × BT + 15 × медиана) / (N + 15)`
6. Нормировка 0–100 внутри каждого класса

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

Запускается **вручную** после каждого ввода новых результатов соревнований. Вторая команда — турнирные таблицы чемпионатов (`ChampionshipPage.standings_cache`), используется Career highlights на странице пилота и `/api/v2/pulse/`. Третья — рекорды трасс (`Track.records_cache`), используется блоком «Рекорды трасс» на странице пилота. Обе см. раздел «Реструктуризация страницы пилота» ниже.

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
| 0029 | `alter_articlepage_body` | Локальная копия блока `"text"` для `ArticlePage.body` с фичами `pilot_mention`/`team_mention` (см. «Упоминания пилотов/команд») |

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

## Упоминания пилотов/команд в статьях (@mentions, реализовано 2026-08-25)

Live-автокомплит в теле статьи (`ArticlePage.body`, только там — строго opt-in, не в `default_features`). Два независимых входа:

- **Draftail-блок `"text"`** — командная палитра Wagtail 7.3 (набрать `/`, выбрать «Упомянуть пилота»/«Упомянуть команду») **или** кнопка-силуэт в плавающем тулбаре, который появляется над выделенным текстом.
- **Markdown-блок** — триггер `@` прямо в тексте, свой попап поиска (не встроенный в Draftail).

Ссылки хранятся как `<a linktype="driver" id="…">`/`<a linktype="team" id="…">` — паттерн как у `PageLinkHandler` в самом Wagtail: реальный URL подставляется при рендере через `DriverLinkHandler`/`TeamLinkHandler.expand_db_attributes()` (`website/wagtail_hooks.py`), смена slug пилота/команды не рвёт уже опубликованные упоминания.

**Файлы:**

| Файл | Роль |
|------|------|
| `website/models.py::_article_body_streamblocks()` | Локальная копия `CONTENT_STREAMBLOCKS` только для `ArticlePage.body` — общий объект менять было нельзя (включило бы автокомплит на всех типах страниц) |
| `website/wagtail_hooks.py` | `DriverLinkHandler`/`TeamLinkHandler`, `PilotMentionElementHandler`/`TeamMentionElementHandler`, хуки `register_rich_text_features`, `mention_markdown_js` |
| `website/static/website/js/pilot-mention.js`, `team-mention.js` | Draftail entity source (React-компонент поиска) |
| `website/static/website/js/driver-search.js`, `team-search.js` | Общий поиск по `/drivers-api/`, `/api/v2/teams-api/` — переиспользуется markdown-вариантом |
| `website/static/website/js/mention-markdown.js` | Автокомплит для markdown-блока (EasyMDE), монки-патчит `window.easymdeAttach` |
| `website/static/website/css/mention.css` | Стили попапа — хардкод-hex (сознательно, см. предупреждение о токенах ниже) |

**Три бага, найденных и исправленных после первого деплоя** (все три — из-за нестандартной интеграции кастомного Draftail entity source, каждый проявлялся только в определённом сценарии, автотесты через `element.click()` их не ловили):

1. **Попап проваливался в конец блока.** Wagtail рендерит source-компонент кастомной entity-фичи обычным дочерним элементом внутри `.Draftail-Editor` (в потоке документа), а не как floating tooltip — в отличие от встроенных источников (Ссылка и т.д.) со своей модалкой. Фикс: вручную ставить `position: fixed` по координатам DOM-узла текущего блока (`data-offset-key`) — `window.getSelection()` на момент монтирования уже невалиден (Draft.js успевает перерендерить DOM между закрытием командной палитры и открытием source).
2. **Клик по результату не реагировал.** Пока source открыт, Wagtail ставит редактируемому блоку `.Draftail-Editor--readonly` (`pointer-events: none`), чтобы заблокировать ввод текста под попапом — наш попап рендерится внутри этого блока и наследует запрет. Фикс: явный `pointer-events: auto` на `.mention-source` в `mention.css`.
3. **Вставка через выделение текста роняла редактор.** `Modifier.insertText` (Draft.js) требует схлопнутое выделение и бросает исключение на диапазоне — а через кнопку в тулбаре над выделением всегда передаётся диапазон. Дальше выяснилось, что `Modifier.replaceText` (который эту невalid-selection проблему решает) **подменяет выделенный текст на каноничное ФИО из базы**, ломая грамматику («Михаила» → «Михаил»). Итоговый фикс: на схлопнутом выделении — `Modifier.insertText` (вставка ФИО как раньше), на непустом — `Modifier.applyEntity` (оставляет исходный текст, просто делает ссылкой).

**Диагностика похожих багов в будущем:** ошибки внутри `onClick` кастомных Draftail-плагинов не показываются пользователю никак — только в консоли браузера (`[EXCEPTION]`, часто минифицированный `draftail.js`). При «попап не закрывается / ничего не происходит» — первым делом смотреть консоль, не гадать по описанию симптома.

---

## Реструктуризация страницы пилота (реализовано 2026-08-27)

Публичная страница пилота (`website/templates/coderedcms/snippets/driver_page.html`, вью `driver_detail_view` в `website/views.py`) переведена с одной длинной простыни на три вкладки на одном URL (якорные, hash-routing `#overview`/`#rating`/`#history`, без перезагрузки — Person-разметка и SEO остаются на одном адресе).

**Вкладка «Обзор»:** компактный хедер (фото 96×120, чипы классов/соцсетей), биография (два состояния — заполнено/пусто с CTA входа), Career highlights (4 бейджа с раскрывающейся панелью деталей), статистика пилота, «Текущая форма» (самая свежая по дате карточка рейтинга), «Рекорды трасс».

**Вкладка «Рейтинг и аналитика»:** существующие полные карточки рейтинга по классам (без изменений в логике) + новый график «Динамика рейтинга» на каждую карточку — **это не история Rating-балла** (такой истории в БД нет и не может быть восстановлена ретроактивно без пересчёта BT-модели «на дату» для каждого прошлого этапа), а переиспользование существующего подхода «Прогресс по этапам»: нормализованная позиция в заезде (% от места) по датам, только теперь раздельно по каждому классу, а не одним смешанным графиком на все классы сразу.

**Вкладка «История выступлений»:** фильтры (сезон/класс), пагинация (8 строк), DNF-бейдж, колонка «Ход гонки». Вся фильтрация и пагинация — на клиенте: `driver_detail_view` отдаёт **всю** историю пилота одним JSON-блобом через `{{ history_data|json_script:"driverHistoryData" }}` (Django `json_script` — не голый `json.dumps` в `{{ }}`, чтобы HTML-автоэкранирование не покорёжило JSON), JS фильтрует/пагинирует без похода на сервер.

**Career highlights — источники данных:**
- **Титул** — перебор `ChampionshipPage.objects.live()` × `get_years()` × `get_champions_by_class(year)` (существующий метод, уже considered use для таблицы чемпионата), берётся самый поздний год, где пилот — `champions[0]`
- **Лучший результат** — лучшая позиция за карьеру (исключая DNF/DQ) + счётчик побед; в панели деталей — самое недавнее из совпадений (не первое)
- **Личный лучший круг** — `min(best_lap_all_ms)` по всем `RaceResult` пилота
- **Подиумы** — переиспользует уже посчитанные `podiums`/`podium_percentage`

**Рекорды трасс** (`_get_driver_track_records` в `views.py`) — статус действующий/закреплён/перебит по паре (трасса, класс). Рекорд трассы определяется через `EventPage.track` FK (заполнен **не у всех** событий — блок часто пуст просто из-за нехватки данных, это не баг) + `RaceResult.best_lap_all_ms`, хронологический проход с бегущим минимумом на класс+трассу. Владение — календарный год установки **текущего** (не обязательно родного для пилота) рекорда.

**result_status (DNF/DQ/DNS)** — реализовано, три поля на `RaceResult` (см. раздел «Ключевые модели» выше).

**Виджет «Ход гонки» (`gripline_lap_chart_widget.js`) — апгрейд, не замена:** решили НЕ делать отдельную страницу заезда (хотя дизайн-макет её описывал) — вместо этого существующая модалка (была только на `event_page.html`) вынесена в переиспользуемый инклюд `website/templates/includes/lap_chart_modal.html` и подключена туда же на `driver_page.html` (кнопка «Ход гонки →» в истории выступлений и в панели деталей бейджа «Личный лучший круг»). Сам виджет увеличен: `viewBox` 760×260 → 900×380, модалка `modal-lg` → `modal-xl`, линии — с прямых `<polyline>` на сглаженные `<path>` (Catmull-Rom → Bezier, функция `smoothPath()`). Триггеры, отрисованные клиентским JS уже после загрузки страницы (таблица истории пилота), ловятся через делегирование на `document` с классом `.gl-lapchart-trigger-dynamic` — обычный `querySelectorAll` при `DOMContentLoaded` их не видит, они появляются позже.

**Три баги в существующем коде, найденные и исправленные попутно** (не относились к макету напрямую, но лежали в тех же блоках, которые переписывались):
1. `driver.bio` в шаблоне никогда не резолвился — в модели поле называется `biography`. Карточка «Биография» из-за этого **всегда** показывала заглушку «скоро будет дополнена», даже если админ заполнил текст (просто пока ни у одного пилота текст не был заполнен, баг не проявлялся).
2. `personal_records` (блок «Личные рекорды») — переменная никогда не передавалась из вью, блок был мёртвым кодом с момента внедрения. Заменён новыми блоками (Career highlights + Рекорды трасс), не восстанавливался.
3. `driver_profile`/`driver_profile.birth_date` — тоже никогда не передавался; дата рождения на публичной странице никогда не отображалась. Реальный источник — `accounts.models.UserProfile` (FK на `Driver`) с полем `birth_date_public` специально под эту цель. Подключено: `UserProfile.objects.filter(driver=driver, birth_date_public=True).first()` — если пилот не разрешил публикацию, профиль вообще не подтягивается.

**Исправлено (2026-08-27, вечер): `get_champions_by_class` больше не пересчитывается на лету.** Раньше при поиске «Титула» в Career highlights код перебирал все `ChampionshipPage` × все их годы, каждый раз заново агрегируя `RaceResult` в турнирную таблицу — ~2с на странице пилота. Теперь `ChampionshipPage.standings_cache` (JSON) хранит готовый результат, обновляется командой `update_championship_standings` (тот же паттерн, что `update_ratings`/`rating_by_class` — материализация в БД, не кэш с TTL, чтобы не ловить тот же класс протухания, что и wagtailcache в этой же сессии). Старая логика вычисления живёт в `_compute_champions_by_class()` без изменений — на неё же fallback, если кэша ещё нет. **Добавить в обычный workflow после ввода результатов**, рядом с `update_ratings` (см. раздел «Рейтинговая система» выше):
```bash
python manage.py update_championship_standings
```
Использует тот же метод `/api/v2/pulse/` (виджет лидеров на главной) — тоже стал быстрее, без отдельных изменений в api.py.

**Исправлено (2026-08-27, тем же вечером):** `_get_driver_track_records` тоже переведён на материализацию в БД — новое поле `Track.records_cache` (JSON), обновляется командой `update_track_records` (тот же вечер, тот же паттерн). Тяжёлая логика (перебор всех `RaceResult` сайта) вынесена в `_compute_all_track_records()` — считает сразу по всем трассам/классам, не на одного пилота, её же использует команда. Fallback на живой расчёт (`_compute_driver_track_records_live`), пока команда ни разу не запускалась. Единичный вызов: ~1.2с → 0.002с; страница пилота целиком: ~1.5с → ~0.6с (профайлер, реальные данные).

```bash
python manage.py update_ratings --entity driver --model bt
python manage.py update_championship_standings
python manage.py update_track_records
```

Все три — обычный workflow после ввода новых результатов соревнований.

---

## Дизайн-система

Все цвета — через CSS-токены (`var(--gl-*)`). Файл `website/static/website/css/tokens.css`.  
Подробнее: `DESIGN_SYSTEM.md`.

Не писать hex-значения напрямую в шаблонах. Не писать inline-стили если есть токен.

---

## Итоги стратегического обсуждения (2026-06-18)

Полное ТЗ: `TZ_platform_roadmap.md` в корне репозитория.

### Принятые решения

**Архитектура:**
- Мобильное приложение: **Flutter**
- Backend API: **FastAPI** (отдельный сервис, порт 8001)
- Авторизация: FastAPI читает Django `auth_user` и выдаёт JWT — единый логин для сайта и мобилки
- БД: PostgreSQL — единый источник правды, оба сервиса читают напрямую
- Django + Wagtail остаётся для CMS и веб-сайта, FastAPI не заменяет его
- Django — единственный владелец миграций; SQLAlchemy-модели FastAPI обновляются вручную синхронно

**Роли пользователей** (пользователь может иметь несколько ролей):
- `pilot` — свой профиль, результаты, рейтинг; привязан к `Driver` по ФИО через верификацию администратором
- `fan` — подписка на пилотов, лента результатов
- `manager` — данные команды и её пилотов; привязан к `Team`
- `organizer` — на паузе, реализуется позже

**Модели Этапа 2 (реализовано):**

`UserProfile` (в `accounts/models.py`) расширен тремя полями:
- `roles` — `ArrayField(CharField(max_length=20))`, денормализованный кэш для FastAPI. Значения: `'pilot'`, `'manager'`. Источник правды — `DriverClaim` и `TeamManager`.
- `team` — FK на `website.Team`, `null=True`. Первая активная команда из `TeamManager`.
- `verified` — `BooleanField`, администратор подтвердил привязку к пилоту.

`PushToken` (в `accounts/models.py`) — отдельная таблица (не поле на профиле):
```python
user       = ForeignKey(User, on_delete=CASCADE)
token      = CharField(max_length=255, unique=True)
created_at = DateTimeField(auto_now_add=True)
```
Стратегия: накапливать все токены, удалять мёртвые по ответу FCM (`InvalidRegistration`/`NotRegistered`).

**Сигналы синхронизации (`accounts/signals.py`):**

Функция `_sync_roles(user)` пересчитывает `roles`/`driver`/`team`/`verified` из источников правды:
- Подключена к `DriverClaim.post_save` — срабатывает при изменении статуса заявки
- Подключена к `TeamManager.post_save` и `post_delete` — срабатывает при изменении роли в команде

**Wagtail admin для DriverClaim** (`accounts/wagtail_hooks.py`):
- Список показывает: email, имя, пилот в базе, статус-бейдж, состояние профиля (верифицирован / нет)
- `inspect_view_enabled = True`
- Workflow: открыть заявку → сменить `status` на `approved` → сохранить → сигнал обновляет `UserProfile`

**Модель данных хронометража (Этап 1, реализовано):**

Отказались от подхода «один `RaceResult` = одна сессия». Принята модель:
> **Один `RaceResult` = один пилот на этапе в классе.** Все сессии (квалификация, предфинал, финал) хранятся в одной записи.

`RaceClassResultGroup` — класс на этапе, без разбивки по сессиям.

`RaceResult` — 16 полей хронометража (см. раздел «Ключевые модели»).

Рейтинговая система (`update_ratings`) использует только `position` (финальная позиция) — без изменений.

**Страница пилота (реализовано в Этапе 1):**
- Таблица истории: колонка «Динамика» (старт→финиш + стрелка), колонка «Круг» (лучший из заполненных сессий с бейджем К/Пф/Ф), бейджи сессий (К/Пф/Ф с tooltip)
- Блок «Личные рекорды»: лучший круг по классу, S1/S2/S3, идеальный круг — агрегируется по всем трём сессиям; скрыт если данных нет
- Бейджи: К = `bg-primary`, Пф = `bg-warning text-dark`, Ф = `bg-success` — единый стиль с `style="font-size:10px; border-radius:4px;"`

**Страница этапа (`event_page.html`, реализовано):**
- Сортировка: `RaceClassResultGroup.sorted_results()` — сначала по очкам (`-points`), затем по месту (`position`)
- Колонка «Лучший круг»: `RaceResult.best_lap_all_ms` (min из трёх сессий) + цветной бейдж сессии с tooltip
- Колонка «Идеальный круг»: `RaceResult.ideal_lap_all_ms` (sum лучших секторов по всем сессиям)
- Бейджи сессий: те же цвета что и на странице пилота

**Свойства RaceResult для агрегации хронометража:**
- `best_lap_all_ms` — минимальное время круга из qual/pre_final/final
- `best_lap_session` — строка `'qual'`/`'pre_final'`/`'final'` — сессия с лучшим кругом
- `ideal_lap_all_ms` — сумма min(S1) + min(S2) + min(S3) по всем сессиям; `None` если хотя бы один сектор отсутствует

**result_status (DQ/DNF/DNS) — реализовано (2026-08-27):**
- Три отдельных поля на `RaceResult`: `qual_status`, `pre_final_status`, `final_status` (не одно общее), `CharField` с `choices` DNF/DQ/DNS, `blank=True, default=''`
- Поле `points` остаётся источником правды по очкам — статус их не пересчитывает (организатор может начислить очки за сошедшего в финале, если он набрал их в квалификации/предфинале)
- На странице пилота (история выступлений): бейдж DNF вместо числа в колонке «Место» + иконка `fa-triangle-exclamation` перед названием соревнования + «—» в колонке «Динамика» вместо стрелки
- В таблице этапа (`event_page.html`) статус пока не выведен — задел на будущее, поля есть, вывод не подключён

**Импорт данных с хронометража (`website/import_utils.py`):**

Инструмент импорта CSV поддерживает 4 типа сессий:

| Тип | Описание | Поля |
|-----|---------|------|
| `qual` | Квалификация | position, best_lap, s1, s2, s3 |
| `pre_final` | Предфинал | start_position, position, best_lap, s1, s2, s3 |
| `final` | Финал (хронометраж) | start_position, position, best_lap, s1, s2, s3 |
| `protocol` | Протокол судейской комиссии | city, team, race_number, chassis, position, points |

Формат времени в CSV: `M:SS.mmm` (например `0:55.420`) или `SS.mmm` (например `55.420`) — оба варианта поддерживаются функцией `seconds_to_ms()`.

Логика `update_or_create`: для `protocol` — полное обновление записи. Для остальных сессий — `get_or_create` с `position=0` для новых записей (чтобы не затирать позицию финала при загрузке квалификации первой).

**Типы документов Apex Timing и что с ними делать:**
- Квалификация (К) — импорт как `qual`
- Предфинал (Пф) — импорт как `pre_final`; стартовая решётка в отдельном файле-скане
- Финал (Ф) — импорт как `final`; стартовая решётка в отдельном файле-скане
- Итоговый протокол — импорт как `protocol`
- Прогрев (ПР) — неофициальный, не импортируется
- Итог АВС / Итог этапа — агрегаты, не импортируются

**PDF-парсер** — отдельный проект (ТЗ в разработке). Будет конвертировать PDF Apex Timing → CSV для последующего импорта через существующий инструмент.

**FastAPI сервис (Этап 3, реализовано):**

Папка `fastapi/` в монорепо. Отдельный Python venv (Python 3.13), отдельный порт 8001.

Зависимости: `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `psycopg[binary]` (v3), `python-jose[cryptography]`, `passlib`, `python-multipart`, `pydantic`, `pydantic-settings`.

SQLAlchemy-модели (`fastapi/models/`) отражают Django-таблицы только для чтения — без собственных миграций. При Django-миграции обновлять вручную синхронно.

Переменные окружения: `fastapi/.env` (локально, в gitignore) → приоритет перед корневым `.env`. На проде — системное окружение.

| Эндпоинт | Метод | Описание |
|----------|-------|---------|
| `/health` | GET | Проверка доступности |
| `/auth/login` | POST | form-data: `username`/`password` → JWT |
| `/auth/refresh` | POST | Обновление JWT (принимает действующий токен) |
| `/auth/me` | GET | Профиль текущего пользователя (все роли) |
| `/pilots` | GET | Список пилотов (фильтр `?class_id=`, `?limit=`, `?offset=`) |
| `/pilots/{id}` | GET | Профиль пилота с командой |
| `/pilots/{id}/results` | GET | История результатов (фильтр `?class_id=`) |
| `/pilots/{id}/rating` | GET | Рейтинг пилота по всем классам |
| `/pilots/me/profile` | GET | Профиль авторизованного пилота |
| `/championships` | GET | Список чемпионатов |
| `/championships/{id}` | GET | Детали чемпионата с этапами |
| `/championships/{id}/stages` | GET | Только этапы чемпионата |
| `/stages/{id}` | GET | Результаты этапа по всем классам |
| `/teams` | GET | Список команд |
| `/teams/{id}` | GET | Профиль команды с пилотами |
| `/news` | GET | Список новостей (фильтр `?limit=`, `?offset=`) |
| `/news/{id}` | GET | Статья по id |
| `/classes` | GET | Список классов картинга |
| `/feed` | GET | Лента (для пилота — его результаты + новости) |
| `/push/register` | POST | Регистрация FCM-токена устройства |
| `/push/register` | DELETE | Удаление FCM-токена (при выходе) |

JWT содержит: `sub` (user_id), `username`, `roles`, `driver_id`, `team_id`. Срок жизни — 7 дней.

Swagger UI (продакшн): **https://gripline.ru/api/mobile/docs** → кнопка **Authorize** → `Bearer <token>`.

Тестовый аккаунт: `demo_pilot_5@email.ru` / `DemoGripline2026!` (демо-пилот, роли не привязаны).

**Тестирование:**
- Локальная машина = staging среда (PostgreSQL локально, `--settings=mysite.settings.dev`)
- Workflow: редактировать локально → тестировать → коммит → push → `./deploy.sh`
- Автотесты только для: расчёта рейтинга (`analytics/`) и FastAPI эндпоинтов (роли, авторизация)

### Дорожная карта (кратко)

| Этап | Статус | Суть |
|------|--------|------|
| **1. Данные хронометража** | **Выполнен** | Поля квал/предфинал/финал + страница пилота |
| **2. Подготовка к FastAPI** | **Выполнен** | `roles`/`team`/`verified` в `UserProfile`, `PushToken`, сигналы синхронизации |
| **3. FastAPI сервис** | **Выполнен + задеплоен** | 20 эндпоинтов, работает на проде: https://gripline.ru/api/mobile/docs |
| **4. Flutter приложение** | **В работе** | Скелет: логин, onboarding, лента, профиль пилота; подключён к prod API |

**Flutter приложение (Этап 4, базовый скелет):**

Папка `flutter_app/` в монорепо. SDK: Flutter 3.x + Dart 3.3+.

Стек: `flutter_riverpod` (состояние), `go_router` (навигация), `dio` (HTTP), `flutter_secure_storage` (JWT), `firebase_messaging` (push).

| Экран | Файл | Описание |
|-------|------|---------|
| Логин | `screens/auth/login_screen.dart` | Форма логина → FastAPI `/auth/login` |
| Onboarding | `screens/auth/onboarding_screen.dart` | Карточки по роли (пилот / менеджер / болельщик) |
| Лента | `screens/feed/feed_screen.dart` | Приветствие по роли, заглушка результатов |
| Пилоты | `screens/pilots/pilots_screen.dart` | Заглушка (рейтинг — следующая итерация) |
| Профиль | `screens/profile/profile_screen.dart` | Данные из `/pilot/profile`, рейтинг по классам |

**Настройка `baseUrl`** (`lib/config.dart`):
- **Продакшн (текущий):** `https://gripline.ru/api/mobile`
- Локальная разработка Android-эмулятор: `http://10.0.2.2:8001`
- Локальная разработка iOS-симулятор: `http://127.0.0.1:8001`

**Запуск:**
```bash
cd flutter_app
flutter pub get
flutter run
```

**Firebase:** скопировать `google-services.json` и `GoogleService-Info.plist` из Firebase Console по шаблонам `.example`. Файлы в `.gitignore`.

### Открытые вопросы
- Apex Timing: экспортирует ли XML/CSV? (уточнить у организатора)
- PDF-парсер: ТЗ готовится; парсер конвертирует PDF Apex Timing → CSV для существующего инструмента импорта
- Flutter: настроить Firebase проект и добавить реальные `google-services.json`
- Flutter: экран рейтинга пилотов (нужен UI поверх готового эндпоинта `/pilots?class_id=`)
- Flutter: push-уведомления (FCM токен → `/push/register`)

---

## Медиа-кит пилота (PDF, реализовано 2026-08-30)

Кнопка «Медиа-кит пилота» в хедере страницы пилота (справа, над «Поделиться результатом» — **в итоге обе кнопки оставлены в хедере**, не в «Обзоре», как сначала предполагало ТЗ: пользователь явно попросил вернуть на место после первой версии). Видна **только владельцу профиля** — `UserProfile.driver == этот driver` и `UserProfile.verified == True`. По клику скачивает A4-PDF (одна страница, светлая тема) с достижениями пилота для спонсоров/команд/партнёров. Полное продуктовое ТЗ v1.0 — вне репозитория, у пользователя.

**Движок — WeasyPrint, не headless Chromium.** Начиная где-то в районе v53 WeasyPrint перешёл на собственный PDF-бэкенд (`pydyf`) вместо cairo — но **`libpango` (текстовый шейпинг) всё ещё требуется**, `pip install weasyprint` его не тянет. **Важно (исправлено 2026-08-30 после ложного вывода при разработке):** при первой проверке на локальной машине `import weasyprint` и рендер PDF сработали без единой системной либы — это создало ложное впечатление, что опасение ТЗ («ставить apt-либы и на проде, и локально») не подтвердилось. На деле локальная dev-машина просто уже имела `libpango` установленным системно (тянется как зависимость другого ПО в окружении, не относящегося к проекту) — маскировка, не отсутствие зависимости. **При первом деплое на прод выяснилось**: чистый Ubuntu 24.04 без единой системной либы → `OSError: cannot load library 'libpango-1.0-0'` при первом же вызове. Установлено вручную (см. ниже) — теперь работает и на проде.

**Системные либы на проде (уже выполнено 2026-08-30):**
```bash
apt-get update && apt-get install -y libpango-1.0-0 libpangoft2-1.0-0
```
Это одноразовый шаг, не входит в `deploy.sh`/обычный workflow — как и первичная настройка FastAPI выше. При воспроизведении на другом сервере (или локально, если там тоже пусто) — выполнить перед первым использованием кнопки «Медиа-кит».

Генерация — **синхронно по клику, без кэша и без очереди** (django-tasks не используется). Таймаут 15с через `ThreadPoolExecutor.result(timeout=...)`, не `signal.alarm` — сигналы работают только в главном потоке процесса, а `runserver` по умолчанию обрабатывает запросы в отдельных потоках (упало бы локально). При таймауте воркер не блокируется: фоновый поток дорендеривается сам по себе, HTTP-запрос отвечает 503 сразу.

**Файлы:**

| Файл | Роль |
|------|------|
| `website/services/mediakit.py` | Контекст для шаблона: хедер (номер/команда/год начала — вычисляются из `RaceResult` на лету, без новых полей на `Driver`), лесенка Career highlights, статистика, рейтинг за 12 мес, топ-3 сезона, титулы и достижения, рекорды круга |
| `website/services/pdf.py` | Обёртка WeasyPrint: резолвит шрифты/лого в абсолютные `file://` пути через `staticfiles.finders` (не через collectstatic/nginx — работает независимо от того, выполнен ли `collectstatic`), QR-код как data URI, таймаут |
| `website/mediakit_views.py` | View + owner-гейтинг. Отдельный модуль, не `website/views.py` (тот уже 3000+ строк, единый файл не пакет) |
| `website/templates/mediakit/driver_mediakit.html` | Шаблон документа (не наследует `web_page.html` — самостоятельный HTML) |
| `website/static/website/css/mediakit-print.css` | Печатная палитра `--mk-*`; значения (цвета/размеры/отступы) сняты через `getComputedStyle` с эталонного макета (design-canvas экспорт от пользователя), не подобраны на глаз — сознательно не связана с `--gl-*` токенами сайта как переменные, хотя сами цвета (#FFC107/#0DCAF0/#15151C) те же, что и на сайте |
| `website/static/website/fonts/mediakit/*.woff2` | Inter Tight (6 начертаний) + JetBrains Mono (2) — статические инстансы, нарезанные из вариативных TTF google/fonts через `fonttools varLib.instancer` (Google отдаёт Inter Tight/JetBrains Mono только как variable fonts, статических WOFF2 в репозитории google/fonts нет) |
| `website/static/website/images/mediakit/gripline-mark-color.svg` | Знак Gripline для хедера (тёмный фон → цветной, см. `logo/README.md`) |
| `website/static/website/images/mediakit/gripline-mark-color-on-light.svg` | Знак Gripline для футера (светлый фон → приглушённый янтарь) |

**Дизайн переделан 2026-08-30 по референс-макету пользователя** (`.dc.html`-экспорт design-canvas, `#dc-root`), после того как первая версия по текстовому ТЗ визуально разошлась с ожиданиями. Цвета/шрифты/отступы сняты программно через `getComputedStyle` в открытой вкладке браузера (`javascript_tool`), а не приблизительно с скриншота — что дало точную шкалу (напр. `42px→31.5pt` для заголовка при допущении 96dpi, подтверждённом соотношением найденного `#dc-root` 794×1123px ≈ A4 210×297мм). Хедер: цветной знак + вордмарк `GRIPLINE` сверху, эйбрау-лейбл «Медиа-кит пилота · сезон {год}» (`--mk-cyan`), класс/номер чипы над именем, подзаголовок одной строкой «Город · Команда · В картинге с {год}», трёхцветная (жёлтый-голубой-жёлтый) полоса-градиент под хедером 0.8мм. Двухколоночная сетка (`--mk-grid`, gap 8мм) под статистикой: слева «Титулы и достижения» + «Рекорды круга», справа тёмная панель «Рейтинг Gripline» + «Лучшие результаты сезона».

**Три конфликта макета с уже принятыми решениями текстового ТЗ — разрешены явно с пользователем, не молча:**
1. **Career highlights** — макет показывал ВСЕ 4 плашки разом (Титул+Подиумы+Стабильность+Круг, лучшая — залита жёлтым, остальные — светло-серым `#F4F6F8`). Пользователь подтвердил **оставить лесенку** («покажи только лучшую ступень», как в тексте ТЗ) и добавить недостающие блоки отдельно, не превращать highlights в витрину всех фактов разом.
2. **Шкала рейтинга** — в макете «1842.6» (число вне какой-либо реальной модели, проверено grep по `website/`/`analytics/` — Elo-подобной шкалы в проекте нет и не считается нигде). Пользователь подтвердил: оставить реальный `normalized_score` (0–100), но **без суффикса** «из 100 баллов» — просто число, как визуально в макете; место — компактно `N/M` вместо «#N из M пилотов».
3. **URL в футере** — макет показывал `gripline.ru/pilots/<slug>`. Проверено: `/pilots/` существует только как префикс FastAPI-роутера (`fastapi/routers/pilots.py`, реально смонтирован под `/api/mobile/pilots/...`) — на самом сайте такого маршрута нет, ссылка была бы 404. Пользователь подтвердил **оставить `/drivers/<slug>/`** (раздел 4.7 ТЗ) — рабочая ссылка в приоритете над визуальным соответствием макету.

**Титулы и достижения** (`_titles_and_achievements()`) — новый блок, не описан текстом ТЗ, добавлен по референсу. Хронологический список **всех** топ-3 мест пилота во всех чемпионатах/классах/годах (не только лучший титул, как в Career highlights) — источник тот же `ChampionshipPage.get_champions_by_class()` (кэш `standings_cache`), `champions` уже приходит top-3 на класс за сезон. Капается на 6 последних записей (`TITLES_MAX`).

**Рекорды круга** (`_track_records_for_mediakit()`) — новый блок, тоже добавлен по референсу. Переиспользует существующий `_get_driver_track_records()` (тот же, что в блоке «Рекорды трасс» на публичной странице пилота), фильтрует только `active`/`locked` — рекорды, которые кто-то другой уже перебил (`beaten`), в рекламный документ включать бессмысленно. Капается на 6 записей (`TRACK_RECORDS_MAX`).

**Career highlights — своя лесенка, не переиспользует блок со страницы пилота** (тот — 4 фиксированных бейджа). Иерархия «покажи лучшую применимую ступень»: 1) Титул (`_get_driver_best_title()`, вынесен из `_get_driver_career_highlights` в отдельную переиспользуемую функцию в `views.py`, чтобы не дублировать обход `ChampionshipPage`) → 2) Подиумы (>0) → 3) Стабильность топ-5/топ-10 (см. ниже) → 4) фолбэк: лучший результат карьеры и/или личный лучший круг (гарантированно есть хоть один, если у пилота есть заезды). Всегда 1-2 бейджа, стиль — заливка жёлтым (`--mk-yellow`), как «лучшая» плашка в макете (раз показываем — значит это уже лучшее, серых «недостигнутых» плашек нет).

**Порог «стабильности»** — `AnalyticsSettings.mediakit_top10_min_field` (default 15, миграция `0035`): бейдж «топ-10» показывается только если среди заездов с полем ≥ порога хотя бы 5 финишей и доля попаданий в топ-10 ≥ 60% — иначе формулировка была бы нечестной на маленьком поле. Порог топ-5 — вдвое меньше порога топ-10 (не отдельная настройка, ТЗ просило один регулируемый параметр). Минимум гонок (5) и доля (60%) — захардкожены осознанно (не запрошена отдельная настройка под них в ТЗ).

**Рейтинг в медиа-ките** — только классы, где пилот выступал за последние 12 месяцев (не вся карьера, чтобы не тащить устаревшие баллы по давно оставленному классу); тот же `normalized_score` (0–100), что на живом сайте, но без суффикса «из 100 баллов» и в компактном формате места `N/M` — см. конфликт №2 выше.

**Подзаголовок хедера собирается строкой в Python** (`_subtitle_line()` в `mediakit.py`), не условными вставками в шаблоне — иначе отсутствующий город (`driver.city` пусто) оставлял бы висячее « · » перед «Команда» (баг, найден и исправлен при первом визуальном ревью в браузере).

**Владение** — не через `request.user.profile.driver_id == driver.id` в шаблоне напрямую (обращение к `.profile` на пользователе без профиля бросает `RelatedObjectDoesNotExist`, шаблоны Django молча проглатывают это через `silent_variable_failure`, но это неявное и хрупкое поведение) — вместо этого `_is_mediakit_owner()` считается один раз во view (`driver_detail_view` и `driver_mediakit_pdf_view` через локальный импорт из `mediakit_views.py`) и передаётся в контекст явным булевым флагом `can_view_mediakit`.

**Циклический импорт (важно при будущих правках):** `mediakit_views.py` → `services/mediakit.py` → `views.py` (переиспользует `_get_driver_best_title`/`_get_driver_class_ratings`). Импорт `website.mediakit_views` внутри `website/views.py` **обязан быть локальным** (внутри функции/метода — `DriverViewSet.get_urlpatterns()` и `driver_detail_view`), не на уровне модуля — иначе цикл ловится при загрузке Django-приложения.

---

## Деплой 2026-06-19 — что сделано

### Исправления кода
- `fastapi/main.py`: добавлен `root_path="/api/mobile"` — без него Swagger UI не загружает схему за nginx-прокси с префиксом
- `flutter_app/lib/config.dart`: `baseUrl` переключён на `https://gripline.ru/api/mobile`
- `.gitignore`: добавлены `.claude/` и `.mimocode/`; добавлено исключение `!flutter_app/lib/**` (правило `lib/` блокировало dart-файлы)

### Настройка сервера
- Создан venv: `fastapi/venv/` (Python 3.12 — версия 3.13 на сервере отсутствует)
- Установлены зависимости из `fastapi/requirements.txt`
- В `.env` добавлен `FASTAPI_SECRET_KEY`
- Создан `/etc/systemd/system/gripline-api.service` с `User=root` (пользователя `www` на сервере нет)
- Сервис запущен: `systemctl enable --now gripline-api`
- В `/etc/nginx/sites-available/gripline` добавлен `location /api/mobile/` → `proxy_pass http://127.0.0.1:8001/`
- nginx перезагружен: `nginx -s reload`

### Проверки
- `GET https://gripline.ru/api/mobile/health` → `{"status":"ok"}` ✅
- `GET https://gripline.ru/api/mobile/classes` → список классов ✅
- `POST https://gripline.ru/api/mobile/auth/login` (demo_pilot_5@email.ru) → JWT токен ✅
- `GET https://gripline.ru/api/mobile/auth/me` с токеном → профиль пользователя ✅
- Swagger UI `https://gripline.ru/api/mobile/docs` → все 20 эндпоинтов отображаются ✅

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
