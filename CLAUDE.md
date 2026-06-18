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

| Ветка | Назначение |
|-------|-----------|
| `design/hero-redesign` | **Продакшн** — работает на сервере |
| `claude/review-project-rating-RxaZa` | **Разработка** — сюда коммитим изменения |

**Важно:** GitHub не имеет прямого доступа к серверу. Workflow:
1. Коммит в `claude/review-project-rating-RxaZa` → push на GitHub
2. На сервере: `git fetch origin` → `git cherry-pick <хеш>` → `systemctl restart gripline`

---

## Сервер

**Хост:** `cleantogo` (root@cleantogo)  
**Путь:** `/www/wwwroot/gripline.ru`  
**Сервис Django:** `gripline` (gunicorn, 3 воркера, порт 8000)  
**Сервис FastAPI:** `gripline-api` (uvicorn, порт 8001)  
**Python venv Django:** `/www/wwwroot/gripline.ru/venv`  
**Python venv FastAPI:** `/www/wwwroot/gripline.ru/fastapi/venv`

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

```bash
# 1. Скопировать systemd-юнит
cp /www/wwwroot/gripline.ru/fastapi/gripline-api.service /etc/systemd/system/
systemctl daemon-reload

# 2. Создать venv и установить зависимости
cd /www/wwwroot/gripline.ru/fastapi
python3.13 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. Добавить FASTAPI_SECRET_KEY в /www/wwwroot/gripline.ru/.env
echo 'FASTAPI_SECRET_KEY=<сгенерировать: python -c "import secrets; print(secrets.token_hex(32))">' >> /www/wwwroot/gripline.ru/.env

# 4. Запустить и включить автозапуск
systemctl enable --now gripline-api

# 5. Добавить nginx location (см. fastapi/nginx_snippet.conf)
# Вставить в /www/server/nginx/conf/vhost/gripline.ru.conf внутрь server {}
# и перезагрузить: nginx -s reload
```

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

```bash
python manage.py update_ratings --entity driver --model bt
```

Запускается **вручную** после каждого ввода новых результатов соревнований.

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
- Таблица истории: колонка «Динамика» (старт→финиш + стрелка), колонка «Круг» (лучший из заполненных сессий с бейджем К/Пф/Ф), бейджи сессий
- Блок «Личные рекорды»: лучший круг по классу, S1/S2/S3, идеальный круг — агрегируется по всем трём сессиям; скрыт если данных нет

**Импорт данных с хронометража:**
- Пока: ручной ввод через Wagtail admin
- Уточнить у организатора: экспортирует ли Apex Timing GoRacing XML/CSV помимо PDF
- PDF-парсер — отдельный проект, реализуется после Этапа 1

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

Swagger UI (авторизация): http://127.0.0.1:8001/docs → кнопка **Authorize** → `Bearer <token>`.

**Тестирование:**
- Локальная машина = staging среда (PostgreSQL локально, `--settings=mysite.settings.dev`)
- Workflow: редактировать локально → тестировать → коммит → push → cherry-pick на сервер
- Автотесты только для: расчёта рейтинга (`analytics/`) и FastAPI эндпоинтов (роли, авторизация)

### Дорожная карта (кратко)

| Этап | Статус | Суть |
|------|--------|------|
| **1. Данные хронометража** | **Выполнен** | Поля квал/предфинал/финал + страница пилота |
| **2. Подготовка к FastAPI** | **Выполнен** | `roles`/`team`/`verified` в `UserProfile`, `PushToken`, сигналы синхронизации |
| **3. FastAPI сервис** | **Выполнен** | 20 эндпоинтов: авторизация, пилоты, чемпионаты, команды, новости, лента, push; деплой на сервер — следующий шаг |
| **4. Flutter приложение** | **В работе** | Скелет: логин, onboarding, лента, профиль пилота |

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
- Android-эмулятор: `http://10.0.2.2:8001`
- iOS-симулятор: `http://127.0.0.1:8001`
- Реальное устройство: IP компьютера в локальной сети

**Запуск:**
```bash
cd flutter_app
flutter pub get
flutter run
```

**Firebase:** скопировать `google-services.json` и `GoogleService-Info.plist` из Firebase Console по шаблонам `.example`. Файлы в `.gitignore`.

### Дорожная карта (кратко)

| Этап | Статус | Суть |
|------|--------|------|
| **1. Данные хронометража** | **Выполнен** | Поля квал/предфинал/финал + страница пилота |
| **2. Подготовка к FastAPI** | **Выполнен** | `roles`/`team`/`verified` в `UserProfile`, `PushToken`, сигналы синхронизации |
| **3. FastAPI сервис** | **Выполнен (базовый)** | JWT авторизация + `/pilot/me` + `/pilot/profile`; деплой на сервер — следующий шаг |
| **4. Flutter приложение** | **В работе** | Скелет: логин, onboarding, лента, профиль пилота; push и рейтинг пилотов — следующая итерация |

### Открытые вопросы
- Экспортирует ли Apex Timing XML/CSV? (уточнить у организатора)
- Деплой FastAPI на сервер: systemd-сервис `gripline-api`, порт 8001, nginx proxy
- Flutter: настроить Firebase проект и добавить реальные `google-services.json`
- Flutter: экран рейтинга пилотов (нужен API-эндпоинт со списком + фильтрами по классу)
