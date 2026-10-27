# Упоминания пилотов/команд в статьях

> Перенесено из `CLAUDE.md` 27.10.2026 без изменений текста. Общие правила проекта — в `CLAUDE.md`.

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
