// Виджет «Обратная связь»: открыть/закрыть окно + цели Яндекс.Метрики (только если Метрика
// загружена — т.е. посетитель дал согласие на аналитику, см. cookie-consent.js).
(function () {
  var root = document.getElementById('glFeedback');
  if (!root) return;
  var toggle = document.getElementById('glFeedbackToggle');
  var panel = document.getElementById('glFeedbackPanel');
  var COUNTER = 108405016;

  function goal(name, params) {
    try { if (typeof window.ym === 'function') window.ym(COUNTER, 'reachGoal', name, params); } catch (e) {}
  }

  // Страница рейтинга меняет класс без перезагрузки (pushState ?class=ID) — пересобираем ссылки
  // с контекстом в момент открытия, иначе они указывали бы на класс, открытый при загрузке.
  function refreshLinks() {
    var m = location.search.match(/[?&]class=(\d+)/);
    if (!m) return;
    panel.querySelectorAll('[data-fb-template]').forEach(function (a) {
      a.href = a.getAttribute('data-fb-template').replace('{id}', m[1]);
    });
  }

  function setOpen(open) {
    if (open) refreshLinks();
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) goal('feedback_widget_open');
  }

  toggle.addEventListener('click', function () { setOpen(panel.hidden); });
  root.querySelector('[data-fb-close]').addEventListener('click', function () { setOpen(false); toggle.focus(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden) { setOpen(false); toggle.focus(); }
  });
  document.addEventListener('click', function (e) {
    if (!panel.hidden && !root.contains(e.target)) setOpen(false);
  });
  panel.addEventListener('click', function (e) {
    var link = e.target.closest('[data-fb-category]');
    if (link) goal('feedback_widget_click', { category: link.getAttribute('data-fb-category') });
  });
})();
