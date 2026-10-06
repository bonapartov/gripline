// Панель состояния бота обратной связи (Wagtail admin → Обратная связь → Настройки бота).
(function () {
  var panel = document.getElementById('feedbackBotPanel');
  if (!panel) return;
  var aliveEl = document.getElementById('feedbackBotAlive');
  var resultEl = document.getElementById('feedbackBotResult');

  function csrf() {
    var el = document.querySelector('input[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function refreshStatus() {
    fetch(panel.dataset.statusUrl, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.heartbeat_age_sec === null) {
          aliveEl.textContent = '⚪ Бот ещё ни разу не выходил на связь.';
        } else if (d.alive) {
          aliveEl.textContent = '🟢 Бот отвечал ' + d.heartbeat_age_sec + ' с назад.';
        } else {
          aliveEl.textContent = '🔴 Бот молчит: последний ответ ' + d.heartbeat_age_sec + ' с назад.';
        }
      })
      .catch(function () { aliveEl.textContent = 'Не удалось получить статус.'; });
  }

  var urls = {
    check: panel.dataset.checkUrl,
    test: panel.dataset.testUrl,
    restart: panel.dataset.restartUrl,
    topics: panel.dataset.topicsUrl,
    digest: panel.dataset.digestUrl
  };

  panel.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-feedback-action]');
    if (!btn) return;
    var action = btn.dataset.feedbackAction;
    if (action === 'restart' && !window.confirm('Перезапустить бота?')) return;
    btn.disabled = true;
    resultEl.textContent = 'Выполняю…';
    fetch(urls[action], {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf() }
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { resultEl.textContent = (d.ok ? '✅ ' : '❌ ') + d.message; })
      .catch(function () { resultEl.textContent = '❌ Запрос не выполнен.'; })
      .then(function () { btn.disabled = false; refreshStatus(); });
  });

  refreshStatus();
  setInterval(refreshStatus, 15000);
})();
