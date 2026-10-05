/*
 * Согласие на cookie и условная загрузка Яндекс Метрики (152-ФЗ, Политика cookie /legal/cookies/).
 *
 * Выбор хранится в cookie gl_cookie_consent на ~180 дней: "all" (принял аналитику) или
 * "necessary" (только необходимые). Пока выбора нет или он "necessary" — скрипт Метрики
 * (и Вебвизор) НЕ загружается вообще, window.ym не существует. Это единственное место,
 * где грузится счётчик: base.html (сайт) и balance/app_base.html (/balance/).
 *
 * Управление на странице политики /legal/cookies/ (блок «Статистика посещений»):
 *   [data-cookie-switch] — переключатель «Учитывать мои визиты» (all <-> necessary);
 *   [data-cookie-status] — текст текущего состояния; [data-cookie-settings] — открыть плашку.
 * Ссылка «Настройки cookie» в подвале ведёт на /legal/cookies/#settings (этот блок).
 */
(function () {
  "use strict";

  var COOKIE = "gl_cookie_consent";
  var MAX_AGE = 60 * 60 * 24 * 180;
  var script = document.querySelector("script[data-ym-counter]");
  var COUNTER = script ? parseInt(script.getAttribute("data-ym-counter"), 10) : 0;
  var POLICY_URL = "/legal/cookies/";
  var banner = null;
  var metrikaLoaded = false;

  function readConsent() {
    var m = document.cookie.match(new RegExp("(?:^|; )" + COOKIE + "=([^;]*)"));
    var v = m ? decodeURIComponent(m[1]) : "";
    return v === "all" || v === "necessary" ? v : "";
  }

  function writeConsent(value) {
    var secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = COOKIE + "=" + value + "; Max-Age=" + MAX_AGE + "; Path=/; SameSite=Lax" + secure;
  }

  function loadMetrika() {
    if (metrikaLoaded || !COUNTER) return;
    metrikaLoaded = true;
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      k = e.createElement(t); a = e.getElementsByTagName(t)[0];
      k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, "script", "https://mc.yandex.ru/metrika/tag.js?id=" + COUNTER, "ym");
    window.ym(COUNTER, "init", {
      ssr: true, webvisor: true, clickmap: true, ecommerce: "dataLayer",
      referrer: document.referrer, url: location.href,
      accurateTrackBounce: true, trackLinks: true
    });
    window.__balanceYmCounter = COUNTER; // /balance/ шлёт цели reachGoal, только если счётчик реально поднят
  }

  // Cookie Метрики (_ym*, _ya*) стираем на хосте и на родительском домене.
  function purgeMetrikaCookies() {
    var host = location.hostname, parts = host.split(".");
    var domains = [host, "." + host];
    if (parts.length > 2) domains.push("." + parts.slice(-2).join("."));
    document.cookie.split(";").forEach(function (c) {
      var name = c.split("=")[0].trim();
      if (!/^_ym|^_ya/.test(name)) return;
      domains.forEach(function (d) {
        document.cookie = name + "=; Max-Age=0; Path=/; Domain=" + d;
      });
      document.cookie = name + "=; Max-Age=0; Path=/";
    });
  }

  function updateStatus() {
    var c = readConsent();
    var text = c === "all" ? "Аналитика включена: ваши визиты учитываются в статистике на этом устройстве."
      : c === "necessary" ? "Аналитика выключена: ваши визиты не попадают в статистику на этом устройстве."
      : "Аналитика сейчас выключена: вы не давали согласие на cookie.";
    [].forEach.call(document.querySelectorAll("[data-cookie-status]"), function (el) { el.textContent = text; });
    [].forEach.call(document.querySelectorAll("[data-cookie-switch]"), function (sw) {
      sw.setAttribute("aria-checked", c === "all" ? "true" : "false");
      var label = sw.querySelector("[data-cookie-switch-label]");
      if (label) label.textContent = c === "all" ? "Не учитывать меня" : "Учитывать мои визиты";
    });
  }

  function hideBanner() {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    banner = null;
  }

  function choose(value) {
    var hadAnalytics = metrikaLoaded || readConsent() === "all";
    writeConsent(value);
    hideBanner();
    if (value === "all") {
      loadMetrika();
    } else if (hadAnalytics) {
      // Уже запущенный счётчик остановить нельзя — чистим его cookie и перезагружаем страницу.
      purgeMetrikaCookies();
      location.reload();
      return;
    }
    updateStatus();
  }

  function button(label, cls, value) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "gl-cookie__btn " + cls;
    b.textContent = label;
    b.addEventListener("click", function () { choose(value); });
    return b;
  }

  function showBanner() {
    if (banner) return;
    banner = document.createElement("div");
    banner.className = "gl-cookie";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-label", "Настройки cookie");

    var text = document.createElement("p");
    text.className = "gl-cookie__text";
    text.appendChild(document.createTextNode(
      "Мы используем cookie: необходимые — для работы сайта (вход, защита форм), и Яндекс Метрику — для статистики, " +
      "включая запись действий на странице (Вебвизор). Статистика включается только с вашего согласия. "
    ));
    var link = document.createElement("a");
    link.href = POLICY_URL;
    link.textContent = "Подробнее";
    text.appendChild(link);

    var actions = document.createElement("div");
    actions.className = "gl-cookie__actions";
    actions.appendChild(button("Принять аналитику", "gl-cookie__btn--primary", "all"));
    actions.appendChild(button("Только необходимые", "gl-cookie__btn--ghost", "necessary"));

    banner.appendChild(text);
    banner.appendChild(actions);
    document.body.appendChild(banner);
  }

  document.addEventListener("click", function (e) {
    var sw = e.target.closest && e.target.closest("[data-cookie-switch]");
    if (sw) {
      e.preventDefault();
      choose(readConsent() === "all" ? "necessary" : "all");
      return;
    }
    var t = e.target.closest && e.target.closest("[data-cookie-settings]");
    if (!t) return;
    e.preventDefault();
    showBanner();
  });

  function init() {
    var consent = readConsent();
    if (consent === "all") loadMetrika();
    if (!consent) showBanner();
    updateStatus();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
