/**
 * Gripline — «Ход гонки» (lap position bump chart)
 *
 * Vanilla JS, без зависимостей. Встраивается в любую страницу сайта
 * (шаблон Wagtail страницы сессии — Финал/Предфинал).
 *
 * Использование:
 *   <div id="lap-chart-final" class="gl-lapchart"></div>
 *   <script src="{% static 'js/gripline_lap_chart_widget.js' %}"></script>
 *   <script>
 *     GriplineLapChart.init(document.getElementById('lap-chart-final'), {
 *       stages: 10,                      // число кругов (без учёта старта)
 *       maxPosition: 26,                 // размер поля для оси Y
 *       drivers: [
 *         { num: 79, name: 'Голубенко Ян', pos: [1,1,1,1,1,1,1,1,1,1,1] },
 *         // pos[0] = позиция на старте, pos[1..N] = позиция после круга N
 *         ...
 *       ]
 *     });
 *   </script>
 *
 * Данные drivers формируются на бэкенде из CSV lap_chart (см.
 * gripline_tz_konverter_lap_chart_v1.md) джойном по race_number с protocol
 * той же сессии для получения имени пилота.
 *
 * Паттерн размещения на странице этапа: столбец с иконкой play в таблице
 * результатов (между «Шасси» и «Лучший круг») — клик по строке пилота
 * открывает модалку с этим виджетом, где сразу выбран (select) этот пилот
 * (selected = race_number при инициализации, см. GriplineLapChart.init
 * — сейчас по умолчанию выбирается первый пилот в drivers; при открытии
 * из таблицы нужно после init() вызвать instance.select(raceNumber), либо
 * передать options.initialSelected). Данные сессии — всегда Финал, вне
 * зависимости от того, какая сессия сейчас отображается в таблице очков.
 *
 * viewBox 760×260 подобран под широкую модалку на десктопе (примерно
 * ширина чата/центральной колонки контента) — при сжатии контейнера SVG
 * масштабируется как единое целое (width:100%), так что на мобильном модалка
 * просто ужимается, без отдельной адаптивной раскладки.
 */
(function (global) {
  'use strict';

  var COLORS = {
    bg: '#111111',
    line: '#4A4A48',
    lineDim: '#2C2C2A',
    grid: 'rgba(240,238,232,0.08)',
    lapLine: 'rgba(240,238,232,0.14)',
    text: '#F0EEE8',
    textMuted: '#C8C4BC',
    accent: '#E24B4A'
  };

  function svgEl(tag, attrs) {
    var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) { el.setAttribute(k, attrs[k]); }
    return el;
  }

  function lerp(a, b, f) { return a + (b - a) * f; }

  function init(container, options) {
    var stages = options.stages;
    var maxPosition = options.maxPosition || 26;
    var drivers = options.drivers;
    var posMin = 1, posMax = maxPosition;

    container.innerHTML = '';
    container.classList.add('gl-lapchart-root');

    var style = document.createElement('style');
    style.textContent =
      '.gl-lapchart-root{font-family:inherit;}' +
      '.gl-lc-info{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:8px;min-height:20px;color:' + COLORS.text + ';}' +
      '.gl-lc-info-name{font-size:14px;font-weight:600;}' +
      '.gl-lc-info-delta{font-size:13px;color:' + COLORS.textMuted + ';}' +
      '.gl-lc-controls{display:flex;align-items:center;gap:10px;margin-top:10px;}' +
      '.gl-lc-play{flex-shrink:0;width:36px;height:36px;padding:0;border-radius:6px;border:1px solid rgba(240,238,232,0.2);background:transparent;color:' + COLORS.text + ';display:flex;align-items:center;justify-content:center;cursor:pointer;}' +
      '.gl-lc-play:hover{background:rgba(240,238,232,0.06);}' +
      '.gl-lc-scrub{flex:1;accent-color:' + COLORS.accent + ';}' +
      '.gl-lc-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;}' +
      '.gl-lc-chip{font-size:12px;padding:4px 10px;border-radius:6px;border:1px solid rgba(240,238,232,0.16);background:transparent;color:' + COLORS.textMuted + ';cursor:pointer;}' +
      '.gl-lc-chip:hover{border-color:rgba(240,238,232,0.32);}' +
      '.gl-lc-chip.active{border-color:' + COLORS.accent + ';color:' + COLORS.accent + ';background:rgba(226,75,74,0.1);}';
    container.appendChild(style);

    var info = document.createElement('div');
    info.className = 'gl-lc-info';
    var infoName = document.createElement('span');
    infoName.className = 'gl-lc-info-name';
    var infoDelta = document.createElement('span');
    infoDelta.className = 'gl-lc-info-delta';
    info.appendChild(infoName);
    info.appendChild(infoDelta);
    container.appendChild(info);

    var pLeft = 44, pRight = 730, pTop = 15, pBottom = 225;
    var svg = svgEl('svg', { viewBox: '0 0 760 260', width: '100%', style: 'display:block;' });
    var gGrid = svgEl('g', {});
    var gLap = svgEl('g', {});
    var gLines = svgEl('g', {});
    var gHeads = svgEl('g', {});
    var gAxis = svgEl('g', {});
    svg.appendChild(gGrid); svg.appendChild(gLap); svg.appendChild(gLines); svg.appendChild(gHeads); svg.appendChild(gAxis);
    container.appendChild(svg);

    function x(i) { return pLeft + i * (pRight - pLeft) / stages; }
    function y(p) { return pTop + (p - posMin) / (posMax - posMin) * (pBottom - pTop); }

    var gridSteps = [];
    var step = Math.max(1, Math.round(maxPosition / 5));
    for (var gp = 1; gp <= maxPosition; gp += step) { gridSteps.push(gp); }
    gridSteps.forEach(function (p) {
      var l = svgEl('line', { x1: pLeft, x2: pRight, y1: y(p), y2: y(p), stroke: COLORS.grid, 'stroke-width': 1 });
      gGrid.appendChild(l);
      var t = svgEl('text', { x: pLeft - 8, y: y(p) + 4, 'text-anchor': 'end', fill: COLORS.textMuted, style: 'font-size:11px;' });
      t.textContent = p;
      gGrid.appendChild(t);
    });

    for (var i = 0; i <= stages; i += 1) {
      var ll = svgEl('line', {
        x1: x(i), x2: x(i), y1: pTop, y2: pBottom,
        stroke: COLORS.lapLine, 'stroke-width': 1, 'stroke-dasharray': '2,3'
      });
      gLap.appendChild(ll);
      var at = svgEl('text', { x: x(i), y: pBottom + 20, 'text-anchor': 'middle', fill: COLORS.textMuted, style: 'font-size:11px;' });
      at.textContent = i === 0 ? 'ст' : i;
      gAxis.appendChild(at);
    }

    var selected = options.initialSelected != null ? options.initialSelected : (drivers.length ? drivers[0].num : null);
    var lineEls = {}, headEls = {}, chipEls = {};

    drivers.forEach(function (d) {
      var pl = svgEl('polyline', { fill: 'none', style: 'cursor:pointer;' });
      pl.addEventListener('click', function () { select(d.num); });
      gLines.appendChild(pl);
      lineEls[d.num] = pl;

      var g = svgEl('g', { style: 'cursor:pointer;' });
      g.addEventListener('click', function () { select(d.num); });
      var c = svgEl('circle', { r: 9 });
      var t = svgEl('text', { 'text-anchor': 'middle', dy: 3, style: 'font-size:9px;font-weight:600;' });
      t.textContent = d.num;
      g.appendChild(c); g.appendChild(t);
      gHeads.appendChild(g);
      headEls[d.num] = { g: g, c: c, t: t };
    });

    var chips = document.createElement('div');
    chips.className = 'gl-lc-chips';
    drivers.forEach(function (d) {
      var b = document.createElement('button');
      b.className = 'gl-lc-chip';
      b.textContent = '№' + d.num;
      b.addEventListener('click', function () { select(d.num); });
      chips.appendChild(b);
      chipEls[d.num] = b;
    });
    container.appendChild(chips);

    var controls = document.createElement('div');
    controls.className = 'gl-lc-controls';
    var playBtn = document.createElement('button');
    playBtn.className = 'gl-lc-play';
    playBtn.setAttribute('aria-label', 'Воспроизвести');
    playBtn.innerHTML = '&#9654;';
    var scrub = document.createElement('input');
    scrub.type = 'range'; scrub.className = 'gl-lc-scrub';
    scrub.min = 0; scrub.max = stages; scrub.step = 0.02; scrub.value = 0;
    controls.appendChild(playBtn); controls.appendChild(scrub);
    container.insertBefore(controls, chips);

    function pointAt(d, tt) {
      var i0 = Math.floor(tt), i1 = Math.min(i0 + 1, stages), f = tt - i0;
      return { x: lerp(x(i0), x(i1), f), y: lerp(y(d.pos[i0]), y(d.pos[i1]), f) };
    }

    function render(tt) {
      drivers.forEach(function (d) {
        var isSel = selected === d.num;
        var dim = selected !== null && !isSel;
        var pts = '';
        for (var i = 0; i <= Math.floor(tt); i += 1) { pts += x(i) + ',' + y(d.pos[i]) + ' '; }
        var head = pointAt(d, tt);
        pts += head.x + ',' + head.y;
        lineEls[d.num].setAttribute('points', pts);
        lineEls[d.num].setAttribute('style',
          'stroke:' + (isSel ? COLORS.accent : COLORS.line) +
          ';stroke-width:' + (isSel ? 3 : 1.75) +
          ';stroke-opacity:' + (dim ? 0.15 : (isSel ? 1 : 0.6)) + ';');
        headEls[d.num].g.setAttribute('transform', 'translate(' + head.x + ',' + head.y + ')');
        headEls[d.num].c.setAttribute('style', 'fill:' + (isSel ? COLORS.accent : COLORS.line) + ';opacity:' + (dim ? 0.25 : 1) + ';');
        headEls[d.num].t.setAttribute('style', 'font-size:9px;font-weight:600;fill:' + COLORS.bg + ';opacity:' + (dim ? 0.25 : 1) + ';');
        chipEls[d.num].classList.toggle('active', isSel);
      });
      scrub.value = tt;
      var stageIdx = Math.round(tt);
      if (selected === null) { infoName.textContent = 'Выбери пилота'; infoDelta.textContent = stageLabel(stageIdx); return; }
      var d = drivers.filter(function (dd) { return dd.num === selected; })[0];
      infoName.textContent = d.name + ' (№' + d.num + ')';
      var curPos = Math.round(lerp(d.pos[Math.floor(tt)], d.pos[Math.min(Math.floor(tt) + 1, stages)], tt - Math.floor(tt)));
      infoDelta.textContent = stageLabel(stageIdx) + ' — P' + curPos;
    }

    function stageLabel(i) { return i === 0 ? 'старт' : 'круг ' + i; }

    function select(num) {
      selected = selected === num ? null : num;
      render(parseFloat(scrub.value));
    }

    var playing = false, rafId = null, lastTs = null, curT = 0;
    var durationMs = Math.max(3000, stages * 600);

    function frame(ts) {
      if (!playing) { return; }
      if (lastTs === null) { lastTs = ts; }
      var dt = ts - lastTs; lastTs = ts;
      curT += dt * (stages / durationMs);
      if (curT >= stages) { curT = stages; render(curT); pause(); return; }
      render(curT);
      rafId = requestAnimationFrame(frame);
    }
    function play() {
      if (curT >= stages) { curT = 0; }
      playing = true; lastTs = null;
      playBtn.innerHTML = '&#10074;&#10074;';
      playBtn.setAttribute('aria-label', 'Пауза');
      rafId = requestAnimationFrame(frame);
    }
    function pause() {
      playing = false;
      if (rafId) { cancelAnimationFrame(rafId); }
      playBtn.innerHTML = '&#9654;';
      playBtn.setAttribute('aria-label', 'Воспроизвести');
    }
    playBtn.addEventListener('click', function () { playing ? pause() : play(); });
    scrub.addEventListener('input', function (e) { pause(); curT = parseFloat(e.target.value); render(curT); });

    render(0);

    return { render: render, play: play, pause: pause, select: select };
  }

  global.GriplineLapChart = { init: init };
}(window));
