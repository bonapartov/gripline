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
**Сервис:** `gripline` (gunicorn, 3 воркера, порт 8000)  
**Python venv:** `/www/wwwroot/gripline.ru/venv`

### Основные команды на сервере

```bash
# Перезапуск сервиса
systemctl restart gripline

# Логи
journalctl -u gripline -f

# Активировать venv
cd /www/wwwroot/gripline.ru && source venv/bin/activate

# Пересчёт рейтингов (запускать вручную после ввода новых результатов)
python manage.py update_ratings --entity driver --model bt

# Миграции
python manage.py migrate

# Django shell
python manage.py shell
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
| `RaceResult` | Результат пилота в заезде |
| `RaceClassResultGroup` | Группа результатов одного заезда |
| `AnalyticsSettings` | Singleton с параметрами аналитики. Доступ: `AnalyticsSettings.get()` |
| `HomePage` | Главная страница. Блоки: герой, новости, топ пилотов, предстоящие события, матчасть |
| `ArticlePage` | Статья/новость |
| `ArticleIndexPage` | Индекс новостей |
| `TechArticleIndexPage` | Индекс матчасти (`/matchast/`, page id=378) |
| `StagePage` | Этап чемпионата |
| `ChampionshipPage` | Чемпионат |

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

## Миграции

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

**Новые модели (Этап 2):**
- `UserProfile`: `roles` (ArrayField, денормализованный кэш), `driver` FK, `team` FK, `verified`. Синхронизируется с существующими Django-моделями (`DriverClaim`, `TeamManager`) через сигналы — атомарно обновляет и `roles`, и FK.
- `PushToken`: отдельная таблица (не поле на профиле). Стратегия — накапливать токены, удалять мёртвые по ответу FCM (`InvalidRegistration`/`NotRegistered`).

**Новые поля моделей (Этап 1):**

`RaceClassResultGroup.session_type`:
```python
('warmup',     'Прогрев')
('qualifying', 'Квалификация')
('heat',       'Заезд (ABC)')
('pre_final',  'Предфинал')
('final',      'Финал')   # default
```
Поле `heat_group` (группа AB/AC/BC) — отложено на потом.

`RaceResult` — новые поля:
- `start_position` (IntegerField, null)
- `best_lap_ms`, `best_s1_ms`, `best_s2_ms`, `best_s3_ms` (IntegerField, null) — миллисекунды

**Страница пилота — что добавляется (Этап 1):**
- В таблице истории: бейдж типа сессии (Ф/Пф/ПР/К), прогресс позиции (5→2 ▲3), лучший круг
- Новый блок «Личные рекорды»: лучший круг по классу, лучшие S1/S2/S3, идеальный круг (S1+S2+S3)
- Блок скрыт если данных нет

**Импорт данных с хронометража:**
- Пока ручной ввод через Wagtail admin (агрегаты: best_lap + секторы)
- Уточнить у организатора: экспортирует ли Apex Timing GoRacing XML/CSV помимо PDF
- PDF-парсер — отдельный проект, реализуется после Этапа 1

**Тестирование:**
- Локальная машина = staging среда
- Workflow: редактировать локально → тестировать → коммит → push → cherry-pick на сервер
- Автотесты только для: расчёта рейтинга (analytics/) и FastAPI эндпоинтов (роли, авторизация)

### Дорожная карта (кратко)

| Этап | Статус | Суть |
|------|--------|------|
| **1. Данные хронометража** | **В работе** | Новые поля моделей + страница пилота |
| **2. Подготовка к FastAPI** | Следующий | `UserProfile`, `PushToken`, локальная среда |
| **3. FastAPI сервис** | Позже | JWT API для мобилки, ingestion, расчёт рейтингов |
| **4. Flutter приложение** | Позже | Мобилка с ролями, push-уведомлениями |

### Открытые вопросы
- Экспортирует ли Apex Timing XML/CSV? (уточнить у организатора)
- Отдельный репозиторий для FastAPI или монорепо? (решить при старте Этапа 3)
- Push-уведомления: Firebase или альтернатива? (решить при старте Этапа 4)
