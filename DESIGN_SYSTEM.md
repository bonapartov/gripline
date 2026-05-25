# Дизайн-система Gripline — руководство разработчика

> Этот файл — живой документ. Обновляй его при каждом изменении токенов,
> компонентов или правил. Дата последнего обновления: 2026-05-22.

---

## Как устроена система токенов

Все визуальные константы определены в одном файле:

```
website/static/website/css/tokens.css   ← единственный источник правды
website/static/website/css/custom.css   ← стили поверх токенов
```

Порядок подключения в `base.html`:
```html
<link rel="stylesheet" href="{% static 'website/css/tokens.css' %}">
<link rel="stylesheet" href="{% static 'website/css/custom.css' %}">
```

### Главное правило

**Никогда не пиши hex-значения напрямую в шаблонах или CSS.**
Добавь токен в `tokens.css` → используй `var(--gl-*)` везде.

---

## Таблица токенов

### Цвета бренда

| Токен | Значение | Использование |
|---|---|---|
| `--gl-brand-yellow` | `#ffc107` | Основной акцент, CTA, первое место |
| `--gl-brand-yellow-bright` | `#ffd400` | Логотип, ссылки, hover |
| `--gl-brand-cyan` | `#0dcaf0` | Информационные элементы, подсветка таблиц |
| `--gl-brand-green` | `#28a745` | Рейтинговый чип, положительные показатели |
| `--gl-brand-bronze` | `#cd7f32` | Третье место |
| `--gl-brand-red` | `#ff0000` | **ТОЛЬКО** дата в карточке новости |

### Сигнальные цвета (состояния UI)

| Токен | Значение | Использование |
|---|---|---|
| `--gl-signal-danger` | `#dc3545` | Ошибки, спад, отрицательные показатели |
| `--gl-signal-success` | `var(--gl-brand-green)` | Успех, рост, положительные показатели |
| `--gl-signal-info` | `var(--gl-brand-cyan)` | Информационные блоки |

### Поверхности (от тёмной к светлой)

| Токен | Значение | Использование |
|---|---|---|
| `--gl-surface-deepest` | `#000000` | Футер |
| `--gl-surface-inset` | `#0d0d15` | Блок обратного отсчёта |
| `--gl-surface-navbar` | `#0e131a` | Навбар, выпадающее меню |
| `--gl-surface-body` | `#15151c` | Фон страницы |
| `--gl-surface-card-warm` | `#171f26` | ⚠️ УСТАРЕВШИЙ — только в legacy-коде |
| `--gl-surface-card` | `#1a1a25` | Стандартная карточка (текущий стандарт) |
| `--gl-surface-card-hover` | `#2a2a35` | Hover, внутренние элементы, бейджи |
| `--gl-surface-divider` | `#3a3a45` | Разделители |

### Цвет текста

| Токен | Значение | Bootstrap-аналог |
|---|---|---|
| `--gl-fg-1` | `#ffffff` | Заголовки карточек |
| `--gl-fg-2` | `#eceff1` | Основной текст |
| `--gl-fg-3` | `#b0bec5` | Текст карточки, подписи |
| `--gl-fg-4` | `#adb5bd` | Вторичный текст |
| `--gl-fg-muted` | `#6c757d` | `.text-muted` |
| `--gl-fg-on-yellow` | `#1a1a25` | Текст на жёлтом фоне |

### Границы

| Токен | Значение |
|---|---|
| `--gl-border-soft` | `#222222` |
| `--gl-border-card` | `#2a2a35` |
| `--gl-border-divider` | `#3a3a45` |
| `--gl-border-mid` | `#333333` |

### Радиусы скругления

| Токен | Значение | Использование |
|---|---|---|
| `--gl-radius-none` | `0` | Выпадающее меню |
| `--gl-radius-sm` | `4px` | Бейджи, мелкие элементы |
| `--gl-radius-md` | `6px` | Переключатели, блоки дат |
| `--gl-radius-lg` | `8px` | Карточки (стандарт) |
| `--gl-radius-2xl` | `12px` | Герой-секция |
| `--gl-radius-pill` | `20px` | Фильтры-кнопки, чипы |
| `--gl-radius-full` | `9999px` | Аватары |

### Тени

| Токен | Использование |
|---|---|
| `--gl-shadow-card` | Карточки, обложки статей |
| `--gl-shadow-hover` | Hover-состояние карточки |
| `--gl-shadow-image` | Картинки в тексте |

### Анимация

| Токен | Значение |
|---|---|
| `--gl-motion-fast` | `0.2s ease` |
| `--gl-motion-medium` | `0.3s ease` |
| `--gl-motion-slow-zoom` | `0.8s cubic-bezier(0.2, 1, 0.3, 1)` |

---

## Правила разработки

### Цвета

- **Нет hex-значений напрямую.** Всегда `var(--gl-*)`.
- **Нет светлой темы.** `background: white`, `background: #fff`, светлые фоны — запрещены.
- **Нет Bootstrap-синего (`#0d6efd`).** Заменяй на `var(--gl-brand-cyan)`.
- **Нет `backdrop-filter`.** Эффект размытия стекла не используется.
- **Нет градиентов между акцентными цветами**, кроме разрешённых паттернов (герой, полоска над dropdown).
- `--gl-surface-card-warm` (`#171f26`) — устаревший токен. В новом коде используй `--gl-surface-card`.

### Иконография

- **Font Awesome 6 Solid** — единственный источник иконок.
- **Две кастомные SVG-иконки:** `helmet.svg` (позиция) и `number-plate.svg` (стартовый номер).
- **Emoji запрещены**, кроме: `🏁` и набора погоды (`🌡️ 💧 🌀 📊 ☀️`).
- Замена emoji на FA-иконки:

| Emoji | FA-иконка |
|---|---|
| ✅ | `<i class="fas fa-check text-success">` |
| ❌ | `<i class="fas fa-xmark text-danger">` |
| ⚠️ | `<i class="fas fa-triangle-exclamation text-warning">` |
| 🏆 | `<i class="fas fa-trophy text-warning">` |
| ⭐ | `<i class="fas fa-star text-warning">` |
| 💡 | `<i class="fas fa-circle-info text-warning">` |
| 🔥 | `<i class="fas fa-fire text-warning">` |
| 💪 | `<i class="fas fa-shield-halved text-info">` |
| 👑 | `<i class="fas fa-crown text-warning">` |

### Типографика

- **Заголовки разделов**: верхний регистр, `font-weight: 800–900`, `letter-spacing: 1–2px`.
- **CTA-кнопки**: только первая буква заглавная (`Подробнее`, `Результаты`).
- **Мини-подписи** над числами: верхний регистр, мелкий кегль, цвет `--gl-brand-cyan`.
- **Числа в таблицах**: `font-family: var(--gl-font-mono); font-variant-numeric: tabular-nums`.

### Карточки — стандартный паттерн

```html
<div style="background: var(--gl-surface-card);
            border: 1px solid var(--gl-border-card);
            border-radius: var(--gl-radius-lg);
            box-shadow: var(--gl-shadow-card);
            transition: transform var(--gl-motion-medium);">
```

Hover (через CSS):
```css
.my-card:hover {
  border-color: var(--gl-border-yellow);
  transform: translateY(-3px);
  box-shadow: var(--gl-shadow-hover);
}
```

### Информационные блоки

```html
<div style="background: var(--gl-surface-card);
            border: 1px solid var(--gl-brand-cyan);
            border-left: 4px solid var(--gl-brand-cyan);
            border-radius: var(--gl-radius-sm);
            color: var(--gl-brand-cyan);">
```

### Таблицы с hover-подсветкой

```css
.table-hover tbody tr:hover {
  background-color: var(--gl-cyan-tint-10) !important;
}
```

---

## Что было исправлено (2026-05-22)

### Создано

- `website/static/website/css/tokens.css` — все дизайн-токены в CSS-переменных `--gl-*`

### Изменено

| Файл | Что исправлено |
|---|---|
| `base.html` | Подключён `tokens.css` перед `custom.css` |
| `custom.css` | Полная замена hex-значений на `var(--gl-*)`. Исправлен цвет карточек: `#171f26` → `var(--gl-surface-card)`. `#1c2633` → `var(--gl-surface-card-hover)` |
| `article_page.html` | `background: white` → `var(--gl-surface-card)`. Серый текст → `var(--gl-fg-muted)` / `var(--gl-fg-3)` |
| `pulse_index_page.html` | `backdrop-filter` удалён. `#0d6efd` → `var(--gl-brand-cyan)` / `var(--gl-surface-card-hover)` |
| `driver_page.html` | `#198754` → `var(--gl-brand-green)`. `#495057` → `var(--gl-surface-divider)`. `#dc3545` → `var(--gl-signal-danger)`. `#0d6efd` → `var(--gl-brand-cyan)`. Emoji заменены на FA-иконки. Жёлтые кнопки «vs» переведены на токены |
| `team_ratings.html` | Градиент `#0dcaf0→#0d6efd` заменён на `var(--gl-brand-cyan)→var(--gl-brand-yellow)` |
| `weather_impact.html` | `#dc3545` / `#28a745` → сигнальные токены. Emoji заменены на FA-иконки |
| `chassis_track_matrix.html` | `#1a3a4a` / `#9ec5fe` → `var(--gl-surface-card)` / `var(--gl-brand-cyan)`. Emoji заменены |
| `tyre_analysis.html` | Emoji заменены на FA-иконки |
| `weights_table.html` | Все hex → токены. Emoji заменены на FA-иконки |
| `rating_info_page_ld.html` | Все hex → токены. `⚠️` / `✅` → FA-иконки |
| `compare_models_page.html` | `#28a745` / `#dc3545` → сигнальные токены |

---

## Что ещё нужно сделать (backlog)

- [ ] Заменить реконструированный логотип в `assets/logo.svg` на финальный.
- [ ] Подключить реальные веб-шрифты (Inter Tight + JetBrains Mono) через `@font-face`
      и раскомментировать `@import` в `tokens.css`.
- [ ] Аудит оставшихся шаблонов (organizers, applications, teams) на hex-значения.
- [ ] Вынести повторяющиеся `<style>`-блоки из шаблонов в отдельные CSS-файлы.
- [ ] Добавить CSS-классы `.gl-card`, `.gl-card-hero` из дизайн-системы в `custom.css`
      и переключить шаблоны на них.
- [ ] Проверить страницы организатора и команды на соответствие дизайн-системе.
