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

  /**
   * 年齢の階段に出す各歳の人数（整数）。
   * 1) 6〜11歳の合計が total（画面の「いまの人数」と同じ値）になるように、12本に同じ倍率を掛ける
   *    （ages と est はどちらも小数1けたで保存しているので、合計が最大0.3人ほど食い違う）。
   * 2) 11歳から0歳へ向かって累積し、累積を丸めた差を各歳の整数にする（累積丸め）。
   * こうすると、2025年の小学生（6〜11歳）の整数の合計は Math.round(total) と必ず一致し、
   * どの連続した6本の合計も、小数のままの合計と1人未満しかずれない。各世代の整数は年を進めても変わらない。
   */
  function cohortInts(ages, total) {
    var el = 0, j;
    for (j = 6; j < 12; j++) el += ages[j] || 0;
    var k = el > 0 && total > 0 ? total / el : 1;
    var out = new Array(12), cum = 0, prev = 0;
    for (j = 11; j >= 0; j--) {
      cum += (ages[j] || 0) * k;
      var r = Math.round(Math.round(cum * 1e6) / 1e6); // 12.4999999 のような誤差で丸めが変わらないように
      out[j] = r - prev;
      prev = r;
    }
    return out;
  }

  /** 画面に出す2つの人数（丸めたもの）から変化率を出す。子どもが画面の数で計算しても同じになる。 */
  function shownPct(from, to) {
    return pctChange(Math.round(from), Math.round(to));
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

  /** 学校名によく出る異体字 → 寄せる先の字。学校名と入力の両方を同じように寄せてから比べる */
  var VARIANTS = {
    "龍": "竜", "﨑": "崎", "嵜": "崎", "碕": "崎", "髙": "高", "邊": "辺", "邉": "辺", "齋": "斎", "齊": "斉",
    "澤": "沢", "濱": "浜", "廣": "広", "國": "国", "櫻": "桜", "瀨": "瀬", "曾": "曽", "德": "徳", "槇": "槙",
    "冨": "富", "嶋": "島", "嶌": "島", "舘": "館", "栁": "柳", "淵": "渕", "萬": "万", "會": "会", "惠": "恵",
    "眞": "真", "黑": "黒", "檜": "桧", "藪": "薮", "鷗": "鴎", "條": "条", "壽": "寿", "實": "実", "峯": "峰"
  };
  var VARIANT_RE = new RegExp("[" + Object.keys(VARIANTS).join("") + "]", "g");
  var KE_AFTER_KANJI = /([㐀-鿿豈-﫿々〆])[ケヶ]/g;

  /** 小さい平仮名 → 大きい字。町字データの読みは「じゆうもんじ」「ちゆうおう」のように小さい字を大きく書いているので、入力・学校名・読みの全部をそろえる */
  var SMALL = { "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お", "っ": "つ", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ", "ゕ": "か", "ゖ": "け" };
  var SMALL_RE = /[ぁぃぅぇぉっゃゅょゎゕゖ]/g;

  /** 比べる前にそろえる：NFKC（半角カナ・全角英数）→ 空白を除く →「ヶ」と（漢字の後の）「ケ」を「が」に → 片仮名を平仮名に → 小さい字を大きく → 異体字を寄せる */
  function foldText(s) {
    s = String(s == null ? "" : s);
    if (s.normalize) s = s.normalize("NFKC");
    s = s.replace(/[\s　]+/g, "").replace(KE_AFTER_KANJI, "$1が").replace(/ヶ/g, "が");
    s = s.replace(/[ァ-ヶ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0x60); });
    s = s.replace(SMALL_RE, function (c) { return SMALL[c]; });
    return s.replace(VARIANT_RE, function (c) { return VARIANTS[c]; });
  }

  /** 平仮名と「ー」だけの入力か（このときは読みでも さがす） */
  function isKanaQuery(k) {
    return /^[ぁ-ゖー]+$/.test(k);
  }

  /** 入力をそろえる：NFKC・空白を除く・先頭の設置者を外す・片仮名を平仮名に・異体字と「ヶ」を寄せる */
  function schoolQuery(q) {
    var s = String(q == null ? "" : q);
    if (s.normalize) s = s.normalize("NFKC");
    return foldText(s.replace(/[\s　]+/g, "").replace(OWNER_HEAD, ""));
  }
  /**
   * 学校が入力に合うか。school は { name, kana } か学校名の文字列。
   *  - そろえた学校名に、そろえた入力が含まれれば合う（漢字とかなが混ざった入力は、これだけ）
   *  - 入力が平仮名と「ー」だけなら、読み（kana）のどれかに含まれても合う（途中から打っても出る）
   *  設置者を外した結果が空なら、どの学校も合う
   */
  function matchSchool(school, q) {
    var k = schoolQuery(q);
    if (!k) return true;
    var name = typeof school === "string" ? school : (school && school.name) || "";
    if (foldText(name).indexOf(k) >= 0) return true;
    if (!isKanaQuery(k) || typeof school === "string") return false;
    var kana = (school && school.kana) || [];
    for (var i = 0; i < kana.length; i++) if (foldText(kana[i]).indexOf(k) >= 0) return true;
    return false;
  }

  /* ---------------- クラスモード：よそうのコード ----------------
   * 子どもの よそうを、先生に わたす 1つながりの文字列にする。
   *   WG50- ＋ 中身（base64url） ＋ 確かめ用（CRC-32 を base64url で 6文字）
   * 中身は JSON の配列を UTF-8 にしたもの。名前（nick）は入れない。
   *   版2：[2, 都道府県コード, 学校の id, guess(u/s/d), 2030, 2035, 2040, 2045, 2050, 端末の印, 番号, 理由?, 実際の人数?]
   *        端末の印は でたらめな6文字（同じ子が2回送ったら新しいほうだけ数える）。番号は その端末で作った順。
   *        理由と実際の人数（calib）は無ければ省く（calib だけあるときは 理由を "" にする）。
   *   版3：版2の 理由・実際の人数（無ければ 0）の後ろに、提案 { s: カード8枚の いいね(g)/しんぱい(b)/どちらとも(m)/えらばない(-),
   *        i: アイデアの id（3つまで）, o: 自分の アイデア, t: 宛先, p: 提案の 文 }（ステップ5）。空のものは省く
   *   版1：[1, 都道府県コード, 学校の id, guess, 2030…2050, 理由?]（読むだけ）
   * 線の値は整数に丸める。
   */
  var CODE_HEAD = "WG50-";
  var CODE_VERSION = 2;
  var MARK_RE = /^[A-Za-z0-9_-]{4,12}$/;
  var CHECK_LEN = 6;
  var B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  var GUESS_TO = { up: "u", same: "s", down: "d" };
  var GUESS_FROM = { u: "up", s: "same", d: "down" };
  var REASON_MAX = 200; // 入力欄は60字。古い端末などで長いものが来ても、ここまでは読む

  function utf8Bytes(s) {
    var out = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c >= 0xd800 && c < 0xdc00 && i + 1 < s.length) {
        var d = s.charCodeAt(i + 1);
        if (d >= 0xdc00 && d < 0xe000) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
      }
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }
  function utf8Text(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += "%" + (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16);
    return decodeURIComponent(s); // こわれた UTF-8 は例外
  }
  function b64Encode(bytes) {
    var out = "";
    for (var i = 0; i < bytes.length; i += 3) {
      var n = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8) | (bytes[i + 2] || 0);
      out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63];
      if (i + 1 < bytes.length) out += B64[(n >> 6) & 63];
      if (i + 2 < bytes.length) out += B64[n & 63];
    }
    return out;
  }
  function b64Decode(s) {
    if (s.length % 4 === 1) return null;
    var out = [], buf = 0, bits = 0;
    for (var i = 0; i < s.length; i++) {
      var v = B64.indexOf(s[i]);
      if (v < 0) return null;
      buf = (buf << 6) | v; bits += 6;
      if (bits >= 8) { bits -= 8; out.push((buf >> bits) & 255); }
    }
    return out;
  }
  var CRC_TABLE = (function () {
    var t = [];
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t.push(c >>> 0);
    }
    return t;
  })();
  function crc32(bytes) {
    var c = 0xffffffff;
    for (var i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 255] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  function checkChars(bytes) {
    var c = crc32(bytes), out = "";
    for (var i = CHECK_LEN - 1; i >= 0; i--) out += B64[Math.floor(c / Math.pow(64, i)) % 64];
    return out;
  }

  /** 1行の文にそろえる（空白をまとめ、前後を切り、長さを そろえる） */
  function oneLine(v, max) {
    return String(v || "").replace(/\s+/g, " ").trim().slice(0, max);
  }
  /** ステップ5の「いいこと？ しんぱいな こと？」の 8枚のカード（views2.js の UG.SORT_CARDS と同じ id・並び） */
  var SORT_IDS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];
  var SORT_TO = { good: "g", bad: "b", mid: "m" };
  var SORT_FROM = { g: "good", b: "bad", m: "mid" };
  var PROPOSAL_MAX = 300, OWN_IDEA_MAX = 100; // 入力欄は 110字・40字。古い端末などで長いものが来ても、ここまでは読む
  var OWN_WISH_MAX = 60, WISH_MAX = 3; // もっと 知りたい データ：自由な 文（入力欄は 30字）と、えらべる 数
  var ID_RE = /^[a-z][a-z0-9_]{0,23}$/;
  /** 提案の中身 → コードに入れる形 { s: "gb-m----", i: [アイデアの id], o: 自分のアイデア, t: 宛先, p: 提案,
   *  w: [もっと 知りたい データの id], d: 自由に 書いた 知りたい データ }（空のものは省く） */
  function propOut(pr) {
    var out = {};
    var sv = SORT_IDS.map(function (id) { return SORT_TO[pr.sort && pr.sort[id]] || "-"; }).join("");
    if (sv !== "--------") out.s = sv;
    var ideas = (pr.ideas || []).filter(function (x) { return typeof x === "string" && ID_RE.test(x); }).slice(0, 3);
    if (ideas.length) out.i = ideas;
    var own = oneLine(pr.ownIdea, OWN_IDEA_MAX);
    if (own) out.o = own;
    if (typeof pr.to === "string" && ID_RE.test(pr.to)) out.t = pr.to;
    var text = oneLine(pr.proposal, PROPOSAL_MAX);
    if (text) out.p = text;
    var wishes = (pr.wishes || []).filter(function (x) { return typeof x === "string" && ID_RE.test(x); }).slice(0, WISH_MAX);
    if (wishes.length) out.w = wishes;
    var wish = oneLine(pr.ownWish, OWN_WISH_MAX);
    if (wish) out.d = wish;
    return out;
  }
  /** コードの形 → 提案の中身 { sort, ideas, ownIdea, to, proposal, wishes, ownWish }。形がおかしければ null。
   *  w・d の無い コード（これまでの もの）は wishes: []、ownWish: "" */
  function propIn(o) {
    if (!o || typeof o !== "object" || Array.isArray(o)) return null;
    var s = o.s == null ? "--------" : o.s, ideas = o.i == null ? [] : o.i;
    if (typeof s !== "string" || !/^[gbm-]{8}$/.test(s) || !Array.isArray(ideas) || ideas.length > 3 ||
        !ideas.every(function (x) { return typeof x === "string" && ID_RE.test(x); }) ||
        (o.o != null && (typeof o.o !== "string" || o.o.length > OWN_IDEA_MAX)) ||
        (o.t != null && (typeof o.t !== "string" || !ID_RE.test(o.t))) ||
        (o.p != null && (typeof o.p !== "string" || o.p.length > PROPOSAL_MAX))) return null;
    var wishes = o.w == null ? [] : o.w;
    if (!Array.isArray(wishes) || wishes.length > WISH_MAX ||
        !wishes.every(function (x) { return typeof x === "string" && ID_RE.test(x); }) ||
        (o.d != null && (typeof o.d !== "string" || o.d.length > OWN_WISH_MAX))) return null;
    var sort = {};
    SORT_IDS.forEach(function (id, i) { if (s[i] !== "-") sort[id] = SORT_FROM[s[i]]; });
    return { sort: sort, ideas: ideas.slice(), ownIdea: o.o || "", to: o.t || "", proposal: o.p || "",
      wishes: wishes.slice(), ownWish: o.d || "" };
  }

  /**
   * よそうをコードにする。g: { pref, school, guess: "up"|"same"|"down", draw: {2030:…, …, 2050:…}, reason, calib, mark, seq,
   *   prop: { sort: {c1: "good"|"bad"|"mid", …}, ideas: [id…], ownIdea, to, proposal, wishes: [id…], ownWish } | 無し }（ステップ5は prop つき）
   * 線が2050年までそろっていなければ null。
   */
  function encodeGuess(g) {
    if (!g || !GUESS_TO[g.guess]) return null;
    var vals = DRAW_YEARS.map(function (y) { return g.draw && g.draw[y]; });
    if (vals.some(function (v) { return v == null || !isFinite(v); })) return null;
    var mark = typeof g.mark === "string" && MARK_RE.test(g.mark) ? g.mark : "";
    var seq = g.seq > 0 && isFinite(g.seq) ? Math.floor(g.seq) : 0;
    var arr = [CODE_VERSION, String(g.pref), String(g.school), GUESS_TO[g.guess]]
      .concat(vals.map(function (v) { return Math.max(0, Math.round(v)); }), [mark, seq]);
    var reason = oneLine(g.reason, REASON_MAX);
    var calib = g.calib > 0 && isFinite(g.calib) ? Math.round(g.calib) : null;
    if (g.prop) {
      // 版3：提案つき（ステップ5）。理由と calib（無ければ 0）は いつも 置く
      arr[0] = 3;
      arr.push(reason, calib || 0, propOut(g.prop));
    } else {
      if (reason || calib) arr.push(reason);
      if (calib) arr.push(calib);
    }
    var bytes = utf8Bytes(JSON.stringify(arr));
    return CODE_HEAD + b64Encode(bytes) + checkChars(bytes);
  }

  /**
   * コードを読む。読めれば { ok: true, code, pref, school, guess, draw, reason, calib, mark, seq }、読めなければ { ok: false, code, error }。
   * 版1（印・番号・calib なし）も読む。
   */
  function decodeGuess(code) {
    var fail = function (e) { return { ok: false, code: code, error: e }; };
    code = String(code == null ? "" : code).trim();
    if (code.indexOf(CODE_HEAD) !== 0) return fail("head");
    var rest = code.slice(CODE_HEAD.length);
    if (rest.length <= CHECK_LEN) return fail("short");
    var bytes = b64Decode(rest.slice(0, -CHECK_LEN));
    if (!bytes || checkChars(bytes) !== rest.slice(-CHECK_LEN)) return fail("check"); // 途中で切れた・書きかえた
    var arr;
    try { arr = JSON.parse(utf8Text(bytes)); } catch (e) { return fail("format"); }
    if (!Array.isArray(arr) || [1, 2, 3].indexOf(arr[0]) < 0) return fail("version");
    var v1 = arr[0] === 1, mark = "", seq = 0, reason = "", calib = null, prop = null;
    if (v1) {
      if (arr.length < 9 || arr.length > 10) return fail("format");
      reason = arr.length > 9 ? arr[9] : "";
    } else if (arr[0] === 3) {
      if (arr.length !== 14) return fail("format");
      mark = arr[9]; seq = arr[10]; reason = arr[11]; calib = arr[12] || null;
      prop = propIn(arr[13]);
      if (!prop || typeof mark !== "string" || (mark && !MARK_RE.test(mark)) || typeof seq !== "number" || !(seq >= 0 && seq <= 1e9) ||
          (calib !== null && !(typeof calib === "number" && calib > 0 && calib <= 100000))) return fail("format");
    } else {
      if (arr.length < 11 || arr.length > 13) return fail("format");
      mark = arr[9]; seq = arr[10];
      reason = arr.length > 11 ? arr[11] : "";
      calib = arr.length > 12 ? arr[12] : null;
      if (typeof mark !== "string" || (mark && !MARK_RE.test(mark)) || typeof seq !== "number" || !(seq >= 0 && seq <= 1e9) ||
          (calib !== null && !(typeof calib === "number" && calib > 0 && calib <= 100000))) return fail("format");
    }
    var pref = arr[1], school = arr[2], guess = GUESS_FROM[arr[3]];
    if (typeof pref !== "string" || !/^\d{2}$/.test(pref) || typeof school !== "string" || !school || school.length > 40 ||
        !guess || typeof reason !== "string" || reason.length > REASON_MAX) return fail("format");
    var draw = {};
    for (var i = 0; i < DRAW_YEARS.length; i++) {
      var v = arr[4 + i];
      if (typeof v !== "number" || !isFinite(v) || v < 0 || v > 100000) return fail("format");
      draw[DRAW_YEARS[i]] = v;
    }
    return { ok: true, code: code, pref: pref, school: school, guess: guess, draw: draw, reason: reason,
      calib: calib, mark: mark, seq: seq, prop: prop };
  }

  /** 端末の印（でたらめな6文字）。rand は 0以上1未満を返す関数。名前や端末の情報からは作らない */
  function makeMark(rand) {
    var s = "";
    for (var i = 0; i < 6; i++) s += B64[Math.floor(rand() * 64) % 64];
    return s;
  }

  /**
   * 貼りつけた文（名前や日時が まじっていてもよい）から、コードを全部取り出して読む。
   *  - すきまなく続けて貼られたコードは WG50- で分ける
   *  - 読めなかったコードが行の終わりにあれば、すぐ後ろの行の頭の base64url の文字を、読めるまで つないで読み直す
   *    （途中で改行されたとき。base64url の文字だけの行が続くあいだ、20行まで。ほかのコードで始まる行は つながない）
   *  - 同じコードは1回。同じ端末の印があれば、番号のいちばん大きいもの（新しいもの）だけを数える
   * 返り値: { items: [読めたもの], bad: [読めなかったコード], dup: 同じコードで除いた数, replaced: 同じ端末の古いもので除いた数 }
   */
  var JOIN_LINES = 20;
  function extractGuesses(text) {
    var s = String(text == null ? "" : text);
    if (s.normalize) s = s.normalize("NFKC");
    var lines = s.split(/\r\n|\r|\n|\u2028|\u2029/);
    var found = [];
    for (var li = 0; li < lines.length; li++) {
      var line = lines[li], re = /WG50-[A-Za-z0-9_-]*/g, m;
      while ((m = re.exec(line))) {
        var pieces = m[0].split(CODE_HEAD).slice(1);
        var atEnd = !line.slice(m.index + m[0].length).trim();
        for (var pi = 0; pi < pieces.length; pi++) {
          var code = CODE_HEAD + pieces[pi];
          if (!decodeGuess(code).ok && pi === pieces.length - 1 && atEnd) {
            var joined = code;
            for (var k = 1; k <= JOIN_LINES && li + k < lines.length; k++) {
              var run = /^\s*([A-Za-z0-9_-]+)/.exec(lines[li + k]);
              if (!run || run[1].indexOf(CODE_HEAD) === 0) break;
              joined += run[1];
              if (decodeGuess(joined).ok) { code = joined; break; }
              if (lines[li + k].trim() !== run[1]) break; // 行の中に ほかの文字が つづく → その先へは つながない
            }
          }
          if (pieces[pi] || code !== CODE_HEAD) found.push(code);
        }
      }
    }
    var seen = {}, all = [], bad = [], dup = 0;
    found.forEach(function (c) {
      if (seen[c]) { dup++; return; }
      seen[c] = true;
      var d = decodeGuess(c);
      if (d.ok) all.push(d); else bad.push(c);
    });
    // 同じ端末から2つ以上 → 番号のいちばん大きいものだけ
    var latest = {};
    all.forEach(function (d) { if (d.mark && (!latest[d.mark] || d.seq > latest[d.mark].seq)) latest[d.mark] = d; });
    var items = all.filter(function (d) { return !d.mark || latest[d.mark] === d; });
    return { items: items, bad: bad, dup: dup, replaced: all.length - items.length };
  }

  /** 読んだコードの calib（実際の人数）で、いちばん多い値（同じ数なら小さい値）。無ければ null */
  function commonCalib(items) {
    var cnt = {}, best = null;
    items.forEach(function (d) { if (d.calib > 0) cnt[d.calib] = (cnt[d.calib] || 0) + 1; });
    Object.keys(cnt).forEach(function (k) {
      var v = +k;
      if (best === null || cnt[k] > cnt[best] || (cnt[k] === cnt[best] && v < best)) best = v;
    });
    return best;
  }

  /** 学校ごとに分ける。人数の多い順 [{ pref, school, items }] */
  function groupGuesses(items) {
    var map = {}, out = [];
    items.forEach(function (d) {
      var k = d.pref + "/" + d.school;
      if (!map[k]) { map[k] = { pref: d.pref, school: d.school, items: [] }; out.push(map[k]); }
      map[k].items.push(d);
    });
    return out.sort(function (a, b) { return b.items.length - a.items.length; });
  }

  /**
   * 集計。est50 があれば、推計（2050年）より多い・少ない・ほぼ同じ（画面の丸めで同じ）の数も出す。
   * 返り値: { n, min, max, median, guess: {up, same, down}, vsEst: {more, less, same} | null }
   */
  function summarizeGuesses(items, est50) {
    var v = items.map(function (d) { return d.draw[TARGET_YEAR]; }).sort(function (a, b) { return a - b; });
    var n = v.length;
    var g = { up: 0, same: 0, down: 0 };
    items.forEach(function (d) { g[d.guess]++; });
    var vs = null;
    if (est50 != null && isFinite(est50)) {
      vs = { more: 0, less: 0, same: 0 };
      var e = Math.round(est50);
      v.forEach(function (x) { var r = Math.round(x); vs[r > e ? "more" : r < e ? "less" : "same"]++; });
    }
    return {
      n: n,
      min: n ? v[0] : null,
      max: n ? v[n - 1] : null,
      median: n ? (n % 2 ? v[(n - 1) / 2] : (v[n / 2 - 1] + v[n / 2]) / 2) : null,
      guess: g,
      vsEst: vs
    };
  }


  /* ---------- 提案の 宛先：市区町村の 長 ---------- */
  /**
   * 「◯◯長さん」の ◯◯ に する 名前。
   *  - 政令市の区（福岡市早良区・京都市上京区）→ 市（福岡市）
   *  - 郡の 付いた 町村（山越郡長万部町）→ 町村（長万部町）。上郡町・小郡市のように 名前に 郡が 入るだけの ものは そのまま
   *  - 東京の 特別区（世田谷区）・ふつうの 市町村 → そのまま
   */
  function mayorBase(cityName) {
    var n = String(cityName == null ? "" : cityName).trim();
    var m = /^(.+?市).+区$/.exec(n);
    if (m) return m[1];
    m = /^.+?郡(.+[町村])$/.exec(n);
    if (m) return m[1];
    return n;
  }
  /** 「福岡市長さん」「長万部町長さん」「世田谷区長さん」。名前が 無ければ「市長さん」 */
  function mayorLabel(cityName) {
    var b = mayorBase(cityName);
    return (b || "市") + "長さん";
  }

  /* ---------- クラスモード 第2段階：提案の 集計 ---------- */
  function withProp(items) {
    return items.filter(function (d) { return d.prop; });
  }
  /** カードごとの いいね・しんぱい・どちらとも の数 { c1: {good, bad, mid}, … }（提案の入ったコードだけ） */
  function sortTally(items) {
    var out = {};
    SORT_IDS.forEach(function (id) { out[id] = { good: 0, bad: 0, mid: 0 }; });
    withProp(items).forEach(function (d) {
      SORT_IDS.forEach(function (id) { var v = d.prop.sort[id]; if (v) out[id][v]++; });
    });
    return out;
  }
  /** prop[key]（id の 配列）ごとの数（多い順。同じ数なら order の順、order に無いものは後ろ）[{ id, n }] */
  function tallyIds(items, key, order) {
    var cnt = {};
    withProp(items).forEach(function (d) { (d.prop[key] || []).forEach(function (id) { cnt[id] = (cnt[id] || 0) + 1; }); });
    var pos = function (id) { var i = (order || []).indexOf(id); return i < 0 ? 1e6 : i; };
    return Object.keys(cnt).map(function (id) { return { id: id, n: cnt[id] }; })
      .sort(function (a, b) { return b.n - a.n || pos(a.id) - pos(b.id) || (a.id < b.id ? -1 : 1); });
  }
  /** アイデアごとの数（多い順。同じ数なら order の順、order に無いものは後ろ）[{ id, n }] */
  function ideaTally(items, order) { return tallyIds(items, "ideas", order); }
  /** もっと 知りたい データごとの数（ideaTally と 同じ 並び）[{ id, n }] */
  function wishTally(items, order) { return tallyIds(items, "wishes", order); }
  /** 自分の アイデア（書いてあるものだけ） */
  function ownIdeas(items) {
    return withProp(items).map(function (d) { return d.prop.ownIdea; }).filter(Boolean);
  }
  /** 自由に 書いた もっと 知りたい データ（書いてあるものだけ） */
  function ownWishes(items) {
    return withProp(items).map(function (d) { return d.prop.ownWish; }).filter(Boolean);
  }
  /** 宛先ごとの 提案（文の あるものだけ）。order の順、order に無い宛先は後ろ [{ to, items }] */
  function proposalsByTo(items, order) {
    var map = {}, out = [];
    withProp(items).forEach(function (d) {
      if (!d.prop.proposal) return;
      var t = d.prop.to || "";
      if (!map[t]) { map[t] = { to: t, items: [] }; out.push(map[t]); }
      map[t].items.push(d);
    });
    var pos = function (t) { var i = (order || []).indexOf(t); return i < 0 ? 1e6 : i; };
    return out.sort(function (a, b) { return pos(a.to) - pos(b.to); });
  }

  /** 決まった種から同じ並びを出す乱数（見本のクラス用） */
  function seeded(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  var SAMPLE_REASONS = {
    up: ["近くに 新しい 家が ふえているから", "マンションが できたから", "駅の 近くは 人気だから", "公園で 小さい 子を よく 見るから", "", ""],
    same: ["あまり 変わって いないと 思うから", "なんとなく", "引っこして くる 人と 出て いく 人が 同じくらいだから", "", ""],
    down: ["赤ちゃんを あまり 見ないから", "空き家が ふえているから", "人が へっていると ニュースで 見たから", "お店が へったから",
      "友だちが 引っこして いったから", "", ""]
  };
  // 見本の 提案（架空。宛先ごと。実在の 地名や 学校は 入れない）
  var SAMPLE_PROPOSALS = {
    mayor: ["空いた 教室を 地域の 人も 使える 場所に して ほしいです。お年よりと 子どもが いっしょに すごせます。",
      "子育てを しやすい まちに して、ひっこして くる 家族を ふやして ほしいです。",
      "子どもが 遊べる 公園を ふやして ほしいです。外で 遊ぶ 子が ふえると、まちが にぎやかに なります。",
      "通学の バスを 走らせて ほしいです。学校が 遠く なっても 通えます。",
      "空き家を 安く かして、若い 家族が 住める ように して ほしいです。",
      "まちの お祭りを 学校で ひらいて、人が あつまる 場所に して ほしいです。"],
    board: ["近くの 学校と オンラインで いっしょに 授業を したいです。いろいろな 考えの 友だちと 話せます。",
      "人数が へっても、大人数で やる 行事が できる ように、近くの 学校と いっしょに やる 工夫を 考えて ほしいです。",
      "少人数でも クラスがえが できる ように、近くの 学校と 交流する 日を 作って ほしいです。"],
    principal: ["空いた 教室を 図書室や 自習室に して ほしいです。",
      "近くの 学校と 運動会を いっしょに やりたいです。",
      "空いた 教室で、地域の 人に 昔の 遊びを 教えて もらいたいです。"],
    town: ["まちの よい ところを 調べて、みんなに 発信したいです。手つだって ください。",
      "地域の 人と いっしょに、校庭で 朝市を ひらきたいです。"],
    family: ["家族で まちの みらいに ついて 話し合いたいです。",
      "休みの 日に 家族で 学校の 畑の 手入れを したいです。"]
  };

  var SAMPLE_OWN = ["校庭で 月に 1回、朝市を ひらく", "学校の 畑で 地域の 人と 野菜を 作る", "空き家を 子どもの 遊び場に する"];
  // カードごとの 感じ方の かたより（いいね, しんぱい, どちらとも）
  var SAMPLE_SORT_W = { c1: [6, 1, 2], c2: [1, 6, 2], c3: [6, 1, 2], c4: [1, 5, 3], c5: [5, 2, 2], c6: [1, 5, 3], c7: [2, 4, 3], c8: [1, 6, 2] };
  var SAMPLE_TO_W = [["mayor", 7], ["board", 4], ["principal", 4], ["town", 3], ["family", 2]];
  function pickW(rnd, pairs) {
    var sum = 0, i;
    for (i = 0; i < pairs.length; i++) sum += pairs[i][1];
    var r = rnd() * sum;
    for (i = 0; i < pairs.length; i++) { r -= pairs[i][1]; if (r < 0) return pairs[i][0]; }
    return pairs[pairs.length - 1][0];
  }
  // 見本の「もっと 知りたい データ」（架空）。候補の 選ばれやすさと、自由な 文
  var SAMPLE_WISH_W = [["akiya", 6], ["move", 5], ["baby", 4], ["past", 3], ["room", 3], ["play", 2]];
  var SAMPLE_OWN_WISH = ["通学路の 歩道の 広さ", "まちの 公園の 数"];
  /** 見本の もっと 知りたい データ。7割が 1〜2個 えらび、12% が 自由な 文を 書く */
  function sampleWishes(rnd) {
    var wishes = [];
    if (rnd() < 0.7) {
      var k = rnd() < 0.5 ? 1 : 2;
      for (var t = 0; t < 20 && wishes.length < k; t++) {
        var id = pickW(rnd, SAMPLE_WISH_W);
        if (wishes.indexOf(id) < 0) wishes.push(id);
      }
    }
    var own = rnd() < 0.12 ? SAMPLE_OWN_WISH[Math.floor(rnd() * SAMPLE_OWN_WISH.length)] : "";
    return { wishes: wishes, ownWish: own };
  }
  /** 見本の 提案（架空）。ideaIds：えらべる アイデアの id */
  function sampleProp(rnd, ideaIds) {
    var sort = {};
    SORT_IDS.forEach(function (id) {
      if (rnd() < 0.12) return; // えらばない カードも ある
      var w = SAMPLE_SORT_W[id];
      sort[id] = pickW(rnd, [["good", w[0]], ["bad", w[1]], ["mid", w[2]]]);
    });
    var ideas = [], k = 1 + Math.floor(rnd() * 3);
    // 前の ほうの アイデアが えらばれやすい（順位に ちがいが 出るように）
    for (var t = 0; t < 20 && ideas.length < k && ideaIds.length; t++) {
      var id = ideaIds[Math.min(ideaIds.length - 1, Math.floor(Math.pow(rnd(), 1.6) * ideaIds.length))];
      if (ideas.indexOf(id) < 0) ideas.push(id);
    }
    var to = pickW(rnd, SAMPLE_TO_W);
    var list = SAMPLE_PROPOSALS[to];
    return { sort: sort, ideas: ideas, to: to,
      ownIdea: rnd() < 0.25 ? SAMPLE_OWN[Math.floor(rnd() * SAMPLE_OWN.length)] : "",
      proposal: rnd() < 0.9 ? list[Math.floor(rnd() * list.length)] : "" };
  }

  /**
   * 見本のクラス（架空の n人分のコード）。練習用のまち（架空の学校）だけに使う。毎回同じ値になるように seed で決める。
   * now: いまの人数、est50: データの 2050年の推計（あれば「へる」の子の 2050年を そのまわりに広げ、データより少ない子も出す）。
   * 子どもごとに ちがう 端末の印を付ける。ideaIds を渡すと、多くの子に 架空の 提案（ステップ5）を 付ける。
   */
  function sampleClass(pref, school, now, est50, n, seed, ideaIds) {
    var rnd = seeded(seed == null ? 2050 : seed), out = [];
    // 提案は べつの 乱数で 作る（よそうの 値は 第1段階と 同じ まま）。4人に1人ほどは ステップ2の コードだけ
    var rp = seeded((seed == null ? 2050 : seed) + 101);
    // もっと 知りたい データも べつの 乱数（よそうと 提案の 値は 変えない）
    var rw = seeded((seed == null ? 2050 : seed) + 202);
    for (var i = 0; i < (n || 30); i++) {
      var r = rnd();
      var guess = r < 0.5 ? "down" : r < 0.75 ? "same" : "up";
      var k;
      if (guess === "down") {
        k = est50 > 0 ? Math.min(0.92, (est50 * (0.55 + rnd() * 0.8)) / now) : 0.3 + rnd() * 0.6;
      } else {
        k = guess === "same" ? 0.92 + rnd() * 0.16 : 1.1 + rnd() * 0.45;
      }
      var draw = {};
      DRAW_YEARS.forEach(function (y, j) {
        var t = (j + 1) / DRAW_YEARS.length;
        var wob = 1 + (rnd() - 0.5) * 0.08 * (j < DRAW_YEARS.length - 1 ? 1 : 0);
        draw[y] = Math.max(0, now * (1 + (k - 1) * t) * wob);
      });
      var g = { pref: pref, school: school, guess: guess, draw: draw, mark: makeMark(rnd), seq: 1,
        reason: SAMPLE_REASONS[guess][Math.floor(rnd() * SAMPLE_REASONS[guess].length)] };
      if (ideaIds && rp() < 0.8) {
        g.prop = sampleProp(rp, ideaIds); g.seq = 2;
        var w = sampleWishes(rw);
        g.prop.wishes = w.wishes; g.prop.ownWish = w.ownWish;
      }
      out.push(encodeGuess(g));
    }
    return out;
  }

  return {
    EST_YEARS: EST_YEARS, BASE_YEAR: BASE_YEAR, TARGET_YEAR: TARGET_YEAR, DRAW_YEARS: DRAW_YEARS,
    CLASS_MAX: CLASS_MAX, MULTI_MAX: MULTI_MAX, MULTI_MAX_WITH_G1: MULTI_MAX_WITH_G1,
    clamp: clamp, interp: interp, estPoints: estPoints, calibFactor: calibFactor, histPoints: histPoints,
    pctChange: pctChange, splitGrades: splitGrades, splitClass: splitClass, classPlan: classPlan,
    simValue: simValue, simPoints: simPoints, agesFor: agesFor, ageStep: ageStep,
    elementaryAfter: elementaryAfter, cohortInts: cohortInts, shownPct: shownPct, niceMax: niceMax, niceTicks: niceTicks, ageIn: ageIn, judgeGuess: judgeGuess,
    schoolQuery: schoolQuery, matchSchool: matchSchool, foldText: foldText, isKanaQuery: isKanaQuery,
    CODE_HEAD: CODE_HEAD, encodeGuess: encodeGuess, decodeGuess: decodeGuess, extractGuesses: extractGuesses,
    makeMark: makeMark, commonCalib: commonCalib, SORT_IDS: SORT_IDS, mayorBase: mayorBase, mayorLabel: mayorLabel,
    sortTally: sortTally, ideaTally: ideaTally, ownIdeas: ownIdeas, wishTally: wishTally, ownWishes: ownWishes,
    proposalsByTo: proposalsByTo,
    groupGuesses: groupGuesses, summarizeGuesses: summarizeGuesses, sampleClass: sampleClass
  };
});
