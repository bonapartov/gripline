/* 3D-схема трассы (three.js r128 + OrbitControls). Грузится track_page.js только по первому
   нажатию «3D» (и редактором схемы для предпросмотра). Строится из той же схемы, что 2D
   (Track.scheme_data, геометрия — track_scheme_geom.js), масштаб — по длине трассы.

   Метка проезжает рекордный круг класса, призрак — идеальный (сумма лучших секторов).
   Метка — модель карта с пилотом из track_3d_kart.js (грузится раньше), opts.kartScale — её размер.
   Скорость внутри сектора расчётная (кривизна → разгон/торможение), затем масштабируется
   так, чтобы время каждого сектора совпало с реальным.

   Нагрузка: рисуем только когда что-то меняется и окно на экране; на сенсорных — до 30 к/с.
   Браузер может отобрать WebGL-контекст — тогда onRebuild() пересоздаёт 3D в экономичном
   режиме (без сглаживания, pixelRatio 1.25). */
(function () {
  'use strict';
  var SEC = [
    { name: 'S1', color: '#ffc107', on: '#1a1a25', hex: 0xffc107 },
    { name: 'S2', color: '#0dcaf0', on: '#1a1a25', hex: 0x0dcaf0 },
    { name: 'S3', color: '#28a745', on: '#ffffff', hex: 0x28a745 }
  ];

  var MAX_SECTOR_KMH = 120;  // по умолчанию; у класса может быть свой порог (c.max_sector_kmh, track_page.py)

  function fmt(t) {
    var m = Math.floor(t / 60), r = (t - m * 60).toFixed(3);
    if (r.length < 6) r = '0' + r;
    return m + ':' + r;
  }

  function build(opts) {
    var G = window.GlTrackGeom, scheme = opts.scheme, low = !!opts.low, onRebuild = opts.onRebuild || function () {};
    var vb = scheme.viewBox || [0, 0, 640, 400], VIEW_W = vb[2], VIEW_H = vb[3];
    // ширина полотна — из схемы (track_width_m), по умолчанию 9 м
    var LENGTH_M = opts.lengthM, N = 800, DS = LENGTH_M / N, HALF = (scheme.track_width_m || 9) / 2;
    var poly = G.fromScheme(scheme), LT = poly.length, Mm = LENGTH_M / LT;
    var mod1 = G.mod1, start = scheme.start;

    var raw = [];
    for (var i = 0; i < N; i++) raw.push(poly.pointAt(start + i / N));
    var xs = raw.map(function (r) { return r[0]; }), ys = raw.map(function (r) { return r[1]; });
    var cx = (Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2, cy = (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2;
    var toW = function (x, y) { return [(x - cx) * Mm, (y - cy) * Mm]; };
    var P = raw.map(function (r) { return toW(r[0], r[1]); });
    // сглаживание: 3 прохода скользящим средним ±3 точки — без изломов
    for (var pass = 0; pass < 3; pass++) {
      P = P.map(function (_, i) {
        var sx = 0, sz = 0;
        for (var k = -3; k <= 3; k++) { var w = P[(i + k + N) % N]; sx += w[0]; sz += w[1]; }
        return [sx / 7, sz / 7];
      });
    }
    var b1 = mod1(scheme.s1s2 - start) * N, b2 = mod1(scheme.s2s3 - start) * N, B1 = Math.round(b1), B2 = Math.round(b2);
    var secOf = function (i) { return i < b1 ? 0 : i < b2 ? 1 : 2; };
    var T = [], Nr = [], curv = [];
    for (i = 0; i < N; i++) {
      var a = P[(i - 1 + N) % N], b = P[(i + 1) % N], tx = b[0] - a[0], tz = b[1] - a[1], l = Math.hypot(tx, tz) || 1;
      T.push([tx / l, tz / l]); Nr.push([-tz / l, tx / l]);
    }
    for (i = 0; i < N; i++) {
      var u = T[(i - 2 + N) % N], v = T[(i + 2) % N];
      curv.push(Math.acos(Math.max(-1, Math.min(1, u[0] * v[0] + u[1] * v[1]))) / (4 * DS));
    }
    var curvS = curv.map(function (_, i) { var s = 0; for (var k = -6; k <= 6; k++) s += curv[(i + k + N) % N]; return s / 13; });
    var cMax = Math.max.apply(null, curvS);
    // скорость: в повороте v = min(32, √(18 / кривизна)) м/с, разгон 3.5 м/с², торможение 8 м/с²
    /* скорость по точкам: на прямой не выше vmax (м/с), в повороте √(сцепление/кривизна), разгон 3.5, торможение 8 м/с² */
    function speeds(vmax, grip) {
      var v = curvS.map(function (c) { return Math.min(vmax, Math.sqrt(grip / Math.max(c, 1e-4))); }), pass, i;
      for (pass = 0; pass < 2; pass++) for (i = 0; i < N; i++) { var pv = v[(i - 1 + N) % N]; v[i] = Math.min(v[i], Math.sqrt(pv * pv + 2 * 3.5 * DS)); }
      for (pass = 0; pass < 2; pass++) for (i = N - 1; i >= 0; i--) { var nv = v[(i + 1) % N]; v[i] = Math.min(v[i], Math.sqrt(nv * nv + 2 * 8 * DS)); }
      return v;
    }
    function lapTime(v) { var t = 0; for (var i = 0; i < N; i++) t += DS / v[i]; return t; }
    /* максимальная скорость — по классу (top_kmh с сервера, track_page.top_speed_kmh), сцепление в поворотах
       подбираем так, чтобы расчётный круг совпал с рекордом: тогда масштаб по секторам почти не меняет
       скорость и метка не разгоняется выше реальной (Лемар, Micro: было 120 км/ч, стало ~80) */
    function speedsForLap(lapSec, topKmh) {
      var vmax = (topKmh || 110) / 3.6, lo = 3, hi = 80;
      if (lapTime(speeds(vmax, hi)) > lapSec) return speeds(vmax, hi);
      for (var it = 0; it < 30; it++) { var mid = (lo + hi) / 2; if (lapTime(speeds(vmax, mid)) > lapSec) lo = mid; else hi = mid; }
      return speeds(vmax, (lo + hi) / 2);
    }
    var vB = speeds(32, 18);
    // накопленное время по точкам при заданных временах секторов (сглаженный множитель — без скачка на границах)
    function profile(st) {
      var base = vB.map(function (x) { return DS / x; }), sb = [0, 0, 0], i;
      for (i = 0; i < N; i++) sb[secOf(i)] += base[i];
      var f = base.map(function (_, i) { return st[secOf(i)] / sb[secOf(i)]; });
      for (var it = 0; it < 5; it++) {
        var g = f.map(function (_, i) { var s = 0; for (var k = -30; k <= 30; k++) s += f[(i + k + N) % N]; return s / 61; });
        var sm = [0, 0, 0];
        for (i = 0; i < N; i++) sm[secOf(i)] += base[i] * g[i];
        f = g.map(function (x, i) { return x * st[secOf(i)] / sm[secOf(i)]; });
      }
      var cum = [0];
      for (i = 0; i < N; i++) cum.push(cum[i] + base[i] * f[i]);
      return cum;
    }
    function sample(cum, t) {
      t = Math.max(0, Math.min(t, cum[N] - 1e-6));
      var lo = 0, hi = N;
      while (hi - lo > 1) { var m = (lo + hi) >> 1; if (cum[m] <= t) lo = m; else hi = m; }
      var f = (t - cum[lo]) / (cum[lo + 1] - cum[lo]), a = P[lo], b = P[(lo + 1) % N], ta = T[lo], tb = T[(lo + 1) % N];
      return { x: a[0] + (b[0] - a[0]) * f, z: a[1] + (b[1] - a[1]) * f, tx: ta[0] + (tb[0] - ta[0]) * f, tz: ta[1] + (tb[1] - ta[1]) * f, i: lo };
    }

    var isTouch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    var renderer = new THREE.WebGLRenderer({ antialias: !low });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, low ? 1.25 : 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    var scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a25);  // фон — clearColor, его выходная кодировка не трогает
    var camera = new THREE.PerspectiveCamera(42, 1.6, 1, 4000);
    var controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.47;
    controls.minDistance = 40; controls.maxDistance = 1600;
    scene.add(new THREE.HemisphereLight(0xcfd8ff, 0x0a0a0f, 0.6));
    var sun = new THREE.DirectionalLight(0xffffff, 0.85);
    sun.position.set(-200, 400, 150); scene.add(sun);

    // подложка — как в 2D: прямоугольник схемы 640×400 с рамкой и скруглением
    var pa = toW(0, 0), pb = toW(VIEW_W, VIEW_H), plateW = pb[0] - pa[0], plateH = pb[1] - pa[1];
    function rrect(x0, z0, x1, z1, r) {
      var sh = new THREE.Shape();
      sh.moveTo(x0 + r, z0); sh.lineTo(x1 - r, z0); sh.quadraticCurveTo(x1, z0, x1, z0 + r); sh.lineTo(x1, z1 - r);
      sh.quadraticCurveTo(x1, z1, x1 - r, z1); sh.lineTo(x0 + r, z1); sh.quadraticCurveTo(x0, z1, x0, z1 - r);
      sh.lineTo(x0, z0 + r); sh.quadraticCurveTo(x0, z0, x0 + r, z0);
      var g = new THREE.ShapeGeometry(sh, 6); g.rotateX(Math.PI / 2); return g;
    }
    var bw = 1.6 * Mm, rad = 8 * Mm;
    // renderer.outputEncoding = sRGB осветляет цвета материалов — переводим в линейные, чтобы подложка была как в 2D
    var srgb = function (hex) { return new THREE.Color(hex).convertSRGBToLinear(); };
    var plateEdge = new THREE.Mesh(rrect(pa[0] - bw, pa[1] - bw, pb[0] + bw, pb[1] + bw, rad + bw), new THREE.MeshBasicMaterial({ color: srgb(0x2a2a35), side: THREE.DoubleSide }));
    plateEdge.position.y = -0.08; scene.add(plateEdge);
    var plate = new THREE.Mesh(rrect(pa[0], pa[1], pb[0], pb[1], rad), new THREE.MeshBasicMaterial({ color: srgb(0x0d0d15), side: THREE.DoubleSide }));
    plate.position.y = -0.05; scene.add(plate);

    function strip(a, b, y, colorAt, mask) {
      var pos = [], col = [], c = new THREE.Color();
      for (var i = 0; i < N; i++) {
        if (mask && !mask(i)) continue;
        var j = (i + 1) % N, pi = P[i], pj = P[j], ni = Nr[i], nj = Nr[j];
        var A = [pi[0] + ni[0] * a, y, pi[1] + ni[1] * a], Bv = [pi[0] + ni[0] * b, y, pi[1] + ni[1] * b], Cv = [pj[0] + nj[0] * a, y, pj[1] + nj[1] * a], D = [pj[0] + nj[0] * b, y, pj[1] + nj[1] * b];
        pos.push.apply(pos, A.concat(Cv, Bv, Bv, Cv, D));
        c.set(colorAt(i));
        for (var k = 0; k < 6; k++) col.push(c.r, c.g, c.b);
      }
      var g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
      g.computeVertexNormals();
      var mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9, side: THREE.DoubleSide }));
      scene.add(mesh); return mesh;
    }
    strip(-HALF, HALF, 0, function () { return 0x2c2c35; });
    strip(-HALF, -HALF + 0.35, 0.02, function () { return 0xd9dde3; });
    strip(HALF - 0.35, HALF, 0.02, function () { return 0xd9dde3; });
    // по сектору — своя полоса и своя подсветка полотна, чтобы фильтр мог их переключать
    var stripes = [0, 1, 2].map(function (k) { return strip(-0.7, 0.7, 0.04, function () { return SEC[k].hex; }, function (i) { return secOf(i) === k; }); });
    stripes.forEach(function (m) { m.material.transparent = true; });
    var bands = [0, 1, 2].map(function (k) {
      var m = strip(-HALF, HALF, 0.01, function () { return SEC[k].hex; }, function (i) { return secOf(i) === k; });
      m.material = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false });
      m.visible = false; return m;
    });
    var km = function (i) { return curvS[i] > cMax * 0.35; }, kc = function (i) { return Math.floor(i / 2) % 2 ? 0xe53935 : 0xf5f5f5; };
    strip(HALF, HALF + 1.3, 0.03, kc, km); strip(-HALF - 1.3, -HALF, 0.03, kc, km);
    (function () {
      var p = P[0], t = T[0], n = Nr[0], cells = 8, w = 2 * HALF / cells, d = 1.1;
      for (var r = 0; r < 2; r++) for (var k = 0; k < cells; k++) {
        var m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshBasicMaterial({ color: (k + r) % 2 ? 0x111111 : 0xffffff, side: THREE.DoubleSide }));
        var off = -HALF + w * (k + 0.5), al = (r - 0.5) * d;
        m.position.set(p[0] + n[0] * off + t[0] * al, 0.06, p[1] + n[1] * off + t[1] * al);
        m.rotation.order = 'YXZ'; m.rotation.x = -Math.PI / 2; m.rotation.y = Math.atan2(-n[1], n[0]);
        scene.add(m);
      }
    })();
    var textures = [];
    function label(text, bg, fg, w, h) {
      var cv = document.createElement('canvas'), s = 4;
      cv.width = w * s; cv.height = h * s;
      var x = cv.getContext('2d'); x.scale(s, s);
      x.fillStyle = bg; x.strokeStyle = '#ffffff'; x.lineWidth = 1.5;
      if (w === h) { x.beginPath(); x.arc(w / 2, h / 2, w / 2 - 2, 0, Math.PI * 2); x.fill(); x.stroke(); }
      else { var r = h / 2; x.beginPath(); x.moveTo(r, 1); x.lineTo(w - r, 1); x.arc(w - r, r, r - 1, -Math.PI / 2, Math.PI / 2); x.lineTo(r, h - 1); x.arc(r, r, r - 1, Math.PI / 2, Math.PI * 1.5); x.fill(); }
      x.fillStyle = fg; x.font = '800 ' + Math.round(h * 0.55) + 'px system-ui, Arial, sans-serif';
      x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(text, w / 2, h / 2 + 1);
      var tex = new THREE.CanvasTexture(cv); tex.encoding = THREE.sRGBEncoding; textures.push(tex);
      return new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
    }
    (scheme.turns || []).forEach(function (tt) {
      var w = toW(tt.x, tt.y), sp = label(String(tt.n), '#15151c', '#ffffff', 32, 32);
      sp.position.set(w[0], 9, w[1]); sp.scale.set(12, 12, 1); scene.add(sp);
      var pole = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 9, 6), new THREE.MeshBasicMaterial({ color: 0x3a3a45 }));
      pole.position.set(w[0], 4.5, w[1]); scene.add(pole);
    });
    [[0, 0, 'S1 · СТАРТ'], [B1 % N, 1, 'S2'], [B2 % N, 2, 'S3']].forEach(function (gt) {
      var p = P[gt[0]], n = Nr[gt[0]], c = SEC[gt[1]].hex, mat = new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.35 });
      [-1, 1].forEach(function (sd) {
        var post = new THREE.Mesh(new THREE.BoxGeometry(0.6, 6, 0.6), mat);
        post.position.set(p[0] + n[0] * (HALF + 1.8) * sd, 3, p[1] + n[1] * (HALF + 1.8) * sd); scene.add(post);
      });
      var bar = new THREE.Mesh(new THREE.BoxGeometry(2 * (HALF + 1.8), 0.5, 0.5), mat);
      bar.position.set(p[0], 6, p[1]); bar.rotation.y = Math.atan2(-n[1], n[0]); scene.add(bar);
      var long = gt[2].length > 3, sp = label(gt[2], SEC[gt[1]].color, SEC[gt[1]].on, long ? 120 : 56, 30);
      sp.position.set(p[0], 11, p[1]); sp.scale.set(long ? 32 : 15, 8, 1); scene.add(sp);
    });
    // метка — модель карта с пилотом (track_3d_kart.js); размер относительно настоящего — из админки
    function kart(color, ghost) {
      var g = window.GlKart3D.build(color, { ghost: ghost, driver: true, scale: opts.kartScale || 3 });
      scene.add(g); return g;
    }
    var rec = kart(0xffc107, false), ghost = kart(0x0dcaf0, true);
    var TR = 160, trp = new Float32Array(TR * 3), trg = new THREE.BufferGeometry();
    trg.setAttribute('position', new THREE.BufferAttribute(trp, 3));
    scene.add(new THREE.Line(trg, new THREE.LineBasicMaterial({ color: 0xffd400, transparent: true, opacity: 0.7 })));
    var trN = 0;

    var box = document.createElement('div');
    box.className = 'gl-tr-w3d';
    box.innerHTML =
      '<div class="gl-tr-v3d">' +
        '<div class="gl-tr-v3d-tl"><div class="gl-tr-seg" role="group" aria-label="Камера"><button type="button" data-c="orbit" aria-pressed="true">Обзор</button><button type="button" data-c="chase" aria-pressed="false">За меткой</button><button type="button" data-c="top" aria-pressed="false">Сверху</button></div></div>' +
        '<div class="gl-tr-v3d-msg gl-tr-v3d-nosec" hidden><span>Нет данных по секторам для этого класса — метка не едет.</span></div>' +
        '<div class="gl-tr-touchhint" hidden>Вращайте двумя пальцами</div>' +
        '<div class="gl-tr-v3d-msg gl-tr-v3d-msg--lost" hidden><span><span class="gl-tr-lost-t">3D-схема перезапускается…</span><button type="button" class="gl-tr-ib gl-tr-ib--y gl-tr-lost-b" hidden>Перезапустить 3D</button></span></div>' +
        '<div class="gl-tr-hud"><div class="gl-tr-hud-box"><span class="gl-tr-hud-time">0:00.000</span><span class="gl-tr-pill">S1</span></div></div>' +
      '</div>' +
      '<div class="gl-tr-under"><div class="gl-tr-ctrl"><button type="button" class="gl-tr-ib gl-tr-ib--y" data-a="play">Пауза</button><button type="button" class="gl-tr-ib" data-a="restart">Сначала</button>' +
        '<div class="gl-tr-seg" role="group" aria-label="Скорость воспроизведения"><button type="button" data-r="0.5" aria-pressed="false">0.5×</button><button type="button" data-r="1" aria-pressed="true">1×</button><button type="button" data-r="2" aria-pressed="false">2×</button><button type="button" data-r="4" aria-pressed="false">4×</button></div></div>' +
        '<label class="gl-tr-toggle"><input type="checkbox" checked data-g="1"> Призрак идеального круга</label>' +
        '<div class="gl-tr-gapline">Отставание от идеального круга: <b class="gl-tr-gv">+0.000 с</b></div></div>';
    var q$ = function (s) { return box.querySelector(s); };
    var view = q$('.gl-tr-v3d');
    view.style.aspectRatio = VIEW_W + ' / ' + VIEW_H;  // пропорции поля схемы, не ниже 260 px (CSS)
    view.insertBefore(renderer.domElement, view.firstChild);

    var dirty = true, onScreen = true, lastDraw = 0, lostTimer = null, io = null, ro = null;
    if (window.IntersectionObserver) {
      io = new IntersectionObserver(function (en) { onScreen = en[0].isIntersecting; if (onScreen) dirty = true; });
      io.observe(view);
    }
    controls.addEventListener('change', function () { dirty = true; });
    renderer.domElement.addEventListener('webglcontextlost', function (e) {
      e.preventDefault(); running = false;
      var m = q$('.gl-tr-v3d-msg--lost'); m.hidden = false;
      lostTimer = setTimeout(function () {
        q$('.gl-tr-lost-t').textContent = '3D-схема остановилась: браузеру не хватило памяти видеокарты.';
        q$('.gl-tr-lost-b').hidden = false;
      }, 2500);
    });
    renderer.domElement.addEventListener('webglcontextrestored', function () { clearTimeout(lostTimer); onRebuild(); });
    q$('.gl-tr-lost-b').addEventListener('click', function () { clearTimeout(lostTimer); onRebuild(); });

    // телефон: один палец — прокрутка страницы, два — вращение и масштаб
    controls.touches = { ONE: null, TWO: THREE.TOUCH.DOLLY_ROTATE };
    renderer.domElement.style.touchAction = 'pan-y';
    var hintT = null;
    ['touchstart', 'touchmove'].forEach(function (ev) {
      view.addEventListener(ev, function (e) {
        var h = q$('.gl-tr-touchhint');
        if (e.touches.length < 2) {
          e.stopPropagation();
          if (ev === 'touchstart' && cam !== 'chase') { h.hidden = false; clearTimeout(hintT); hintT = setTimeout(function () { h.hidden = true; }, 1400); }
        } else { h.hidden = true; }
      }, { capture: true, passive: true });
    });

    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var cls = null, recCum = null, ghCum = null, t = 0, hold = 0, playing = !reduce, rate = 1, cam = 'orbit', running = false, host = null, sized = false;
    q$('[data-a="play"]').textContent = playing ? 'Пауза' : 'Старт';
    box.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      dirty = true;
      if (b.dataset.a === 'play') { playing = !playing; b.textContent = playing ? 'Пауза' : 'Старт'; }
      if (b.dataset.a === 'restart') { t = 0; hold = 0; trN = 0; }
      if (b.dataset.r) { rate = +b.dataset.r; box.querySelectorAll('[data-r]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); }); }
      if (b.dataset.c) setCam(b.dataset.c);
    });
    var ghostOk = true;
    q$('[data-g]').addEventListener('change', function (e) { ghost.visible = e.target.checked && !!recCum && ghostOk; dirty = true; });

    function setCam(m) {
      cam = m;
      box.querySelectorAll('[data-c]').forEach(function (x) { x.setAttribute('aria-pressed', String(x.dataset.c === m)); });
      controls.enabled = m !== 'chase';
      rec.userData.glow.visible = ghost.userData.glow.visible = m !== 'chase';
      var tanH = Math.tan(camera.fov * Math.PI / 360), fit = Math.max(plateH / 2 / tanH, plateW / 2 / (tanH * camera.aspect));
      var mid = new THREE.Vector3((pa[0] + pb[0]) / 2, 0, (pa[1] + pb[1]) / 2);
      var dir = m === 'orbit' ? new THREE.Vector3(-0.25, 0.75, 0.62).normalize() : new THREE.Vector3(0, 1, 0.00001).normalize();
      if (m !== 'chase') {
        // приближение под окно: вписываем саму трассу (не подложку с полями), угол камеры не меняется
        var xs = P.map(function (q) { return q[0]; }), zs = P.map(function (q) { return q[1]; });
        var tmid = new THREE.Vector3((Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2, 0, (Math.min.apply(null, zs) + Math.max.apply(null, zs)) / 2);
        var probe = [];
        for (var pi = 0; pi < N; pi += 8) {
          var w = HALF + 6;  // полотно и столбики поворотов/ворот
          probe.push(new THREE.Vector3(P[pi][0] + Nr[pi][0] * w, 0, P[pi][1] + Nr[pi][1] * w), new THREE.Vector3(P[pi][0] - Nr[pi][0] * w, 0, P[pi][1] - Nr[pi][1] * w));
        }
        var v = new THREE.Vector3();
        var fits = function (dist) {
          camera.position.copy(tmid).addScaledVector(dir, dist); camera.lookAt(tmid); camera.updateMatrixWorld();
          return probe.every(function (c) { v.copy(c).project(camera); return Math.abs(v.x) <= 0.92 && Math.abs(v.y) <= 0.86; });
        };
        var lo = 5, hi = fit * 4;
        for (var it = 0; it < 30; it++) { var md = (lo + hi) / 2; if (fits(md)) hi = md; else lo = md; }
        fits(hi);
        controls.target.copy(tmid);
      }
      controls.update(); dirty = true;
    }
    function resize() {
      if (!host) return;
      var w = view.clientWidth, h = view.clientHeight;
      if (!w || !h) return;
      var first = !sized; sized = true;
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); dirty = true;
      if (first && cam !== 'chase') setCam(cam);
    }
    if (window.ResizeObserver) { ro = new ResizeObserver(resize); ro.observe(view); } else window.addEventListener('resize', resize);
    setCam('orbit');

    var cp = new THREE.Vector3(), cl = new THREE.Vector3(), last = performance.now(), lastGap = 0;
    function place(g, s) {
      var u = g.userData;
      // колёса крутятся на пройденное расстояние; скачок (новый круг, «Сначала») не крутит
      if (u.px !== undefined) { var d = Math.hypot(s.x - u.px, s.z - u.pz); if (d > 0 && d < 60) window.GlKart3D.roll(g, d); }
      u.px = s.x; u.pz = s.z;
      g.position.set(s.x, 0.1, s.z); g.rotation.y = -Math.atan2(s.tz, s.tx);
    }
    function frame(now) {
      if (!running) return;
      requestAnimationFrame(frame);
      if (!onScreen || document.hidden) { last = now; return; }
      if (isTouch && now - lastDraw < 32) return;
      lastDraw = now;
      var dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (recCum) {
        var total = recCum[N];
        if (playing) {
          if (hold > 0) { hold -= dt; if (hold <= 0) { t = 0; trN = 0; } }
          else { t += dt * rate; if (t >= total) { t = total; hold = 1.6; } }
        }
        var s = sample(recCum, t), sg = sample(ghCum, Math.min(t, ghCum[N]));
        place(rec, s); place(ghost, sg);
        if (playing && hold <= 0) {
          if (trN < TR) trN++;
          trp.copyWithin(3, 0, (TR - 1) * 3); trp[0] = s.x; trp[1] = 0.6; trp[2] = s.z;
          trg.setDrawRange(0, trN); trg.attributes.position.needsUpdate = true;
        }
        var cs = t >= total ? 2 : secOf(s.i), pill = q$('.gl-tr-pill');
        q$('.gl-tr-hud-time').textContent = fmt(t);
        pill.textContent = SEC[cs].name; pill.style.background = SEC[cs].color; pill.style.color = SEC[cs].on;
        var gl = q$('.gl-tr-gapline');
        gl.style.visibility = ghost.visible ? 'visible' : 'hidden';
        if (ghost.visible && (now - lastGap > 100 || t >= total || t === 0)) {
          lastGap = now;
          // отставание от призрака в той же точке трассы
          var fi = (t - recCum[s.i]) / (recCum[s.i + 1] - recCum[s.i]);
          var gt = t >= total ? ghCum[N] : ghCum[s.i] + Math.max(0, Math.min(1, fi)) * (ghCum[s.i + 1] - ghCum[s.i]);
          q$('.gl-tr-gv').textContent = '+' + Math.max(0, t - gt).toFixed(3) + ' с';
        }
        if (cam === 'chase') {
          cp.set(s.x - s.tx * 34, 16, s.z - s.tz * 34); cl.set(s.x + s.tx * 30, 0, s.z + s.tz * 30);
          camera.position.lerp(cp, 0.08); controls.target.lerp(cl, 0.12); camera.lookAt(controls.target);
        }
      }
      var moved = (cam !== 'chase' || !recCum) ? controls.update() : true;
      if ((recCum && playing) || moved || dirty) { renderer.render(scene, camera); dirty = false; }
    }

    return {
      mount: function (el) {
        host = el; el.innerHTML = ''; el.appendChild(box); resize(); dirty = true;
        if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); }
      },
      pause: function () { running = false; },
      destroy: function () {
        running = false; clearTimeout(lostTimer);
        if (io) io.disconnect();
        if (ro) ro.disconnect(); else window.removeEventListener('resize', resize);
        controls.dispose();
        scene.traverse(function (o) { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
        textures.forEach(function (x) { x.dispose(); });
        renderer.dispose(); box.remove();
      },
      setSector: function (k) {
        stripes.forEach(function (m, i) { m.material.opacity = k === -1 || k === i ? 1 : 0.12; });
        bands.forEach(function (m, i) { m.visible = k === i; });
        dirty = true;
      },
      /* c: {record_ms, sectors_ms: [ms, ms, ms] | null} */
      setClass: function (c) {
        if (cls === c) return;
        cls = c; t = 0; hold = 0; trN = 0; dirty = true;
        // средняя скорость сектора = длина сектора по схеме / его время; больше MAX_SECTOR_KMH — время секторов
        // не сходится со схемой (ошибка в протоколе или граница сектора не там) — метку не пускаем
        var shares = [b1 / N, (b2 - b1) / N, (N - b2) / N];
        var plausible = !!(c && c.sectors_ms && c.record_ms) && c.sectors_ms.every(function (ms, k) {
          return LENGTH_M * shares[k] / (ms / 1000) * 3.6 <= (c.max_sector_kmh || MAX_SECTOR_KMH);
        });
        q$('.gl-tr-v3d-nosec span').textContent = c && c.sectors_ms && !plausible
          ? 'Время секторов не сходится со схемой трассы — метка не едет.'
          : 'Нет данных по секторам для этого класса — метка не едет.';
        if (plausible) {
          var sec = c.sectors_ms.map(function (x) { return x / 1000; }), rcd = c.record_ms / 1000;
          var ideal = sec[0] + sec[1] + sec[2];
          // время секторов рекордного круга = лучшие секторы × (рекорд / идеальный круг)
          vB = speedsForLap(rcd, c.top_kmh);
          recCum = profile(sec.map(function (x) { return x * rcd / ideal; }));
          ghCum = profile(sec);
          // идеальный круг не быстрее рекорда (рекорд — с круга без секторов) — призрак отставал бы, его не показываем
          ghostOk = ideal < rcd;
          rec.visible = true; ghost.visible = ghostOk && q$('[data-g]').checked;
          q$('.gl-tr-toggle').style.display = ghostOk ? '' : 'none';
          q$('.gl-tr-v3d-nosec').hidden = true; q$('.gl-tr-under').style.visibility = '';
        } else {
          recCum = null; ghCum = null; rec.visible = false; ghost.visible = false;
          q$('.gl-tr-v3d-nosec').hidden = false; q$('.gl-tr-under').style.visibility = 'hidden';
          q$('.gl-tr-hud-time').textContent = c && c.record_ms ? fmt(c.record_ms / 1000) : '—';
          var pill = q$('.gl-tr-pill');
          pill.textContent = 'рекорд'; pill.style.background = '#2a2a35'; pill.style.color = '#eceff1';
        }
      }
    };
  }

  window.GlTrack3D = { build: build };
})();
