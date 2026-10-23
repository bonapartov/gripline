/* Редактор схемы трассы (админка → Трассы → «Редактор схемы»). Чистый JS + SVG.
   Координаты — поле схемы: ширина 640, высота по форме трассы (240–480). На сервер уходят
   только числа (track_scheme_views.editor_save), SVG для сайта сервер строит сам.
   Геометрия (сплайн, доли длины) — track_scheme_geom.js, та же, что у 3D и у Python.
   ТЗ: gripline_tz_track_page_v1.md, раздел 7 + дополнение №1 (импорт/экспорт, OSM, поле, поворот,
   ширина полотна, черновик). */
(function () {
  'use strict';
  var G = window.GlTrackGeom;
  var root = document.getElementById('tse');
  if (!root || !G) return;
  var NS = 'http://www.w3.org/2000/svg';
  var W = 640, H_MIN = 240, H_MAX = 480, PAD_X = 46, PAD_TOP = 46, PAD_BOTTOM = 70;
  var SHARP_DEG = 35, KART_MIN_RADIUS_M = 5, MARK_SNAP = 24, MARK_TOL = 3, EARTH_R = 6371008.8;
  var SEC_COLORS = ['#ffc107', '#0dcaf0', '#28a745'];
  var PROV_LABELS = { start: 'Старт/финиш', s1s2: 'Граница S1|S2', s2s3: 'Граница S2|S3', track_width_m: 'Ширина полотна', turns: 'Повороты', direction: 'Направление движения' };
  var INIT = JSON.parse(document.getElementById('tse-data').textContent);
  var $ = function (id) { return document.getElementById(id); };
  var canvas = $('tseCanvas');
  var csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';

  function blank() {
    return {
      viewBox: [0, 0, W, 400], interpolation: 'centripetal-catmull-rom', points: [], tension: 1,
      start: null, s1s2: null, s2s3: null, turns: [], sector_labels: [], reference: null,
      source: { type: 'manual' }, rotation_deg: 0, scale_m_per_unit: null, track_width_m: 9,
      provisional: [], publish_draft: false
    };
  }
  function fromData(d) {
    var st = blank();
    if (!d) return st;
    Object.keys(st).forEach(function (k) { if (d[k] !== undefined && d[k] !== null) st[k] = JSON.parse(JSON.stringify(d[k])); });
    if (!d.interpolation) st.interpolation = 'catmull-rom';
    st.turns = (st.turns || []).map(function (t) { return { n: String(t.n), x: +t.x, y: +t.y }; });
    return st;
  }
  var state = fromData(INIT.scheme);
  var tool = 'points', sel = null, drag = null, undo = [], dirty = false, autoLabels = null, lastPreview = '';
  var refImg = { url: INIT.has_reference ? root.dataset.referenceUrl + '?t=' + Date.now() : null, w: 0, h: 0 };

  var HINTS = {
    points: 'Клик по пустому месту — новая точка в конец линии (по направлению движения). Клик по линии — вставить точку. Тяните точку, чтобы сдвинуть; Delete — удалить выбранную. Жёлтая — первая точка.',
    start: 'Клик по линии — поставить старт/финиш. Метку можно тянуть вдоль линии.',
    s1s2: 'Клик по линии — граница сектора S1|S2.',
    s2s3: 'Клик по линии — граница сектора S2|S3.',
    turns: 'Клик рядом с линией — новый поворот. Тяните, чтобы сдвинуть; Delete — удалить выбранный; номер — справа. «Пронумеровать по порядку» — 1…N от старта.',
    labels: 'Тяните плашки S1/S2/S3, чтобы поправить их положение. Двойной клик — вернуть автоматическое (у линии своего сектора).',
    reference: 'Тяните подложку мышью. Масштаб, поворот и прозрачность — справа.'
  };

  function H() { return state.viewBox[3]; }
  function snapshot() { return JSON.stringify(state); }
  function pushUndo() { undo.push(snapshot()); if (undo.length > 100) undo.shift(); dirty = true; }
  function confirmProv(key) { var i = state.provisional.indexOf(key); if (i >= 0) state.provisional.splice(i, 1); }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function toSvg(evt) {
    var pt = canvas.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    var p = pt.matrixTransform(canvas.getScreenCTM().inverse());
    return [p.x, p.y];
  }
  function poly() { return state.points.length >= 3 ? G.fromScheme(state) : null; }
  function round1(v) { return Math.round(v * 10) / 10; }
  function round5(v) { return Math.round(v * 100000) / 100000; }
  function marksSet() { return state.start != null && state.s1s2 != null && state.s2s3 != null; }
  function scaleMPU() {
    if (state.scale_m_per_unit) return state.scale_m_per_unit;
    var p = poly();
    return p && INIT.length_m ? INIT.length_m / p.length : null;
  }
  function widths() {
    var sc = scaleMPU();
    if (!sc) return [30, 14];
    var w = Math.max(4, Math.min(60, (state.track_width_m || 9) / sc));
    return [w, Math.max(4.5, w * 0.45)];
  }

  // ── Проверки ────────────────────────────────────────────────────────
  /* «Резкий угол — карт так не поворачивает»: при известном масштабе — радиус сглаженной линии у опорной
     точки меньше KART_MIN_RADIUS_M (на плотных точках OSM угол между отрезками в шпильке всегда велик,
     а сама кривая нормальная); без масштаба — поворот направления в узле больше SHARP_DEG */
  var sharpMemo = { key: null, value: {} };
  function sharpIndexes() {
    var key = JSON.stringify([state.points, state.tension, state.interpolation, state.scale_m_per_unit, INIT.length_m]);
    if (sharpMemo.key !== key) sharpMemo = { key: key, value: computeSharp() };
    return sharpMemo.value;
  }
  function computeSharp() {
    var n = state.points.length, out = {}, p = poly(), sc = scaleMPU();
    if (n < 3) return out;
    if (p && sc) {
      var R = radii(p, sc);
      for (var q = 0; q < n; q++) {
        var at = Math.round(p.cum[q * G.SAMPLES_PER_SEGMENT] / p.length * R.M) % R.M, rmin = Infinity;
        for (var d = -2; d <= 2; d++) rmin = Math.min(rmin, R.r[(at + d + R.M) % R.M]);
        if (rmin < KART_MIN_RADIUS_M) out[q] = true;
      }
      return out;
    }
    for (var i = 0; i < n; i++) {
      var a = state.points[(i - 1 + n) % n], b = state.points[i], c = state.points[(i + 1) % n];
      var u = [b[0] - a[0], b[1] - a[1]], v = [c[0] - b[0], c[1] - b[1]];
      var lu = Math.hypot(u[0], u[1]), lv = Math.hypot(v[0], v[1]);
      if (!lu || !lv) { out[i] = true; continue; }
      var cos = Math.max(-1, Math.min(1, (u[0] * v[0] + u[1] * v[1]) / (lu * lv)));
      if (Math.acos(cos) * 180 / Math.PI > SHARP_DEG) out[i] = true;
    }
    return out;
  }
  /* Места, где два участка трассы ближе ширины полотна + 2 м (часто — ошибка обводки), Д5 */
  var closeMemo = { key: null, value: [] };
  function closeSpots() {
    var key = JSON.stringify([state.points, state.tension, state.interpolation, state.track_width_m, state.scale_m_per_unit, INIT.length_m]);
    if (closeMemo.key !== key) closeMemo = { key: key, value: computeCloseSpots() };
    return closeMemo.value;
  }
  function computeCloseSpots() {
    var p = poly(), sc = scaleMPU();
    if (!p || !sc) return [];
    var thr = ((state.track_width_m || 9) + 2) / sc, step = Math.max(2, thr / 3), M = Math.ceil(p.length / step), pts = [];
    if (M > 1500) M = 1500;
    for (var i = 0; i < M; i++) pts.push(p.pointAt(i / M));
    var minArc = Math.ceil(thr * 4 / (p.length / M)), out = [];
    for (i = 0; i < M; i++) {
      for (var j = i + minArc; j < M; j++) {
        if (M - (j - i) < minArc) break;
        if (Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) < thr) {
          var mid = [(pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2];
          if (!out.some(function (q) { return Math.hypot(q[0] - mid[0], q[1] - mid[1]) < thr * 3; })) out.push(mid);
        }
      }
    }
    return out;
  }
  function warnings() {
    var w = [], n = state.points.length;
    if (n < 3) { w.push(['bad', 'Нужно хотя бы 3 точки линии']); return w; }
    var sharp = Object.keys(sharpIndexes()).length;
    if (sharp) w.push(['bad', 'Резкий угол — карт так не поворачивает (точек: ' + sharp + ', красные). Добавьте точки или сгладьте. Сохранить можно.']);
    var drawn = G.drawnDirection(state.points);
    if (INIT.direction) {
      if (drawn !== INIT.direction) w.push(['bad', 'Линия нарисована ' + (drawn === 'cw' ? 'по часовой' : 'против часовой') + ', а в карточке трассы — ' + (INIT.direction === 'cw' ? 'по часовой' : 'против часовой') + '. Нажмите «Развернуть направление» или поправьте карточку.']);
      else w.push(['ok', 'Направление совпадает с карточкой трассы']);
    } else {
      w.push(['', 'В карточке трассы не указано направление — проверить нельзя (нарисовано ' + (drawn === 'cw' ? 'по часовой' : 'против часовой') + ')']);
    }
    ['start', 's1s2', 's2s3'].forEach(function (k) { if (state[k] == null) w.push(['bad', 'Не отмечено: ' + PROV_LABELS[k]]); });
    if (marksSet()) {
      var l1 = G.mod1(state.s1s2 - state.start), l2 = G.mod1(state.s2s3 - state.start);
      if (!(l1 > 0 && l1 < l2 && l2 < 1)) w.push(['bad', 'Порядок по направлению движения должен быть: старт → S1|S2 → S2|S3 → старт']);
    }
    var lw = lengthWarning();
    if (lw) w.push(['bad', lw]);
    if (H() >= H_MAX && n >= 3) {
      var pb = poly(), ys = pb.pts.map(function (q) { return q[1]; }), xs = pb.pts.map(function (q) { return q[0]; });
      if (Math.max.apply(null, ys) - Math.min.apply(null, ys) > (Math.max.apply(null, xs) - Math.min.apply(null, xs)) * 0.9)
        w.push(['bad', 'Трасса вытянута по высоте — поверните схему на 90° («⟲ 90°» / «⟳ 90°»), чтобы она легла горизонтально']);
    }
    var close = closeSpots();
    if (close.length) w.push(['bad', 'Участки трассы ближе, чем ширина полотна + 2 м (мест: ' + close.length + ', обведены красным) — проверьте обводку']);
    if (!INIT.length_m) w.push(['', 'В карточке трассы не указана длина — 3D на сайте не покажется']);
    return w;
  }
  function lengthWarning() {
    var p = poly();
    if (!p || !state.scale_m_per_unit || !INIT.length_m) return '';
    var measured = p.length * state.scale_m_per_unit, diff = Math.abs(measured - INIT.length_m) / INIT.length_m;
    return diff > 0.03 ? 'Длина по схеме ' + Math.round(measured) + ' м расходится с длиной в карточке (' + INIT.length_m + ' м) на ' + (diff * 100).toFixed(1) + ' %' : '';
  }

  // ── Отрисовка ───────────────────────────────────────────────────────
  function labelPos(i, p) {
    var custom = state.sector_labels.filter(function (l) { return l.s === i; })[0];
    if (custom) return custom;
    if (autoLabels && autoLabels[i]) return autoLabels[i];
    var fr = [state.start, state.s1s2, state.s2s3][i] + 0.03, q = p.pointAt(fr), nn = p.outwardNormal(fr), off = widths()[0] / 2 + 16;
    return { x: q[0] + nn[0] * off, y: q[1] + nn[1] * off };
  }
  function render() {
    canvas.setAttribute('viewBox', '0 0 ' + W + ' ' + H());
    canvas.innerHTML = '';
    el('rect', { x: 0, y: 0, width: W, height: H(), fill: '#0d0d15' }, canvas);
    if (refImg.url && state.reference) {
      var r = state.reference;
      var img = el('image', {
        href: refImg.url, x: 0, y: 0, width: refImg.w || W, height: refImg.h || H(), opacity: r.opacity, preserveAspectRatio: 'none',
        transform: 'translate(' + r.x + ',' + r.y + ') rotate(' + r.rotate + ',' + (refImg.w / 2 * r.scale) + ',' + (refImg.h / 2 * r.scale) + ') scale(' + r.scale + ')',
        'class': 'tse-ref'
      }, canvas);
      img.style.pointerEvents = tool === 'reference' ? 'auto' : 'none';
    }
    var p = poly(), wd = widths();
    if (p) {
      var d = G.pathD(state.points, state.tension, state.interpolation);
      el('path', { d: d, fill: 'none', stroke: '#2a2a35', 'stroke-width': wd[0], 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'pointer-events': 'none' }, canvas);
      if (marksSet()) {
        [[state.start, state.s1s2], [state.s1s2, state.s2s3], [state.s2s3, state.start]].forEach(function (ab, i) {
          var pts = p.between(ab[0], ab[1]);
          el('path', { d: 'M' + pts.map(function (q) { return round1(q[0]) + ',' + round1(q[1]); }).join(' L'), fill: 'none', stroke: SEC_COLORS[i], 'stroke-width': wd[1], 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'pointer-events': 'none' }, canvas);
        });
      } else {
        el('path', { d: d, fill: 'none', stroke: '#b0bec5', 'stroke-width': 2, 'pointer-events': 'none' }, canvas);
      }
      el('path', { d: d, 'class': 'tse-hit', 'data-hit': 'line', 'stroke-width': Math.max(18, wd[0]) }, canvas);
      for (var k = 1; k <= 8; k++) {
        var f = k / 8 - 0.0625, q = p.pointAt(f), t = p.tangentAt(f);
        var tip = [q[0] + t[0] * 6, q[1] + t[1] * 6], n = [-t[1], t[0]];
        el('path', { d: 'M' + round1(tip[0] - t[0] * 9 + n[0] * 4.5) + ',' + round1(tip[1] - t[1] * 9 + n[1] * 4.5) + ' L' + round1(tip[0]) + ',' + round1(tip[1]) + ' L' + round1(tip[0] - t[0] * 9 - n[0] * 4.5) + ',' + round1(tip[1] - t[1] * 9 - n[1] * 4.5), fill: 'none', stroke: '#ffffff', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'pointer-events': 'none' }, canvas);
      }
      [['start', '#ffffff', 'СТАРТ'], ['s1s2', SEC_COLORS[1], 'S1|S2'], ['s2s3', SEC_COLORS[2], 'S2|S3']].forEach(function (m) {
        if (state[m[0]] == null) return;
        var q = p.pointAt(state[m[0]]), t = p.tangentAt(state[m[0]]), n = [-t[1], t[0]], half = wd[0] / 2 + 6;
        var g = el('g', { 'class': 'tse-mark', 'data-mark': m[0] }, canvas);
        el('line', { x1: round1(q[0] - n[0] * half), y1: round1(q[1] - n[1] * half), x2: round1(q[0] + n[0] * half), y2: round1(q[1] + n[1] * half), stroke: m[1], 'stroke-width': 4, 'data-mark': m[0] }, g);
        var lab = p.outwardNormal(state[m[0]]);  // подпись внутрь — снаружи стоят плашки S1–S3
        var txt = m[2] + (state.provisional.indexOf(m[0]) >= 0 ? ' ?' : '');
        el('text', { x: round1(q[0] - lab[0] * (half + 14)), y: round1(q[1] - lab[1] * (half + 14) + 4), fill: m[1], 'font-size': 11, 'font-weight': 800, 'text-anchor': 'middle', 'data-mark': m[0] }, g).textContent = txt;
      });
      if (marksSet()) {
        [0, 1, 2].forEach(function (i) {
          var pos = labelPos(i, p);
          var g = el('g', { 'class': 'tse-label', 'data-label': i }, canvas);
          el('rect', { x: round1(pos.x - 16), y: round1(pos.y - 9), width: 32, height: 18, rx: 9, fill: SEC_COLORS[i], 'data-label': i, opacity: tool === 'labels' ? 1 : 0.85 }, g);
          el('text', { x: round1(pos.x), y: round1(pos.y + 4), fill: i === 2 ? '#fff' : '#1a1a25', 'font-size': 11, 'font-weight': 800, 'text-anchor': 'middle', 'pointer-events': 'none' }, g).textContent = 'S' + (i + 1);
        });
      }
      closeSpots().forEach(function (c) { el('circle', { cx: round1(c[0]), cy: round1(c[1]), r: 14, 'class': 'tse-close' }, canvas); });
    } else if (state.points.length === 2) {
      el('line', { x1: state.points[0][0], y1: state.points[0][1], x2: state.points[1][0], y2: state.points[1][1], stroke: '#b0bec5', 'stroke-width': 3 }, canvas);
    }
    state.turns.forEach(function (t, i) {
      var g = el('g', { 'class': 'tse-turn' + (sel && sel.type === 'turn' && sel.i === i ? ' is-sel' : ''), 'data-turn': i }, canvas);
      el('circle', { cx: t.x, cy: t.y, r: String(t.n).length > 2 ? 12 : 10, 'data-turn': i }, g);
      el('text', { x: t.x, y: t.y + 3.5 }, g).textContent = t.n;
    });
    var sharp = sharpIndexes(), many = state.points.length > 150;
    state.points.forEach(function (pt, i) {
      var c = el('circle', { cx: pt[0], cy: pt[1], r: tool === 'points' ? (many ? 3 : 5) : 2.5, 'data-pt': i,
        'class': 'tse-pt' + (i === 0 ? ' is-first' : '') + (sharp[i] ? ' is-sharp' : '') + (sel && sel.type === 'pt' && sel.i === i ? ' is-sel' : '') }, canvas);
      if (tool !== 'points') c.style.pointerEvents = 'none';
    });
    renderSide();
    schedulePreview();
  }

  function renderSide() {
    $('tseWarnings').innerHTML = warnings().map(function (w) { return '<li class="' + (w[0] === 'bad' ? 'is-bad' : w[0] === 'ok' ? 'is-ok' : '') + '">' + esc(w[1]) + '</li>'; }).join('');
    var p = poly(), sc = scaleMPU();
    $('tseScale').textContent = p && sc ? 'Масштаб: 1 ед. = ' + sc.toFixed(3) + ' м · длина по схеме ' + Math.round(p.length * sc) + ' м' + (INIT.length_m ? ' (в карточке ' + INIT.length_m + ' м)' : '') : 'Масштаб неизвестен: укажите длину трассы в карточке или импортируйте из OpenStreetMap';
    $('tseTension').value = state.tension;
    $('tseTrackWidth').value = state.track_width_m;
    var turnSel = sel && sel.type === 'turn';
    $('tseTurnNumWrap').hidden = !turnSel;
    if (turnSel && document.activeElement !== $('tseTurnNum')) $('tseTurnNum').value = state.turns[sel.i].n;
    $('tseRefControls').hidden = !(refImg.url && state.reference);
    if (state.reference) {
      $('tseRefOpacity').value = state.reference.opacity;
      $('tseRefScale').value = Math.log(state.reference.scale);
      $('tseRefRotate').value = state.reference.rotate;
    }
    var prov = state.provisional;
    $('tseProvBox').hidden = !prov.length;
    $('tseProv').innerHTML = prov.map(function (k) { return '<li><span>' + esc(PROV_LABELS[k] || k) + '</span><button type="button" class="button button-small button-secondary" data-confirm="' + k + '">Подтверждаю</button></li>'; }).join('');
    $('tsePublishDraftWrap').hidden = !prov.length;
    $('tsePublishDraft').checked = !!state.publish_draft;
    $('tseSourceOsm').checked = !!(state.source && state.source.type === 'osm');
    $('tseHint').textContent = HINTS[tool];
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  /* Автоматические плашки S1–S3 считает сервер (track_scheme.label_positions) — одна логика с сайтом */
  var previewTimer = null;
  function schedulePreview() {
    if (!marksSet() || state.points.length < 3) return;
    var body = JSON.stringify(payload());
    if (body === lastPreview) return;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(function () {
      lastPreview = body;
      post(root.dataset.previewUrl, JSON.parse(body)).then(function (res) {
        if (!res[0] || body !== lastPreview) return;
        autoLabels = {};
        res[1].labels.forEach(function (l) { autoLabels[l.s] = l; });
        render();
      }, function () {});
    }, 500);
  }

  // ── Мышь / палец ────────────────────────────────────────────────────
  function segmentOf(frac) { return Math.floor(poly().locate(frac)[0] / G.SAMPLES_PER_SEGMENT); }
  canvas.addEventListener('pointerdown', function (e) {
    var xy = toSvg(e), t = e.target, p = poly();
    canvas.setPointerCapture(e.pointerId);
    if (tool === 'points') {
      if (t.dataset.pt != null) { pushUndo(); sel = { type: 'pt', i: +t.dataset.pt }; drag = { type: 'pt', i: +t.dataset.pt }; render(); return; }
      if (t.dataset.hit === 'line' && p) {
        pushUndo();
        var at = segmentOf(p.project(xy[0], xy[1]).frac) + 1, keep = markXY();
        state.points.splice(at, 0, [round1(xy[0]), round1(xy[1])]);
        restoreMarks(keep);
        sel = { type: 'pt', i: at }; drag = { type: 'pt', i: at }; render(); return;
      }
      pushUndo();
      state.points.push([round1(xy[0]), round1(xy[1])]);
      sel = { type: 'pt', i: state.points.length - 1 }; drag = { type: 'pt', i: sel.i }; render(); return;
    }
    if ((tool === 'start' || tool === 's1s2' || tool === 's2s3') && p) {
      var pr = p.project(xy[0], xy[1]);
      if (t.dataset.mark || pr.dist < MARK_SNAP) {
        var key = t.dataset.mark || tool;
        pushUndo(); state[key] = round5(pr.frac); confirmProv(key); drag = { type: 'mark', key: key }; render();
      }
      return;
    }
    if (tool === 'turns') {
      if (t.dataset.turn != null) { pushUndo(); sel = { type: 'turn', i: +t.dataset.turn }; drag = { type: 'turn', i: sel.i }; render(); return; }
      pushUndo();
      var nmax = state.turns.reduce(function (m, x) { var v = parseInt(x.n, 10); return isNaN(v) ? m : Math.max(m, v); }, 0);
      state.turns.push({ n: String(nmax + 1), x: round1(xy[0]), y: round1(xy[1]) });
      confirmProv('turns');
      sel = { type: 'turn', i: state.turns.length - 1 }; drag = { type: 'turn', i: sel.i }; render(); return;
    }
    if (tool === 'labels' && t.dataset.label != null) { pushUndo(); drag = { type: 'label', s: +t.dataset.label }; return; }
    if (tool === 'reference' && state.reference) { pushUndo(); drag = { type: 'ref', from: xy, x: state.reference.x, y: state.reference.y }; }
  });
  canvas.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var xy = toSvg(e);
    if (drag.type === 'pt') state.points[drag.i] = [round1(xy[0]), round1(xy[1])];
    else if (drag.type === 'mark') state[drag.key] = round5(poly().project(xy[0], xy[1]).frac);
    else if (drag.type === 'turn') { state.turns[drag.i].x = round1(xy[0]); state.turns[drag.i].y = round1(xy[1]); }
    else if (drag.type === 'label') {
      state.sector_labels = state.sector_labels.filter(function (l) { return l.s !== drag.s; });
      state.sector_labels.push({ s: drag.s, x: round1(xy[0]), y: round1(xy[1]) });
    } else if (drag.type === 'ref') {
      state.reference.x = round1(drag.x + xy[0] - drag.from[0]);
      state.reference.y = round1(drag.y + xy[1] - drag.from[1]);
    }
    render();
  });
  ['pointerup', 'pointercancel'].forEach(function (ev) { canvas.addEventListener(ev, function () { drag = null; }); });
  canvas.addEventListener('dblclick', function (e) {
    if (tool === 'labels' && e.target.dataset.label != null) {
      pushUndo();
      var s = +e.target.dataset.label;
      state.sector_labels = state.sector_labels.filter(function (l) { return l.s !== s; });
      render();
    }
  });

  function deleteSelected() {
    if (!sel) return;
    pushUndo();
    if (sel.type === 'pt') {
      var keep = markXY();
      state.points.splice(sel.i, 1);
      restoreMarks(keep);
    } else if (sel.type === 'turn') state.turns.splice(sel.i, 1);
    sel = null; render();
  }
  function markXY() {
    var p = poly(), out = {};
    if (!p) return out;
    ['start', 's1s2', 's2s3'].forEach(function (k) { if (state[k] != null) out[k] = p.pointAt(state[k]); });
    return out;
  }
  function restoreMarks(xy) {
    var p = poly();
    ['start', 's1s2', 's2s3'].forEach(function (k) {
      if (xy[k] && p) state[k] = round5(p.project(xy[k][0], xy[k][1]).frac);
      else if (!p) state[k] = null;
    });
  }

  document.addEventListener('keydown', function (e) {
    if (e.target.closest('input, select, textarea')) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { if (sel) { e.preventDefault(); deleteSelected(); } }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); doUndo(); }
  });
  function doUndo() { if (!undo.length) return; state = JSON.parse(undo.pop()); sel = null; render(); }

  // ── Поле схемы и поворот (Д3, Д4) ──────────────────────────────────
  /* Ширина 640, высота по форме трассы: габарит + поля 46/46 по бокам и сверху, 70 снизу; 240…480 */
  function fitView() {
    var p = poly();
    if (!p) return;
    var xs = p.pts.map(function (q) { return q[0]; }), ys = p.pts.map(function (q) { return q[1]; });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs), minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var bw = (maxX - minX) || 1, bh = (maxY - minY) || 1;
    var k = (W - 2 * PAD_X) / bw, h = bh * k + PAD_TOP + PAD_BOTTOM;
    if (h > H_MAX) { k = (H_MAX - PAD_TOP - PAD_BOTTOM) / bh; h = H_MAX; }
    h = Math.max(H_MIN, Math.round(h));
    var ox = (W - bw * k) / 2, oy = PAD_TOP + ((h - PAD_TOP - PAD_BOTTOM) - bh * k) / 2;
    transformAll(function (x, y) { return [ox + (x - minX) * k, oy + (y - minY) * k]; }, k, 0);
    state.viewBox = [0, 0, W, h];
  }
  /* Применить преобразование (сдвиг/масштаб k/поворот rot°) к линии, поворотам, плашкам и подложке */
  function transformAll(fn, k, rot) {
    state.points = state.points.map(function (q) { var r = fn(q[0], q[1]); return [round1(r[0]), round1(r[1])]; });
    state.turns.forEach(function (t) { var r = fn(t.x, t.y); t.x = round1(r[0]); t.y = round1(r[1]); });
    state.sector_labels.forEach(function (l) { var r = fn(l.x, l.y); l.x = round1(r[0]); l.y = round1(r[1]); });
    if (state.reference && refImg.w) {
      var rf = state.reference, cx = rf.x + refImg.w * rf.scale / 2, cy = rf.y + refImg.h * rf.scale / 2, c = fn(cx, cy);
      rf.scale = round5(rf.scale * k);
      rf.rotate = round1(((rf.rotate + rot + 540) % 360) - 180);
      rf.x = round1(c[0] - refImg.w * rf.scale / 2); rf.y = round1(c[1] - refImg.h * rf.scale / 2);
    }
    if (state.scale_m_per_unit) state.scale_m_per_unit = round5(state.scale_m_per_unit / k);
    autoLabels = null;
  }
  function rotateAll(deg) {
    var a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), cx = W / 2, cy = H() / 2;
    transformAll(function (x, y) { return [cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c]; }, 1, deg);
    state.rotation_deg = round1((state.rotation_deg || 0) + deg);
    fitView();
  }
  $('tseRotL').addEventListener('click', function () { if (poly()) { pushUndo(); rotateAll(-90); render(); } });
  $('tseRotR').addEventListener('click', function () { if (poly()) { pushUndo(); rotateAll(90); render(); } });
  $('tseFit').addEventListener('click', function () { if (poly()) { pushUndo(); fitView(); render(); } });
  var fineBase = null;
  $('tseRotFine').addEventListener('pointerdown', function () { if (poly()) { pushUndo(); fineBase = snapshot(); } });
  $('tseRotFine').addEventListener('input', function (e) {
    if (!fineBase) return;
    state = JSON.parse(fineBase);
    rotateAll(+e.target.value);
    render();
  });
  $('tseRotFine').addEventListener('change', function (e) { fineBase = null; e.target.value = 0; });

  // ── Панель справа ───────────────────────────────────────────────────
  root.querySelectorAll('.tse-tool').forEach(function (b) {
    b.addEventListener('click', function () {
      tool = b.dataset.tool; sel = null;
      root.querySelectorAll('.tse-tool').forEach(function (x) { x.classList.toggle('is-on', x === b); });
      render();
    });
  });
  $('tseUndo').addEventListener('click', doUndo);
  $('tseDelete').addEventListener('click', deleteSelected);
  $('tseTension').addEventListener('pointerdown', pushUndo);
  $('tseTension').addEventListener('input', function (e) {
    var keep = markXY();
    state.tension = +e.target.value; restoreMarks(keep); render();
  });
  $('tseTrackWidth').addEventListener('change', function (e) {
    var v = parseFloat(e.target.value);
    if (v >= 2 && v <= 40) { pushUndo(); state.track_width_m = v; confirmProv('track_width_m'); render(); }
  });
  $('tseReverse').addEventListener('click', function () {
    if (state.points.length < 3) return;
    pushUndo();
    var keep = markXY();
    state.points.reverse();
    restoreMarks(keep);
    // по новому направлению границы идут в обратном порядке
    var a = state.s1s2; state.s1s2 = state.s2s3; state.s2s3 = a;
    state.sector_labels = []; autoLabels = null;
    if (state.source && state.source.type === 'osm') state.source.reversed = !state.source.reversed;
    // автоматически найденные повороты (ещё не подтверждены) — сразу 1…N по новому направлению
    if (state.provisional.indexOf('turns') >= 0) renumberTurns();
    confirmProv('direction');
    render();
  });
  /* 1…N по ходу движения от старта — по ближайшей точке линии к маркеру (Д8) */
  function renumberTurns() {
    var p = poly(), st = state.start || 0;
    if (!p) return;
    state.turns.sort(function (a, b) { return G.mod1(p.project(a.x, a.y).frac - st) - G.mod1(p.project(b.x, b.y).frac - st); });
    state.turns.forEach(function (t, i) { t.n = String(i + 1); });
  }
  $('tseRenumber').addEventListener('click', function () {
    if (!poly() || !state.turns.length) return;
    pushUndo(); renumberTurns(); sel = null; render();
  });
  $('tseTurnNum').addEventListener('change', function (e) {
    if (!(sel && sel.type === 'turn')) return;
    var v = e.target.value.trim();
    if (v && v.length <= 4) { pushUndo(); state.turns[sel.i].n = v; render(); }
  });
  $('tseProv').addEventListener('click', function (e) {
    var b = e.target.closest('[data-confirm]');
    if (b) { pushUndo(); confirmProv(b.dataset.confirm); render(); }
  });
  $('tsePublishDraft').addEventListener('change', function (e) { state.publish_draft = e.target.checked; dirty = true; });
  $('tseSourceOsm').addEventListener('change', function (e) {
    pushUndo();
    if (e.target.checked) state.source = Object.assign({}, state.source, { type: 'osm' });
    else state.source = { type: 'manual' };
    render();
  });

  // ── Импорт / экспорт JSON (Д1) ─────────────────────────────────────
  function showImport(errors, okText) {
    $('tseImportErrors').innerHTML = errors.map(function (x) { return '<li class="is-bad">' + esc(x) + '</li>'; }).join('') +
      (okText ? '<li class="is-ok">' + esc(okText) + '</li>' : '');
  }
  function importJson(d) {
    var errors = [];
    if (!d || typeof d !== 'object') return ['Файл не похож на схему (ожидается объект JSON)'];
    var vb = Array.isArray(d.viewBox) && d.viewBox.length === 4 ? d.viewBox.map(Number) : [0, 0, W, 400];
    if (vb[2] !== W || vb[3] < H_MIN || vb[3] > H_MAX) errors.push('viewBox: ширина должна быть 640, высота 240–480');
    var pts = Array.isArray(d.points) ? d.points : [];
    if (pts.length < 8) errors.push('Опорных точек меньше 8 (в файле ' + pts.length + ')');
    var outside = pts.filter(function (q) { return !Array.isArray(q) || !(q[0] >= 0 && q[0] <= vb[2] && q[1] >= 0 && q[1] <= vb[3]); }).length;
    if (outside) errors.push('Точек вне поля схемы: ' + outside);
    if (errors.length) return errors;
    var st = fromData(d);
    st.viewBox = [0, 0, W, vb[3]];
    st.points = pts.map(function (q) { return [+q[0], +q[1]]; });
    var p = G.fromScheme(st);
    ['start', 's1s2', 's2s3'].forEach(function (k) {
      if (typeof d[k] === 'number') { st[k] = G.mod1(d[k]); return; }
      var xy = d[k + '_xy'];
      if (!Array.isArray(xy)) { errors.push('Не задано: ' + PROV_LABELS[k]); return; }
      var pr = p.project(+xy[0], +xy[1]);
      if (pr.dist > MARK_TOL) errors.push(PROV_LABELS[k] + ': точка не лежит на линии (отстоит на ' + pr.dist.toFixed(1) + ')');
      st[k] = round5(pr.frac);
    });
    if (!errors.length) {
      var l1 = G.mod1(st.s1s2 - st.start), l2 = G.mod1(st.s2s3 - st.start);
      if (!(l1 > 0 && l1 < l2 && l2 < 1)) errors.push('Порядок по ходу движения должен быть: старт → S1|S2 → S2|S3 → старт');
    }
    if (errors.length) return errors;
    pushUndo();
    state = st; sel = null; autoLabels = null; lastPreview = '';
    return [];
  }
  $('tseJsonFile').addEventListener('change', function (e) {
    var f = e.target.files[0];
    if (!f) return;
    f.text().then(function (txt) {
      var d;
      try { d = JSON.parse(txt); } catch (err) { showImport(['Файл не читается как JSON']); return; }
      var errors = importJson(d);
      if (errors.length) { showImport(errors); return; }
      var notes = [];
      var lw = lengthWarning();
      if (lw) notes.push(lw);
      showImport(notes, 'Схема открыта' + (state.provisional.length ? ' — есть условные элементы, см. «Нужно подтвердить»' : ''));
      render();
    });
    e.target.value = '';
  });
  $('tseExport').addEventListener('click', function () {
    var p = poly();
    if (!p) { status('Нечего экспортировать — нет линии', true); return; }
    var out = payload();
    ['start', 's1s2', 's2s3'].forEach(function (k) { if (out[k] != null) { var q = p.pointAt(out[k]); out[k + '_xy'] = [round1(q[0]), round1(q[1])]; } });
    out.version = 1;
    out.direction = G.drawnDirection(out.points);
    var sc = scaleMPU();
    if (sc) { out.scale_m_per_unit = round5(sc); out.measured_length_m = round1(p.length * sc); }
    delete out.reference;
    var blob = new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (root.dataset.slug || 'track') + '_scheme_data.json';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  });

  // ── Импорт из OpenStreetMap (Д2) ───────────────────────────────────
  var osmCandidates = [];
  /* Линии highway=raceway из .osm (XML) или GeoJSON. out.missing — id линий, у которых в файле нет
     координат точек (выгрузка одной линии /api/0.6/way/<id>): их скачиваем целиком (/way/<id>/full). */
  function parseOsm(txt) {
    var out = [];
    out.missing = [];
    if (/^\s*</.test(txt)) {
      var doc = new DOMParser().parseFromString(txt, 'application/xml');
      if (doc.getElementsByTagName('parsererror').length) return out;
      var nodes = {};
      Array.prototype.forEach.call(doc.getElementsByTagName('node'), function (n) { nodes[n.getAttribute('id')] = [+n.getAttribute('lat'), +n.getAttribute('lon')]; });
      Array.prototype.forEach.call(doc.getElementsByTagName('way'), function (w) {
        var tags = {};
        Array.prototype.forEach.call(w.getElementsByTagName('tag'), function (t) { tags[t.getAttribute('k')] = t.getAttribute('v'); });
        if (tags.highway !== 'raceway') return;
        var nds = w.getElementsByTagName('nd');
        var coords = Array.prototype.map.call(nds, function (nd) { return nodes[nd.getAttribute('ref')]; }).filter(Boolean);
        if (coords.length < nds.length) { out.missing.push(+w.getAttribute('id')); return; }
        if (coords.length < 4) return;
        out.push({ name: tags.name || '', way: +w.getAttribute('id'), version: +w.getAttribute('version') || null, edited: (w.getAttribute('timestamp') || '').slice(0, 10), coords: coords });
      });
    } else {
      var gj = JSON.parse(txt), feats = gj.type === 'FeatureCollection' ? gj.features : [gj];
      (feats || []).forEach(function (f) {
        var g = f.geometry || {}, props = f.properties || {}, line = null;
        if (g.type === 'LineString') line = g.coordinates;
        if (g.type === 'Polygon') line = g.coordinates[0];
        if (!line || line.length < 4) return;
        if (props.highway && props.highway !== 'raceway') return;
        var id = typeof f.id === 'string' ? parseInt(f.id.replace(/\D/g, ''), 10) : f.id;
        out.push({ name: props.name || '', way: id || null, version: null, edited: '', coords: line.map(function (c) { return [c[1], c[0]]; }) });
      });
    }
    out.forEach(function (c) {
      var len = 0;
      for (var i = 1; i < c.coords.length; i++) len += haversine(c.coords[i - 1], c.coords[i]);
      c.length = len;
      var a = c.coords[0], b = c.coords[c.coords.length - 1];
      c.closed = a[0] === b[0] && a[1] === b[1];
    });
    out.sort(function (a, b) { return b.length - a.length; });
    return out;
  }
  function haversine(a, b) {
    var r = Math.PI / 180, dLat = (b[0] - a[0]) * r, dLon = (b[1] - a[1]) * r;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * EARTH_R * Math.asin(Math.sqrt(h));
  }
  $('tseOsmFile').addEventListener('change', function (e) {
    var f = e.target.files[0];
    if (!f) return;
    f.text().then(function (txt) {
      try { osmCandidates = parseOsm(txt); } catch (err) { osmCandidates = []; }
      if (!osmCandidates.length && osmCandidates.missing && osmCandidates.missing.length) {
        var id = osmCandidates.missing[0];
        showImport([], 'В файле нет координат точек — скачиваю линию ' + id + ' из OpenStreetMap…');
        fetch('https://api.openstreetmap.org/api/0.6/way/' + id + '/full')
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
          .then(function (full) { osmCandidates = parseOsm(full); showOsmCandidates(); })
          .catch(function () { showImport(['Не удалось скачать линию ' + id + ' из OpenStreetMap. Скачайте файл https://www.openstreetmap.org/api/0.6/way/' + id + '/full и загрузите его.']); });
        return;
      }
      showOsmCandidates();
    });
    e.target.value = '';
  });
  function showOsmCandidates() {
    if (!osmCandidates.length) { showImport(['В файле нет линий highway=raceway']); return; }
    $('tseOsmPick').innerHTML = osmCandidates.map(function (c, i) {
      return '<option value="' + i + '">' + esc((c.name || 'Без названия') + ' — ' + Math.round(c.length) + ' м, ' + (c.closed ? 'замкнута' : 'не замкнута')) + '</option>';
    }).join('');
    $('tseOsmPickWrap').hidden = osmCandidates.length < 2;
    applyOsm(0);
  }
  $('tseOsmPick').addEventListener('change', function (e) { applyOsm(+e.target.value); });
  function applyOsm(idx) {
    var c = osmCandidates[idx];
    if (!c) return;
    var coords = c.closed ? c.coords.slice(0, -1) : c.coords.slice();
    var lat0 = coords.reduce(function (s, q) { return s + q[0]; }, 0) / coords.length, lon0 = coords.reduce(function (s, q) { return s + q[1]; }, 0) / coords.length;
    var r = Math.PI / 180, cosL = Math.cos(lat0 * r);
    // равнопромежуточная проекция относительно центра трассы, в метрах (y вниз — север сверху)
    var meters = coords.map(function (q) { return [(q[1] - lon0) * r * cosL * EARTH_R, -(q[0] - lat0) * r * EARTH_R]; });
    pushUndo();
    var st = blank();
    st.points = meters;
    st.scale_m_per_unit = 1;  // 1 ед. = 1 м до подгонки поля
    st.source = { type: 'osm', way: c.way, name: c.name, osm_version: c.version, edited: c.edited, reversed: false };
    st.reference = state.reference;
    state = st;
    fitView();
    autoDefaults();
    state.provisional = ['start', 's1s2', 's2s3', 'track_width_m', 'turns', 'direction'];
    sel = null; autoLabels = null; lastPreview = '';
    var lw = lengthWarning();
    showImport(lw ? [lw] : [], 'Линия из OpenStreetMap: ' + Math.round(c.length) + ' м. Проверьте направление движения (в OSM оно не совпадает с направлением гонки) — «Развернуть направление».');
    render();
  }
  /* Радиус по трём точкам с шагом ~2 м вдоль сглаженной линии */
  function radii(p, sc) {
    var step = 2 / sc, M = Math.max(60, Math.round(p.length / step)), pts = [], out = [];
    for (var i = 0; i < M; i++) pts.push(p.pointAt(i / M));
    var k = 3;
    for (i = 0; i < M; i++) {
      var a = pts[(i - k + M) % M], b = pts[i], c = pts[(i + k) % M];
      var ab = Math.hypot(b[0] - a[0], b[1] - a[1]), bc = Math.hypot(c[0] - b[0], c[1] - b[1]), ca = Math.hypot(a[0] - c[0], a[1] - c[1]);
      var cross = Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
      out.push(cross < 1e-9 ? Infinity : ab * bc * ca / (2 * cross) * sc);
    }
    return { M: M, pts: pts, r: out };
  }
  /* Старт — середина самой длинной прямой (радиус > 100 м), границы — 1/3 и 2/3; повороты —
     участки с радиусом < 40 м и суммарным поворотом ≥ 25°, маркер у точки минимального радиуса */
  function autoDefaults() {
    var p = poly(), sc = scaleMPU();
    if (!p || !sc) return;
    var R = radii(p, sc), M = R.M, best = null, i, j;
    var startIdx = 0;
    for (i = 0; i < M; i++) if (R.r[i] <= 100) { startIdx = i; break; }
    var run = 0, runStart = 0;
    for (j = 1; j <= M; j++) {
      var idx = (startIdx + j) % M;
      if (R.r[idx] > 100) { if (!run) runStart = j; run++; if (!best || run > best.len) best = { from: runStart, len: run }; }
      else run = 0;
    }
    var st = best ? ((startIdx + best.from + best.len / 2) % M) / M : 0;
    state.start = round5(st); state.s1s2 = round5(G.mod1(st + 1 / 3)); state.s2s3 = round5(G.mod1(st + 2 / 3));
    var turns = [], inTurn = false, cur = null, half = widths()[0] / 2;
    function heading(a) { var q = R.pts[(a + 1) % M], o = R.pts[a]; return Math.atan2(q[1] - o[1], q[0] - o[0]); }
    for (j = 0; j < M; j++) {
      var id = (Math.round(st * M) + j) % M;
      if (R.r[id] < 40) {
        if (!inTurn) { inTurn = true; cur = { min: id, angle: 0 }; }
        if (R.r[id] < R.r[cur.min]) cur.min = id;
        var dh = heading(id) - heading((id - 1 + M) % M);
        while (dh > Math.PI) dh -= 2 * Math.PI;
        while (dh < -Math.PI) dh += 2 * Math.PI;
        cur.angle += dh;
      } else if (inTurn) {
        inTurn = false;
        if (Math.abs(cur.angle) * 180 / Math.PI >= 25) turns.push(cur);
      }
    }
    if (inTurn && Math.abs(cur.angle) * 180 / Math.PI >= 25) turns.push(cur);
    state.turns = turns.map(function (t, n) {
      var f = t.min / M, q = p.pointAt(f), nn = p.outwardNormal(f), off = half + 14;
      return { n: String(n + 1), x: round1(q[0] + nn[0] * off), y: round1(q[1] + nn[1] * off) };
    });
  }

  // ── Импорт SVG ──────────────────────────────────────────────────────
  var svgCandidates = [], svgFull = null;
  $('tseSvgFile').addEventListener('change', function (e) {
    var f = e.target.files[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) { showImport(['SVG больше 5 МБ']); return; }
    f.text().then(function (txt) {
      var parsed = parseSvg(txt);
      svgCandidates = parsed.lines; svgFull = parsed.gripline;
      if (svgFull) { applyGriplineSvg(svgFull); return; }
      if (!svgCandidates.length) { showImport(['В файле не нашлось линий (path, polyline, polygon)']); return; }
      $('tseSvgPick').innerHTML = svgCandidates.map(function (c, i) { return '<option value="' + i + '">Линия ' + (i + 1) + (c.closed ? ', замкнутая' : '') + ' — длина ' + Math.round(c.length) + '</option>'; }).join('');
      $('tseSvgPickWrap').hidden = svgCandidates.length < 2;
      applySvg(0);
      showImport([], 'Линия взята из SVG — проверьте направление и расставьте отметки');
    });
    e.target.value = '';
  });
  $('tseSvgPick').addEventListener('change', function (e) { applySvg(+e.target.value); });
  $('tseSvgCount').addEventListener('change', function () { if (svgFull) applyGriplineSvg(svgFull); else if (svgCandidates.length) applySvg(+$('tseSvgPick').value || 0); });

  /* Из чужого SVG берём только геометрию: атрибуты d / points / transform копируются в
     новые элементы скрытого SVG — сам файл в документ не вставляется (никаких скриптов). */
  function parseSvg(txt) {
    var doc = new DOMParser().parseFromString(txt, 'image/svg+xml');
    if (doc.getElementsByTagName('parsererror').length) return { lines: [], gripline: null };
    var hidden = el('svg', { width: 1, height: 1 });
    hidden.style.cssText = 'position:absolute;left:-10px;top:-10px;visibility:hidden;overflow:hidden';
    document.body.appendChild(hidden);
    function sample(node, step) {
      var d = shapeToD(node);
      if (!d) return null;
      var chain = [], n = node;
      while (n && n.nodeType === 1 && n.tagName.toLowerCase() !== 'svg') { if (n.getAttribute('transform')) chain.unshift(n.getAttribute('transform')); n = n.parentNode; }
      var parent = hidden;
      chain.forEach(function (tr) { parent = el('g', { transform: tr }, parent); });
      var path = el('path', { d: d }, parent), L;
      try { L = path.getTotalLength(); } catch (err) { return null; }
      if (!L || !isFinite(L)) return null;
      var m = hidden.getScreenCTM().inverse().multiply(path.getScreenCTM()), N = Math.max(50, Math.min(4000, Math.round(L / (step || 1)))), raw = [];
      for (var i = 0; i <= N; i++) {
        var q = path.getPointAtLength(i / N * L);
        raw.push([m.a * q.x + m.c * q.y + m.e, m.b * q.x + m.d * q.y + m.f]);
      }
      return { raw: raw, length: L * Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)), closed: /z\s*$/i.test(d) || node.tagName.toLowerCase() !== 'path' };
    }
    var out = { lines: [], gripline: null };
    try {
      // Схема Gripline (наш формат: g#sectors с тремя path[data-s]) — берём всё: секторы, повороты, плашки
      var secs = [0, 1, 2].map(function (i) { return doc.querySelector('#sectors [data-s="' + i + '"]'); });
      if (secs.every(Boolean)) {
        var parts = secs.map(function (s) { return sample(s, 0.5); });
        if (parts.every(Boolean)) {
          var vb = (doc.documentElement.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
          var turns = [], labels = [];
          Array.prototype.forEach.call(doc.querySelectorAll('#turns circle'), function (c) {
            var t = c.nextElementSibling;
            turns.push({ n: t && t.tagName.toLowerCase() === 'text' ? t.textContent.trim().slice(0, 4) : '', x: +c.getAttribute('cx'), y: +c.getAttribute('cy') });
          });
          Array.prototype.forEach.call(doc.querySelectorAll('#labels rect'), function (r, i) {
            labels.push({ s: i, x: +r.getAttribute('x') + +r.getAttribute('width') / 2, y: +r.getAttribute('y') + +r.getAttribute('height') / 2 });
          });
          // толщина полотна в нашем SVG = ширина полотна (9 м по умолчанию) в масштабе схемы → масштаб
          var trackPath = doc.querySelector('#track path'), sw = trackPath ? parseFloat(trackPath.getAttribute('stroke-width')) : NaN;
          out.gripline = { parts: parts, viewBox: vb.length === 4 ? vb : null, turns: turns.filter(function (t) { return t.n; }), labels: labels.slice(0, 3),
            scale: sw > 0 && sw !== 30 ? 9 / sw : null };
        }
      }
      Array.prototype.forEach.call(doc.querySelectorAll('path, polyline, polygon, rect, ellipse, circle'), function (node) {
        var c = sample(node, 1);
        if (c) out.lines.push(c);
      });
    } catch (err) { /* битый файл — что успели, то и берём */ }
    hidden.remove();
    out.lines.sort(function (a, b) { return b.length - a.length; });
    out.lines = out.lines.slice(0, 20);
    return out;
  }
  function shapeToD(node) {
    var tag = node.tagName.toLowerCase(), a = function (k) { return parseFloat(node.getAttribute(k)) || 0; };
    if (tag === 'path') return node.getAttribute('d');
    if (tag === 'polyline' || tag === 'polygon') {
      var nums = (node.getAttribute('points') || '').trim().split(/[\s,]+/).map(parseFloat);
      if (nums.length < 4) return null;
      var d = 'M' + nums[0] + ',' + nums[1];
      for (var i = 2; i + 1 < nums.length; i += 2) d += ' L' + nums[i] + ',' + nums[i + 1];
      return d + (tag === 'polygon' ? ' Z' : '');
    }
    if (tag === 'rect') { var x = a('x'), y = a('y'), w = a('width'), h = a('height'); return w && h ? 'M' + x + ',' + y + ' h' + w + ' v' + h + ' h' + (-w) + ' Z' : null; }
    if (tag === 'ellipse' || tag === 'circle') {
      var cx = a('cx'), cy = a('cy'), rx = tag === 'circle' ? a('r') : a('rx'), ry = tag === 'circle' ? a('r') : a('ry');
      return rx && ry ? 'M' + (cx - rx) + ',' + cy + ' a' + rx + ',' + ry + ' 0 1,0 ' + (2 * rx) + ',0 a' + rx + ',' + ry + ' 0 1,0 ' + (-2 * rx) + ',0 Z' : null;
    }
    return null;
  }
  function controlCount(lengthUnits) {
    var v = parseInt($('tseSvgCount').value, 10);
    return v >= 8 && v <= 400 ? v : Math.max(24, Math.min(200, Math.round(lengthUnits / 20)));
  }
  /* Равномерно по длине: count опорных точек по ломаной raw (с первой точки) */
  function resample(raw, count) {
    var rp = new G.Polyline(raw), pts = [];
    for (var i = 0; i < count; i++) pts.push(rp.pointAt(i / count));
    return pts;
  }
  function applyGriplineSvg(g) {
    var raw = [];
    g.parts.forEach(function (p) { raw = raw.concat(p.raw.slice(0, -1)); });
    var total = new G.Polyline(raw).length;
    pushUndo();
    var st = blank();
    st.points = resample(raw, controlCount(total)).map(function (q) { return [round1(q[0]), round1(q[1])]; });
    st.source = { type: 'svg' };
    st.scale_m_per_unit = g.scale ? round5(g.scale) : null;
    st.turns = g.turns;
    st.sector_labels = g.labels;
    st.reference = state.reference;
    var okView = g.viewBox && g.viewBox[2] === W && g.viewBox[3] >= H_MIN && g.viewBox[3] <= H_MAX;
    st.viewBox = okView ? [0, 0, W, g.viewBox[3]] : [0, 0, W, 400];
    state = st;
    var p = poly();
    ['start', 's1s2', 's2s3'].forEach(function (k, i) { var q = g.parts[i].raw[0]; state[k] = round5(p.project(q[0], q[1]).frac); });
    if (!okView) fitView();
    sel = null; autoLabels = null; lastPreview = '';
    showImport([], 'Открыта схема Gripline из SVG: линия, старт, границы секторов, ' + g.turns.length + ' поворотов');
    render();
  }
  function applySvg(idx) {
    var c = svgCandidates[idx];
    if (!c) return;
    pushUndo();
    var st = blank();
    st.points = resample(c.raw.slice(0, -1), controlCount(c.length));
    st.source = { type: 'svg' };
    st.reference = state.reference;
    state = st;
    fitView();
    sel = null; autoLabels = null; lastPreview = '';
    render();
  }

  // ── Подложка ────────────────────────────────────────────────────────
  function loadRefImage(cb) {
    if (!refImg.url) return;
    var im = new Image();
    im.onload = function () {
      refImg.w = im.naturalWidth; refImg.h = im.naturalHeight;
      if (!state.reference) state.reference = { x: 0, y: 0, scale: round5(W / refImg.w), rotate: 0, opacity: 0.5 };
      render(); if (cb) cb();
    };
    im.src = refImg.url;
  }
  $('tseRefFile').addEventListener('change', function (e) {
    var f = e.target.files[0];
    if (!f) return;
    var fd = new FormData(); fd.append('file', f);
    status('Загрузка подложки…');
    fetch(root.dataset.referenceUrl, { method: 'POST', body: fd, headers: { 'X-CSRFToken': csrf }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); })
      .then(function (res) {
        if (!res[0]) { status(res[1].error || 'Не удалось загрузить', true); return; }
        state.reference = null;
        refImg.url = root.dataset.referenceUrl + '?t=' + Date.now();
        loadRefImage(function () { dirty = true; status('Подложка загружена — не забудьте «Сохранить», чтобы запомнить её положение'); });
      }, function () { status('Не удалось загрузить подложку', true); });
  });
  $('tseRefDelete').addEventListener('click', function () {
    var fd = new FormData(); fd.append('action', 'delete');
    fetch(root.dataset.referenceUrl, { method: 'POST', body: fd, headers: { 'X-CSRFToken': csrf }, credentials: 'same-origin' })
      .then(function () { refImg.url = null; state.reference = null; dirty = true; render(); status('Подложка удалена'); });
  });
  $('tseRefOpacity').addEventListener('input', function (e) { if (state.reference) { state.reference.opacity = +e.target.value; dirty = true; render(); } });
  $('tseRefScale').addEventListener('input', function (e) { if (state.reference) { state.reference.scale = round5(Math.exp(+e.target.value)); dirty = true; render(); } });
  $('tseRefRotate').addEventListener('input', function (e) { if (state.reference) { state.reference.rotate = +e.target.value; dirty = true; render(); } });

  // ── Сервер ──────────────────────────────────────────────────────────
  function payload() {
    var out = JSON.parse(JSON.stringify(state));
    if (!(refImg.url && out.reference)) delete out.reference;
    if (!out.provisional.length) out.publish_draft = false;
    return out;
  }
  function post(url, body) {
    return fetch(url, { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }, function () { return [false, { error: 'Ошибка сервера (' + r.status + ')' }]; }); });
  }
  function status(text, bad) { var s = $('tseStatus'); s.textContent = text; s.classList.toggle('is-error', !!bad); }
  $('tseSave').addEventListener('click', function () {
    status('Сохранение…');
    post(root.dataset.saveUrl, payload()).then(function (res) {
      if (!res[0]) { status(res[1].error || 'Ошибка сохранения', true); return; }
      dirty = false;
      status('Сохранено ' + res[1].saved_at + (res[1].published ? ' — схема на сайте обновлена' : ' — черновик, на сайте не показывается'));
    }, function () { status('Нет связи с сервером', true); });
  });
  $('tseClear').addEventListener('click', function () {
    var btn = $('tseClear');
    if (btn.dataset.confirm !== '1') { btn.dataset.confirm = '1'; btn.textContent = 'Точно удалить схему с сайта? Нажмите ещё раз'; return; }
    post(root.dataset.clearUrl, {}).then(function () { btn.dataset.confirm = ''; btn.textContent = 'Удалить схему с сайта'; status('Схема удалена с сайта (в редакторе она осталась — можно сохранить снова)'); });
  });
  window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  // ── Вкладки предпросмотра ───────────────────────────────────────────
  var inst3d = null, loading3d = null;
  function addScript(src) { return new Promise(function (ok, bad) { var sc = document.createElement('script'); sc.src = src; sc.onload = ok; sc.onerror = bad; document.head.appendChild(sc); }); }
  function showTab(name) {
    root.querySelectorAll('.tse-tab').forEach(function (b) { b.classList.toggle('is-on', b.dataset.tab === name); });
    root.querySelectorAll('.tse-pane').forEach(function (p) { p.hidden = p.dataset.pane !== name; });
    if (inst3d && name !== '3d') inst3d.pause();
    if (name === 'scheme') {
      $('tsePreview').innerHTML = '<p class="tse-hint">Загрузка…</p>';
      post(root.dataset.previewUrl, payload()).then(function (res) {
        $('tsePreview').innerHTML = res[0] ? res[1].svg : '<p class="tse-hint">' + esc(res[1].error || 'Ошибка') + '</p>';
      });
    }
    if (name === '3d') {
      var host = $('tse3d');
      if (!INIT.length_m) { host.innerHTML = '<p class="tse-hint">Укажите длину трассы в карточке — без неё 3D не строится.</p>'; return; }
      post(root.dataset.previewUrl, payload()).then(function (res) {
        if (!res[0]) { host.innerHTML = '<p class="tse-hint">' + esc(res[1].error || 'Ошибка') + '</p>'; return; }
        if (!loading3d) loading3d = addScript(root.dataset.three).then(function () { return addScript(root.dataset.orbit); }).then(function () { return addScript(root.dataset.module); });
        loading3d.then(function () {
          if (inst3d) inst3d.destroy();
          inst3d = window.GlTrack3D.build({ scheme: res[1].public, lengthM: INIT.length_m, onRebuild: function () { showTab('3d'); } });
          inst3d.mount(host);
          // условный круг: секторы по их длине при средней скорости 15 м/с
          var sc = res[1].public, l1 = G.mod1(sc.s1s2 - sc.start), l2 = G.mod1(sc.s2s3 - sc.s1s2), l3 = 1 - l1 - l2;
          var lap = INIT.length_m / 15 * 1000, secs = [l1, l2, l3].map(function (x) { return Math.round(x * lap); });
          inst3d.setClass({ record_ms: Math.round((secs[0] + secs[1] + secs[2]) * 1.003), sectors_ms: secs });
          inst3d.setSector(-1);
        }, function () { host.innerHTML = '<p class="tse-hint">Не удалось загрузить 3D.</p>'; });
      });
    }
  }
  root.querySelectorAll('.tse-tab').forEach(function (b) { b.addEventListener('click', function () { showTab(b.dataset.tab); }); });

  loadRefImage();
  render();
})();
