/*
 * わたしの学校2050 — 計算モデル（画面に依存しない純粋関数）
 * ブラウザでは window.UG.model、Node では module.exports として使える。
 * tests/model.test.js で検算している。
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else (root.UG = root.UG || {}).model = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** 推計年（国土数値情報 メッシュ別将来推計人口 R6 は 2025〜2070 の5年ごと） */
  var EST_YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060, 2065, 2070];
  var BASE_YEAR = 2025;
  var TARGET_YEAR = 2050;
  /** 子どもが線を描く年（いま=2025 の次から 2050 まで） */
  var DRAW_YEARS = [2030, 2035, 2040, 2045, 2050];

  /** 国の学級編制の標準（公立義務教育諸学校の学級編制及び教職員定数の標準に関する法律） */
  var CLASS_MAX = 35; // 小学校 同学年で編制する学級 35人
  var MULTI_MAX = 16; // 複式学級 2つの学年で16人以下
  var MULTI_MAX_WITH_G1 = 8; // 1年生を含む場合は8人以下

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  /** [{y, v}]（年の昇順）を線形補間。範囲外は端の値。 */
  function interp(points, year) {
    if (!points.length) return null;
    if (year <= points[0].y) return points[0].v;
    for (var i = 1; i < points.length; i++) {
      if (year <= points[i].y) {
        var a = points[i - 1], b = points[i];
        return a.v + ((b.v - a.v) * (year - a.y)) / (b.y - a.y);
      }
    }
    return points[points.length - 1].v;
  }

  /** est 配列を [{y, v}] に。calib（いまの実際の人数）があれば 2025年値との比で全体を補正する。 */
  function estPoints(school, calib) {
    var k = calibFactor(school, calib);
    return EST_YEARS.map(function (y, i) {
      return { y: y, v: school.est[i] * k };
    });
  }

  function calibFactor(school, calib) {
    var base = school.est[0];
    if (calib == null || !isFinite(calib) || calib <= 0 || !(base > 0)) return 1;
    return calib / base;
  }

  /** 過去の児童数（データにあるもの＋子どもが調べて足したもの）を年の昇順で返す。 */
  function histPoints(school, extra) {
    var map = {};
    var h = school.hist || {};
    Object.keys(h).forEach(function (y) {
      map[+y] = { y: +y, v: +h[y], src: "data" };
    });
    (extra || []).forEach(function (p) {
      if (isFinite(p.y) && isFinite(p.v) && p.y < BASE_YEAR) map[+p.y] = { y: +p.y, v: +p.v, src: "kid" };
    });
    return Object.keys(map)
      .map(function (y) { return map[y]; })
      .sort(function (a, b) { return a.y - b.y; });
  }

  /** 変化率（%）。from が 0 のときは null。 */
  function pctChange(from, to) {
    if (!(from > 0)) return null;
    return ((to - from) / from) * 100;
  }

  /** 全校児童数を6学年に分ける（学年別データがないための均等割り。端数は上の学年から）。 */
  function splitGrades(total) {
    var n = Math.max(0, Math.round(total));
    var base = Math.floor(n / 6), rem = n % 6;
    var g = [];
    for (var i = 0; i < 6; i++) g.push(base + (i >= 6 - rem ? 1 : 0));
    return g; // [1年, 2年, ..., 6年]
  }

  /** n人を c学級に分けた各学級の人数 */
  function splitClass(n, c) {
    var base = Math.floor(n / c), rem = n % c, out = [];
    for (var i = 0; i < c; i++) out.push(base + (i < rem ? 1 : 0));
    return out;
  }

  /**
   * 国の標準にもとづく学級のめやす。
   * 返り値: { total, grades[6], rows[{grades:[学年番号], n, classes:[人数...], multi:boolean}],
   *           classCount, shuffle: "all"|"some"|"none", hasMulti }
   */
  function classPlan(total) {
    var g = splitGrades(total);
    var rows = [];
    for (var p = 0; p < 3; p++) {
      var a = p * 2, b = a + 1;
      var sum = g[a] + g[b];
      var limit = a === 0 ? MULTI_MAX_WITH_G1 : MULTI_MAX;
      if (sum > 0 && sum <= limit) {
        rows.push({ grades: [a + 1, b + 1], n: sum, classes: [sum], multi: true });
      } else {
        [a, b].forEach(function (i) {
          var c = g[i] > 0 ? Math.ceil(g[i] / CLASS_MAX) : 0;
          rows.push({ grades: [i + 1], n: g[i], classes: c ? splitClass(g[i], c) : [], multi: false });
        });
      }
    }
    var single = rows.filter(function (r) { return !r.multi; });
    var canShuffle = single.filter(function (r) { return r.classes.length >= 2; }).length;
    var hasMulti = rows.some(function (r) { return r.multi; });
    var shuffle = "none";
    if (!hasMulti && canShuffle === 6) shuffle = "all";
    else if (canShuffle > 0) shuffle = "some";
    return {
      total: Math.max(0, Math.round(total)),
      grades: g,
      rows: rows,
      classCount: rows.reduce(function (s, r) { return s + r.classes.length; }, 0),
      shuffle: shuffle,
      hasMulti: hasMulti
    };
  }

  /**
   * 「もしも」シミュレーター（説明用のかんたんなモデル）。
   *  move  : 毎年 学区に加わる小学生の数（人/年）。2026年から始まり、6年間在籍すると考える
   *          → 上乗せは move × min(6, 年−2026)。
   *  birth : 2027年以降に生まれる子どもの数の変化（%）。その子たちは2033年から入学し、
   *          2039年に全学年が入れ替わる → 係数は 1 + birth% × clamp((年−2033)/6, 0, 1)。
   */
  function simValue(year, base, move, birth) {
    var add = (move || 0) * clamp(year - 2026, 0, 6);
    var f = 1 + ((birth || 0) / 100) * clamp((year - 2033) / 6, 0, 1);
    return Math.max(0, base * f + add);
  }

  function simPoints(points, move, birth) {
    return points.map(function (p) {
      return { y: p.y, v: simValue(p.y, p.v, move, birth) };
    });
  }

  /**
   * 0〜11歳の年齢別人口（2025年）。
   * pipeline 出力の ages（0〜4歳・5〜9歳・10〜14歳を各歳に均等割りしたもの）があればそれを使い、
   * なければ 2025年と2030年の小学生数から直線で近似する（サンプル用）。
   */
  function agesFor(school, calib) {
    var k = calibFactor(school, calib);
    if (school.ages && school.ages.length === 12) {
      return school.ages.map(function (v) { return v * k; });
    }
    var e25 = school.est[0], e30 = school.est[1];
    var beta = (e25 - e30) / 30;
    var alpha = e25 / 6 - 8.5 * beta;
    var a = [];
    for (var i = 0; i < 12; i++) a.push(Math.max(0, alpha + beta * i));
    var s = 0;
    for (var j = 6; j < 12; j++) s += a[j];
    var norm = s > 0 ? e25 / s : 0;
    return a.map(function (v) { return v * norm * k; });
  }

  /**
   * コーホートを k年進める。返り値は12本（0〜11歳）で、まだ生まれていない世代は null。
   * 引っ越しや亡くなる人を考えない、しくみの説明用。
   */
  function ageStep(ages, k) {
    var out = [];
    for (var j = 0; j < 12; j++) out.push(j - k >= 0 ? ages[j - k] : null);
    return out;
  }

  /** k年後の小学生（6〜11歳）の合計。未知の世代が混ざるときは known:false。 */
  function elementaryAfter(ages, k) {
    var st = ageStep(ages, k), sum = 0, known = true;
    for (var j = 6; j < 12; j++) {
      if (st[j] == null) known = false;
      else sum += st[j];
    }
    return { sum: sum, known: known };
  }

  /** グラフの上限をきりのよい数にする */
  function niceMax(v) {
    if (!(v > 0)) return 10;
    var pow = Math.pow(10, Math.floor(Math.log10(v)));
    var steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < steps.length; i++) if (steps[i] * pow >= v) return steps[i] * pow;
    return 10 * pow;
  }

  function niceTicks(max, count) {
    var raw = max / (count || 4);
    var pow = Math.pow(10, Math.floor(Math.log10(raw)));
    var cands = [1, 2, 2.5, 5, 10];
    var step = cands[cands.length - 1] * pow;
    for (var i = 0; i < cands.length; i++) if (cands[i] * pow >= raw) { step = cands[i] * pow; break; }
    var out = [];
    for (var t = 0; t <= max + 1e-9; t += step) out.push(Math.round(t * 100) / 100);
    return out;
  }

  /** 学年（'e4'…'j3'）から2050年の年齢のめやす。小1=7歳（年度末）として計算。 */
  function ageIn(grade, year, nowYear) {
    var m = /^([ej])(\d)$/.exec(grade || "");
    if (!m) return null;
    var g = +m[2] + (m[1] === "j" ? 6 : 0);
    return g + 6 + (year - (nowYear || 2026));
  }

  /** 予想とデータの差の評価 */
  function judgeGuess(mine, data) {
    if (!(data > 0)) return { diff: mine - data, ratio: null, level: "na" };
    var d = Math.abs(mine - data), r = d / data;
    // 小さな学校では1〜2人の差で割合が大きくぶれるので、人数の許容幅も持たせる
    var level = d <= Math.max(2, data * 0.1) ? "close" : d <= Math.max(5, data * 0.3) ? "near" : "far";
    return { diff: mine - data, ratio: r, level: level };
  }

  /**
   * 学校をさがす欄の入力から、比べる文字を作る。先頭の設置者（「福岡市立」「〜町立」「〜村立」「〜区立」「〜組合立」）を外す。
   * 学校名のデータは設置者を外してあるので、「福岡市立西新小学校」と入れても「西新小学校」と比べられる。
   */
  var OWNER_HEAD = /^[^\s]{0,15}?(?:組合立|市立|町立|村立|区立)/;
  function schoolQuery(q) {
    return String(q == null ? "" : q).replace(/[\s\u3000]+/g, "").replace(OWNER_HEAD, "");
  }
  /** 学校名が入力に合うか。設置者を外した結果が空なら、どの学校も合う */
  function matchSchool(name, q) {
    var k = schoolQuery(q);
    return !k || String(name).indexOf(k) >= 0;
  }

  return {
    EST_YEARS: EST_YEARS, BASE_YEAR: BASE_YEAR, TARGET_YEAR: TARGET_YEAR, DRAW_YEARS: DRAW_YEARS,
    CLASS_MAX: CLASS_MAX, MULTI_MAX: MULTI_MAX, MULTI_MAX_WITH_G1: MULTI_MAX_WITH_G1,
    clamp: clamp, interp: interp, estPoints: estPoints, calibFactor: calibFactor, histPoints: histPoints,
    pctChange: pctChange, splitGrades: splitGrades, splitClass: splitClass, classPlan: classPlan,
    simValue: simValue, simPoints: simPoints, agesFor: agesFor, ageStep: ageStep,
    elementaryAfter: elementaryAfter, niceMax: niceMax, niceTicks: niceTicks, ageIn: ageIn, judgeGuess: judgeGuess,
    schoolQuery: schoolQuery, matchSchool: matchSchool
  };
});
