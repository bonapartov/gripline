/*
 * Список сохранённых сетапов (/balance/mine/, Блок 3 ТЗ, Этапы 3, 5-6 — см.
 * /home/v/.claude/plans/smooth-snacking-spindle.md). Весь датасет прилетает
 * одним json_script-блобом (balance_setup_views.py::setups_list) — группировка
 * по карту, сортировка по дате внутри группы, фильтры класс/погода/трасса и
 * переключатель архива работают целиком на клиенте, без похода на сервер.
 * Тот же принцип, что «История выступлений» на странице пилота.
 *
 * Копировать/архивировать — прямо с карточки (только когда row.can_edit,
 * тот же гейт, что владение сетапом на сервере). Шеринг — только на странице
 * редактирования конкретного сетапа (setup_edit) — там больше контекста для
 * двух разных чекбоксов "открыть команде"/"открыть пилоту", на компактной
 * карточке списка это было бы тесно и запутанно.
 */
(function () {
  "use strict";

  function readJson(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return fallback;
    }
  }

  var listEl = document.getElementById("glSetupsList");
  if (!listEl) return; // не на странице списка

  var DATA = readJson("balanceSetupsData", []);
  var emptyEl = document.getElementById("glSetupsEmpty");
  var messageEl = document.getElementById("glSetupsMessage");
  var classFilter = document.getElementById("glSetupsFilterClass");
  var weatherFilter = document.getElementById("glSetupsFilterWeather");
  var trackFilter = document.getElementById("glSetupsFilterTrack");
  var archivedToggle = document.getElementById("glSetupsShowArchived");

  // Блок 7 (сравнение сетапов, ТЗ §8.1) — выбор ровно двух карточек для
  // "Сравнить". Состояние держим здесь (не в DOM), потому что render()
  // перерисовывает список целиком при каждой смене фильтра — DOM-чекбоксы
  // сами по себе теряли бы отметки, cardHtml() читает selectedForCompare,
  // чтобы восстановить checked после перерисовки.
  var selectedForCompare = [];
  var compareBar = document.getElementById("glSetupsCompareBar");
  var compareCountEl = document.getElementById("glSetupsCompareCount");
  var compareGoBtn = document.getElementById("glSetupsCompareGo");
  var compareClearBtn = document.getElementById("glSetupsCompareClear");

  function updateCompareBar() {
    if (!compareBar) return;
    compareBar.hidden = selectedForCompare.length === 0;
    if (compareCountEl) compareCountEl.textContent = selectedForCompare.length + "/2";
    if (compareGoBtn) compareGoBtn.disabled = selectedForCompare.length !== 2;
  }

  function showMessage(text, isError) {
    if (!messageEl) return;
    messageEl.textContent = text || "";
    messageEl.hidden = !text;
    messageEl.classList.toggle("gl-setups-message--error", !!isError);
  }

  // Тот же паттерн, что balance-setup-editor.js — независимо загружаемые
  // страницы /balance/, дублировать 10-строчный helper проще, чем заводить
  // общий модуль ради него (см. getCookie в _social_auth_buttons.html — та
  // же идиома уже применяется в проекте).
  function getCookie(name) {
    var value = null;
    if (document.cookie) {
      document.cookie.split(";").forEach(function (part) {
        part = part.trim();
        if (part.indexOf(name + "=") === 0) value = decodeURIComponent(part.slice(name.length + 1));
      });
    }
    return value;
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      body: JSON.stringify(payload),
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        return { ok: resp.ok, data: data };
      });
    });
  }

  // Ровно тот же паттерн, что mention-markdown.js::escapeHtml — name/kart_name
  // приходят из свободного текстового поля пилота, вставка в innerHTML без
  // экранирования была бы хранимой XSS.
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function matchesFilters(row) {
    if (classFilter && classFilter.value && String(row.class_id) !== classFilter.value) return false;
    if (weatherFilter && weatherFilter.value && row.weather !== weatherFilter.value) return false;
    if (trackFilter && trackFilter.value && String(row.track_id) !== trackFilter.value) return false;
    if (!(archivedToggle && archivedToggle.checked) && row.is_archived) return false;
    return true;
  }

  function badgesHtml(row) {
    var badges = "";
    if (row.is_archived) badges += '<span class="gl-setups-badge gl-setups-badge--archived">В архиве</span>';
    if (!row.can_edit) badges += '<span class="gl-setups-badge gl-setups-badge--shared">Только просмотр</span>';
    if (row.shared_with_team) badges += '<span class="gl-setups-badge">Открыт команде</span>';
    if (row.shared_with_driver) badges += '<span class="gl-setups-badge">Открыт пилоту</span>';
    return badges ? '<div class="gl-setups-card__badges">' + badges + "</div>" : "";
  }

  // Копировать/архивировать — через делегирование кликов на listEl (карточки
  // перерисовываются при каждой смене фильтра, навешивать обработчик на
  // каждую заново было бы утечкой/дублированием).
  function actionsHtml(row) {
    if (!row.can_edit) return "";
    var archiveLabel = row.is_archived ? "Вернуть из архива" : "Архивировать";
    return (
      '<div class="gl-setups-card__actions">' +
      '<button type="button" class="gl-setups-card__action" data-action="copy" data-setup-id="' + row.id + '">Копировать</button>' +
      '<button type="button" class="gl-setups-card__action" data-action="archive" data-setup-id="' + row.id +
      '" data-archived="' + (row.is_archived ? "true" : "false") + '">' + archiveLabel + "</button>" +
      "</div>"
    );
  }

  function cardHtml(row) {
    var meta = [escapeHtml(row.class_name)];
    if (row.weather_label) meta.push(escapeHtml(row.weather_label));
    if (row.track_name) meta.push(escapeHtml(row.track_name));

    var checked = selectedForCompare.indexOf(String(row.id)) !== -1;
    return (
      '<div class="gl-setups-card">' +
      '<div class="gl-setups-card__header">' +
      '<label class="gl-setups-card__compare">' +
      '<input type="checkbox" class="gl-setups-compare-check" data-setup-id="' + row.id + '"' +
      (checked ? " checked" : "") + '>' +
      '<span class="gl-setups-card__name">' + escapeHtml(row.name) + "</span>" +
      "</label>" +
      '<span class="gl-setups-card__date">' + escapeHtml(row.created_at_display) + "</span>" +
      "</div>" +
      '<div class="gl-setups-card__meta"><span>' + meta.join("</span><span>") + "</span></div>" +
      '<div class="gl-setups-card__corners">' +
      "<span>ЛП " + escapeHtml(row.corners.lf) + "</span>" +
      "<span>ПП " + escapeHtml(row.corners.rf) + "</span>" +
      "<span>ЛЗ " + escapeHtml(row.corners.lr) + "</span>" +
      "<span>ПЗ " + escapeHtml(row.corners.rr) + "</span>" +
      '<span class="gl-setups-card__total">Итого ' + escapeHtml(row.total_kg) + " кг</span>" +
      "</div>" +
      badgesHtml(row) +
      actionsHtml(row) +
      '<a class="gl-setups-card__open" href="/balance/setup/' + encodeURIComponent(row.id) + '/">' +
      (row.can_edit ? "Открыть →" : "Открыть (только просмотр) →") +
      "</a>" +
      "</div>"
    );
  }

  function render() {
    var filtered = DATA.filter(matchesFilters);

    if (!filtered.length) {
      listEl.innerHTML = "";
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;

    var groupOrder = [];
    var groups = {};
    filtered.forEach(function (row) {
      if (!groups[row.kart_id]) {
        groups[row.kart_id] = { name: row.kart_name, rows: [] };
        groupOrder.push(row.kart_id);
      }
      groups[row.kart_id].rows.push(row);
    });
    groupOrder.sort(function (a, b) {
      return groups[a].name.localeCompare(groups[b].name, "ru");
    });

    var html = "";
    groupOrder.forEach(function (kartId) {
      var group = groups[kartId];
      group.rows.sort(function (a, b) {
        return new Date(b.created_at) - new Date(a.created_at);
      });
      html += '<section class="gl-setups-group"><h2 class="gl-setups-group__title">' +
        escapeHtml(group.name) + "</h2>";
      group.rows.forEach(function (row) {
        html += cardHtml(row);
      });
      html += "</section>";
    });
    listEl.innerHTML = html;
  }

  [classFilter, weatherFilter, trackFilter, archivedToggle].forEach(function (el) {
    if (el) el.addEventListener("change", render);
  });

  // Чекбоксы "Сравнить" — отдельное делегирование через change (не click,
  // как у data-action кнопок ниже): нативный чекбокс уже сам переключает
  // checked, нам остаётся только синхронизировать selectedForCompare.
  listEl.addEventListener("change", function (evt) {
    var checkbox = evt.target;
    if (!checkbox.classList || !checkbox.classList.contains("gl-setups-compare-check")) return;
    var id = String(checkbox.dataset.setupId);
    if (checkbox.checked) {
      if (selectedForCompare.length >= 2) {
        checkbox.checked = false;
        showMessage("Можно сравнить только два сетапа за раз — сначала снимите один из выбранных.", true);
        return;
      }
      selectedForCompare.push(id);
    } else {
      selectedForCompare = selectedForCompare.filter(function (x) { return x !== id; });
    }
    updateCompareBar();
  });

  if (compareGoBtn) {
    compareGoBtn.addEventListener("click", function () {
      if (selectedForCompare.length !== 2) return;
      window.location.href = "/balance/compare/?a=" + encodeURIComponent(selectedForCompare[0]) +
        "&b=" + encodeURIComponent(selectedForCompare[1]);
    });
  }
  if (compareClearBtn) {
    compareClearBtn.addEventListener("click", function () {
      selectedForCompare = [];
      updateCompareBar();
      render();
    });
  }

  // Делегирование — карточки перерисовываются целиком при каждом render(),
  // отдельные обработчики на кнопках были бы утеряны/задублированы.
  listEl.addEventListener("click", function (evt) {
    var btn = evt.target.closest("[data-action]");
    if (!btn) return;
    var action = btn.dataset.action;
    var setupId = btn.dataset.setupId;
    var row = DATA.filter(function (r) { return String(r.id) === String(setupId); })[0];
    if (!row) return;

    if (action === "copy") {
      btn.disabled = true;
      postJson("/balance/setup/" + setupId + "/copy/", {})
        .then(function (res) {
          if (!res.ok) {
            btn.disabled = false;
            showMessage(res.data.error || "Не удалось скопировать сетап.", true);
            return;
          }
          // Редирект сразу на копию (ТЗ: копирование должно быть предельно
          // лёгким, без промежуточных подтверждений).
          window.location.href = "/balance/setup/" + res.data.id + "/";
        })
        .catch(function () {
          btn.disabled = false;
          showMessage("Не удалось скопировать сетап — проверьте соединение.", true);
        });
    } else if (action === "archive") {
      var currentlyArchived = btn.dataset.archived === "true";
      btn.disabled = true;
      postJson("/balance/setup/" + setupId + "/archive/", { archived: !currentlyArchived })
        .then(function (res) {
          btn.disabled = false;
          if (!res.ok) {
            showMessage(res.data.error || "Не удалось изменить архив.", true);
            return;
          }
          row.is_archived = res.data.is_archived;
          showMessage(row.is_archived ? "Сетап отправлен в архив." : "Сетап возвращён из архива.", false);
          render();
        })
        .catch(function () {
          btn.disabled = false;
          showMessage("Не удалось изменить архив — проверьте соединение.", true);
        });
    }
  });

  render();
})();
