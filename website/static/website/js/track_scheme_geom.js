/* Геометрия схемы трассы — копия website/services/track_scheme.py (сплайн, дискретизация,
   доли длины). Используется редактором схемы в админке и 3D на странице трассы.
   При правке менять оба места; website/tests/test_track_scheme.py сверяет их через Node. */
(function (root) {
  'use strict';
  var SAMPLES_PER_SEGMENT = 20;

  function bezierSegments(points, tension) {
    var n = points.length, k = (tension == null ? 1 : tension) / 6, segs = [];
    for (var i = 0; i < n; i++) {
      var p0 = points[(i - 1 + n) % n], p1 = points[i], p2 = points[(i + 1) % n], p3 = points[(i + 2) % n];
      segs.push([
        [p1[0], p1[1]],
        [p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k],
        [p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k],
        [p2[0], p2[1]]
      ]);
    }
    return segs;
  }

  function bezierPoint(s, t) {
    var u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
    return [a * s[0][0] + b * s[1][0] + c * s[2][0] + d * s[3][0], a * s[0][1] + b * s[1][1] + c * s[2][1] + d * s[3][1]];
  }

  function samplePolyline(points, tension) {
    var out = [];
    bezierSegments(points, tension).forEach(function (s) {
      for (var j = 0; j < SAMPLES_PER_SEGMENT; j++) out.push(bezierPoint(s, j / SAMPLES_PER_SEGMENT));
    });
    return out;
  }

  /* SVG d для редактора: кривые Безье, замкнутые */
  function pathD(points, tension) {
    if (points.length < 2) return '';
    var segs = bezierSegments(points, tension), r = function (v) { return Math.round(v * 10) / 10; };
    var d = 'M' + r(segs[0][0][0]) + ',' + r(segs[0][0][1]);
    segs.forEach(function (s) { d += ' C' + r(s[1][0]) + ',' + r(s[1][1]) + ' ' + r(s[2][0]) + ',' + r(s[2][1]) + ' ' + r(s[3][0]) + ',' + r(s[3][1]); });
    return d + ' Z';
  }

  function mod1(v) { v = v % 1; return v < 0 ? v + 1 : v; }

  function Polyline(pts) {
    this.pts = pts;
    var n = pts.length, cum = [0];
    for (var i = 0; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      cum.push(cum[i] + Math.hypot(b[0] - a[0], b[1] - a[1]));
    }
    this.cum = cum;
    this.length = cum[n] || 1;
  }
  Polyline.prototype.locate = function (frac) {
    var s = mod1(frac) * this.length, lo = 0, hi = this.pts.length;
    while (hi - lo > 1) { var m = (lo + hi) >> 1; if (this.cum[m] <= s) lo = m; else hi = m; }
    var len = this.cum[lo + 1] - this.cum[lo];
    return [lo, len ? (s - this.cum[lo]) / len : 0];
  };
  Polyline.prototype.pointAt = function (frac) {
    var l = this.locate(frac), a = this.pts[l[0]], b = this.pts[(l[0] + 1) % this.pts.length];
    return [a[0] + (b[0] - a[0]) * l[1], a[1] + (b[1] - a[1]) * l[1]];
  };
  Polyline.prototype.tangentAt = function (frac) {
    var l = this.locate(frac), a = this.pts[l[0]], b = this.pts[(l[0] + 1) % this.pts.length];
    var dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy) || 1;
    return [dx / d, dy / d];
  };
  Polyline.prototype.project = function (x, y) {
    var best = 0, bestD = Infinity, n = this.pts.length;
    for (var i = 0; i < n; i++) {
      var a = this.pts[i], b = this.pts[(i + 1) % n], dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
      var t = l2 ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / l2)) : 0;
      var px = a[0] + dx * t, py = a[1] + dy * t, d = (px - x) * (px - x) + (py - y) * (py - y);
      if (d < bestD) { bestD = d; best = (this.cum[i] + Math.sqrt(l2) * t) / this.length; }
    }
    return { frac: mod1(best), dist: Math.sqrt(bestD) };
  };
  Polyline.prototype.contains = function (x, y) {
    var inside = false, n = this.pts.length;
    for (var i = 0; i < n; i++) {
      var p = this.pts[i], q = this.pts[(i + 1) % n];
      if ((p[1] > y) !== (q[1] > y) && x < (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]) + p[0]) inside = !inside;
    }
    return inside;
  };
  Polyline.prototype.outwardNormal = function (frac) {
    var t = this.tangentAt(frac), n = [t[1], -t[0]], p = this.pointAt(frac);
    if (this.contains(p[0] + n[0] * 6, p[1] + n[1] * 6)) n = [-n[0], -n[1]];
    return n;
  };
  /* Точки от доли fa до fb по направлению движения */
  Polyline.prototype.between = function (fa, fb) {
    var span = mod1(fb - fa) || 1, startS = mod1(fa) * this.length, inner = [];
    for (var i = 0; i < this.pts.length; i++) {
      var rel = mod1((this.cum[i] - startS) / this.length);
      if (rel > 0 && rel < span) inner.push([rel, this.pts[i]]);
    }
    inner.sort(function (a, b) { return a[0] - b[0]; });
    return [this.pointAt(fa)].concat(inner.map(function (x) { return x[1]; }), [this.pointAt(fa + span)]);
  };

  /* > 0 — по часовой на экране (ось Y вниз) */
  function signedArea(points) {
    var s = 0, n = points.length;
    for (var i = 0; i < n; i++) { var a = points[i], b = points[(i + 1) % n]; s += a[0] * b[1] - b[0] * a[1]; }
    return s / 2;
  }

  function fromScheme(scheme) {
    return new Polyline(samplePolyline(scheme.points, scheme.tension));
  }

  var api = {
    SAMPLES_PER_SEGMENT: SAMPLES_PER_SEGMENT,
    bezierSegments: bezierSegments, samplePolyline: samplePolyline, pathD: pathD,
    Polyline: Polyline, fromScheme: fromScheme, signedArea: signedArea, mod1: mod1,
    drawnDirection: function (points) { return signedArea(points) > 0 ? 'cw' : 'ccw'; }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GlTrackGeom = api;
})(this);
