/* Редактор схемы трассы (админка → Трассы → «Редактор схемы»). Чистый JS + SVG.
   Всё хранится в координатах схемы viewBox 0 0 640 400 (как на сайте). На сервер уходят
   только числа (track_scheme_views.editor_save), SVG для сайта сервер строит сам.
   Геометрия (сплайн, доли длины) — track_scheme_geom.js, та же, что у 3D и у Python. */
(function () {
  'use strict';
  var G = window.GlTrackGeom;
  var root = document.getElementById('tse');
  if (!root || !G) return;
  var NS = 'http://www.w3.org/2000/svg';
  var W = 640, H = 400, SHARP_DEG = 35, MARK_SNAP = 24;
  var SEC_COLORS = ['#ffc107', '#0dcaf0', '#28a745'];
  var INIT = JSON.parse(document.getElementById('tse-data').textContent);
  var $ = function (id) { return document.getElementById(id); };
  var canvas = $('tseCanvas');
  var csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';

  var s = INIT.scheme ? JSON.parse(JSON.stringify(INIT.scheme)) : {};
  var state = {
    points: s.points || [],
    tension: s.tension == null ? 1 : s.tension,
    start: s.start == null ? null : s.start,
    s1s2: s.s1s2 == null ? null : s.s1s2,
    s2s3: s.s2s3 == null ? null : s.s2s3,
    turns: s.turns || [],
    sector_labels: s.sector_labels || [],
    reference: s.reference || null
  };
  var tool = 'points', sel = null, drag = null, undo = [], dirty = false;
  var refImg = { url: INIT.has_reference ? root.dataset.referenceUrl + '?t=' + Date.now() : null, w: 0, h: 0 };

  var HINTS = {
    points: 'Клик по пустому месту — новая точка в конец линии (по направлению движения). Клик по линии — вставить точку. Тяните точку, чтобы сдвинуть; Delete — удалить выбранную. Жёлтая — первая точка.',
    start: 'Клик по линии — поставить старт/финиш. Метку можно тянуть вдоль линии.',
    s1s2: 'Клик по линии — граница сектора S1|S2.',
    s2s3: 'Клик по линии — граница сектора S2|S3.',
    turns: 'Клик рядом с линией — новый номер поворота (по порядку). Тяните, чтобы сдвинуть; выбранному можно поменять номер справа.',
    labels: 'Тяните плашки S1/S2/S3, чтобы поправить их положение на схеме сайта. Двойной клик — вернуть автоматическое.',
    reference: 'Тяните подложку мышью. Масштаб, поворот и прозрачность — справа.'
  };

  function snapshot() { return JSON.stringify(state); }
  function pushUndo() { undo.push(snapshot()); if (undo.length > 100) undo.shift(); dirty = true; }
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

  // ── Проверки ────────────────────────────────────────────────────────
  function sharpIndexes() {
    var n = state.points.length, out = {};
    if (n < 3) return out;
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
  function warnings() {
    var w = [], n = state.points.length;
    if (n < 3) { w.push(['bad', 'Нужно хотя бы 3 точки линии']); return w; }
    var sharp = Object.keys(sharpIndexes()).length;
    if (sharp) w.push(['bad', 'Резкий угол — карт так не поворачивает (точек: ' + sharp + '). Добавьте точки или сгладьте. Сохранить можно.']);
    var drawn = G.drawnDirection(state.points);
    if (INIT.direction) {
      if (drawn !== INIT.direction) w.push(['bad', 'Линия нарисована ' + (drawn === 'cw' ? 'по часовой' : 'против часовой') + ', а в карточке трассы — ' + (INIT.direction === 'cw' ? 'по часовой' : 'против часовой') + '. Нажмите «Развернуть направление» или поправьте карточку.']);
      else w.push(['ok', 'Направление совпадает с карточкой трассы']);
    } else {
      w.push(['', 'В карточке трассы не указано направление — проверить нельзя (нарисовано ' + (drawn === 'cw' ? 'по часовой' : 'против часовой') + ')']);
    }
    ['start', 's1s2', 's2s3'].forEach(function (k) {
      if (state[k] == null) w.push(['bad', 'Не отмечено: ' + { start: 'старт/финиш', s1s2: 'граница S1|S2', s2s3: 'граница S2|S3' }[k]]);
    });
    if (state.start != null && state.s1s2 != null && state.s2s3 != null) {
      var l1 = G.mod1(state.s1s2 - state.start), l2 = G.mod1(state.s2s3 - state.start);
      if (!(l1 > 0 && l1 < l2 && l2 < 1)) w.push(['bad', 'Порядок по направлению движения должен быть: старт → S1|S2 → S2|S3 → старт']);
    }
    if (!INIT.length_m) w.push(['', 'В карточке трассы не указана длина — 3D на сайте не покажется']);
    return w;
  }

  // ── Отрисовка ───────────────────────────────────────────────────────
  function render() {
    canvas.innerHTML = '';
    el('rect', { x: 0, y: 0, width: W, height: H, fill: '#0d0d15' }, canvas);
    if (refImg.url && state.reference) {
      var r = state.reference;
      var img = el('image', {
        href: refImg.url, x: 0, y: 0, width: refImg.w || W, height: refImg.h || H, opacity: r.opacity, preserveAspectRatio: 'none',
        transform: 'translate(' + r.x + ',' + r.y + ') rotate(' + r.rotate + ',' + (refImg.w / 2 * r.scale) + ',' + (refImg.h / 2 * r.scale) + ') scale(' + r.scale + ')',
        'class': 'tse-ref'
      }, canvas);
      img.style.pointerEvents = tool === 'reference' ? 'auto' : 'none';
    }
    var p = poly();
    if (p) {
      var d = G.pathD(state.points, state.tension);
      el('path', { d: d, fill: 'none', stroke: '#2a2a35', 'stroke-width': 30, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'pointer-events': 'none' }, canvas);
      if (state.start != null && state.s1s2 != null && state.s2s3 != null) {
        [[state.start, state.s1s2], [state.s1s2, state.s2s3], [state.s2s3, state.start]].forEach(function (ab, i) {
          var pts = p.between(ab[0], ab[1]);
          el('path', { d: 'M' + pts.map(function (q) { return round1(q[0]) + ',' + round1(q[1]); }).join(' L'), fill: 'none', stroke: SEC_COLORS[i], 'stroke-width': 10, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'pointer-events': 'none' }, canvas);
        });
      } else {
        el('path', { d: d, fill: 'none', stroke: '#b0bec5', 'stroke-width': 3, 'pointer-events': 'none' }, canvas);
      }
      el('path', { d: d, 'class': 'tse-hit', 'data-hit': 'line' }, canvas);
      // стрелки направления
      for (var k = 1; k <= 8; k++) {
        var f = k / 8 - 0.0625, q = p.pointAt(f), t = p.tangentAt(f);
        var tip = [q[0] + t[0] * 7, q[1] + t[1] * 7], n = [-t[1], t[0]];
        el('path', { d: 'M' + round1(tip[0] - t[0] * 10 + n[0] * 5) + ',' + round1(tip[1] - t[1] * 10 + n[1] * 5) + ' L' + round1(tip[0]) + ',' + round1(tip[1]) + ' L' + round1(tip[0] - t[0] * 10 - n[0] * 5) + ',' + round1(tip[1] - t[1] * 10 - n[1] * 5), fill: 'none', stroke: '#ffffff', 'stroke-width': 2, 'stroke-linecap': 'round', 'pointer-events': 'none' }, canvas);
      }
      // отметки старта и границ
      [['start', '#ffffff', 'СТАРТ'], ['s1s2', SEC_COLORS[1], 'S1|S2'], ['s2s3', SEC_COLORS[2], 'S2|S3']].forEach(function (m) {
        if (state[m[0]] == null) return;
        var q = p.pointAt(state[m[0]]), t = p.tangentAt(state[m[0]]), n = [-t[1], t[0]];
        var g = el('g', { 'class': 'tse-mark', 'data-mark': m[0] }, canvas);
        el('line', { x1: round1(q[0] - n[0] * 18), y1: round1(q[1] - n[1] * 18), x2: round1(q[0] + n[0] * 18), y2: round1(q[1] + n[1] * 18), stroke: m[1], 'stroke-width': 5, 'data-mark': m[0] }, g);
        var lab = p.outwardNormal(state[m[0]]);
        el('text', { x: round1(q[0] + lab[0] * 34), y: round1(q[1] + lab[1] * 34 + 4), fill: m[1], 'font-size': 11, 'font-weight': 800, 'text-anchor': 'middle', 'data-mark': m[0] }, g).textContent = m[2];
      });
      // плашки секторов (только когда все отметки стоят)
      if (state.start != null && state.s1s2 != null && state.s2s3 != null) {
        var custom = {};
        state.sector_labels.forEach(function (l) { custom[l.s] = l; });
        [state.start, state.s1s2, state.s2s3].forEach(function (fr, i) {
          var pos = custom[i];
          if (!pos) {
            // как track_scheme.default_label_positions: S1 — за стрелкой, S2/S3 — сразу за границей
            var ff = fr + (i === 0 ? 110 : 25) / p.length, q = p.pointAt(ff), nn = p.outwardNormal(ff);
            pos = { x: q[0] + nn[0] * 30, y: q[1] + nn[1] * 30 };
          }
          var g = el('g', { 'class': 'tse-label', 'data-label': i }, canvas);
          el('rect', { x: round1(pos.x - 17), y: round1(pos.y - 10), width: 34, height: 20, rx: 10, fill: SEC_COLORS[i], 'data-label': i, opacity: tool === 'labels' ? 1 : 0.85 }, g);
          el('text', { x: round1(pos.x), y: round1(pos.y + 4), fill: i === 2 ? '#fff' : '#1a1a25', 'font-size': 12, 'font-weight': 800, 'text-anchor': 'middle', 'pointer-events': 'none' }, g).textContent = 'S' + (i + 1);
        });
      }
    } else if (state.points.length === 2) {
      el('line', { x1: state.points[0][0], y1: state.points[0][1], x2: state.points[1][0], y2: state.points[1][1], stroke: '#b0bec5', 'stroke-width': 3 }, canvas);
    }
    // повороты
    state.turns.forEach(function (t, i) {
      var g = el('g', { 'class': 'tse-turn' + (sel && sel.type === 'turn' && sel.i === i ? ' is-sel' : ''), 'data-turn': i }, canvas);
      el('circle', { cx: t.x, cy: t.y, r: 11, 'data-turn': i }, g);
      el('text', { x: t.x, y: t.y + 4 }, g).textContent = t.n;
    });
    // опорные точки — поверх всего, в режиме «Точки»
    var sharp = sharpIndexes();
    state.points.forEach(function (pt, i) {
      var c = el('circle', { cx: pt[0], cy: pt[1], r: tool === 'points' ? 5 : 3, 'data-pt': i,
        'class': 'tse-pt' + (i === 0 ? ' is-first' : '') + (sharp[i] ? ' is-sharp' : '') + (sel && sel.type === 'pt' && sel.i === i ? ' is-sel' : '') }, canvas);
      if (tool !== 'points') c.style.pointerEvents = 'none';
    });
    renderSide();
  }

  function renderSide() {
    $('tseWarnings').innerHTML = warnings().map(function (w) { return '<li class="' + (w[0] === 'bad' ? 'is-bad' : w[0] === 'ok' ? 'is-ok' : '') + '">' + w[1] + '</li>'; }).join('');
    var p = poly();
    $('tseScale').textContent = p && INIT.length_m ? 'Масштаб: 1 ед. = ' + (INIT.length_m / p.length).toFixed(2) + ' м (длина ' + INIT.length_m + ' м)' : (INIT.length_m ? '' : 'Длина трассы не указана — масштаб неизвестен');
    $('tseTension').value = state.tension;
    var turnSel = sel && sel.type === 'turn';
    $('tseTurnNumWrap').hidden = !turnSel;
    if (turnSel) $('tseTurnNum').value = state.turns[sel.i].n;
    $('tseRefControls').hidden = !(refImg.url && state.reference);
    if (state.reference) {
      $('tseRefOpacity').value = state.reference.opacity;
      $('tseRefScale').value = Math.log(state.reference.scale);
      $('tseRefRotate').value = state.reference.rotate;
    }
    $('tseHint').textContent = HINTS[tool];
  }

  // ── Мышь / палец ────────────────────────────────────────────────────
  function segmentOf(frac) {
    // доля длины → индекс отрезка между опорными точками (для вставки точки)
    var p = poly(), loc = p.locate(frac);
    return Math.floor(loc[0] / G.SAMPLES_PER_SEGMENT);
  }
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
        pushUndo(); state[key] = round5(pr.frac); drag = { type: 'mark', key: key }; render();
      }
      return;
    }
    if (tool === 'turns') {
      if (t.dataset.turn != null) { pushUndo(); sel = { type: 'turn', i: +t.dataset.turn }; drag = { type: 'turn', i: sel.i, dx: 0 }; render(); return; }
      pushUndo();
      var nmax = state.turns.reduce(function (m, x) { return Math.max(m, x.n); }, 0);
      state.turns.push({ n: nmax + 1, x: round1(xy[0]), y: round1(xy[1]) });
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
  function round5(v) { return Math.round(v * 100000) / 100000; }

  function deleteSelected() {
    if (!sel) return;
    pushUndo();
    if (sel.type === 'pt') {
      // доли отметок пересчитываем по их положению, чтобы они не уехали
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
  $('tseReverse').addEventListener('click', function () {
    if (state.points.length < 3) return;
    pushUndo();
    var keep = markXY();
    state.points.reverse();
    restoreMarks(keep);
    // по новому направлению границы идут в обратном порядке
    var a = state.s1s2; state.s1s2 = state.s2s3; state.s2s3 = a;
    state.sector_labels = [];
    render();
  });
  $('tseRenumber').addEventListener('click', function () {
    var p = poly();
    if (!p || !state.turns.length) return;
    pushUndo();
    var st = state.start || 0;
    state.turns.sort(function (a, b) { return G.mod1(p.project(a.x, a.y).frac - st) - G.mod1(p.project(b.x, b.y).frac - st); });
    state.turns.forEach(function (t, i) { t.n = i + 1; });
    sel = null; render();
  });
  $('tseTurnNum').addEventListener('change', function (e) {
    if (!(sel && sel.type === 'turn')) return;
    var v = parseInt(e.target.value, 10);
    if (v >= 1 && v <= 99) { pushUndo(); state.turns[sel.i].n = v; render(); }
  });

  // ── Загрузка SVG ────────────────────────────────────────────────────
  var svgCandidates = [];
  $('tseSvgFile').addEventListener('change', function (e) {
    var f = e.target.files[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) { status('SVG больше 5 МБ', true); return; }
    f.text().then(function (txt) {
      svgCandidates = parseSvgLines(txt);
      if (!svgCandidates.length) { status('В файле не нашлось линий (path, polyline, polygon)', true); return; }
      var pick = $('tseSvgPick');
      pick.innerHTML = svgCandidates.map(function (c, i) { return '<option value="' + i + '">Линия ' + (i + 1) + (c.closed ? ', замкнутая' : '') + ' — длина ' + Math.round(c.length) + '</option>'; }).join('');
      $('tseSvgPickWrap').hidden = svgCandidates.length < 2;
      applySvg(0);
      status('Линия взята из SVG — проверьте направление и расставьте отметки');
    });
  });
  $('tseSvgPick').addEventListener('change', function (e) { applySvg(+e.target.value); });
  $('tseSvgCount').addEventListener('change', function () { if (svgCandidates.length) applySvg(+$('tseSvgPick').value || 0); });

  /* Из чужого SVG берём только геометрию: атрибуты d / points / transform копируются в
     новые элементы скрытого SVG — сам файл в документ не вставляется (никаких скриптов). */
  function parseSvgLines(txt) {
    var doc = new DOMParser().parseFromString(txt, 'image/svg+xml');
    if (doc.getElementsByTagName('parsererror').length) return [];
    var hidden = el('svg', { width: 1, height: 1 });
    hidden.style.cssText = 'position:absolute;left:-10px;top:-10px;visibility:hidden;overflow:hidden';
    document.body.appendChild(hidden);
    var out = [];
    try {
      var nodes = doc.querySelectorAll('path, polyline, polygon, rect, ellipse, circle');
      Array.prototype.forEach.call(nodes, function (node) {
        var d = shapeToD(node);
        if (!d) return;
        // цепочка transform от корня до элемента
        var chain = [], n = node;
        while (n && n.nodeType === 1 && n.tagName.toLowerCase() !== 'svg') { if (n.getAttribute('transform')) chain.unshift(n.getAttribute('transform')); n = n.parentNode; }
        var parent = hidden;
        chain.forEach(function (tr) { parent = el('g', { transform: tr }, parent); });
        var path = el('path', { d: d }, parent);
        var len;
        try { len = path.getTotalLength(); } catch (err) { return; }
        if (!len || !isFinite(len)) return;
        var m = hidden.getScreenCTM().inverse().multiply(path.getScreenCTM());
        out.push({ path: path, m: m, length: len * Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)), closed: /z\s*$/i.test(d) || node.tagName.toLowerCase() !== 'path' });
      });
    } catch (err) { /* битый файл — что успели, то и берём */ }
    out.sort(function (a, b) { return b.length - a.length; });
    out.forEach(function (c) {
      var N = 1500, raw = [], L = c.path.getTotalLength();
      for (var i = 0; i < N; i++) {
        var q = c.path.getPointAtLength(i / N * L);
        raw.push([c.m.a * q.x + c.m.c * q.y + c.m.e, c.m.b * q.x + c.m.d * q.y + c.m.f]);
      }
      c.raw = raw;
    });
    hidden.remove();
    return out.slice(0, 20);
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
  function applySvg(idx) {
    var c = svgCandidates[idx];
    if (!c) return;
    var count = Math.max(8, Math.min(200, parseInt($('tseSvgCount').value, 10) || 48));
    // равномерно по длине: по накопленной длине исходной ломаной
    var rp = new G.Polyline(c.raw), pts = [];
    for (var i = 0; i < count; i++) pts.push(rp.pointAt(i / count));
    var xs = pts.map(function (p) { return p[0]; }), ys = pts.map(function (p) { return p[1]; });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs), minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var M = 40, k = Math.min((W - 2 * M) / ((maxX - minX) || 1), (H - 2 * M) / ((maxY - minY) || 1));
    var ox = (W - (maxX - minX) * k) / 2, oy = (H - (maxY - minY) * k) / 2;
    pushUndo();
    state.points = pts.map(function (p) { return [round1(ox + (p[0] - minX) * k), round1(oy + (p[1] - minY) * k)]; });
    state.start = state.s1s2 = state.s2s3 = null;
    state.sector_labels = [];
    sel = null; render();
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
    return out;
  }
  function post(url, body) {
    return fetch(url, { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); });
  }
  function status(text, bad) { var s = $('tseStatus'); s.textContent = text; s.classList.toggle('is-error', !!bad); }
  $('tseSave').addEventListener('click', function () {
    status('Сохранение…');
    post(root.dataset.saveUrl, payload()).then(function (res) {
      if (!res[0]) { status(res[1].error || 'Ошибка сохранения', true); return; }
      dirty = false; status('Сохранено ' + res[1].saved_at + ' — схема на сайте обновлена');
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
        $('tsePreview').innerHTML = res[0] ? res[1].svg : '<p class="tse-hint">' + (res[1].error || 'Ошибка') + '</p>';
      });
    }
    if (name === '3d') {
      var host = $('tse3d');
      if (!INIT.length_m) { host.innerHTML = '<p class="tse-hint">Укажите длину трассы в карточке — без неё 3D не строится.</p>'; return; }
      post(root.dataset.previewUrl, payload()).then(function (res) {
        if (!res[0]) { host.innerHTML = '<p class="tse-hint">' + (res[1].error || 'Ошибка') + '</p>'; return; }
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
