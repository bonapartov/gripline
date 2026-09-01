/*
 * PWA-баннер «Добавить на экран» для /balance/ (ТЗ 1.4, уровень 2).
 * Показывается не сразу, а после N визитов (localStorage-счётчик) — чтобы не
 * раздражать при первом заходе. Скрипт подключается в конце <body>, банер уже
 * в DOM к моменту выполнения — DOMContentLoaded не нужен.
 *
 * iOS Safari не поддерживает beforeinstallprompt вообще (нет программного
 * триггера установки) — для неё показывается статичная подсказка «Поделиться
 * → На экран «Домой»» вместо кнопки.
 */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/balance/sw.js", { scope: "/balance/" });
  }

  var STORAGE_VISITS = "gl_balance_visits";
  var STORAGE_DISMISSED = "gl_balance_install_dismissed";
  var VISITS_THRESHOLD = 3;

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true
    );
  }

  function isIosSafari() {
    var ua = window.navigator.userAgent;
    var isIos = /iphone|ipad|ipod/i.test(ua);
    var isSafari = /safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua);
    return isIos && isSafari;
  }

  function readVisits() {
    try {
      return parseInt(window.localStorage.getItem(STORAGE_VISITS) || "0", 10) || 0;
    } catch (e) {
      return 0; // приватный режим / localStorage заблокирован — баннер просто не покажется
    }
  }

  function bumpVisits() {
    var next = readVisits() + 1;
    try {
      window.localStorage.setItem(STORAGE_VISITS, String(next));
    } catch (e) { /* ignore */ }
    return next;
  }

  function wasDismissed() {
    try {
      return window.localStorage.getItem(STORAGE_DISMISSED) === "1";
    } catch (e) {
      return false;
    }
  }

  function markDismissed() {
    try {
      window.localStorage.setItem(STORAGE_DISMISSED, "1");
    } catch (e) { /* ignore */ }
  }

  var deferredPrompt = null;
  var visits = bumpVisits();

  var banner = document.getElementById("gl-balance-install-banner");
  var textEl = banner ? banner.querySelector("[data-role='text']") : null;
  var acceptBtn = banner ? banner.querySelector("[data-role='accept']") : null;
  var dismissBtn = banner ? banner.querySelector("[data-role='dismiss']") : null;

  function hideBanner() {
    if (banner) banner.hidden = true;
  }

  function showBanner(nativePromptAvailable) {
    if (!banner) return;
    if (nativePromptAvailable) {
      if (acceptBtn) acceptBtn.hidden = false;
      if (textEl) textEl.textContent = "Добавьте Развесовку на экран — быстрый доступ и офлайн на треке.";
    } else {
      if (acceptBtn) acceptBtn.hidden = true;
      if (textEl) textEl.textContent = "Добавьте Развесовку на экран: «Поделиться» → «На экран «Домой»».";
    }
    banner.hidden = false;
  }

  function maybeShowBanner() {
    if (isStandalone() || wasDismissed() || visits < VISITS_THRESHOLD) return;

    if (deferredPrompt) {
      showBanner(true);
    } else if (isIosSafari()) {
      showBanner(false);
    }
    // Остальные случаи (Android/desktop без beforeinstallprompt на этот
    // момент, либо браузер без поддержки установки) — показывать нечего.
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredPrompt = event;
    maybeShowBanner();
  });

  window.addEventListener("appinstalled", function () {
    markDismissed();
    hideBanner();
  });

  if (acceptBtn) {
    acceptBtn.addEventListener("click", function () {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      deferredPrompt.userChoice.finally(function () {
        deferredPrompt = null;
        hideBanner();
      });
    });
  }

  if (dismissBtn) {
    dismissBtn.addEventListener("click", function () {
      markDismissed();
      hideBanner();
    });
  }

  maybeShowBanner();
})();
