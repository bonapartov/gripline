/*
 * Сохранение сетапов развесовки (/balance/, Блок 3 ТЗ, Этапы 2 и 4 —
 * см. /home/v/.claude/plans/smooth-snacking-spindle.md). Подключается
 * только на home.html, после balance-calculator.js (тот определяет
 * window.GripBalanceCalc — см. конец его IIFE).
 *
 * Три независимые части:
 * 1. Стэш состояния калькулятора вокруг ухода на Яндекс-логин и возврата —
 *    работает для ЛЮБОГО анонимного посетителя, независимо от identity.
 * 2. Загрузка сетапа на редактирование (#balanceLoadedSetup, Этап 4) —
 *    если страница отдана через setup_edit, приоритетнее стэша (см. ниже).
 * 3. Форма сохранения сетапа (#glCalcSavePanel) — рендерится сервером
 *    только пилотам/менеджерам с доступом к развесовке, поэтому её просто
 *    может не быть в DOM. data-mode на панели ("create"/"edit") решает,
 *    создаётся новый сетап или обновляется уже существующий (setup_id).
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

  var STASH_KEY = "glBalanceCalcStash";
  // 10 минут — щедро на случай медленного OAuth у Яндекса, но не бесконечно:
  // старый стэш из позавчерашней сессии не должен молча подменить то, что
  // пилот успел ввести сегодня.
  var STASH_TTL_MS = 10 * 60 * 1000;

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

  // ── 1. Стэш вокруг OAuth-редиректа ───────────────────────────────────

  var loginLink = document.getElementById("glCalcLoginLink");
  if (loginLink) {
    loginLink.addEventListener("click", function () {
      if (!window.GripBalanceCalc) return;
      try {
        sessionStorage.setItem(STASH_KEY, JSON.stringify({
          ts: Date.now(),
          state: window.GripBalanceCalc.getState(),
        }));
      } catch (e) {
        // приватный режим / квота — просто теряем стэш, переход на логин
        // всё равно не должен блокироваться.
      }
    });
  }

  function restoreStash() {
    if (!window.GripBalanceCalc) return;
    var raw;
    try {
      raw = sessionStorage.getItem(STASH_KEY);
      if (raw) sessionStorage.removeItem(STASH_KEY);
    } catch (e) {
      return;
    }
    if (!raw) return;
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      return;
    }
    if (!parsed || !parsed.state || Date.now() - parsed.ts > STASH_TTL_MS) return;
    window.GripBalanceCalc.loadState(parsed.state);
  }

  // ── 2. Загрузка сетапа на редактирование (Этап 4) ────────────────────
  // Приоритетнее стэша: пришли по прямой ссылке на конкретный сетап — то,
  // что могло залежаться в sessionStorage с прошлого визита, не должно его
  // молча подменить. Стэш в этом случае просто остаётся непрочитанным до
  // следующего обычного визита на /balance/ (не удаляется — TTL сам почистит).
  var loadedSetup = readJson("balanceLoadedSetup", null);
  if (loadedSetup && window.GripBalanceCalc) {
    window.GripBalanceCalc.loadState(loadedSetup.state);
  } else {
    restoreStash();
  }

  // ── 3. Форма сохранения ───────────────────────────────────────────────

  var savePanel = document.getElementById("glCalcSavePanel");
  if (!savePanel) return;

  var kartSelect = document.getElementById("glCalcSaveKartSelect");
  var newKartRow = document.getElementById("glCalcNewKartRow");
  var newKartName = document.getElementById("glCalcNewKartName");
  var newKartChassis = document.getElementById("glCalcNewKartChassis");
  var newKartType = document.getElementById("glCalcNewKartType");
  var newKartCreateBtn = document.getElementById("glCalcNewKartCreate");
  var setupNameInput = document.getElementById("glCalcSetupName");
  var saveBtn = document.getElementById("glCalcSetupSaveBtn");
  var messageEl = document.getElementById("glCalcSaveMessage");

  function showMessage(text, isError) {
    if (!messageEl) return;
    messageEl.textContent = text || "";
    messageEl.hidden = !text;
    messageEl.classList.toggle("gl-calc-save__message--error", !!isError);
  }

  if (kartSelect) {
    kartSelect.addEventListener("change", function () {
      if (newKartRow) newKartRow.hidden = kartSelect.value !== "__new__";
    });
  }

  function addKartOption(id, name) {
    if (!kartSelect) return;
    var placeholder = kartSelect.querySelector('option[value="__new__"]');
    var opt = document.createElement("option");
    opt.value = String(id);
    opt.textContent = name;
    if (placeholder) kartSelect.insertBefore(opt, placeholder);
    else kartSelect.appendChild(opt);
    kartSelect.value = String(id);
    if (newKartRow) newKartRow.hidden = true;
  }

  if (newKartCreateBtn) {
    newKartCreateBtn.addEventListener("click", function () {
      var name = newKartName ? newKartName.value.trim() : "";
      var chassisId = newKartChassis ? newKartChassis.value : "";
      var chassisType = newKartType ? newKartType.value : "";
      if (!name || !chassisId) {
        showMessage("Укажите название и шасси нового карта.", true);
        return;
      }
      newKartCreateBtn.disabled = true;
      postJson("/balance/kart/create/", { name: name, chassis_id: chassisId, chassis_type: chassisType })
        .then(function (res) {
          newKartCreateBtn.disabled = false;
          if (!res.ok) {
            showMessage(res.data.error || "Не удалось создать карт.", true);
            return;
          }
          addKartOption(res.data.id, res.data.name);
          if (newKartName) newKartName.value = "";
          showMessage("Карт «" + res.data.name + "» создан.", false);
        })
        .catch(function () {
          newKartCreateBtn.disabled = false;
          showMessage("Не удалось создать карт — проверьте соединение.", true);
        });
    });
  }

  var mode = savePanel.dataset.mode || "create";
  var editingSetupId = savePanel.dataset.setupId || "";

  if (saveBtn) {
    saveBtn.addEventListener("click", function () {
      if (!window.GripBalanceCalc) return;

      var payload = null;
      if (mode === "edit") {
        payload = { setup_id: editingSetupId };
      } else {
        var kartId = kartSelect ? kartSelect.value : "";
        if (!kartId || kartId === "__new__") {
          showMessage("Выберите или создайте карт.", true);
          return;
        }
        payload = { kart_id: kartId };
      }

      var state = window.GripBalanceCalc.getState();
      if (!state.class_id) {
        showMessage("Выберите класс, чтобы сохранить сетап.", true);
        return;
      }
      payload.name = setupNameInput ? setupNameInput.value.trim() : "";
      payload.class_id = state.class_id;
      payload.corners = state.corners;
      payload.driver_weight_kg = state.driver_weight;
      payload.weather = state.weather;
      payload.wheelbase_mm = state.wheelbase_mm;
      payload.track_front_mm = state.track_front_mm;
      payload.track_rear_mm = state.track_rear_mm;
      payload.ballasts = state.ballasts;

      saveBtn.disabled = true;
      postJson("/balance/setup/save/", payload)
        .then(function (res) {
          saveBtn.disabled = false;
          if (!res.ok) {
            showMessage(res.data.error || "Не удалось сохранить сетап.", true);
            return;
          }
          showMessage(
            mode === "edit"
              ? "Изменения сохранены."
              : "Сетап «" + res.data.name + "» сохранён.",
            false
          );
          if (window.__balanceYmCounter && typeof window.ym === "function") {
            try { window.ym(window.__balanceYmCounter, "reachGoal", "setup_saved"); } catch (e) { /* аналитика не должна ронять сохранение */ }
          }
        })
        .catch(function () {
          saveBtn.disabled = false;
          showMessage("Не удалось сохранить сетап — проверьте соединение.", true);
        });
    });
  }

  // ── Копия / архив / шеринг (Этап 5-6, только data-mode="edit") ────────

  if (mode === "edit" && editingSetupId) {
    var copyBtn = document.getElementById("glCalcSetupCopyBtn");
    var archiveBtn = document.getElementById("glCalcSetupArchiveBtn");
    var shareTeamCheckbox = document.getElementById("glCalcShareTeam");
    var shareDriverCheckbox = document.getElementById("glCalcShareDriver");

    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        copyBtn.disabled = true;
        postJson("/balance/setup/" + editingSetupId + "/copy/", {})
          .then(function (res) {
            if (!res.ok) {
              copyBtn.disabled = false;
              showMessage(res.data.error || "Не удалось скопировать сетап.", true);
              return;
            }
            // Редирект сразу на копию (ТЗ: копирование — основной путь
            // итерации, должно быть предельно лёгким, без промежуточных шагов).
            window.location.href = "/balance/setup/" + res.data.id + "/";
          })
          .catch(function () {
            copyBtn.disabled = false;
            showMessage("Не удалось скопировать сетап — проверьте соединение.", true);
          });
      });
    }

    if (archiveBtn) {
      archiveBtn.addEventListener("click", function () {
        var currentlyArchived = archiveBtn.dataset.archived === "true";
        archiveBtn.disabled = true;
        postJson("/balance/setup/" + editingSetupId + "/archive/", { archived: !currentlyArchived })
          .then(function (res) {
            archiveBtn.disabled = false;
            if (!res.ok) {
              showMessage(res.data.error || "Не удалось изменить архив.", true);
              return;
            }
            archiveBtn.dataset.archived = res.data.is_archived ? "true" : "false";
            archiveBtn.textContent = res.data.is_archived ? "Вернуть из архива" : "Архивировать";
            showMessage(res.data.is_archived ? "Сетап отправлен в архив." : "Сетап возвращён из архива.", false);
          })
          .catch(function () {
            archiveBtn.disabled = false;
            showMessage("Не удалось изменить архив — проверьте соединение.", true);
          });
      });
    }

    function wireShareCheckbox(checkbox, target) {
      if (!checkbox) return;
      checkbox.addEventListener("change", function () {
        var shared = checkbox.checked;
        checkbox.disabled = true;
        postJson("/balance/setup/" + editingSetupId + "/share/", { target: target, shared: shared })
          .then(function (res) {
            checkbox.disabled = false;
            if (!res.ok) {
              checkbox.checked = !shared; // откатить визуально
              showMessage(res.data.error || "Не удалось изменить доступ.", true);
              return;
            }
            showMessage(shared ? "Доступ открыт." : "Доступ закрыт.", false);
          })
          .catch(function () {
            checkbox.disabled = false;
            checkbox.checked = !shared;
            showMessage("Не удалось изменить доступ — проверьте соединение.", true);
          });
      });
    }

    wireShareCheckbox(shareTeamCheckbox, "team");
    wireShareCheckbox(shareDriverCheckbox, "driver");
  }
})();
