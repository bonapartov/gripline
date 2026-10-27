# Платформа: роли, FastAPI, Flutter, хронометраж

> Перенесено из `CLAUDE.md` 27.10.2026 без изменений текста. Общие правила проекта — в `CLAUDE.md`.

## Деплой FastAPI на сервер (первый раз)


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
