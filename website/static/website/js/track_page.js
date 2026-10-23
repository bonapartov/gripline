/* Страница трассы: переключение класса без перезагрузки (?class=<id>), выбор сектора
   (схема, фильтры, строки панели), режим 3D — загружается только по первому нажатию «3D».
   Блоки по классам заранее отрендерены сервером в <template id="glTrPanelTpl<id>"> и
   <template id="glTrStatsTpl<id>"> — JS только подставляет их. */
(function () {
  'use strict';
  var dataEl = document.getElementById('track-data');
  if (!dataEl) return;
  var DATA = JSON.parse(dataEl.textContent);
  var $ = function (id) { return document.getElementById(id); };
  var byId = {};
  DATA.classes.forEach(function (c) { byId[c.id] = c; });
  var state = { cls: byId[DATA.selected] || null, sector: -1, mode: 'top' };
  var COARSE = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  var NOTE_2D = 'Нажмите на сектор на схеме или на фильтр выше.';

  function hasSectors() { return !!(state.cls && state.cls.sectors_ms); }

  function fill(containerId, tplId) {
    var box = $(containerId), tpl = $(tplId);
    if (!box || !tpl) return;
    box.innerHTML = '';
    box.appendChild(tpl.content.cloneNode(true));
  }

  function setClass(id, push) {
    var c = byId[id];
    if (!c || c === state.cls) return;
    state.cls = c;
    state.sector = -1;
    fill('glTrPanel', 'glTrPanelTpl' + c.id);
    fill('glTrStats', 'glTrStatsTpl' + c.id);
    document.querySelectorAll('.gl-tr-chip').forEach(function (ch) {
      ch.setAttribute('aria-pressed', String(+ch.dataset.classId === c.id));
    });
    document.querySelectorAll('.gl-tr-records tr[data-class-id]').forEach(function (tr) {
      tr.classList.toggle('is-selected', +tr.dataset.classId === c.id);
    });
    if (push) {
      try {
        var url = new URL(window.location.href);
        url.searchParams.set('class', c.id);
        history.replaceState(null, '', url.pathname + url.search + url.hash);
      } catch (e) { /* старый браузер — адрес не меняем */ }
    }
    if (window.GlTrack3DInstance) window.GlTrack3DInstance.setClass(c);
    setSector(-1);
  }

  function setSector(k) {
    if (!hasSectors()) k = -1;
    state.sector = k;
    var on = hasSectors();
    document.querySelectorAll('#glTrFilters .gl-tr-filt').forEach(function (b) {
      b.disabled = !on;
      b.setAttribute('aria-pressed', String(+b.dataset.sector === k));
    });
    document.querySelectorAll('#glTrPanel [data-sector-view]').forEach(function (v) {
      v.hidden = +v.dataset.sectorView !== k;
    });
    var plate = $('glTrPlate');
    if (plate) {
      plate.classList.toggle('is-locked', !on);
      plate.querySelectorAll('path.sec').forEach(function (p) {
        var i = +p.dataset.s;
        p.style.opacity = k === -1 || k === i ? 1 : 0.18;
        p.setAttribute('stroke-width', k === i ? 18 : 14);
      });
    }
    if (window.GlTrack3DInstance) window.GlTrack3DInstance.setSector(k);
  }

  document.addEventListener('click', function (e) {
    var chip = e.target.closest('.gl-tr-chip');
    if (chip) { e.preventDefault(); setClass(+chip.dataset.classId, true); return; }
    var sec = e.target.closest('.gl-track [data-sector]');
    if (sec && !sec.disabled) { setSector(+sec.dataset.sector); return; }
    var path = e.target.closest('#glTrPlate .sec, #glTrPlate .sec-label');
    if (path && hasSectors()) { setSector(+path.dataset.s); return; }
    var mode = e.target.closest('#glTrModes button');
    if (mode) setMode(mode.dataset.mode);
  });

  // ── 3D ─────────────────────────────────────────────────────────────
  var btn3d = $('glTrBtn3d');
  var hasGL = (function () {
    try {
      var c = document.createElement('canvas');
      return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl')));
    } catch (e) { return false; }
  })();
  if (btn3d && hasGL && DATA.scheme && DATA.length_m) btn3d.hidden = false;

  var loading = null;
  function addScript(src) {
    return new Promise(function (ok, bad) {
      var s = document.createElement('script');
      s.src = src; s.onload = ok; s.onerror = bad;
      document.head.appendChild(s);
    });
  }
  function build(low) {
    return window.GlTrack3D.build({
      scheme: DATA.scheme, lengthM: DATA.length_m, low: low, onRebuild: rebuild
    });
  }
  function mountCurrent() {
    var inst = window.GlTrack3DInstance;
    inst.mount($('glTrHost3d'));
    inst.setClass(state.cls);
    inst.setSector(state.sector);
  }
  // Браузер отобрал WebGL-контекст (телефоны — нехватка видеопамяти, нагрев):
  // пересоздаём 3D целиком, уже в экономичном режиме.
  function rebuild() {
    var old = window.GlTrack3DInstance;
    window.GlTrack3DInstance = null;
    if (old) old.destroy();
    window.GlTrack3DInstance = build(true);
    if (state.mode === '3d') mountCurrent();
  }
  function load3d(cb) {
    if (window.GlTrack3DInstance) { cb(); return; }
    if (!loading) {
      var st = DATA.static;
      loading = addScript(st.three)
        .then(function () { return addScript(st.orbit); })
        .then(function () { return window.GlTrackGeom ? null : addScript(st.geom); })
        .then(function () { return addScript(st.module); })
        .then(function () { window.GlTrack3DInstance = build(false); });
    }
    loading.then(cb, function () {
      $('glTrHost3d').innerHTML = '<div class="gl-tr-v3d"><div class="gl-tr-v3d-msg"><span>Не удалось загрузить 3D. Проверьте соединение и попробуйте ещё раз.</span></div></div>';
      loading = null;
    });
  }
  function setMode(m) {
    var plate = $('glTrPlate'), host = $('glTrHost3d'), note = $('glTrStageNote');
    if (m === '3d') {
      if (!btn3d || btn3d.hidden) return;
      state.mode = '3d';
      plate.hidden = true; host.hidden = false;
      note.textContent = (COARSE ? 'Вращайте и приближайте двумя пальцами, одним — прокрутка страницы.' : 'Тяните — вращать, колесо — масштаб.') +
        ' Метка проезжает рекордный круг выбранного класса.';
      load3d(mountCurrent);
    } else {
      state.mode = 'top';
      if (plate) plate.hidden = false;
      if (host) host.hidden = true;
      if (note) note.textContent = NOTE_2D;
      if (window.GlTrack3DInstance) window.GlTrack3DInstance.pause();
    }
    document.querySelectorAll('#glTrModes button').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.mode === state.mode));
    });
  }

  setSector(-1);
})();
