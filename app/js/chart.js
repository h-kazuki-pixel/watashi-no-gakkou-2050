/*
 * わたしの学校2050 — グラフと地図（ライブラリなしの SVG）
 *  UG.lineChart : これまで／きみのよそう／データのよそう／もしも を1枚に描く。指やマウスで予想を描ける。
 *  UG.townMap   : 学区の地図（タイル不要。ポリゴンだけを SVG に描く）
 */
(function () {
  "use strict";
  var UG = window.UG, M = UG.model, esc = UG.esc;
  var L = 54, T = 30, B = 42;

  function path(points, sx, sy) {
    return points.map(function (p, i) { return (i ? "L" : "M") + sx(p.y).toFixed(1) + " " + sy(p.v).toFixed(1); }).join(" ");
  }

  /**
   * cfg: { xMin, xMax, yMax, hist[{y,v,src}], now{y,v}, est[{y,v}]|null, estAnimate,
   *        alt[{y,v}]|null, mine{year:value}|null, drawYears[], drawable, onDraw(values, done),
   *        target (強調する年), labelEst, labelMine, labelAlt }
   */
  UG.lineChart = function (container, cfg) {
    var xMin = cfg.xMin, xMax = cfg.xMax, yMax = cfg.yMax;
    // せまい画面では縦長にして、文字が小さくなりすぎないようにする
    var narrow = (container.clientWidth || 720) < 560;
    var W = narrow ? 440 : 720, H = narrow ? 370 : 380;
    // 目標の年が右端のときは、値のラベルを線の外（右の余白）に出す
    var R = cfg.target != null && cfg.target >= xMax ? 128 : 22;
    var sx = function (y) { return L + ((y - xMin) / (xMax - xMin)) * (W - L - R); };
    var sy = function (v) { return H - B - (M.clamp(v, 0, yMax) / yMax) * (H - T - B); };
    var inv = function (py) { return M.clamp(((H - B - py) / (H - T - B)) * yMax, 0, yMax); };
    var mine = {};
    Object.keys(cfg.mine || {}).forEach(function (k) { mine[k] = cfg.mine[k]; });
    var drawYears = cfg.drawYears || [];
    var s = [];

    // 方眼と軸
    var room = Math.max(2, Math.floor((W - L - R) / 50)); // 年のラベルが重ならない数
    var xStep = 5;
    while ((xMax - xMin) / xStep + 1 > room) xStep = xStep === 5 ? 10 : xStep + 10;
    var xs = [];
    for (var x = Math.ceil(xMin / xStep) * xStep; x <= xMax; x += xStep) xs.push(x);
    // 目標の年（2050年）の目もりは必ず出す。近すぎるほかの目もりはゆずる
    if (cfg.target != null && cfg.target >= xMin && cfg.target <= xMax && xs.indexOf(cfg.target) < 0) {
      xs = xs.filter(function (v) { return Math.abs(sx(v) - sx(cfg.target)) > 52; });
      xs.push(cfg.target);
    }
    xs.forEach(function (x) {
      var strong = x === cfg.target;
      s.push('<line class="grid" x1="' + sx(x) + '" y1="' + T + '" x2="' + sx(x) + '" y2="' + (H - B) + '"/>');
      s.push('<text class="tick' + (strong ? " strong" : "") + '" x="' + sx(x) + '" y="' + (H - B + 22) + '" text-anchor="middle">' + x + (strong ? "年" : "") + "</text>");
    });
    M.niceTicks(yMax, 4).forEach(function (t, i, arr) {
      s.push('<line class="grid' + (t === 0 ? " base" : "") + '" x1="' + L + '" y1="' + sy(t) + '" x2="' + (W - R) + '" y2="' + sy(t) + '"/>');
      s.push('<text class="tick" x="' + (L - 8) + '" y="' + (sy(t) + 5) + '" text-anchor="end">' + UG.num(t) + "</text>");
    });
    s.push('<text class="tick" x="' + (L - 8) + '" y="' + (T - 14) + '" text-anchor="end">（人）</text>');

    // 「これまで」と「これから」の境目
    if (cfg.now) {
      var nx = sx(cfg.now.y);
      s.push('<rect class="future" x="' + nx + '" y="' + T + '" width="' + (W - R - nx) + '" height="' + (H - T - B) + '"/>');
      s.push('<line class="nowline" x1="' + nx + '" y1="' + T + '" x2="' + nx + '" y2="' + (H - B) + '"/>');
      if (nx - L > 90) s.push('<text class="zone" x="' + (nx - 8) + '" y="' + (T - 8) + '" text-anchor="end">これまで</text>');
      s.push('<text class="zone" x="' + (nx + 8) + '" y="' + (T - 8) + '">これから</text>');
    }

    // これまでの線
    var past = (cfg.hist || []).filter(function (p) { return p.y >= xMin; });
    if (cfg.now) past.push({ y: cfg.now.y, v: cfg.now.v, src: "now" });
    if (past.length > 1) s.push('<path class="l-hist" d="' + path(past, sx, sy) + '"/>');
    past.forEach(function (p) {
      var cls = p.src === "kid" ? "p-kid" : p.src === "now" ? "p-now" : "p-hist";
      if (p.src === "kid") {
        var cx = sx(p.y), cy = sy(p.v);
        s.push('<rect class="' + cls + '" x="' + (cx - 5) + '" y="' + (cy - 5) + '" width="10" height="10" transform="rotate(45 ' + cx + " " + cy + ')"/>');
      } else {
        s.push('<circle class="' + cls + '" cx="' + sx(p.y) + '" cy="' + sy(p.v) + '" r="' + (p.src === "now" ? 7 : 4.5) + '"/>');
      }
    });
    var nowBelow = false;
    if (cfg.now) {
      // 「いま」のラベルは、これまでの線と重ならない側（線が上から来るなら下、下から来るなら上）に置く。
      // なぞる画面（drawable）では、案内の文「ここから 右へ なぞってね →」を点の上に出すので、「いま」は下に置く
      var prev = past.length > 1 ? past[past.length - 2] : null;
      var ny = sy(cfg.now.v), below = cfg.drawable ? true : prev ? prev.v > cfg.now.v : false;
      if (below && ny + 26 > H - B - 4) below = false;
      if (!below && ny - 14 < T + 12) below = true;
      nowBelow = below;
      var nowLabY = { below: ny + 26, above: ny - 14, canBelow: ny + 26 <= H - B - 4, canAbove: ny - 14 >= T + 12 };
      var roomLeft = sx(cfg.now.y) - L;
      var nowLabLeft = roomLeft > 96, nowPastAbove = prev ? prev.v > cfg.now.v : true;
      s.push('<text class="lab-now" x="' + (roomLeft > 96 ? sx(cfg.now.y) - 10 : L + 4) + '" y="' + (below ? ny + 26 : ny - 14) +
        '" text-anchor="' + (roomLeft > 96 ? "end" : "start") + '">いま ' + UG.num(cfg.now.v) + "人</text>");
    }

    // もしも（緑）・データ（赤）
    if (cfg.alt) s.push('<path class="l-alt" d="' + path(cfg.alt.filter(function (p) { return p.y <= xMax; }), sx, sy) + '"/>');
    if (cfg.est) {
      var estIn = cfg.est.filter(function (p) { return p.y <= xMax; });
      s.push('<path class="l-est' + (cfg.estAnimate ? " draw-in" : "") + '" pathLength="1" d="' + path(estIn, sx, sy) + '"/>');
      estIn.slice(1).forEach(function (p) {
        s.push('<circle class="p-est' + (cfg.estAnimate ? " fade-in" : "") + '" cx="' + sx(p.y) + '" cy="' + sy(p.v) + '" r="' + (p.y === cfg.target ? 6 : 3.5) + '"/>');
      });
    }

    s.push('<g class="mine"></g><g class="endlabels"></g>');
    if (cfg.drawable) {
      var dx0 = sx(cfg.now.y) + 2;
      s.push('<rect class="pad" x="' + dx0 + '" y="' + (T - 10) + '" width="' + (W - dx0) + '" height="' + (H - T - B + 20) + '"/>');
    }

    container.innerHTML =
      '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(cfg.aria || "児童数のグラフ") + '">' + s.join("") + "</svg>";
    var svg = container.firstChild;
    var gMine = svg.querySelector(".mine"), gEnd = svg.querySelector(".endlabels");

    function minePoints() {
      var pts = [{ y: cfg.now.y, v: cfg.now.v }];
      drawYears.forEach(function (y) { if (mine[y] != null) pts.push({ y: y, v: mine[y] }); });
      return pts;
    }
    function isDone() { return drawYears.every(function (y) { return mine[y] != null; }); }

    function renderMine(focusYear) {
      var out = [], pts = minePoints();
      var hasAny = pts.length > 1;
      // なぞる画面で線をかいたら、「いま ○人」の置き場を決め直す。
      // 文字が点の左にあるとき：よそうの線とは当たらないので、これまでの線と重ならない側（線が上から来るなら下）。
      // 文字が点の右にあるとき：よそうの線と反対の側（線が下へ向かうなら上、上へ向かうなら下）
      var lab = cfg.drawable && cfg.now ? svg.querySelector(".lab-now") : null;
      if (lab) {
        var wantBelow = !hasAny ? nowBelow : nowLabLeft ? nowPastAbove : pts[1].v > cfg.now.v;
        if (wantBelow && !nowLabY.canBelow) wantBelow = false;
        if (!wantBelow && !nowLabY.canAbove) wantBelow = true;
        lab.setAttribute("y", wantBelow ? nowLabY.below : nowLabY.above);
      }
      if (hasAny) out.push('<path class="l-mine" d="' + path(pts, sx, sy) + '"/>');
      if (cfg.drawable) {
        drawYears.forEach(function (y) {
          var has = mine[y] != null;
          var cy = has ? sy(mine[y]) : sy(cfg.now.v);
          out.push('<circle class="handle' + (has ? "" : " empty") + '" data-year="' + y + '" cx="' + sx(y) + '" cy="' + cy +
            '" r="9" tabindex="0" role="slider" aria-label="' + y + '年のよそう" aria-valuemin="0" aria-valuemax="' + yMax +
            '" aria-valuenow="' + (has ? Math.round(mine[y]) : "") + '"/>');
        });
        if (!hasAny) {
          // 案内の文は「いま ○人」と反対の側に置く。同じ側になるとき（点がグラフの上か下の端）は、1段離す
          var py0 = sy(cfg.now.v), hy;
          if (nowBelow) hy = py0 - 22 >= T + 4 ? py0 - 22 : py0 + 50;
          else hy = py0 - 38 >= T + 4 ? py0 - 38 : py0 + 30;
          out.push('<text class="hint" x="' + (sx(cfg.now.y) + 16) + '" y="' + hy + '">ここから 右へ なぞってね →</text>');
        }
      } else {
        pts.slice(1).forEach(function (p) { out.push('<circle class="p-mine" cx="' + sx(p.y) + '" cy="' + sy(p.v) + '" r="4"/>'); });
      }
      gMine.innerHTML = out.join("");
      renderEndLabels();
      if (focusYear) {
        var h = gMine.querySelector('.handle[data-year="' + focusYear + '"]');
        if (h) h.focus();
      }
    }

    // 2050年の値のラベル。文字はインク色、どの線かは色つきの丸で示す（重ならないよう上下に振り分ける）
    function renderEndLabels() {
      var items = [];
      var tx = cfg.target;
      if (tx == null) { gEnd.innerHTML = ""; return; }
      if (mine[tx] != null) items.push({ v: mine[tx], dot: "d-mine", cls: "", text: (cfg.labelMine || "きみ") + " " + UG.num(mine[tx]) + "人" });
      if (cfg.est) items.push({ v: M.interp(cfg.est, tx), dot: "d-est", cls: cfg.estAnimate ? " fade-in" : "", text: (cfg.labelEst || "データ") + " " + UG.num(M.interp(cfg.est, tx)) + "人" });
      if (cfg.alt) items.push({ v: M.interp(cfg.alt, tx), dot: "d-alt", cls: "", text: (cfg.labelAlt || "もしも") + " " + UG.num(M.interp(cfg.alt, tx)) + "人" });
      items.sort(function (a, b) { return b.v - a.v; });
      var outside = tx >= xMax;
      var last = items.length - 1;
      var ys = items.map(function (it, i) {
        if (outside) return sy(it.v) + 5; // 点の真横
        return i === last && items.length > 1 ? sy(it.v) + 24 : sy(it.v) - 12; // いちばん下だけ点の下に
      });
      var i, gap = 20;
      for (i = 1; i < ys.length; i++) if (ys[i] < ys[i - 1] + gap) ys[i] = ys[i - 1] + gap;
      for (i = last; i >= 0; i--) { var cap = H - B - 4 - (last - i) * gap; if (ys[i] > cap) ys[i] = cap; }
      for (i = 0; i < ys.length; i++) { var floor = T + 14 + i * gap; if (ys[i] < floor) ys[i] = floor; }
      var lx = sx(tx) + (outside ? 14 : 12);
      gEnd.innerHTML = items.map(function (it, i) {
        return '<g class="endlab' + it.cls + '"><circle class="' + it.dot + '" cx="' + (lx + 5) + '" cy="' + (ys[i] - 5).toFixed(1) + '" r="5"/>' +
          '<text class="lab" x="' + (lx + 15) + '" y="' + ys[i].toFixed(1) + '">' + esc(it.text) + "</text></g>";
      }).join("");
    }

    function emit() {
      if (cfg.onDraw) {
        var copy = {};
        Object.keys(mine).forEach(function (k) { copy[k] = mine[k]; });
        cfg.onDraw(copy, isDone());
      }
    }

    if (cfg.drawable) {
      var pad = svg.querySelector(".pad"), lastYear = null, active = false;
      var toLocal = function (ev) {
        var r = svg.getBoundingClientRect();
        return { x: ((ev.clientX - r.left) / r.width) * W, y: ((ev.clientY - r.top) / r.height) * H };
      };
      var nearestYear = function (px) {
        var best = drawYears[0], bd = Infinity;
        drawYears.forEach(function (y) { var d = Math.abs(sx(y) - px); if (d < bd) { bd = d; best = y; } });
        return best;
      };
      var apply = function (ev) {
        var p = toLocal(ev), y = nearestYear(p.x), v = Math.round(inv(p.y));
        // すばやくなぞったとき、あいだの年も線でつなぐ
        if (lastYear != null && lastYear !== y) {
          var a = lastYear, va = mine[a], step = y > a ? 1 : -1;
          var ia = drawYears.indexOf(a), ib = drawYears.indexOf(y);
          for (var i = ia + step; i !== ib; i += step) {
            var yy = drawYears[i];
            mine[yy] = Math.round(va + ((v - va) * (yy - a)) / (y - a));
          }
        }
        mine[y] = v; lastYear = y;
        renderMine(); emit();
      };
      pad.addEventListener("pointerdown", function (ev) {
        active = true; lastYear = null;
        try { pad.setPointerCapture(ev.pointerId); } catch (e) { /* 古いブラウザ */ }
        apply(ev); ev.preventDefault();
      });
      pad.addEventListener("pointermove", function (ev) { if (active) { apply(ev); ev.preventDefault(); } });
      var end = function () { active = false; lastYear = null; };
      pad.addEventListener("pointerup", end);
      pad.addEventListener("pointercancel", end);
      svg.addEventListener("keydown", function (ev) {
        var h = ev.target.closest && ev.target.closest(".handle");
        if (!h) return;
        var y = +h.getAttribute("data-year"), stepV = Math.max(1, Math.round(yMax / 50));
        var cur = mine[y] != null ? mine[y] : cfg.now.v, next = null;
        if (ev.key === "ArrowUp") next = cur + stepV;
        if (ev.key === "ArrowDown") next = cur - stepV;
        if (next == null) return;
        mine[y] = Math.round(M.clamp(next, 0, yMax));
        renderMine(y); emit(); ev.preventDefault();
      });
    }
    renderMine();
    if (!cfg.drawable) attachHover();

    // なぞる・タップすると、その年の数字が出る
    function attachHover() {
      var years = [];
      for (var yy = Math.ceil(xMin / 5) * 5; yy <= xMax; yy += 5) years.push(yy);
      (cfg.hist || []).forEach(function (p) { if (years.indexOf(p.y) < 0 && p.y >= xMin) years.push(p.y); });
      var rowsAt = function (year) {
        var rows = [];
        (cfg.hist || []).forEach(function (p) { if (p.y === year) rows.push(["d-hist", (p.src === "kid" ? "しらべた 数" : "これまで"), p.v]); });
        if (cfg.now && year === cfg.now.y) rows.push(["d-hist", "いま", cfg.now.v]);
        if (year > cfg.now.y) {
          if (mine[year] != null) rows.push(["d-mine", cfg.labelMine || "きみ", mine[year]]);
          if (cfg.est) rows.push(["d-est", cfg.labelEst || "データ", M.interp(cfg.est, year)]);
          if (cfg.alt) rows.push(["d-alt", cfg.labelAlt || "もしも", M.interp(cfg.alt, year)]);
        }
        return rows;
      };
      var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "tipbox"); g.setAttribute("aria-hidden", "true");
      var hp = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      hp.setAttribute("class", "hoverpad");
      hp.setAttribute("x", L); hp.setAttribute("y", T); hp.setAttribute("width", W - L - R); hp.setAttribute("height", H - T - B);
      svg.appendChild(g); svg.appendChild(hp);
      var show = function (ev) {
        var r = svg.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
        var best = null, bd = Infinity;
        years.forEach(function (y) { var d = Math.abs(sx(y) - px); if (d < bd && rowsAt(y).length) { bd = d; best = y; } });
        if (best == null) { g.innerHTML = ""; return; }
        var rows = rowsAt(best), bw = 168, bh = 30 + rows.length * 22, x = sx(best);
        var bx = x + 12 + bw > W - 4 ? x - 12 - bw : x + 12, by = T + 6;
        g.innerHTML = '<line class="tipline" x1="' + x + '" y1="' + T + '" x2="' + x + '" y2="' + (H - B) + '"/>' +
          '<rect class="tipbg" x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh + '" rx="8"/>' +
          '<text class="tiphead" x="' + (bx + 12) + '" y="' + (by + 21) + '">' + best + "年</text>" +
          rows.map(function (rw, i) {
            var ty = by + 43 + i * 22;
            return '<circle class="' + rw[0] + '" cx="' + (bx + 17) + '" cy="' + (ty - 5) + '" r="5"/><text class="tiprow" x="' + (bx + 29) + '" y="' + ty + '">' + esc(rw[1]) + '</text>' +
              '<text class="tiprow num" x="' + (bx + bw - 12) + '" y="' + ty + '" text-anchor="end">' + UG.num(rw[2]) + "人</text>";
          }).join("");
      };
      hp.addEventListener("pointermove", show);
      hp.addEventListener("pointerdown", show);
      hp.addEventListener("pointerleave", function (ev) { if (ev.pointerType === "mouse") g.innerHTML = ""; });
    }
    return {
      reset: function () { mine = {}; renderMine(); emit(); },
      values: function () { return mine; }
    };
  };

  /**
   * 学区の地図。opts: { selected, value(school) -> 色の段階 0..4 | null, onSelect(id), showNames }
   * 実データは経度・緯度（北が上）、サンプルは平面座標（下向きが正）。
   */
  UG.townMap = function (container, city, opts) {
    opts = opts || {};
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    var lat0 = 0, n = 0;
    city.schools.forEach(function (sc) {
      (sc.geom || []).forEach(function (ring) { ring.forEach(function (p) { lat0 += p[1]; n++; }); });
    });
    lat0 = n ? lat0 / n : 0;
    var kx = city.plane ? 1 : Math.cos((lat0 * Math.PI) / 180);
    var proj = function (p) { return city.plane ? [p[0], p[1]] : [p[0] * kx, -p[1]]; };
    city.schools.forEach(function (sc) {
      (sc.geom || []).forEach(function (ring) {
        ring.forEach(function (p) {
          var q = proj(p);
          minX = Math.min(minX, q[0]); maxX = Math.max(maxX, q[0]);
          minY = Math.min(minY, q[1]); maxY = Math.max(maxY, q[1]);
        });
      });
    });
    if (!isFinite(minX)) { container.innerHTML = ""; return; }
    var VW = 400, pad = 10;
    var scale = (VW - pad * 2) / Math.max(maxX - minX, 1e-9);
    var VH = Math.max(120, Math.min(520, (maxY - minY) * scale + pad * 2));
    scale = Math.min(scale, (VH - pad * 2) / Math.max(maxY - minY, 1e-9));
    var ox = (VW - (maxX - minX) * scale) / 2, oy = (VH - (maxY - minY) * scale) / 2;
    var pt = function (p) { var q = proj(p); return [(q[0] - minX) * scale + ox, (q[1] - minY) * scale + oy]; };
    var d = function (rings) {
      return rings.map(function (ring) {
        return ring.map(function (p, i) { var q = pt(p); return (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); }).join("") + "Z";
      }).join("");
    };
    var s = [];
    city.schools.forEach(function (sc) {
      if (!sc.geom) return;
      var lv = opts.value ? opts.value(sc) : null;
      s.push('<path class="dist' + (sc.approx ? " approx" : "") + (lv != null ? " lv" + lv : "") + (sc.id === opts.selected ? " sel" : "") + '" data-id="' + esc(sc.id) + '" d="' + d(sc.geom) + '" fill-rule="evenodd"' +
        (opts.onSelect ? ' tabindex="0" role="button" aria-label="' + esc(sc.name) + '"' : "") + "><title>" + esc(sc.name) + "</title></path>");
    });
    var dec = city.decor;
    if (dec) {
      var line = function (pts) { return pts.map(function (p, i) { var q = pt(p); return (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); }).join(""); };
      if (dec.river) s.push('<path class="river" d="' + line(dec.river) + '"/>');
      if (dec.rail) s.push('<path class="rail" d="' + line(dec.rail) + '"/><path class="rail2" d="' + line(dec.rail) + '"/>');
      if (dec.station) {
        var st = pt(dec.station.xy);
        s.push('<rect class="station" x="' + (st[0] - 7) + '" y="' + (st[1] - 5) + '" width="14" height="10" rx="2"/>');
      }
    }
    // 選ばれた学区の輪郭を最後に重ねる
    city.schools.forEach(function (sc) {
      if (sc.id === opts.selected && sc.geom) s.push('<path class="dist-sel" d="' + d(sc.geom) + '"/>');
    });
    city.schools.forEach(function (sc) {
      var xy = sc.xy || (sc.lng != null ? [sc.lng, sc.lat] : null);
      if (!xy) return;
      var q = pt(xy);
      s.push('<circle class="school-dot' + (sc.id === opts.selected ? " sel" : "") + '" cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="' + (sc.id === opts.selected ? 5 : 3.2) + '"/>');
      if (opts.showNames && city.schools.length <= 12) {
        var short = sc.name.replace(/小学校$/, "小");
        s.push('<text class="school-name' + (sc.id === opts.selected ? " sel" : "") + '" x="' + q[0].toFixed(1) + '" y="' + (q[1] - 8).toFixed(1) + '" text-anchor="middle">' + esc(short) + "</text>");
      }
    });
    container.innerHTML = '<svg class="map" viewBox="0 0 ' + VW + " " + VH.toFixed(0) + '" role="group" aria-label="' + esc(city.name) + 'の学区の地図">' + s.join("") + "</svg>";
    if (opts.onSelect) {
      var svg = container.firstChild;
      var pick = function (ev) {
        var t = ev.target.closest && ev.target.closest(".dist");
        if (t) opts.onSelect(t.getAttribute("data-id"));
      };
      svg.addEventListener("click", pick);
      svg.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { pick(ev); ev.preventDefault(); } });
    }
  };

  /** クイズ用：同じデータで、たて軸の始まりだけがちがう2つの小さなグラフ */
  UG.miniAxisChart = function (values, yMin, yMaxV, label) {
    var w = 250, h = 170, l = 40, r = 10, t = 14, b = 26;
    var sx = function (i) { return l + (i / (values.length - 1)) * (w - l - r); };
    var sy = function (v) { return h - b - ((v - yMin) / (yMaxV - yMin)) * (h - t - b); };
    var s = ['<svg class="mini" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="' + esc(label) + '">'];
    [yMin, (yMin + yMaxV) / 2, yMaxV].forEach(function (v) {
      s.push('<line class="grid" x1="' + l + '" y1="' + sy(v) + '" x2="' + (w - r) + '" y2="' + sy(v) + '"/>');
      s.push('<text class="tick" x="' + (l - 6) + '" y="' + (sy(v) + 4) + '" text-anchor="end">' + v + "</text>");
    });
    s.push('<path class="l-hist" d="' + values.map(function (v, i) { return (i ? "L" : "M") + sx(i).toFixed(1) + " " + sy(v).toFixed(1); }).join("") + '"/>');
    values.forEach(function (v, i) { s.push('<circle class="p-hist" cx="' + sx(i) + '" cy="' + sy(v) + '" r="3.5"/>'); });
    s.push('<text class="tick" x="' + l + '" y="' + (h - 6) + '">2000年</text><text class="tick" x="' + (w - r) + '" y="' + (h - 6) + '" text-anchor="end">2025年</text>');
    s.push("</svg>");
    return s.join("");
  };

  /**
   * クラスで 見る：全員の よそうの線を重ねた図（さわれない）。
   * cfg: { xMin, yMax, hist[{y,v}], now{y,v}, lines[{2030:…,…,2050:…}], est[{y,v}]|null }
   * 線は「きみの よそう」と同じ青の点線を細くしたもの。データ（赤）は est を渡したときだけ。
   */
  UG.classChart = function (container, cfg) {
    var xMin = cfg.xMin, xMax = M.TARGET_YEAR, yMax = cfg.yMax;
    var W = 720, H = 400, R = cfg.est ? 112 : 40;
    var sx = function (y) { return L + ((y - xMin) / (xMax - xMin)) * (W - L - R); };
    var sy = function (v) { return H - B - (M.clamp(v, 0, yMax) / yMax) * (H - T - B); };
    var s = [];
    var xs = [];
    for (var x = Math.ceil(xMin / 10) * 10; x <= xMax; x += 10) xs.push(x);
    if (xs.indexOf(2025) < 0) xs.push(2025);
    xs.sort();
    xs.forEach(function (x) {
      var strong = x === xMax;
      s.push('<line class="grid" x1="' + sx(x) + '" y1="' + T + '" x2="' + sx(x) + '" y2="' + (H - B) + '"/>');
      s.push('<text class="tick' + (strong ? " strong" : "") + '" x="' + sx(x) + '" y="' + (H - B + 22) + '" text-anchor="middle">' + x + (strong ? "年" : "") + "</text>");
    });
    M.niceTicks(yMax, 4).forEach(function (t) {
      s.push('<line class="grid' + (t === 0 ? " base" : "") + '" x1="' + L + '" y1="' + sy(t) + '" x2="' + (W - R) + '" y2="' + sy(t) + '"/>');
      s.push('<text class="tick" x="' + (L - 8) + '" y="' + (sy(t) + 5) + '" text-anchor="end">' + UG.num(t) + "</text>");
    });
    s.push('<text class="tick" x="' + (L - 8) + '" y="' + (T - 14) + '" text-anchor="end">（人）</text>');
    var nx = sx(cfg.now.y);
    s.push('<rect class="future" x="' + nx + '" y="' + T + '" width="' + (W - R - nx) + '" height="' + (H - T - B) + '"/>');
    s.push('<line class="nowline" x1="' + nx + '" y1="' + T + '" x2="' + nx + '" y2="' + (H - B) + '"/>');

    var past = (cfg.hist || []).filter(function (p) { return p.y >= xMin; }).concat([{ y: cfg.now.y, v: cfg.now.v }]);
    if (past.length > 1) s.push('<path class="l-hist" d="' + path(past, sx, sy) + '"/>');
    (cfg.lines || []).forEach(function (d) {
      var pts = [{ y: cfg.now.y, v: cfg.now.v }].concat(M.DRAW_YEARS.map(function (y) { return { y: y, v: d[y] }; }));
      s.push('<path class="l-class" d="' + path(pts, sx, sy) + '"/>');
    });
    if (cfg.est) {
      var estIn = cfg.est.filter(function (p) { return p.y <= xMax; });
      s.push('<path class="l-est draw-in" pathLength="1" d="' + path(estIn, sx, sy) + '"/>');
      var e50 = estIn[estIn.length - 1];
      s.push('<circle class="p-est" cx="' + sx(e50.y) + '" cy="' + sy(e50.v) + '" r="7"/>');
      s.push('<text class="lab-end" x="' + (sx(e50.y) + 14) + '" y="' + (sy(e50.v) + 6) + '">データ ' + UG.num(e50.v) + "人</text>");
    }
    s.push('<circle class="p-now" cx="' + nx + '" cy="' + sy(cfg.now.v) + '" r="7"/>');
    s.push('<text class="lab-now" x="' + (nx - 10) + '" y="' + (sy(cfg.now.v) + 28) + '" text-anchor="end">いま ' + UG.num(cfg.now.v) + "人</text>");
    container.innerHTML = '<svg class="chart class-chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' +
      esc(cfg.aria || "みんなの よそうの 線") + '">' + s.join("") + "</svg>";
  };

  /**
   * 2050年の よそうの 散らばり（点を 横に 並べ、同じ くらいの 値は 上に 積む）。
   * cfg: { values[], now, est50|null }
   */
  UG.dotPlot = function (container, cfg) {
    var vals = cfg.values || [];
    var top = Math.max.apply(null, vals.concat([cfg.now, cfg.est50 || 0, 1]));
    var xMax = M.niceMax(top * 1.05);
    var W = 720, l = 28, r = 28, bins = 36, rad = 7.5, gap = 2 * rad + 2;
    var bw = xMax / bins, stack = {};
    var dots = vals.slice().sort(function (a, b) { return a - b; }).map(function (v) {
      var b = Math.min(bins - 1, Math.floor(v / bw));
      stack[b] = (stack[b] || 0) + 1;
      return { b: b, k: stack[b] - 1 };
    });
    var maxStack = Math.max.apply(null, [1].concat(Object.keys(stack).map(function (k) { return stack[k]; })));
    var top0 = 34, base = top0 + maxStack * gap + 6, H = base + 40;
    var sx = function (v) { return l + (M.clamp(v, 0, xMax) / xMax) * (W - l - r); };
    var s = [];
    s.push('<line class="grid base" x1="' + l + '" y1="' + base + '" x2="' + (W - r) + '" y2="' + base + '"/>');
    M.niceTicks(xMax, 5).forEach(function (t) {
      s.push('<line class="grid" x1="' + sx(t) + '" y1="' + base + '" x2="' + sx(t) + '" y2="' + (base + 6) + '"/>');
      s.push('<text class="tick" x="' + sx(t) + '" y="' + (base + 26) + '" text-anchor="middle">' + UG.num(t) + "</text>");
    });
    s.push('<line class="dp-now" x1="' + sx(cfg.now) + '" y1="' + (top0 - 10) + '" x2="' + sx(cfg.now) + '" y2="' + base + '"/>');
    s.push('<text class="tick" x="' + sx(cfg.now) + '" y="' + (top0 - 16) + '" text-anchor="middle">いま ' + UG.num(cfg.now) + "人</text>");
    dots.forEach(function (d) {
      s.push('<circle class="dp-dot" cx="' + (sx((d.b + 0.5) * bw)) + '" cy="' + (base - rad - 2 - d.k * gap) + '" r="' + rad + '"/>');
    });
    if (cfg.est50 != null) {
      s.push('<line class="dp-est" x1="' + sx(cfg.est50) + '" y1="' + (top0 - 10) + '" x2="' + sx(cfg.est50) + '" y2="' + base + '"/>');
      s.push('<text class="tick" x="' + sx(cfg.est50) + '" y="' + (base + 26 + 0) + '" dy="18" text-anchor="middle">データ ' + UG.num(cfg.est50) + "人</text>");
    }
    container.innerHTML = '<svg class="dotplot" viewBox="0 0 ' + W + " " + (H + (cfg.est50 != null ? 18 : 0)) + '" role="img" aria-label="' +
      esc("2050年の よそうの 散らばり。点 1つが 1人") + '">' + s.join("") + "</svg>";
  };
})();
