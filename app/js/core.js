/*
 * わたしの学校2050 — 共通部品（データ登録・状態・ふりがな・保存）
 * ビルド不要。index.html を直接開いても（file://）動くよう、モジュールではなく
 * window.UG に集約している。データも fetch ではなく <script> で読み込む（JSONP方式）。
 */
(function () {
  "use strict";
  var UG = (window.UG = window.UG || {});

  /* ---------- 文字列 ---------- */
  UG.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  /** ふりがな処理をかけない文字列（学校名や子どもが入力した文など）。エスケープもする。 */
  UG.nr = function (s) {
    return "\u0001" + UG.esc(s) + "\u0002";
  };
  UG.num = function (v) {
    return Math.round(v).toLocaleString("ja-JP");
  };

  /* ---------- ふりがな ----------
   * 1) {漢字|よみ} と書いたところはそのままルビにする
   * 2) それ以外は ruby-dict.js の辞書で、長い語から順に自動でルビを付ける
   * 3) UG.nr() で包んだ部分とタグの中は触らない
   */
  var dictRe = null;
  function buildDictRe() {
    var keys = Object.keys(UG.RUBY || {}).sort(function (a, b) { return b.length - a.length; });
    dictRe = keys.length
      ? new RegExp(keys.map(function (k) { return k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("|"), "g")
      : null;
  }
  /** <ruby data-g="N">：N はその語の漢字のうち最も上の学年（kanji-grade.js。配当表に無い漢字は 7）。
   *  CSS が body[data-grade] と比べて、習った学年の漢字のふりがなを消す。 */
  function rubyTag(base, reading) {
    var g = UG.kanjiGrade ? UG.kanjiGrade.gradeOf(base) : 7;
    return '<ruby data-g="' + g + '">' + base + "<rt>" + reading + "</rt></ruby>";
  }
  function explicit(s) {
    return s.replace(/\{([^|{}]+)\|([^|{}]+)\}/g, function (_, base, reading) { return rubyTag(base, reading); });
  }
  /* ことばの途中で改行しないように、ルビを含む語を <span class="w">（CSS で white-space: nowrap）で包む。
   * 語＝空白・「・」「〜」で区切った1かたまり。前の開きかっこと、後ろの句読点・閉じかっこも語に含める。
   * 閉じかっこの後に続く文字（「力」を」の「を」）も同じ語。句読点（。、！？：）の後と開きかっこの前は <wbr> で改行してよい。
   * Chromium は word-break: keep-all でも <ruby> の前後で改行し（「計算|を」「合|わせる」）、WebKit は <ruby> と閉じかっこの間で
   * 改行する（「力|」」）ため。 */
  var OPEN = "「『（(", CLOSE_BR = "」』）)", PUNCT = "。、．，！？!?：:…", CLOSE = CLOSE_BR + PUNCT;
  var SEP = "\\s\u3000・〜";
  var CORE = "(?:[^" + SEP + OPEN + CLOSE + "\u0003\u0004]|\u0003r\\d+\u0004)+";
  var WORD_RE = new RegExp("[" + OPEN + "]*" + CORE + "(?:[" + CLOSE_BR + "]+" + CORE + ")*[" + CLOSE + "]*", "g");
  /* 句点・読点の後は、空白が無くても改行してよい。読点（、）も入れるのは、WebKit で「同じ まちでも、場所に」の「、」の後で
   * 折れず、前の行に大きな空きが残ったため（Chromium はもともと「、」の後で折る。入れると両方の折れ方がそろう）。 */
  var BREAK_AFTER_RE = new RegExp("[。．！？!?、，](?=[^" + SEP + CLOSE + "])", "g");
  var LONE_RUBY =/^<ruby[^>]*>[^<]*<rt>[^<]*<\/rt><\/ruby>$/;
  UG.ruby = function (html) {
    if (dictRe === null) buildDictRe();
    var keep = [];
    function stash(s, isRuby) { keep.push(s); return "\u0003" + (isRuby ? "r" : "") + (keep.length - 1) + "\u0004"; }
    // 先にタグ（属性の値ごと）と <textarea> の中身をよける。入力欄の文（value・<textarea> の中）に
    // ふりがなや <wbr> が入ると、子どもの文そのものが書きかわる（ステップ5の提案の箱にタグが出ていた）
    var s = String(html)
      .replace(/<textarea\b[^>]*>[\s\S]*?<\/textarea>/gi, function (t) { return stash(t); })
      .replace(/<[^>]+>/g, function (t) { return stash(t); })
      .replace(/\u0001([\s\S]*?)\u0002/g, function (_, t) { return stash("<span data-nr>" + t + "</span>"); })
      .replace(/\{([^|{}]+)\|([^|{}]+)\}/g, function (m) { return stash(explicit(m), true); });
    if (dictRe) {
      s = s.replace(dictRe, function (w) {
        var r = UG.RUBY[w];
        // 「 人」のように前に空白のある見出し語は、空白を語の外に出す（空白は改行してよい位置）
        var lead = /^\s*/.exec(w)[0];
        var html = r.indexOf("{") >= 0 ? explicit(r) : rubyTag(w.slice(lead.length), r);
        return lead + stash(html.replace(/^\s+/, ""), true);
      });
    }
    // 句読点の後に、空白が無くても改行してよい所（<wbr>）を置く。ふりがなの無い文にも効かせる。
    // WebKit は word-break: keep-all のとき「なるだろう。つまみを」の「。」の後で改行しないため。
    // 後ろが空白・閉じかっこ・句読点・文の終わりのときは置かない（「なぜ？」を の「を」の前では折らない）
    s = s.replace(BREAK_AFTER_RE, function (c) { return c + stash("<wbr>"); });
    // ルビを含み、ほかの文字かルビとつながっている語だけを包む（ルビ1つだけなら改行は起きない）。長すぎる語は包まない
    s = s.replace(WORD_RE, function (w) {
      if (w.indexOf("\u0003r") < 0) return w;
      var one = /^\u0003r(\d+)\u0004$/.exec(w);
      if (one && LONE_RUBY.test(keep[+one[1]])) return w; // ルビ1つだけの語は、途中で改行しようがない
      var len = w.replace(/\u0003r\d+\u0004/g, "xx").length;
      if (len > 16) return w;
      // 開きかっこの前と、句読点・閉じかっこの後は、空白が無くても改行してよい（<wbr>）
      return (OPEN.indexOf(w.charAt(0)) >= 0 ? "<wbr>" : "") + '<span class="w">' + w + "</span>" +
        (PUNCT.indexOf(w.charAt(w.length - 1)) >= 0 ? "<wbr>" : "");
    });
    return s.replace(/\u0003r?(\d+)\u0004/g, function (_, i) { return keep[+i]; }).replace(/(?:<wbr>)+/g, "<wbr>");
  };
  /** ルビなしのプレーンテキスト（カード画像・コピー用） */
  UG.plain = function (html) {
    return String(html)
      .replace(/\u0001|\u0002/g, "")
      .replace(/\{([^|{}]+)\|([^|{}]+)\}/g, "$1")
      .replace(/<rt>.*?<\/rt>/g, "")
      .replace(/<[^>]+>/g, "");
  };

  /* ---------- データ登録 ---------- */
  UG.prefs = {};
  UG.index = []; // 実データの都道府県一覧（data/index.js が登録）
  UG.registerPref = function (pref) {
    pref.cities.forEach(function (c) {
      c.schools.forEach(function (s) { s.city = c; s.pref = pref; });
      c.pref = pref;
    });
    UG.prefs[pref.code] = pref;
  };
  UG.registerIndex = function (list) {
    UG.index = list || [];
  };
  var loading = {};
  /** 都道府県データを読み込む（script 注入。file:// でも動く） */
  UG.loadPref = function (code) {
    if (UG.prefs[code]) return Promise.resolve(UG.prefs[code]);
    if (loading[code]) return loading[code];
    loading[code] = new Promise(function (resolve, reject) {
      var el = document.createElement("script");
      el.src = "data/pref_" + code + ".js";
      el.onload = function () {
        UG.prefs[code] ? resolve(UG.prefs[code]) : reject(new Error("データの形式が正しくありません"));
      };
      el.onerror = function () {
        delete loading[code];
        reject(new Error("データを読み込めませんでした"));
      };
      document.head.appendChild(el);
    });
    return loading[code];
  };
  UG.findSchool = function (prefCode, cityCode, schoolId) {
    var p = UG.prefs[prefCode];
    if (!p) return null;
    for (var i = 0; i < p.cities.length; i++) {
      var c = p.cities[i];
      if (cityCode && c.code !== cityCode) continue;
      for (var j = 0; j < c.schools.length; j++) if (c.schools[j].id === schoolId) return c.schools[j];
    }
    return null;
  };

  /* ---------- 状態（この端末の中だけに保存。どこにも送信しない） ---------- */
  var KEY = "ug2050:v1";
  UG.defaults = function () {
    return {
      prefCode: "00", cityCode: "00000", schoolId: null,
      grade: null, guess: null, reason: "", calib: null,
      draw: {}, revealed: false, extraHist: [],
      viewYear: 2050, ageStep: 0, sim: { move: 0, birth: 0 },
      quiz: {}, sort: {}, ideas: [], ownIdea: "", proposal: "", to: "mayor", nick: "",
      furigana: true, step: "home", maxStep: 0,
      // クラスモード：この端末の でたらめな 印（初めて コードを 作るときに 作る）と、作った 順の 番号。
      // 同じ 子が 2回 送ったら、先生の 画面で 新しい ほうだけ 数える。「さいしょから やりなおす」で 消える
      classMark: "", classSeq: 0
    };
  };
  UG.state = UG.defaults();
  /** 子どもが書いた文から、まちがって入りこんだタグとよけ印を取りのぞく。
   *  以前の UG.ruby は <textarea> の中身にもふりがなを付けていた。そのまま箱の文を消したり直したりすると、
   *  タグごと保存された（<span class="w"><ruby …>教室<rt>きょうしつ</rt></ruby>を</span>）。
   *  入力欄の value には {漢字|よみ} がよけ印（\u0003r1\u0004）になって入っていた。読みこむときにもとの文にもどす。 */
  UG.cleanText = function (s) {
    if (typeof s !== "string") return s;
    return s
      .replace(/<rt\b[^>]*>[^<]*(<\/[^>]*>)?/gi, "")   // ふりがな（よみ）は文ではない。とじタグがこわれていても消す
      .replace(/<\/?[a-z][^<>]*>/gi, "")                // <span …> <ruby …> <wbr> とそのとじタグ（こわれたものも）
      .replace(/[\u0001-\u0004]r?\d*[\u0004]?/g, "");    // ふりがな処理のよけ印
  };
  var FREE_TEXT = ["reason", "ownIdea", "proposal", "nick"];
  UG.loadState = function (seed) {
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { saved = null; }
    var src = seed && Object.keys(seed).length ? seed : saved;
    if (src && typeof src === "object") {
      var d = UG.defaults();
      Object.keys(d).forEach(function (k) { if (src[k] !== undefined) d[k] = src[k]; });
      FREE_TEXT.forEach(function (k) { d[k] = UG.cleanText(d[k]); });
      UG.state = d;
    }
  };
  UG.save = function () {
    try { localStorage.setItem(KEY, JSON.stringify(UG.state)); } catch (e) { /* 保存できなくても動く */ }
  };
  UG.resetState = function () {
    var keep = { furigana: UG.state.furigana };
    UG.state = UG.defaults();
    UG.state.furigana = keep.furigana;
    UG.save();
  };

  /* ---------- 保存・コピー ---------- */
  /** Claude の画面内で開かれているか（印刷と通常のダウンロードが使えない） */
  UG.inViewer = function () { return !!window.claude; };

  /** ファイルを保存する。成功: true / キャンセル: false / 失敗: 例外 */
  UG.saveFile = function (filename, blob) {
    if (window.claude && typeof window.claude.use === "function") {
      return window.claude.use("downloads").then(function (d) {
        if (!d) throw new Error("この画面では保存できません");
        return d.save({ filename: filename, data: blob }).then(
          function () { return true; },
          function (err) { if (err && err.code === "declined") return false; throw err; }
        );
      });
    }
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      resolve(true);
    });
  };
  UG.copyText = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    return Promise.resolve(false);
  };

  /** でたらめな数（0以上1未満）。使えれば crypto を使う。端末や 名前の 情報は 使わない */
  UG.random = function () {
    try {
      var a = new Uint32Array(1);
      window.crypto.getRandomValues(a);
      return a[0] / 4294967296;
    } catch (e) {
      return Math.random();
    }
  };

  /* ---------- 小さな DOM ヘルパー ---------- */
  UG.$ = function (sel, root) { return (root || document).querySelector(sel); };
  UG.$$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  UG.on = function (root, type, sel, fn) {
    root.addEventListener(type, function (ev) {
      var t = ev.target.closest ? ev.target.closest(sel) : null;
      if (t && root.contains(t)) fn(ev, t);
    });
  };
  UG.toast = function (msg) {
    var el = UG.$("#toast");
    if (!el) return;
    el.innerHTML = UG.ruby(msg);
    el.classList.add("show");
    clearTimeout(UG._toastT);
    UG._toastT = setTimeout(function () { el.classList.remove("show"); }, 2600);
  };
})();
