/* Метка 3D-схемы трассы — модель карта с пилотом (по фото Sodi, CRG, Birel; шлем — Bell KC7, Arai CK-6, OMP KJ-8).
   Строится из примитивов three.js r128, без внешних файлов: обтекатели — «лофт» по сечениям, шины и диски —
   LatheGeometry, раскраска и логотип — текстуры на canvas в цветах Gripline.

   Оси как у метки: +x вперёд, +y вверх, +z вправо по ходу. Размеры — метры настоящего CIK-карта
   (длина ≈ 1,85, ширина 1,38, база 1,04); внешняя группа двигается по трассе, внутренняя масштабируется
   на scale (TrackPageSettings.kart_scale в админке — карт настоящего размера в «Обзоре» не разглядеть).

   GlKart3D.build(color, {ghost, driver, scale}) → THREE.Group, userData: {wheels, glow}
   GlKart3D.roll(group, metres) — прокрутить колёса на пройденное расстояние.
   Подключается до track_3d.js (track_page.js, редактор схемы). Текстуры общие на страницу. */
(function () {
  'use strict';

  function radialTex(inner, outer) {
    var c = document.createElement('canvas'); c.width = c.height = 64;
    var x = c.getContext('2d'), g = x.createRadialGradient(32, 32, 2, 32, 32, 30);
    g.addColorStop(0, inner); g.addColorStop(1, outer); x.fillStyle = g; x.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  }
  var shadowTex = radialTex('rgba(0,0,0,0.6)', 'rgba(0,0,0,0)');
  var glowTex = { };
  function glowFor(color) {
    if (!glowTex[color]) glowTex[color] = radialTex('#' + new THREE.Color(color).getHexString(), 'rgba(0,0,0,0)');
    return glowTex[color];
  }


  /* Обтекатели — «лофт» по сечениям: каждое сечение — скруглённый прямоугольник (суперэллипс)
     в плоскости z–y на своей координате x; между заданными сечениями — сглаживание Catmull-Rom.
     UV: u — вдоль оси лофта, v — по периметру сечения (off/dir задают, где на периметре v = 0.5). */
  var LOFT_KEYS = ['x', 'w', 'yb', 'yt', 'zc', 'slope', 'dip', 'nTop', 'nBot'];
  function cr(p0, p1, p2, p3, t) {
    var t2 = t * t, t3 = t2 * t;
    return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
  }
  function loft(secs, mat, o) {
    o = o || {};
    var M = o.M || 36, sub = o.sub || 6, off = o.off || 0, dir = o.dir || 1, uvByX = !!o.uvByX, uvArc = !!o.uvArc;
    secs = secs.map(function (s) { return { x: s.x, w: s.w, yb: s.yb, yt: s.yt, zc: s.zc || 0, slope: s.slope || 0, dip: s.dip || 0, nTop: s.nTop || o.nTop || 3, nBot: s.nBot || o.nBot || 6 }; });
    var rings = [];
    for (var i = 0; i < secs.length - 1; i++) {
      var a = secs[Math.max(0, i - 1)], b = secs[i], c = secs[i + 1], d = secs[Math.min(secs.length - 1, i + 2)];
      for (var k = 0; k < sub; k++) {
        var t = k / sub, r = {};
        LOFT_KEYS.forEach(function (key) { r[key] = cr(a[key], b[key], c[key], d[key], t); });
        rings.push(r);
      }
    }
    rings.push(secs[secs.length - 1]);
    function ringPts(s) {
      var out = [], ym = (s.yb + s.yt) / 2, h = (s.yt - s.yb) / 2;
      for (var j = 0; j <= M; j++) {
        var th = off + dir * 2 * Math.PI * j / M, co = Math.cos(th), si = Math.sin(th), n = si >= 0 ? s.nTop : s.nBot;
        var z = s.zc + s.w / 2 * Math.sign(co) * Math.pow(Math.abs(co), 2 / n);
        var y = ym + h * Math.sign(si) * Math.pow(Math.abs(si), 2 / n), zz = (z - s.zc) / (s.w / 2);
        if (si > 0) y += (s.slope * zz - s.dip * (1 - zz * zz)) * si;
        out.push([s.x, y, z]);
      }
      return out;
    }
    var pos = [], uv = [], idx = [], R = M + 1;
    rings.forEach(function (s, ri) {
      var uu = uvByX ? (s.x - rings[0].x) / (rings[rings.length - 1].x - rings[0].x) : ri / (rings.length - 1);
      // uvArc: v — по длине периметра, а не по углу; иначе на плоских местах суперэллипса текстура растягивается
      var rp = ringPts(s), cum = [0];
      for (var jj = 1; jj <= M; jj++) cum.push(cum[jj - 1] + Math.hypot(rp[jj][1] - rp[jj - 1][1], rp[jj][2] - rp[jj - 1][2]));
      rp.forEach(function (p, j) { pos.push(p[0], p[1], p[2]); uv.push(uu, uvArc ? cum[j] / cum[M] : j / M); });
    });
    for (var ri = 0; ri < rings.length - 1; ri++) for (var j = 0; j < M; j++) {
      var p = ri * R + j, q = p + 1, u = p + R, v = q + R;
      idx.push(p, u, q, q, u, v);
    }
    // торцы — отдельные вершины, чтобы край оставался чётким
    [0, rings.length - 1].forEach(function (ri) {
      var s = rings[ri], base = pos.length / 3, pts = ringPts(s);
      pos.push(s.x, (s.yb + s.yt) / 2, s.zc); uv.push(ri ? 1 : 0, 0.02);
      pts.forEach(function (pt) { pos.push(pt[0], pt[1], pt[2]); uv.push(ri ? 1 : 0, 0.02); });
      for (var j = 0; j < M; j++) idx.push(base, base + 1 + j, base + 2 + j);
    });
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx); g.computeVertexNormals();
    return new THREE.Mesh(g, mat);
  }
  function mirrorSecs(secs) { return secs.map(function (s) { var o = Object.assign({}, s); o.zc = -(s.zc || 0); o.slope = -(s.slope || 0); return o; }); }
  function box(w, h, d, mat, x, y, z) { var m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.position.set(x, y, z); return m; }
  function tube(pts, r, mat) {
    var curve = new THREE.CatmullRomCurve3(pts.map(function (p) { return new THREE.Vector3(p[0], p[1], p[2]); }));
    return new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(8, pts.length * 10), r, 8, false), mat);
  }
  function cyl(r, len, mat, axis, x, y, z, seg) {
    var m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg || 20), mat);
    if (axis === 'z') m.rotation.x = Math.PI / 2; else if (axis === 'x') m.rotation.z = Math.PI / 2;
    m.position.set(x, y, z); return m;
  }
  function mirror(pts) { return pts.map(function (p) { return [p[0], p[1], -p[2]]; }); }

  // профиль шины для LatheGeometry: (радиус, вдоль оси), скруглённые плечи
  function tyreGeo(R, w, rimR) {
    var pts = [], sh = Math.min(0.035, w * 0.28), hw = w / 2, i, a;
    pts.push(new THREE.Vector2(rimR, -hw + 0.01));
    pts.push(new THREE.Vector2(rimR + (R - rimR) * 0.45, -hw));
    for (i = 0; i <= 6; i++) { a = Math.PI / 2 * (i / 6); pts.push(new THREE.Vector2(R - sh + Math.sin(a) * sh, -hw + sh - Math.cos(a) * sh)); }
    for (i = 0; i <= 6; i++) { a = Math.PI / 2 * (i / 6); pts.push(new THREE.Vector2(R - sh + Math.cos(a) * sh, hw - sh + Math.sin(a) * sh)); }
    pts.push(new THREE.Vector2(rimR + (R - rimR) * 0.45, hw));
    pts.push(new THREE.Vector2(rimR, hw - 0.01));
    return new THREE.LatheGeometry(pts, 40);
  }
  // литой диск: закраины и «тарелка» к ступице, наружная сторона — +y
  function rimGeo(rimR, w) {
    var hw = w / 2;
    return new THREE.LatheGeometry([
      new THREE.Vector2(0.02, hw * 0.2), new THREE.Vector2(0.04, hw * 0.35), new THREE.Vector2(rimR * 0.8, hw * 0.55),
      new THREE.Vector2(rimR - 0.004, hw - 0.004), new THREE.Vector2(rimR + 0.006, hw), new THREE.Vector2(rimR + 0.006, hw - 0.01),
      new THREE.Vector2(rimR, hw - 0.012), new THREE.Vector2(rimR, -hw + 0.012), new THREE.Vector2(rimR + 0.006, -hw + 0.01),
      new THREE.Vector2(rimR + 0.006, -hw), new THREE.Vector2(rimR - 0.004, -hw + 0.004), new THREE.Vector2(0.03, -hw * 0.3)
    ], 32);
  }

  /* ---------- раскраска: холсты в цветах Gripline ---------- */
  var INK = '#15151c', GOLD = '#ffc107', CHALK = '#f1f1ec';
  var WORD = '900 italic {s}px "Arial Black", "Inter Tight", Arial, sans-serif';
  function canvasTex(W, H, draw) {
    var c = document.createElement('canvas'); c.width = W; c.height = H;
    draw(c.getContext('2d'), W, H);
    var t = new THREE.CanvasTexture(c); t.encoding = THREE.sRGBEncoding; t.anisotropy = 8; return t;
  }
  function rrect(x, X, Y, w, h, r) { x.beginPath(); x.moveTo(X + r, Y); x.arcTo(X + w, Y, X + w, Y + h, r); x.arcTo(X + w, Y + h, X, Y + h, r); x.arcTo(X, Y + h, X, Y, r); x.arcTo(X, Y, X + w, Y, r); x.closePath(); }
  // боковой понтон: u — спереди назад, наружная сторона — средняя полоса холста. Правый — зеркально.
  function podLivery(mirrored) {
    return canvasTex(1024, 640, function (x, W, H) {
      if (mirrored) { x.translate(W, 0); x.scale(-1, 1); }
      x.fillStyle = INK; x.fillRect(0, 0, W, H);
      x.fillStyle = GOLD; x.fillRect(0, 0.16 * H, W, 0.66 * H);
      // чёрный клин спереди и белая линия по его краю
      x.fillStyle = INK; x.beginPath(); x.moveTo(0, 0.16 * H); x.lineTo(0.3 * W, 0.16 * H);
      x.quadraticCurveTo(0.15 * W, 0.5 * H, 0.1 * W, 0.82 * H); x.lineTo(0, 0.82 * H); x.closePath(); x.fill();
      x.strokeStyle = CHALK; x.lineWidth = 0.022 * H; x.beginPath(); x.moveTo(0.345 * W, 0.16 * H); x.quadraticCurveTo(0.2 * W, 0.5 * H, 0.15 * W, 0.82 * H); x.stroke();
      // нижняя чёрная полоса, поднимается к корме
      x.fillStyle = INK; x.beginPath(); x.moveTo(0.14 * W, 0.82 * H); x.lineTo(W, 0.82 * H); x.lineTo(W, 0.6 * H); x.lineTo(0.4 * W, 0.74 * H); x.closePath(); x.fill();
      x.strokeStyle = CHALK; x.lineWidth = 0.012 * H; x.beginPath(); x.moveTo(0.4 * W, 0.71 * H); x.lineTo(W, 0.57 * H); x.stroke();
      // надпись
      x.fillStyle = INK; x.font = WORD.replace('{s}', Math.round(0.16 * H)); x.textAlign = 'center'; x.textBaseline = 'middle';
      x.fillText('GRIPLINE', 0.55 * W, 0.44 * H);
      // номер на корме понтона
      x.fillStyle = CHALK; rrect(x, 0.81 * W, 0.22 * H, 0.15 * W, 0.34 * H, 20); x.fill();
      x.lineWidth = 6; x.strokeStyle = INK; x.stroke();
      x.fillStyle = INK; x.font = '900 ' + Math.round(0.28 * H) + 'px "Arial Black", Arial, sans-serif'; x.fillText('1', 0.885 * W, 0.4 * H);
    });
  }
  // нос: u — поперёк, слева направо; v = 0.75 — верх, 0.5 — передняя стенка
  function noseLivery() {
    return canvasTex(1024, 640, function (x, W, H) {
      x.fillStyle = INK; x.fillRect(0, 0, W, H);
      x.fillStyle = GOLD; x.fillRect(0, 0.06 * H, W, 0.44 * H);
      x.strokeStyle = CHALK; x.lineCap = 'round';
      [[0.012, 0.13], [0.008, 0.19]].forEach(function (s) {
        x.lineWidth = s[0] * H * 2; x.beginPath(); x.moveTo(0.06 * W, s[1] * H); x.lineTo(0.5 * W, (s[1] + 0.2) * H); x.lineTo(0.94 * W, s[1] * H); x.stroke();
      });
      x.fillStyle = INK; x.beginPath(); x.moveTo(0.36 * W, 0.5 * H); x.lineTo(0.5 * W, 0.4 * H); x.lineTo(0.64 * W, 0.5 * H); x.closePath(); x.fill();
      x.fillRect(0, 0, 0.035 * W, H); x.fillRect(0.965 * W, 0, 0.035 * W, H);
    });
  }
  // передняя панель: u — от носа к рулю; v = 0.75 — лицевая сторона
  function panelLivery() {
    return canvasTex(512, 256, function (x, W, H) {
      x.fillStyle = INK; x.fillRect(0, 0, W, H);
      x.fillStyle = GOLD; x.fillRect(0.16 * W, 0.08 * H, 0.84 * W, 0.34 * H);
      x.strokeStyle = CHALK; x.lineWidth = 3; x.beginPath(); x.moveTo(0.2 * W, 0.12 * H); x.lineTo(W, 0.12 * H); x.moveTo(0.2 * W, 0.38 * H); x.lineTo(W, 0.38 * H); x.stroke();
    });
  }
  // номерная табличка: цифра повёрнута так, чтобы читалась спереди
  function plateTex() {
    return canvasTex(260, 340, function (x, W, H) {
      x.fillStyle = CHALK; rrect(x, 8, 8, W - 16, H - 16, 60); x.fill(); x.lineWidth = 10; x.strokeStyle = INK; x.stroke();
      x.translate(W / 2, H / 2); x.rotate(Math.PI / 2);
      x.fillStyle = INK; x.font = '900 190px "Arial Black", Arial, sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText('1', 0, 8);
    });
  }
  function finsTex() {
    return canvasTex(128, 128, function (x, W, H) {
      x.fillStyle = '#3a3d45'; x.fillRect(0, 0, W, H);
      x.fillStyle = '#8d929c'; for (var i = 0; i < W; i += 6) x.fillRect(i, 0, 2, H);
    });
  }
  // шлем: u — вокруг головы (0.5 — лицо, 0.25 — правый бок, 0.75 — левый, 0 и 1 — затылок), v — от макушки вниз
  function helmetTex() {
    return canvasTex(1024, 512, function (x, W, H) {
      x.fillStyle = GOLD; x.fillRect(0, 0, W, H);
      x.fillStyle = INK; x.fillRect(0, 0.74 * H, W, 0.26 * H);
      // гребень по центру: от лба через макушку к затылку
      x.fillRect(0.465 * W, 0, 0.07 * W, 0.34 * H); x.fillRect(0, 0, 0.05 * W, 0.6 * H); x.fillRect(0.95 * W, 0, 0.05 * W, 0.6 * H);
      x.fillStyle = CHALK;
      [0.452, 0.535].forEach(function (u) { x.fillRect(u * W, 0, 0.013 * W, 0.34 * H); });
      [0.05, 0.937].forEach(function (u) { x.fillRect(u * W, 0, 0.013 * W, 0.6 * H); });
      x.fillRect(0, 0.725 * H, W, 0.015 * H);
      // угловатые блоки на боках, острым концом к лицу; белая обводка со сдвигом
      [[0.25, 1], [0.75, -1]].forEach(function (sd) {
        var c = sd[0] * W, d = sd[1] * W;
        function poly(o) {
          x.beginPath(); x.moveTo(c - 0.17 * d, 0.72 * H - o); x.lineTo(c - 0.05 * d, 0.4 * H - o); x.lineTo(c + 0.09 * d, 0.4 * H - o);
          x.lineTo(c + 0.16 * d, 0.5 * H - o); x.lineTo(c + 0.04 * d, 0.5 * H - o); x.lineTo(c - 0.02 * d, 0.72 * H - o); x.closePath();
        }
        x.fillStyle = INK; poly(0); x.fill();
        x.strokeStyle = CHALK; x.lineWidth = 7; poly(0.045 * H); x.stroke();
      });
    });
  }
  // знак «Секторы» (logo/SVG/mark/gripline-mark-color.svg, версия для тёмного фона) и под ним «GripLine».
  // Рисуется в миллиметрах, центр блока — (0, 0), ось y вниз.
  function drawLogo(x, k) {
    var m = 160 * k, s = m / 64;
    x.save(); x.translate(-m / 2, -125 * k); x.scale(s, s);
    x.lineCap = 'round'; x.lineWidth = 7;
    [['M36.58 8.44 A24 24 0 0 1 54.69 39.81', '#E24B4A'], ['M50.11 47.74 A24 24 0 0 1 13.89 47.74', '#E8A33D'], ['M9.31 39.81 A24 24 0 0 1 27.42 8.44', '#F0EEE8']].forEach(function (p) {
      x.strokeStyle = p[1]; x.stroke(new Path2D(p[0]));
    });
    x.lineWidth = 6; x.strokeStyle = '#F0EEE8'; x.stroke(new Path2D('M32 32 L32 15.5'));
    x.fillStyle = '#F0EEE8'; x.beginPath(); x.arc(32, 32, 3.5, 0, Math.PI * 2); x.fill();
    x.restore();
    x.fillStyle = '#F0EEE8'; x.font = '800 ' + Math.round(42 * k) + 'px Archivo, "Arial Black", Arial, sans-serif';
    x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText('GripLine', 0, 70 * k);
  }
  /* комбинезон: текстура на корпус пилота. u — вверх по корпусу (0…0,6 м), v — по периметру:
     0.25 — спина, 0.75 — грудь. Логотип повёрнут так, чтобы читаться и сзади, и спереди. */
  var SUIT_LEN = 0.6, SUIT_PERIM = 1.1;
  function suitTex() {
    return canvasTex(512, 1024, function (x, W, H) {
      x.fillStyle = '#2b2d38'; x.fillRect(0, 0, W, H);
      // жёлтые лампасы по бокам
      x.fillStyle = GOLD; [0, 0.5, 1].forEach(function (v) { x.fillRect(0, (1 - v) * H - 7, W, 14); });
      function place(h, v, k) {
        x.save(); x.translate(h / SUIT_LEN * W, (1 - v) * H);
        x.scale(W / SUIT_LEN / 1000, H / SUIT_PERIM / 1000); x.rotate(Math.PI / 2);
        drawLogo(x, k); x.restore();
      }
      place(0.42, 0.25, 1.15);  // спина
      place(0.4, 0.75, 0.8);    // грудь
    });
  }
  var LIV = null;
  function livery() {
    if (!LIV) LIV = { podL: podLivery(false), podR: podLivery(true), nose: noseLivery(), panel: panelLivery(), plate: plateTex(), fins: finsTex(), helmet: helmetTex(), suit: suitTex() };
    return LIV;
  }

  /* ---------- модель карта ----------
     По референсам Sodi, CRG и Birel: широкий нос с «крыльями», длинная передняя панель-лопасть,
     узкие высокие понтоны на трубчатых рамках, длинное сиденье-ванна, двигатель Rotax справа, радиатор слева.
     Оси как у метки на сайте: +x вперёд, +y вверх, +z вправо. Метры: длина ≈ 1,85, ширина 1,38, база 1,04. */
  function buildKart(color, ghost, withDriver, S) {
    var outer = new THREE.Group(), g = new THREE.Group(); outer.add(g); g.scale.setScalar(S);
    var M, L = ghost ? null : livery();
    if (ghost) {
      var gm = new THREE.MeshStandardMaterial({ color: color, emissive: color, emissiveIntensity: 0.55, transparent: true, opacity: 0.35, side: THREE.DoubleSide });
      M = {}; ['podL', 'podR', 'nose', 'panel', 'plate', 'bumper', 'tyre', 'rim', 'frame', 'seat', 'suit', 'glove', 'alu', 'red', 'black', 'visor', 'tank', 'fins', 'paint'].forEach(function (k) { M[k] = gm; });
    } else {
      var liv = function (map) { return new THREE.MeshStandardMaterial({ map: map, roughness: 0.32, metalness: 0.1, emissive: 0xffffff, emissiveMap: map, emissiveIntensity: 0.1, side: THREE.DoubleSide }); };
      M = {
        podL: liv(L.podL), podR: liv(L.podR), nose: liv(L.nose), panel: liv(L.panel),
        plate: new THREE.MeshStandardMaterial({ map: L.plate, roughness: 0.5 }),
        paint: new THREE.MeshStandardMaterial({ color: color, roughness: 0.32, side: THREE.DoubleSide }),
        bumper: new THREE.MeshStandardMaterial({ color: 0x17171c, roughness: 0.6, side: THREE.DoubleSide }),
        tyre: new THREE.MeshStandardMaterial({ color: 0x111113, roughness: 0.9, side: THREE.DoubleSide }),
        rim: new THREE.MeshStandardMaterial({ color: 0x24252b, roughness: 0.35, metalness: 0.6, side: THREE.DoubleSide }),
        frame: new THREE.MeshStandardMaterial({ color: 0xc4c8d0, roughness: 0.22, metalness: 0.9 }),
        seat: new THREE.MeshStandardMaterial({ color: 0xa9aeb6, roughness: 0.5, metalness: 0.35, side: THREE.DoubleSide }),
        suit: new THREE.MeshStandardMaterial({ color: 0x2b2d38, roughness: 0.75, side: THREE.DoubleSide }),
        glove: new THREE.MeshStandardMaterial({ color: 0x15151a, roughness: 0.8 }),
        alu: new THREE.MeshStandardMaterial({ color: 0xaeb3bc, roughness: 0.35, metalness: 0.75 }),
        red: new THREE.MeshStandardMaterial({ color: 0xd8262b, roughness: 0.4, metalness: 0.3 }),
        black: new THREE.MeshStandardMaterial({ color: 0x141418, roughness: 0.55 }),
        visor: new THREE.MeshStandardMaterial({ color: 0x07070b, roughness: 0.08, metalness: 0.6 }),
        tank: new THREE.MeshStandardMaterial({ color: 0xeef0f2, roughness: 0.25, transparent: true, opacity: 0.78, side: THREE.DoubleSide }),
        fins: new THREE.MeshStandardMaterial({ map: L.fins, roughness: 0.5, metalness: 0.5 })
      };
    }
    function add(m) { g.add(m); return m; }

    if (!ghost) {
      var sh = new THREE.Mesh(new THREE.PlaneGeometry(2.5, 1.9), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
      sh.rotation.x = -Math.PI / 2; sh.position.y = 0.012; g.add(sh);
    }

    /* рама: хромированные трубы 30 мм */
    var F = M.frame, rr = 0.015;
    var rail = [[-0.66, 0.045, 0.24], [-0.3, 0.045, 0.25], [0.1, 0.045, 0.22], [0.45, 0.05, 0.15], [0.66, 0.065, 0.12]];
    add(tube(rail, rr, F)); add(tube(mirror(rail), rr, F));
    add(tube([[0.66, 0.065, -0.12], [0.66, 0.065, 0.12]], rr, F));
    var toKing = [[0.6, 0.06, 0.13], [0.54, 0.09, 0.32], [0.52, 0.11, 0.43]];
    add(tube(toKing, rr, F)); add(tube(mirror(toKing), rr, F));
    add(tube([[-0.1, 0.045, -0.25], [-0.1, 0.045, 0.25]], rr, F));
    add(tube([[-0.66, 0.045, -0.24], [-0.66, 0.045, 0.24]], rr, F));
    // рамки понтонов
    var nerf = [[0.3, 0.07, 0.25], [0.28, 0.11, 0.5], [-0.28, 0.11, 0.51], [-0.34, 0.07, 0.26]];
    add(tube(nerf, 0.011, F)); add(tube(mirror(nerf), 0.011, F));
    var nerf2 = [[0.24, 0.17, 0.5], [-0.24, 0.17, 0.51]];
    add(tube(nerf2, 0.009, F)); add(tube(mirror(nerf2), 0.009, F));
    // передний бампер под носом и кронштейн панели
    add(tube([[0.64, 0.06, -0.2], [0.9, 0.07, -0.3], [1.0, 0.08, 0], [0.9, 0.07, 0.3], [0.64, 0.06, 0.2]], 0.011, F));
    add(tube([[0.66, 0.065, 0], [0.62, 0.27, 0]], 0.01, F));
    var stay = [[-0.42, 0.05, 0.18], [-0.44, 0.34, 0.12]];
    add(tube(stay, 0.009, F)); add(tube(mirror(stay), 0.009, F));
    // поворотные кулаки, рулевые тяги, колонка
    add(cyl(0.013, 0.12, F, 'y', 0.52, 0.13, 0.44)); add(cyl(0.013, 0.12, F, 'y', 0.52, 0.13, -0.44));
    add(tube([[0.47, 0.1, 0], [0.47, 0.11, 0.42]], 0.006, F)); add(tube([[0.47, 0.1, 0], [0.47, 0.11, -0.42]], 0.006, F));
    add(tube([[0.47, 0.11, 0], [0.18, 0.42, 0]], 0.012, F));
    // задняя ось, буксы, тормоз слева, звезда и кожух цепи справа
    add(cyl(0.025, 1.3, F, 'z', -0.52, 0.14, 0));
    add(box(0.05, 0.12, 0.03, M.alu, -0.52, 0.1, 0.42)); add(box(0.05, 0.12, 0.03, M.alu, -0.52, 0.1, -0.42));
    add(cyl(0.1, 0.012, M.alu, 'z', -0.52, 0.14, -0.13, 28));
    add(box(0.07, 0.05, 0.05, M.red, -0.44, 0.2, -0.13));
    add(box(0.42, 0.17, 0.03, M.black, -0.41, 0.15, 0.22));

    /* колёса: широкие слики, чёрные литые диски; вращение — группа rot */
    var wheels = [];
    function wheel(x, z, R, w) {
      var pivot = new THREE.Group(); pivot.position.set(x, R, z);
      var rot = new THREE.Group(); rot.rotation.x = Math.PI / 2; pivot.add(rot);
      var holder = new THREE.Group(); if (z < 0) holder.rotation.z = Math.PI; rot.add(holder);
      holder.add(new THREE.Mesh(tyreGeo(R, w, 0.064), M.tyre));
      holder.add(new THREE.Mesh(rimGeo(0.064, w - 0.01), M.rim));
      for (var b = 0; b < 3; b++) {
        var nut = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.012, 8), M.alu), a = b * Math.PI * 2 / 3;
        nut.position.set(Math.cos(a) * 0.028, w * 0.12, Math.sin(a) * 0.028); holder.add(nut);
      }
      g.add(pivot); wheels.push({ rot: rot, r: R, spin: 0 });
    }
    wheel(0.52, 0.52, 0.13, 0.13); wheel(0.52, -0.52, 0.13, 0.13);
    wheel(-0.52, 0.585, 0.14, 0.21); wheel(-0.52, -0.585, 0.14, 0.21);

    /* нос: лофт поперёк карта (локальная x → мировая z), центр выступает, «крылья» уходят назад и вверх */
    var nose = loft([
      { x: -0.58, zc: -0.765, w: 0.05, yb: 0.15, yt: 0.22 },
      { x: -0.545, zc: -0.775, w: 0.12, yb: 0.09, yt: 0.235 },
      { x: -0.42, zc: -0.8, w: 0.2, yb: 0.055, yt: 0.2 },
      { x: -0.22, zc: -0.86, w: 0.26, yb: 0.045, yt: 0.165 },
      { x: 0, zc: -0.89, w: 0.26, yb: 0.045, yt: 0.155 },
      { x: 0.22, zc: -0.86, w: 0.26, yb: 0.045, yt: 0.165 },
      { x: 0.42, zc: -0.8, w: 0.2, yb: 0.055, yt: 0.2 },
      { x: 0.545, zc: -0.775, w: 0.12, yb: 0.09, yt: 0.235 },
      { x: 0.58, zc: -0.765, w: 0.05, yb: 0.15, yt: 0.22 }
    ], M.nose, { M: 40, dir: -1, nBot: 8 });
    nose.rotation.y = -Math.PI / 2; add(nose);

    /* передняя панель: длинная лопасть от носа к рулю, слегка выгнута, номер наверху */
    var pA = [0.86, 0.12], pB = [0.29, 0.5], pLen = Math.hypot(pB[0] - pA[0], pB[1] - pA[1]);
    var pSecs = [[0, 0.11], [0.25, 0.14], [0.55, 0.22], [0.85, 0.28], [0.97, 0.27], [1.0, 0.2]].map(function (q) {
      var bow = -0.035 * Math.sin(Math.PI * q[0]);
      return { x: q[0] * pLen, w: q[1], yb: bow - 0.009, yt: bow + 0.009, nTop: 5, nBot: 5 };
    });
    var panelG = new THREE.Group(); panelG.position.set(pA[0], pA[1], 0);
    panelG.rotation.z = Math.atan2(pB[1] - pA[1], pB[0] - pA[0]); g.add(panelG);
    panelG.add(loft(pSecs, M.panel, { M: 28 }));
    var plate = new THREE.Mesh(new THREE.PlaneGeometry(0.13, 0.17), M.plate);
    plate.rotation.x = Math.PI / 2; plate.position.set(0.8 * pLen, -0.035 * Math.sin(Math.PI * 0.8) - 0.012, 0); panelG.add(plate);

    /* понтоны: узкие и высокие, по краям */
    var pod = [
      { x: 0.34, zc: 0.575, w: 0.03, yb: 0.08, yt: 0.12 },
      { x: 0.3, zc: 0.575, w: 0.065, yb: 0.06, yt: 0.18, nTop: 2.2 },
      { x: 0.12, zc: 0.578, w: 0.075, yb: 0.05, yt: 0.215, nTop: 2.2 },
      { x: -0.14, zc: 0.58, w: 0.075, yb: 0.05, yt: 0.225, nTop: 2.2 },
      { x: -0.31, zc: 0.582, w: 0.068, yb: 0.05, yt: 0.215, nTop: 2.2 },
      { x: -0.355, zc: 0.584, w: 0.03, yb: 0.07, yt: 0.15 }
    ];
    add(loft(pod, M.podR, { off: Math.PI, nBot: 6 }));
    add(loft(mirrorSecs(pod), M.podL, { off: 0, dir: -1, nBot: 6 }));

    /* задний бампер: чёрный, во всю ширину, с жёлтой вставкой по центру */
    add(loft([
      { x: -0.69, w: 1.18, yb: 0.08, yt: 0.15 },
      { x: -0.73, w: 1.38, yb: 0.05, yt: 0.2, nTop: 4 },
      { x: -0.82, w: 1.38, yb: 0.05, yt: 0.2, nTop: 4 },
      { x: -0.86, w: 1.26, yb: 0.07, yt: 0.15 }
    ], M.bumper, { M: 40 }));
    add(box(0.02, 0.05, 0.22, M.paint, -0.862, 0.13, 0));

    /* сиденье: длинная серебристая «ванна», спинка поднимается к оси */
    add(loft([
      { x: 0.06, w: 0.28, yb: 0.06, yt: 0.12, nTop: 4, nBot: 4 },
      { x: -0.04, w: 0.38, yb: 0.04, yt: 0.17, dip: 0.06, nTop: 4, nBot: 4 },
      { x: -0.2, w: 0.42, yb: 0.04, yt: 0.24, dip: 0.12, nTop: 4, nBot: 4 },
      { x: -0.34, w: 0.42, yb: 0.05, yt: 0.36, dip: 0.16, nTop: 4, nBot: 4 },
      { x: -0.43, w: 0.38, yb: 0.12, yt: 0.43, dip: 0.12, nTop: 4, nBot: 4 },
      { x: -0.46, w: 0.3, yb: 0.24, yt: 0.43, nTop: 4, nBot: 4 }
    ], M.seat, { M: 40 }));

    /* бак между ног */
    add(loft([{ x: 0.12, w: 0.08, yb: 0.08, yt: 0.16 }, { x: 0.17, w: 0.13, yb: 0.06, yt: 0.22 }, { x: 0.3, w: 0.13, yb: 0.06, yt: 0.21 }, { x: 0.35, w: 0.08, yb: 0.08, yt: 0.16 }], M.tank, { M: 24 }));
    add(cyl(0.018, 0.03, M.black, 'y', 0.24, 0.235, 0));

    /* двигатель Rotax справа от сиденья: картер, цилиндр с красной головкой, большой фильтр, глушитель */
    add(box(0.2, 0.15, 0.14, M.alu, -0.26, 0.14, 0.32));
    add(cyl(0.06, 0.13, M.alu, 'y', -0.24, 0.28, 0.32));
    add(cyl(0.07, 0.06, M.red, 'y', -0.24, 0.37, 0.32));
    add(cyl(0.012, 0.04, M.black, 'y', -0.24, 0.42, 0.32));
    add(cyl(0.075, 0.045, M.black, 'z', -0.3, 0.14, 0.23));
    add(cyl(0.03, 0.08, M.alu, 'x', -0.13, 0.22, 0.32));
    var airbox = add(loft([{ x: -0.36, w: 0.12, yb: 0.08, yt: 0.2 }, { x: -0.4, w: 0.18, yb: 0.06, yt: 0.3 }, { x: -0.56, w: 0.18, yb: 0.08, yt: 0.32 }, { x: -0.6, w: 0.12, yb: 0.12, yt: 0.26 }], M.black, { M: 24 }));
    airbox.position.z = 0.34;
    add(tube([[-0.19, 0.3, 0.36], [-0.08, 0.28, 0.43], [-0.2, 0.31, 0.48], [-0.45, 0.38, 0.46], [-0.64, 0.38, 0.32], [-0.68, 0.33, 0.12]], 0.042, M.alu));
    add(cyl(0.058, 0.26, M.black, 'z', -0.68, 0.33, -0.01));

    /* радиатор слева: высокий, серебристая рамка, соты */
    // опущен к раме и наклонён назад: поворот вокруг нижней кромки
    var rad = new THREE.Group(); rad.position.set(-0.12, 0.1, -0.36); rad.rotation.z = 0.38; g.add(rad);
    rad.add(box(0.045, 0.34, 0.25, M.alu, 0, 0.17, 0));
    rad.add(box(0.05, 0.3, 0.21, M.fins, 0, 0.17, 0));
    add(tube([[-0.14, 0.14, -0.3], [-0.2, 0.1, -0.05], [-0.26, 0.14, 0.25]], 0.014, M.black));

    /* руль: обод, три спицы, ступица — перпендикулярно колонке */
    var colDir = new THREE.Vector3(0.29, -0.31, 0).normalize();
    var sw = new THREE.Group(); sw.position.set(0.18, 0.42, 0);
    sw.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), colDir.clone().negate()); g.add(sw);
    var ring = new THREE.Mesh(new THREE.TorusGeometry(0.155, 0.015, 8, 36), M.glove); ring.rotation.y = Math.PI / 2; sw.add(ring);
    [Math.PI / 2, Math.PI / 2 + 2.2, Math.PI / 2 - 2.2].forEach(function (a) {
      var sp = new THREE.Mesh(new THREE.BoxGeometry(0.008, 0.15, 0.022), M.alu);
      sp.position.set(0, Math.sin(a) * 0.075, Math.cos(a) * 0.075); sp.rotation.x = -(a - Math.PI / 2); sw.add(sp);
    });
    var hub = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.03, 16), M.glove); hub.rotation.z = Math.PI / 2; sw.add(hub);

    /* пилот — по переключателю */
    if (withDriver) {
      var hip = new THREE.Vector3(-0.24, 0.12, 0), lean = 0.24;
      var torso = loft([
        { x: 0, w: 0.32, yb: -0.1, yt: 0.1 }, { x: 0.2, w: 0.34, yb: -0.11, yt: 0.11 }, { x: 0.4, w: 0.42, yb: -0.115, yt: 0.115 },
        { x: 0.5, w: 0.44, yb: -0.09, yt: 0.09 }, { x: 0.56, w: 0.2, yb: -0.07, yt: 0.07 }, { x: 0.6, w: 0.12, yb: -0.06, yt: 0.06 }
      ], ghost ? M.suit : new THREE.MeshStandardMaterial({ map: L.suit, roughness: 0.75, side: THREE.DoubleSide }), { M: 96, uvByX: true, uvArc: true, nBot: 3 });
      torso.position.copy(hip); torso.rotation.z = Math.PI / 2 + lean; add(torso);
      var up = new THREE.Vector3(-Math.sin(lean), Math.cos(lean), 0), neck = hip.clone().addScaledVector(up, 0.6);
      var collar = add(new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.03, 8, 20), M.black));
      collar.position.copy(neck).addScaledVector(up, -0.03); collar.rotation.x = Math.PI / 2;
      // нижний край шлема у ушей — на 0,08 м ниже центра: центр ставим так, чтобы край лег на воротник, а затылок его накрыл
      var hc = neck.clone().addScaledVector(up, 0.1); hc.x += 0.02;
      var neckM = add(new THREE.Mesh(new THREE.CylinderGeometry(0.052, 0.06, 0.14, 14), M.black));
      neckM.position.copy(neck).addScaledVector(up, 0.03); neckM.rotation.z = lean;
      /* шлем по фото Bell KC7, Arai CK-6, OMP KJ-8: один корпус-«яйцо», вытянутый вперёд-назад;
         подбородочная часть вырастает из него вперёд и вниз; нижний край низко у подбородка, выше у ушей,
         ниже на затылке, с чёрной окантовкой; большой тонированный визор до шарниров у висков. */
      var HR = 0.145;
      function hDeform(nx, ny, nz) {
        var x = nx * 1.1, y = ny * (ny > 0 ? 1.05 : 1), z = nz * 0.94;
        var front = Math.max(0, nx), low = Math.max(0, -ny);
        x += 0.2 * front * front * low; y -= 0.1 * front * front * low;
        var ang = Math.atan2(nz, nx), cf = Math.max(0, Math.cos(ang)), cb = Math.max(0, -Math.cos(ang));
        var yB = -0.55 - 0.42 * cf * cf - 0.25 * cb * cb;
        return [x, Math.max(y, yB), z];
      }
      function hGeo(k, ps, pl, ts, tl, ws, hs) {
        var gg = new THREE.SphereGeometry(1, ws, hs, ps, pl, ts, tl), pa = gg.attributes.position;
        for (var i = 0; i < pa.count; i++) { var d = hDeform(pa.getX(i), pa.getY(i), pa.getZ(i)); pa.setXYZ(i, d[0] * HR * k, d[1] * HR * k, d[2] * HR * k); }
        gg.computeVertexNormals(); return gg;
      }
      function hPt(phi, th, k) {
        var d = hDeform(-Math.cos(phi) * Math.sin(th), Math.cos(th), Math.sin(phi) * Math.sin(th));
        return new THREE.Vector3(d[0] * HR * k, d[1] * HR * k, d[2] * HR * k);
      }
      var hm = new THREE.Group(); hm.position.copy(hc).add(new THREE.Vector3(-0.012, 0.01, 0)); hm.rotation.z = -0.06; g.add(hm);
      var shellMat = ghost ? M.paint : new THREE.MeshStandardMaterial({ map: L.helmet, roughness: 0.2, metalness: 0.15, emissive: 0xffffff, emissiveMap: L.helmet, emissiveIntensity: 0.08 });
      hm.add(new THREE.Mesh(hGeo(1, 0, Math.PI * 2, 0, Math.PI, 64, 44), shellMat));
      if (!ghost) {
        var visorMat = new THREE.MeshStandardMaterial({ color: 0x141a26, emissive: 0x0b1530, emissiveIntensity: 0.4, roughness: 0.06, metalness: 0.9, side: THREE.DoubleSide });
        hm.add(new THREE.Mesh(hGeo(1.03, Math.PI - 0.95, 1.9, 1.2, 0.62, 48, 12), visorMat));
        var tab = box(0.012, 0.01, 0.05, M.black, 0, 0, 0); tab.position.copy(hPt(Math.PI, 1.2, 1.045)); hm.add(tab);
        [1, -1].forEach(function (s) {
          var pv = cyl(0.024, 0.008, M.black, 'z', 0, 0, 0, 18); pv.position.copy(hPt(Math.PI - 1.02 * s, 1.47, 1.02)); pv.rotation.y = -0.45 * s; hm.add(pv);
          var tv = box(0.03, 0.006, 0.012, M.black, 0, 0, 0); tv.position.copy(hPt(Math.PI - 0.22 * s, 0.55, 1.004)); tv.rotation.z = -0.5; hm.add(tv);
        });
        [-0.012, 0.012].forEach(function (dy) {
          var sl = box(0.006, 0.007, 0.06, M.black, 0, 0, 0); sl.position.copy(hPt(Math.PI, 2.08, 1.006)); sl.position.y += dy; sl.rotation.z = 0.5; hm.add(sl);
        });
        var spoiler = box(0.05, 0.012, 0.15, M.black, 0, 0, 0); spoiler.position.copy(hPt(0, 0.95, 1.02)); spoiler.rotation.z = -0.6; hm.add(spoiler);
        var edge = [];
        for (var ea = 0; ea < 64; ea++) {
          var an = ea / 64 * Math.PI * 2, cf2 = Math.max(0, Math.cos(an)), cb2 = Math.max(0, -Math.cos(an));
          var ny0 = -0.55 - 0.42 * cf2 * cf2 - 0.25 * cb2 * cb2 + 0.015, rr0 = Math.sqrt(Math.max(0, 1 - ny0 * ny0));
          var dd = hDeform(Math.cos(an) * rr0, ny0, Math.sin(an) * rr0);
          edge.push(new THREE.Vector3(dd[0] * HR, dd[1] * HR, dd[2] * HR));
        }
        hm.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(edge, true), 96, 0.009, 8, true), M.black));
      }
      var sh0 = hip.clone().addScaledVector(up, 0.48);
      [1, -1].forEach(function (s) {
        add(tube([[sh0.x, sh0.y, 0.2 * s], [-0.16, 0.5, 0.26 * s], [-0.05, 0.46, 0.265 * s]], 0.05, M.suit));
        add(tube([[-0.05, 0.46, 0.265 * s], [0.06, 0.44, 0.22 * s], [0.15, 0.43, 0.16 * s]], 0.042, M.suit));
        var gl = add(new THREE.Mesh(new THREE.SphereGeometry(0.04, 12, 10), M.glove)); gl.position.set(0.165, 0.425, 0.152 * s);
        add(tube([[-0.2, 0.13, 0.11 * s], [-0.02, 0.2, 0.13 * s], [0.12, 0.24, 0.14 * s]], 0.075, M.suit));
        add(tube([[0.12, 0.24, 0.14 * s], [0.3, 0.18, 0.125 * s], [0.44, 0.13, 0.11 * s]], 0.055, M.suit));
        var boot = add(box(0.1, 0.14, 0.08, M.glove, 0.47, 0.15, 0.11 * s)); boot.rotation.z = -0.25;
      });
    }

    var glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowFor(color), transparent: true, opacity: ghost ? 0.45 : 0.9, depthWrite: false }));
    glow.scale.set(22, 22, 1); glow.position.y = 7; outer.add(glow);
    outer.userData = { wheels: wheels, glow: glow };
    return outer;
  }

  function build(color, opts) {
    opts = opts || {};
    var g = buildKart(color, !!opts.ghost, opts.driver !== false, opts.scale || 3);
    g.userData.scale = opts.scale || 3;
    return g;
  }
  function roll(g, dist) {
    var u = g.userData;
    u.wheels.forEach(function (w) { w.spin -= dist / (w.r * u.scale); w.rot.rotation.set(Math.PI / 2, 0, 0); w.rot.rotateY(w.spin); });
  }

  window.GlKart3D = { build: build, roll: roll };
})();
