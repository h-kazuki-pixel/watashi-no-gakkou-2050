/*
 * わたしの学校2050 — みらい ていあんカード（SVG → 画像／印刷／テキスト）
 * 画像に変換するときは Web フォントが使えないため、端末のフォントだけで組む。
 */
(function () {
  "use strict";
  var UG = window.UG, M = UG.model, esc = UG.esc, num = UG.num;
  var FONT = "'Hiragino Maru Gothic ProN','BIZ UDPGothic','Noto Sans JP','Noto Sans CJK JP','Yu Gothic','Meiryo',sans-serif";
  var CW = 1200, CH = 850;

  function gradeLabel(id) {
    for (var i = 0; i < UG.GRADES.length; i++) if (UG.GRADES[i].id === id) return UG.GRADES[i].label;
    return "";
  }

  UG.cardData = function () {
    var st = UG.state, c = UG.ctx();
    var ideas = UG.IDEAS.filter(function (k) { return st.ideas.indexOf(k.id) >= 0; }).map(function (k) { return k.t.replace(/ /g, ""); });
    if (st.ownIdea.trim()) ideas.push(st.ownIdea.trim());
    var d = new Date();
    return {
      school: c.school.name, city: c.city.name, sample: c.sample,
      to: UG.toLabel(st.to, c.city.name).replace(/ /g, ""),
      nick: st.nick.trim(), grade: st.grade && st.grade !== "adult" ? gradeLabel(st.grade) : "",
      date: d.getFullYear() + "年" + (d.getMonth() + 1) + "月" + d.getDate() + "日",
      now: c.now, v50: c.v50, pct: c.pct, mine50: st.draw[2050],
      hist: c.hist, est: c.est, draw: st.draw, yMax: c.yMax, xMin: c.xMin,
      ideas: ideas, proposal: st.proposal.trim()
    };
  };

  /** 全角=1、半角=0.55 として幅を数え、maxUnits ごとに折り返す（行頭の句読点は前の行へ） */
  function wrap(text, maxUnits, maxLines) {
    var lines = [], cur = "", w = 0;
    String(text).split("").forEach(function (ch) {
      if (ch === "\n") { lines.push(cur); cur = ""; w = 0; return; }
      var cw = /[\u0000-ÿ]/.test(ch) ? 0.55 : 1;
      if (w + cw > maxUnits && !/[、。，．！？）」』]/.test(ch)) { lines.push(cur); cur = ""; w = 0; }
      cur += ch; w += cw;
    });
    if (cur) lines.push(cur);
    if (maxLines && lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      lines[maxLines - 1] = lines[maxLines - 1].replace(/.$/, "…");
    }
    return lines;
  }
  UG._wrap = wrap;

  function tspans(lines, x, y, lh) {
    return lines.map(function (ln, i) {
      return '<tspan x="' + x + '" y="' + (y + i * lh) + '">' + esc(ln) + "</tspan>";
    }).join("");
  }

  function miniChart(d, x0, y0, w, h) {
    var l = 56, r = 96, t = 14, b = 34;
    var xMin = d.xMin, xMax = 2050, yMax = d.yMax;
    var sx = function (y) { return x0 + l + ((y - xMin) / (xMax - xMin)) * (w - l - r); };
    var sy = function (v) { return y0 + h - b - (M.clamp(v, 0, yMax) / yMax) * (h - t - b); };
    var line = function (pts) { return pts.map(function (p, i) { return (i ? "L" : "M") + sx(p.y).toFixed(1) + " " + sy(p.v).toFixed(1); }).join(""); };
    var s = [];
    M.niceTicks(yMax, 4).forEach(function (v) {
      s.push('<line x1="' + (x0 + l) + '" y1="' + sy(v) + '" x2="' + (x0 + w - r) + '" y2="' + sy(v) + '" stroke="#cfe0ea" stroke-width="' + (v === 0 ? 2 : 1) + '"/>');
      s.push('<text x="' + (x0 + l - 8) + '" y="' + (sy(v) + 6) + '" font-size="17" text-anchor="end" fill="#51607d">' + num(v) + "</text>");
    });
    var step = xMax - xMin > 40 ? 10 : 5;
    for (var y = Math.ceil(xMin / step) * step; y <= xMax; y += step) {
      s.push('<text x="' + sx(y) + '" y="' + (y0 + h - 8) + '" font-size="17" text-anchor="middle" fill="#51607d"' + (y === 2050 ? ' font-weight="700"' : "") + ">" + y + "</text>");
    }
    s.push('<line x1="' + sx(2025) + '" y1="' + (y0 + t) + '" x2="' + sx(2025) + '" y2="' + (y0 + h - b) + '" stroke="#1d2b4f" stroke-width="1.5" stroke-dasharray="5 5"/>');
    var past = d.hist.concat([{ y: 2025, v: d.now }]);
    if (past.length > 1) s.push('<path d="' + line(past) + '" fill="none" stroke="#1d2b4f" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>');
    var minePts = [{ y: 2025, v: d.now }];
    M.DRAW_YEARS.forEach(function (yy) { if (d.draw[yy] != null) minePts.push({ y: yy, v: d.draw[yy] }); });
    var estPts = d.est.filter(function (p) { return p.y <= 2050; });
    s.push('<path d="' + line(estPts) + '" fill="none" stroke="#e03131" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>');
    if (minePts.length > 1) s.push('<path d="' + line(minePts) + '" fill="none" stroke="#1c7ed6" stroke-width="4" stroke-dasharray="2 9" stroke-linejoin="round" stroke-linecap="round"/>');
    s.push('<circle cx="' + sx(2025) + '" cy="' + sy(d.now) + '" r="7" fill="#1d2b4f"/>');
    // 右端のラベル（重なるときは上下にずらす）
    var labs = [{ v: d.v50, c: "#e03131", t: "データ " + num(d.v50) + "人" }];
    if (d.mine50 != null) labs.push({ v: d.mine50, c: "#1c7ed6", t: "わたし " + num(d.mine50) + "人" });
    labs.sort(function (a, b2) { return b2.v - a.v; });
    var ys = labs.map(function (o) { return sy(o.v) + 6; });
    if (ys.length === 2 && ys[1] - ys[0] < 22) { var mid = (ys[0] + ys[1]) / 2; ys[0] = mid - 11; ys[1] = mid + 11; }
    labs.forEach(function (o, i) {
      s.push('<circle cx="' + sx(2050) + '" cy="' + sy(o.v) + '" r="6" fill="' + o.c + '"/>');
      s.push('<text x="' + (sx(2050) + 12) + '" y="' + ys[i] + '" font-size="18" font-weight="700" fill="#1d2b4f">' + esc(o.t) + "</text>");
    });
    return s.join("");
  }

  UG.cardSVG = function (d) {
    var s = [];
    var from = [d.nick, d.grade].filter(Boolean).join("・");
    var pct = d.pct == null ? "" : UG.pctText(d.pct).replace(/ /g, "");
    s.push('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + CW + " " + CH + '" width="' + CW + '" height="' + CH + '" font-family="' + FONT + '" role="img" aria-label="みらい ていあんカード">');
    s.push('<defs><pattern id="cg" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M25 0H0V25" fill="none" stroke="#e3eef4" stroke-width="1"/></pattern></defs>');
    s.push('<rect width="' + CW + '" height="' + CH + '" fill="#ffffff"/><rect width="' + CW + '" height="' + CH + '" fill="url(#cg)"/>');
    s.push('<rect x="14" y="14" width="' + (CW - 28) + '" height="' + (CH - 28) + '" fill="none" stroke="#1d2b4f" stroke-width="5" rx="18"/>');
    // 見出し
    s.push('<rect x="14" y="14" width="' + (CW - 28) + '" height="96" fill="#1d2b4f" rx="18"/><rect x="14" y="70" width="' + (CW - 28) + '" height="40" fill="#1d2b4f"/>');
    s.push('<text x="50" y="78" font-size="44" font-weight="800" fill="#ffffff">みらい ていあんカード</text>');
    s.push('<text x="' + (CW - 50) + '" y="62" font-size="20" text-anchor="end" fill="#cfe0ea">' + esc(d.date) + '</text><text x="' + (CW - 50) + '" y="90" font-size="20" text-anchor="end" fill="#ffe066">わたしの学校2050</text>');
    // あて先・学校
    s.push('<text x="50" y="164" font-size="34" font-weight="800" fill="#1d2b4f">' + esc(d.to) + " へ</text>");
    s.push('<text x="' + (CW - 50) + '" y="150" font-size="24" font-weight="700" text-anchor="end" fill="#1d2b4f">' + esc(d.school) + "（" + esc(d.city) + "）</text>");
    if (from) s.push('<text x="' + (CW - 50) + '" y="182" font-size="20" text-anchor="end" fill="#51607d">' + esc(from) + " より</text>");
    s.push('<line x1="50" y1="200" x2="' + (CW - 50) + '" y2="200" stroke="#1d2b4f" stroke-width="2"/>');
    // グラフ
    s.push('<text x="50" y="238" font-size="22" font-weight="800" fill="#1d2b4f">子どもの 数の グラフ</text>');
    s.push(miniChart(d, 40, 250, 640, 290));
    // 数字
    s.push('<text x="720" y="238" font-size="22" font-weight="800" fill="#1d2b4f">データで わかった こと</text>');
    s.push('<rect x="716" y="254" width="434" height="286" rx="14" fill="#fff8d6" stroke="#1d2b4f" stroke-width="2"/>');
    s.push('<text x="740" y="304" font-size="24" fill="#1d2b4f">2025年</text><text x="1126" y="308" font-size="46" font-weight="800" text-anchor="end" fill="#1d2b4f">' + num(d.now) + '<tspan font-size="24"> 人</tspan></text>');
    s.push('<circle cx="748" cy="369" r="8" fill="#e03131"/><text x="764" y="378" font-size="24" fill="#1d2b4f">2050年（データ）</text><text x="1126" y="382" font-size="46" font-weight="800" text-anchor="end" fill="#1d2b4f">' + num(d.v50) + '<tspan font-size="24"> 人</tspan></text>');
    s.push('<line x1="740" y1="406" x2="1126" y2="406" stroke="#1d2b4f" stroke-width="1.5" stroke-dasharray="4 6"/>');
    s.push('<text x="740" y="448" font-size="26" font-weight="800" fill="#1d2b4f">' + esc(pct) + " 計算</text>");
    if (d.mine50 != null) s.push('<circle cx="748" cy="492" r="8" fill="#1c7ed6"/><text x="764" y="500" font-size="22" fill="#1d2b4f">わたしの よそうは ' + num(d.mine50) + "人</text>");
    // アイデア
    s.push('<text x="50" y="592" font-size="22" font-weight="800" fill="#1d2b4f">やってみたい アイデア</text>');
    var iy = 628, lines = 0;
    (d.ideas.length ? d.ideas : ["（まだ えらんで いません）"]).forEach(function (t) {
      if (lines >= 6) return;
      var ws = wrap(t, 24, 2);
      if (lines + ws.length > 6) return;
      s.push('<circle cx="60" cy="' + (iy + lines * 30 - 7) + '" r="5" fill="#1d2b4f"/>');
      s.push('<text font-size="21" fill="#1d2b4f">' + tspans(ws, 76, iy + lines * 30, 30) + "</text>");
      lines += ws.length;
    });
    // ていあん
    s.push('<text x="620" y="592" font-size="22" font-weight="800" fill="#1d2b4f">わたしの ていあん</text>');
    s.push('<rect x="616" y="606" width="534" height="176" rx="14" fill="#ffffff" stroke="#1d2b4f" stroke-width="2.5"/>');
    var pl = wrap(d.proposal || "（ここに きみの ていあんが 入ります）", 21, 5);
    s.push('<text font-size="23" fill="' + (d.proposal ? "#1d2b4f" : "#8a96ad") + '">' + tspans(pl, 636, 644, 31) + "</text>");
    // 出典
    var src = d.sample
      ? "これは れんしゅう用の 架空の まちの データです。"
      : "データ：国土数値情報（500mメッシュ別将来推計人口・小学校区）を もとに 計算。「いまの ながれが つづいたら」の 推計です。";
    s.push('<text x="50" y="' + (CH - 34) + '" font-size="16" fill="#51607d">' + esc(src) + "</text>");
    s.push("</svg>");
    return s.join("");
  };

  UG.cardText = function (d) {
    var pct = d.pct == null ? "" : UG.pctText(d.pct).replace(/ /g, "");
    var out = [];
    out.push(d.to + " へ");
    out.push("");
    out.push(d.school + "（" + d.city + "）の子どもは、2025年の" + num(d.now) + "人から、2050年には" + num(d.v50) + "人（" + pct + "）になる計算です。");
    if (d.mine50 != null) out.push("わたしのよそうは" + num(d.mine50) + "人でした。");
    if (d.ideas.length) { out.push(""); out.push("やってみたいアイデア"); d.ideas.forEach(function (t) { out.push("・" + t); }); }
    if (d.proposal) { out.push(""); out.push("わたしのていあん"); out.push(d.proposal); }
    out.push("");
    out.push([d.nick, d.grade].filter(Boolean).join("・") + (d.nick || d.grade ? "　" : "") + d.date);
    out.push(d.sample ? "（れんしゅう用の架空のデータです）" : "（データ：国土数値情報をもとに「わたしの学校2050」で計算。いまのながれがつづいた場合の推計です）");
    return out.join("\n");
  };

  UG.cardPNG = function (svg) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        try {
          var cv = document.createElement("canvas");
          cv.width = CW * 2; cv.height = CH * 2;
          var g = cv.getContext("2d");
          g.fillStyle = "#ffffff"; g.fillRect(0, 0, cv.width, cv.height);
          g.drawImage(img, 0, 0, cv.width, cv.height);
          cv.toBlob(function (b) { b ? resolve(b) : reject(new Error("画像に できませんでした")); }, "image/png");
        } catch (e) { reject(e); }
      };
      img.onerror = function () { reject(new Error("画像に できませんでした")); };
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    });
  };
})();
