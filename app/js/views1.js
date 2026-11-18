/*
 * わたしの学校2050 — 画面（ホーム／1 ぎもん／2 よそう／3 しらべる）
 * 文章は子ども向け。漢字のふりがなは UG.ruby() が辞書（ruby-dict.js）で自動的に付ける。
 */
(function () {
  "use strict";
  var UG = window.UG, M = UG.model, esc = UG.esc, nr = UG.nr, num = UG.num;
  var V = (UG.views = {});
  // 学区データの利用条件が「条件公開」か特記条件つきの市区町村（pref_XX.js の city.note）
  UG.PROCESSOR = "わたしの学校2050（h-kazuki-pixel）"; // 出典の「加工：」に出す名前（pipeline の export.PROCESSOR と同じ）
  UG.TERMS_NOTE = "この まちの 学区は めやすです。くわしくは 教育委員会に たしかめてね。";
  // 国の 推計が いくつかの まちを まとめて 計算されている まち（pref_XX.js の city.combined。福島県の 浜通り）
  UG.COMBINED_NOTE = "この ちいきの 推計は、まわりの まちと まとめて 計算されて います。数字は めやすです。";
  UG.APPROX_NOTE = "この まちは 学区の 地図データが ないため、学校から いちばん 近い 場所で 分けた「おおよその 区域」で 計算しています。本当の 学区とは ちがう ところが あります。人数が かなり ちがう ことも あります。";
  // 学区データのある まちで、学区データに 入って いない 学校（学校だけが approx）
  UG.APPROX_SCHOOL_NOTE = "この 学校は 学区の 地図データに 入って いません。まわりの 学区に 入らなかった 場所から「おおよその 区域」を 作って 計算しています。本当の 学区とは ちがう ところが あります。人数が かなり ちがう ことも あります。";
  // ステップ1の 実際の 人数を 入れる 欄の 文。おおよその 区域の 学校では、しらべて 入れる ことを すすめる
  UG.CALIB_DISTRICT = "学校の 本当の 人数（全校の 児童数）を 知っていたら 入れてね。計算を それに 合わせるよ。";
  UG.CALIB_APPROX = "学校の 本当の 人数（全校の 児童数）を 先生に 聞いたり しらべたり して、入れて みよう。計算を それに 合わせるよ。";
  /** 「おおよその 区域」の 注意（まち全体か、学校だけか）。どちらでもなければ "" */
  UG.approxNote = function (city, school) {
    if (city && city.approx) return UG.APPROX_NOTE;
    if (school && school.approx) return UG.APPROX_SCHOOL_NOTE;
    return "";
  };

  UG.STEPS = [
    { id: "step1", no: 1, name: "ぎもん", desc: "「何人に なる？」と 問いを 立てる" },
    { id: "step2", no: 2, name: "よそう", desc: "じぶんの よそうを 線で かく" },
    { id: "step3", no: 3, name: "しらべる", desc: "国の データで たしかめる" },
    { id: "step4", no: 4, name: "なぜ？", desc: "しくみと ちがいを さぐる" },
    { id: "step5", no: 5, name: "ていあん", desc: "まちへの カードを 作る" }
  ];
  UG.GRADES = [
    { id: "e4", label: "小4" }, { id: "e5", label: "小5" }, { id: "e6", label: "小6" },
    { id: "j1", label: "中1" }, { id: "j2", label: "中2" }, { id: "j3", label: "中3" },
    { id: "adult", label: "おとな" }
  ];

  /** いま選ばれている学校と、そこから計算した値 */
  UG.ctx = function () {
    var st = UG.state;
    var school = UG.findSchool(st.prefCode, st.cityCode, st.schoolId);
    if (!school) return null;
    var est = M.estPoints(school, st.calib);
    var hist = M.histPoints(school, st.extraHist);
    var now = est[0].v, v50 = M.interp(est, M.TARGET_YEAR);
    var top = now;
    hist.forEach(function (p) { top = Math.max(top, p.v); });
    return {
      school: school, city: school.city, pref: school.pref, sample: !!school.pref.sample,
      est: est, hist: hist, now: now, v50: v50, pct: M.shownPct(now, v50),
      yMax: Math.max(20, M.niceMax(top * 1.35)),
      xMin: hist.length ? Math.min(hist[0].y, 2015) : 2020,
      age: M.ageIn(st.grade, M.TARGET_YEAR)
    };
  };

  UG.pctText = function (pct) {
    if (pct == null) return "";
    var a = Math.abs(Math.round(pct));
    if (a === 0) return "ほぼ 同じ";
    return a + "% " + (pct < 0 ? "へる" : "ふえる");
  };

  function head(no, title, lead) {
    return '<header class="page-head"><span class="step-no" aria-hidden="true">' + no + "</span><div><h1>" + title + "</h1>" +
      (lead ? '<p class="lead">' + lead + "</p>" : "") + "</div></header>";
  }
  UG.pageHead = head;

  function nav(back, backLabel, next, nextLabel, nextDisabled) {
    return '<nav class="step-nav" aria-label="ページ移動">' +
      '<button type="button" class="btn ghost" data-go="' + back + '">← ' + backLabel + "</button>" +
      (next ? '<button type="button" class="btn primary" id="next-btn" data-go="' + next + '"' + (nextDisabled ? " disabled" : "") + ">" + nextLabel + " →</button>" : "") +
      "</nav>";
  }
  UG.stepNav = nav;

  /* ====================== ホーム ====================== */
  V.home = function (root) {
    var st = UG.state;
    var pref = UG.prefs[st.prefCode] || UG.prefs["00"];
    var city = null;
    pref.cities.forEach(function (c) { if (c.code === st.cityCode) city = c; });
    if (!city) { city = pref.cities[0]; st.cityCode = city.code; }
    var filter = "";

    function pickerHtml() {
      if (!UG.index.length) return "";
      // <option> の中にはルビを入れられないので、文字はすべてふりがな処理から外す（UG.nr）
      var opts = '<option value="00"' + (st.prefCode === "00" ? " selected" : "") + ">" + nr("れんしゅう用（みらい市）") + "</option>" +
        UG.index.map(function (p) {
          return '<option value="' + esc(p.code) + '"' + (st.prefCode === p.code ? " selected" : "") + ">" + nr(p.name) + "</option>";
        }).join("");
      var cities = pref.cities.map(function (c) {
        return '<option value="' + esc(c.code) + '"' + (c.code === city.code ? " selected" : "") + ">" + nr(c.name) + "</option>";
      }).join("") + (pref.missing || []).map(function (m) {
        // nothandled：このアプリでは 扱わない まち（福島県 浜通りの 7町村）。それ以外は 学区データも 学校の 位置も 無い まち
        return "<option disabled>" + nr((m.name || m.code) + (m.nothandled ? "（このアプリでは あつかって いません）" : "（学区データなし）")) + "</option>";
      }).join("");
      return '<div class="picker">' +
        '<label for="sel-pref">都道府県</label><select id="sel-pref">' + opts + "</select>" +
        '<label for="sel-city">市区町村</label><select id="sel-city">' + cities + "</select>" +
        '<label for="q-school">学校の 名前で さがす</label><input id="q-school" type="search" autocomplete="off" placeholder="ひらがなでも いいよ">' +
        "</div>";
    }
    function listHtml() {
      var items = city.schools.filter(function (s) { return M.matchSchool(s, filter); }); // ひらがなは 読み（kana）でも さがす。読みは 画面に 出さない
      if (!items.length) return '<p class="empty">見つからなかったよ。もう 少し みじかく 入れるか、けして 一覧から えらんでね。</p>';
      return items.map(function (s) {
        return '<button type="button" class="school-btn' + (s.id === st.schoolId ? " on" : "") + '" data-school="' + esc(s.id) + '" aria-pressed="' + (s.id === st.schoolId) + '">' +
          '<span class="nm">' + nr(s.name) + "</span>" +
          (s.tag ? '<span class="tg">' + s.tag + "</span>" : "") +
          '<span class="ct">' + num(s.est[0]) + "人</span></button>";
      }).join("");
    }
    function ageHtml() {
      if (!st.grade) return "学年を えらぶと、2050年の きみの 年れいが わかるよ。";
      if (st.grade === "adult") return "2050年は、いまから 24年後。いまの 小学生が 親の 世代に なる ころです。";
      return "2050年、きみは <b>" + M.ageIn(st.grade, 2050) + "さい</b>くらい。その とき、学校は どう なっているだろう？";
    }

    root.innerHTML = UG.ruby(
      '<section class="hero">' +
        '<p class="eyebrow">データで 調べる 自由研究｜小学4年生から</p>' +
        '<h1 class="title">2050年、<br>わたしの 学校は <em>何人？</em></h1>' +
        '<p class="lead">きみが おとなに なる ころ、学校は どう なっているだろう。<br>よそうして、国の データで たしかめて、まちに ていあん しよう。</p>' +
      "</section>" +
      '<section class="setup" aria-label="はじめる 前に">' +
        '<div class="card pick">' +
          '<h2><span class="no">1</span>学校を えらぶ</h2>' +
          pickerHtml() +
          (pref.sample ? '<p class="note">れんしゅう用の「みらい市」です。本当には ない まちで、数字は つくりものです。</p>' : "") +
          (city.approx ? '<p class="note">' + UG.APPROX_NOTE + "</p>" : "") +
          '<div id="school-note">' + schoolNoteHtml() + "</div>" +
          (city.combined ? '<p class="note">' + UG.COMBINED_NOTE + "</p>" : "") +
          (city.note ? '<p class="note">' + UG.TERMS_NOTE + "</p>" : "") +
          '<div class="pick-body"><div class="school-list" id="school-list">' + listHtml() + '</div><div class="mapbox" id="home-map"></div></div>' +
        "</div>" +
        '<div class="card grade">' +
          '<h2><span class="no">2</span>きみは いま 何年生？</h2>' +
          '<div class="chips" role="group" aria-label="学年">' +
            UG.GRADES.map(function (g) {
              return '<button type="button" class="chip' + (st.grade === g.id ? " on" : "") + '" data-grade="' + g.id + '" aria-pressed="' + (st.grade === g.id) + '">' + g.label + "</button>";
            }).join("") +
          "</div>" +
          '<p class="age-out" id="age-out">' + ageHtml() + "</p>" +
          '<button type="button" class="btn primary big" id="start"' + (st.schoolId ? "" : " disabled") + ">たんけんを はじめる →</button>" +
          '<p class="fine">名前は 聞きません。入力した ことは この タブレットや パソコンの 中だけに のこります。</p>' +
        "</div>" +
      "</section>" +
      '<section class="flow" aria-label="たんけんの 進め方">' +
        "<h2>5つの ステップで 進むよ</h2><ol>" +
        UG.STEPS.map(function (s) {
          return '<li><span class="no">' + s.no + "</span><b>" + s.name + "</b><span>" + s.desc + "</span></li>";
        }).join("") +
        "</ol></section>" +
      // 出典と、先生向けページへの入口
      '<p class="credit fine">出典：国土数値情報（国土交通省）を加工して作成。加工：' + esc(UG.PROCESSOR) + "　" +
        '<button type="button" class="link" data-go="teachers">先生・大人の方へ →</button></p>'
    );

    function drawMap() {
      UG.townMap(UG.$("#home-map", root), city, {
        selected: st.schoolId, showNames: true,
        onSelect: function (id) { select(id); }
      });
    }
    /** 学区データのある まちで、えらんだ 学校が「おおよその 区域」の とき だけ 出す */
    function schoolNoteHtml() {
      if (city.approx) return "";
      var sc = null;
      city.schools.forEach(function (s) { if (s.id === st.schoolId) sc = s; });
      var t = UG.approxNote(city, sc);
      return t ? '<p class="note">' + t + "</p>" : "";
    }
    function select(id) {
      if (st.schoolId !== id) {
        // 学校を変えたら、その学校についての作業はやり直し
        var keep = { grade: st.grade, furigana: st.furigana, prefCode: st.prefCode, cityCode: st.cityCode };
        UG.state = UG.defaults();
        Object.keys(keep).forEach(function (k) { UG.state[k] = keep[k]; });
        st = UG.state;
        st.schoolId = id;
      }
      UG.save();
      UG.$("#school-list", root).innerHTML = UG.ruby(listHtml());
      UG.$("#school-note", root).innerHTML = UG.ruby(schoolNoteHtml());
      UG.$("#start", root).disabled = false;
      drawMap();
      UG.renderChrome();
    }
    drawMap();

    UG.on(root, "click", "[data-school]", function (ev, el) { select(el.getAttribute("data-school")); });
    UG.on(root, "click", "[data-grade]", function (ev, el) {
      st.grade = el.getAttribute("data-grade"); UG.save();
      UG.$$("[data-grade]", root).forEach(function (b) {
        var on = b === el; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
      });
      UG.$("#age-out", root).innerHTML = UG.ruby(ageHtml());
      UG.renderChrome(); // body の data-grade（ふりがなの量）を変える
    });
    UG.$("#start", root).addEventListener("click", function () { UG.go("step1"); });

    var selPref = UG.$("#sel-pref", root);
    if (selPref) {
      selPref.addEventListener("change", function () {
        var code = selPref.value;
        UG.loadPref(code).then(function (p) {
          st.prefCode = code; st.cityCode = p.cities[0].code; st.schoolId = null; UG.save(); UG.render();
        }, function (err) { UG.toast(err.message); selPref.value = st.prefCode; });
      });
      UG.$("#sel-city", root).addEventListener("change", function (ev) {
        st.cityCode = ev.target.value; st.schoolId = null; UG.save(); UG.render();
      });
      UG.$("#q-school", root).addEventListener("input", function (ev) {
        filter = ev.target.value.trim();
        UG.$("#school-list", root).innerHTML = UG.ruby(listHtml());
      });
    }
  };

  /* ====================== 1 ぎもん ====================== */
  V.step1 = function (root) {
    var st = UG.state, c = UG.ctx();
    var unit = c.now <= 120 ? 1 : c.now <= 600 ? 5 : 10;
    function dots(n) {
      var k = Math.round(n / unit), out = "";
      for (var i = 0; i < k; i++) out += "<i></i>";
      return out;
    }
    var nowLine = c.sample || st.calib
      ? "いま、子どもは <span class=\"nw\"><b class=\"n\">" + num(c.now) + "</b>人。</span>"
      : "いま、この 学区に 住む 小学生は <span class=\"nw\">やく <b class=\"n\">" + num(c.now) + "</b>人。</span>";
    var ageLine = c.age ? "きみが " + c.age + "さいに なる ころ" : "いまから 24年後";

    root.innerHTML = UG.ruby(
      head(1, "ぎもんを もとう", "たんけんは「ほんとうかな？」「どう なるのかな？」から はじまる。") +
      '<section class="card now-card">' +
        '<p class="school-name">' + nr(c.school.name) + '<span class="city">' + nr(c.city.name) + "</span></p>" +
        '<p class="big">' + nowLine + "</p>" +
        '<div class="dots" aria-hidden="true">' + dots(c.now) + "</div>" +
        '<p class="fine">● 1つ ＝ ' + unit + "人" + (c.sample ? "" : "（国の 2025年の 推計から 計算）") + "</p>" +
        (UG.approxNote(c.city, c.school) ? '<p class="note">' + UG.approxNote(c.city, c.school) + "</p>" : "") +
        (c.city.note ? '<p class="note">' + UG.TERMS_NOTE + "</p>" : "") +
        (c.city.combined ? '<p class="note">' + UG.COMBINED_NOTE + "</p>" : "") +
        (c.sample ? "" :
          '<div class="calib"><label for="calib">' + (UG.approxNote(c.city, c.school) ? UG.CALIB_APPROX : UG.CALIB_DISTRICT) + "</label>" +
          '<div class="row"><input id="calib" type="number" inputmode="numeric" min="1" max="3000" value="' + (st.calib || "") + '"><span>人</span>' +
          '<button type="button" class="btn small" id="calib-btn">合わせる</button></div></div>') +
      "</section>" +
      '<section class="card question">' +
        "<h2>2050年、" + ageLine + "、<br>子どもは 何人に なっていると 思う？</h2>" +
        '<div class="choices" role="group" aria-label="よそう">' +
          [["up", "いまより ふえる"], ["same", "同じくらい"], ["down", "いまより へる"]].map(function (o) {
            return '<button type="button" class="choice' + (st.guess === o[0] ? " on" : "") + '" data-guess="' + o[0] + '" aria-pressed="' + (st.guess === o[0]) + '">' + o[1] + "</button>";
          }).join("") +
        "</div>" +
        '<label class="reason" for="reason">どうして そう 思った？（書かなくても だいじょうぶ）</label>' +
        '<input id="reason" type="text" maxlength="60" value="' + esc(st.reason) + '" placeholder="れい：近くに 新しい 家が ふえているから">' +
      "</section>" +
      nav("home", "学校を えらびなおす", "step2", "線で よそうを かく", !st.guess)
    );

    UG.on(root, "click", "[data-guess]", function (ev, el) {
      st.guess = el.getAttribute("data-guess"); UG.save();
      UG.$$("[data-guess]", root).forEach(function (b) {
        var on = b === el; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
      });
      UG.$("#next-btn", root).disabled = false;
    });
    UG.$("#reason", root).addEventListener("input", function (ev) { st.reason = ev.target.value; UG.save(); });
    var cb = UG.$("#calib-btn", root);
    if (cb) cb.addEventListener("click", function () {
      var v = parseInt(UG.$("#calib", root).value, 10);
      st.calib = v > 0 ? v : null; st.draw = {}; st.revealed = false; UG.save(); UG.render();
      UG.toast(st.calib ? "学校の 人数に 合わせました" : "データの よそうに もどしました");
    });
  };

  /* ====================== 2 よそう ====================== */
  V.step2 = function (root) {
    var st = UG.state, c = UG.ctx();
    var done = M.DRAW_YEARS.every(function (y) { return st.draw[y] != null; });
    root.innerHTML = UG.ruby(
      head(2, "よそうを 線で かこう",
        (c.hist.length ? "黒い 線は これまでの 人数。" : "黒い 点は いまの 人数。") + "2050年まで、つづきを かいてみよう。ゆびや マウスで 右へ なぞってね。") +
      '<section class="card chart-card">' +
        '<div class="legend"><span class="k hist">これまで</span><span class="k mine">きみの よそう</span></div>' +
        '<div id="chart"></div>' +
        // よそうの数字と「かきなおす」は同じ行。幅が足りないときだけ、ボタンが下の行（右寄せ）に回る
        '<div class="readout-row"><div class="readout" id="readout" aria-live="polite"></div>' +
          '<button type="button" class="btn sub" id="redo">かきなおす</button></div>' +
        // タッチの端末（pointer: coarse）では出さない。キーボードでの操作そのものは変えない
        '<p class="fine kbd-hint">キーボードの ときは、丸を えらんで ↑↓ で 動かせます。</p>' +
      "</section>" +
      '<aside class="tip"><b>ヒント</b>　まわりの ようすを 思い出そう。新しい 家は ふえている？ 赤ちゃんや 小さい 子を よく 見かける？ 空き家は ある？</aside>' +
      // クラスモード：線を かきおえたら、先生に よそうを わたす コードを 出せる（授業で 使わない 子には 小さく）
      '<div class="handoff" id="handoff"' + (done ? "" : " hidden") + '>' +
        '<button type="button" class="btn sub" id="handoff-btn" aria-expanded="false" aria-controls="handoff-box">先生に よそうを わたす</button>' +
        '<div class="handoff-box" id="handoff-box" hidden>' +
          '<p class="fine">この コードを コピーして、先生に 言われた ところに はりつけてね。名前は 入って いないよ。</p>' +
          '<div class="handoff-row"><textarea id="handoff-code" class="code" rows="2" readonly aria-label="よそうの コード" data-nr></textarea>' +
          '<button type="button" class="btn small" id="handoff-copy">コピー</button></div>' +
        "</div>" +
      "</div>" +
      nav("step1", "もどる", "step3", "データと くらべる", !done)
    );
    /** いまの よそうの コード（名前は 入れない）。中身が 変わったときだけ 番号を 1つ 進める（線を なぞる あいだに 何度も 進めない） */
    var lastCode = null, lastKey = null;
    function handoffCode() {
      var g = { pref: st.prefCode, school: st.schoolId, guess: st.guess, reason: st.reason, calib: st.calib, draw: {} };
      M.DRAW_YEARS.forEach(function (y) { g.draw[y] = st.draw[y] == null ? null : Math.round(st.draw[y]); });
      var key = JSON.stringify(g);
      if (key === lastKey && lastCode) return lastCode;
      if (!st.classMark) st.classMark = M.makeMark(UG.random);
      st.classSeq = (st.classSeq || 0) + 1;
      UG.save();
      g.mark = st.classMark; g.seq = st.classSeq;
      lastKey = key; lastCode = M.encodeGuess(g);
      return lastCode;
    }
    function handoffUpdate(ok) {
      UG.$("#handoff", root).hidden = !ok;
      var box = UG.$("#handoff-box", root);
      if (!ok) { box.hidden = true; UG.$("#handoff-btn", root).setAttribute("aria-expanded", "false"); }
      if (!box.hidden) UG.$("#handoff-code", root).value = handoffCode() || "";
    }
    function readout(vals, ok) {
      var el = UG.$("#readout", root);
      el.innerHTML = UG.ruby(ok
        ? "きみの よそう：<wbr>2050年に <span class=\"nw\"><b>" + num(vals[2050]) + "</b>人</span>"
        : "2050年まで 線を のばそう");
    }
    var chart = UG.lineChart(UG.$("#chart", root), {
      xMin: c.xMin, xMax: 2050, yMax: c.yMax, hist: c.hist, now: { y: 2025, v: c.now },
      mine: st.draw, drawYears: M.DRAW_YEARS, drawable: true, target: 2050,
      aria: "児童数の グラフ。2050年までの よそうを かく",
      onDraw: function (vals, ok) {
        st.draw = vals; st.revealed = false; UG.save();
        readout(vals, ok);
        UG.$("#next-btn", root).disabled = !ok;
        handoffUpdate(ok);
      }
    });
    readout(st.draw, done);
    UG.$("#handoff-btn", root).addEventListener("click", function (ev) {
      var box = UG.$("#handoff-box", root), open = box.hidden;
      box.hidden = !open;
      ev.currentTarget.setAttribute("aria-expanded", String(open));
      handoffUpdate(true);
    });
    UG.$("#handoff-copy", root).addEventListener("click", function () {
      var ta = UG.$("#handoff-code", root);
      UG.copyText(ta.value).then(function (ok) {
        if (!ok) { ta.focus(); ta.select(); }
        UG.toast(ok ? "コピーしました。先生に 言われた ところに はりつけてね" : "コピーできませんでした。えらんだ 文字を コピーしてね");
      });
    });
    UG.$("#redo", root).addEventListener("click", function () { chart.reset(); });
  };

  /* ====================== 3 しらべる ====================== */
  V.step3 = function (root) {
    var st = UG.state, c = UG.ctx();
    var mine50 = st.draw[2050];
    var j = M.judgeGuess(mine50, c.v50);
    var first = !st.revealed;
    var wide = false;
    var verdict = j.level === "close" ? ["ぴったり賞", "すごい！ ほぼ ぴったりの よそうだね。"]
      : j.level === "near" ? ["おしい賞", "おしい！ データに 近い よそうだったね。"]
      : ["はっけん賞", "データと 大きく ちがったね。「なぜ ちがったか」を 考える のが、たんけんの いちばん おもしろい ところだよ。"];
    var diff = Math.round(mine50) - Math.round(c.v50);

    root.innerHTML = UG.ruby(
      head(3, "データで たしかめよう", "赤い 線が、国の データから 計算した よそうだよ。") +
      '<section class="card chart-card">' +
        '<div class="legend"><span class="k hist">これまで</span><span class="k mine">きみの よそう</span><span class="k est">データの よそう</span></div>' +
        '<div id="chart"></div>' +
        '<div class="row end"><button type="button" class="btn small ghost" id="wide" aria-pressed="false">2070年まで 見る</button></div>' +
        '<div class="table-wrap" id="data-table"></div>' +
        '<div class="verdict' + (first ? " pop" : "") + '">' +
          '<span class="stamp" aria-hidden="true">' + verdict[0] + "</span>" +
          "<div><p><b>" + verdict[1] + "</b></p>" +
          "<p>データの よそうは <b class=\"est\">" + num(c.v50) + "人</b>、きみの よそうは <b class=\"mine\">" + num(mine50) + "人</b>。" +
          (diff === 0 ? "ぴったり 同じ！" : "差は " + num(Math.abs(diff)) + "人（きみの ほうが " + (diff > 0 ? "多い" : "少ない") + "）。") + "</p>" +
          "<p>2025年の " + num(c.now) + "人から、2050年には " + num(c.v50) + "人。<mark>" + UG.pctText(c.pct) + "</mark> 計算に なる。</p></div>" +
        "</div>" +
      "</section>" +

      '<section class="card room-card">' +
        "<h2>数字を 教室で 見てみよう</h2>" +
        '<p>人数が かわると、クラスは どう なるだろう。つまみを 動かして 年を かえてみよう。</p>' +
        '<div class="year-slider"><label for="year-range">見る 年</label>' +
          '<input id="year-range" type="range" min="0" max="9" step="1" value="' + Math.max(0, M.EST_YEARS.indexOf(st.viewYear)) + '">' +
          '<output id="year-out" for="year-range"></output></div>' +
        '<div class="tiles" id="tiles"></div>' +
        '<div class="rooms" id="rooms"></div>' +
        '<p class="fine">1クラスは 35人まで（国の きまり）。学年ごとの 人数は 全校の 人数を 6つに 分けた めやすです。</p>' +
      "</section>" +

      '<section class="card source-card">' +
        "<h2>この 数字は どこから 来たの？</h2>" +
        (c.sample ? '<p class="note">この まちは れんしゅう用で、数字は つくりものです。本物の データでは 下の 方法で 計算します。</p>' : "") +
        '<ol class="source-steps">' +
          "<li><b>数える</b><br>国が 5年に 1回、日本に 住む 人を みんな 数える（国勢調査）。</li>" +
          "<li><b>計算する</b><br>国が、500メートルの ますめ ごとに、これからの 人口を 計算する（将来推計人口）。</li>" +
          "<li><b>たし算する</b><br>この アプリが、学区の 中の ますめを たして、小学生の 年れい（6〜11さい）の 人数を 出す。" +
            (c.city.approx ? "この まちは 学区の 地図が ないので、学校から いちばん 近い ますめを たしている。" :
              c.school.approx ? "この 学校は 学区の 地図に 入って いないので、どの 学区にも 入らなかった ますめの うち、この 学校に 近い ますめを たしている。" : "") + "</li>" +
        "</ol>" +
        '<p class="caution"><b>だいじな こと</b>　これは「いまの ながれが つづいたら」の 計算。きまった みらい では ないよ。</p>' +
      "</section>" +

      '<section class="card hist-card">' +
        "<h2>むかしの 人数を しらべて、グラフに 足そう</h2>" +
        "<p>学校の きねん誌や 学校だより、校長先生、おうちの 人に 聞いてみよう。きみが 集めた データが グラフに のるよ。</p>" +
        '<form class="row" id="hist-form"><label for="hist-y">年</label><input id="hist-y" type="number" inputmode="numeric" min="1950" max="2024" placeholder="1990">' +
          '<label for="hist-v">人数</label><input id="hist-v" type="number" inputmode="numeric" min="0" max="5000" placeholder="600"><span>人</span>' +
          '<button type="submit" class="btn small">グラフに 足す</button></form>' +
        '<ul class="hist-list" id="hist-list"></ul>' +
      "</section>" +
      nav("step2", "よそうを かきなおす", "step4", "「なぜ？」を さぐる")
    );

    function drawChart(animate) {
      var cc = UG.ctx();
      UG.lineChart(UG.$("#chart", root), {
        xMin: cc.xMin, xMax: wide ? 2070 : 2050, yMax: cc.yMax, hist: cc.hist, now: { y: 2025, v: cc.now },
        est: cc.est, estAnimate: animate, mine: st.draw, drawYears: M.DRAW_YEARS, target: 2050,
        aria: "児童数の グラフ。きみの よそうと データの よそう"
      });
    }
    // グラフと同じ数字を表でも見せる（表とグラフを行き来して読む。グラフが見づらい子の助けにもなる）
    function drawTable() {
      var cc = UG.ctx(), years = M.EST_YEARS.filter(function (y) { return y <= (wide ? 2070 : 2050); });
      var cell = function (y, v) { return "<td" + (y === 2050 ? ' class="t50"' : "") + ">" + (v == null ? "—" : num(v)) + "</td>"; };
      UG.$("#data-table", root).innerHTML = UG.ruby(
        '<table class="data-table"><thead><tr><th scope="col">年</th>' +
        years.map(function (y) { return '<th scope="col"' + (y === 2050 ? ' class="t50"' : "") + ">" + y + "</th>"; }).join("") + "</tr></thead><tbody>" +
        '<tr><th scope="row">データの よそう（人）</th>' + years.map(function (y) { return cell(y, M.interp(cc.est, y)); }).join("") + "</tr>" +
        '<tr><th scope="row">きみの よそう（人）</th>' + years.map(function (y) { return cell(y, y === 2025 ? cc.now : st.draw[y]); }).join("") + "</tr>" +
        "</tbody></table>");
    }
    /** 箱の数字の大きさを合わせる。3つの箱（全校・1学年・クラスの 数）は同じ大きさにそろえ、
     *  「数字＋単位」が箱に入りきらないときだけ 1px ずつ小さくする（いちばん小さくて 18px）。
     *  「やく」を同じ行に入れると 26px より小さくなるときは、「やく」を数字の上の行に出す（.stack）。 */
    var TILE_MIN = 18, PRE_MIN = 26;
    function fitTiles() {
      var fits = UG.$$("#tiles .fit", root);
      if (!fits.length) return;
      function largest(el, box) {   // el（数字＋単位）が box の中に入る、いちばん大きい字の大きさ
        var b = el.querySelector("b"), cs = getComputedStyle(box);
        var avail = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        b.style.fontSize = "";
        var size = parseFloat(getComputedStyle(b).fontSize);
        while (el.getBoundingClientRect().width > avail && size > TILE_MIN) { size -= 1; b.style.fontSize = size + "px"; }
        return size;
      }
      var size = Infinity;
      fits.forEach(function (el) {
        var tile = el.parentElement, s;
        tile.classList.remove("stack");
        s = largest(el, tile);
        if (el.querySelector(".pre") && s < PRE_MIN) {
          tile.classList.add("stack");
          s = largest(el.querySelector(".nw"), tile);
        }
        size = Math.min(size, s);
      });
      fits.forEach(function (el) { el.querySelector("b").style.fontSize = size + "px"; });
    }
    // 文字（Web フォント）が読みこまれると幅が変わるので、読みこみのあとにもう一度合わせる
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { if (root.isConnected) fitTiles(); });
    function drawRooms() {
      var y = st.viewYear, total = M.interp(UG.ctx().est, y), plan = M.classPlan(total);
      UG.$("#year-out", root).textContent = y + "年";
      var perGrade = plan.total / 6;
      var shuffle = plan.shuffle === "all" ? "どの 学年も できる" : plan.shuffle === "some" ? "できる 学年と できない 学年が ある" : "できない";
      UG.$("#tiles", root).innerHTML = UG.ruby(
        // 数字と単位（「1,306人」「やく 218人」「42クラス」）は1行にまとめる（.fit）。入りきらない幅では数字の字を小さくする（fitTiles）
        '<div class="tile"><span class="lab">全校</span><span class="nw fit"><b>' + num(plan.total) + "</b>人</span></div>" +
        '<div class="tile"><span class="lab">1学年</span><span class="nw fit"><span class="pre">やく </span><span class="nw"><b>' + num(perGrade) + "</b>人</span></span></div>" +
        '<div class="tile"><span class="lab">クラスの 数</span><span class="nw fit"><b>' + plan.classCount + "</b>クラス</span></div>" +
        '<div class="tile wide ' + plan.shuffle + '"><span class="lab">クラスがえ</span><b class="txt">' + shuffle + "</b></div>"
      );
      fitTiles();
      UG.$("#rooms", root).innerHTML = UG.ruby(plan.rows.map(function (r) {
        var label = r.grades.join("・") + "年";
        var boxes = r.classes.map(function (n) {
          var seats = "";
          for (var i = 0; i < M.CLASS_MAX; i++) seats += "<i" + (i < n ? ' class="on"' : "") + "></i>";
          return '<div class="room' + (r.multi ? " multi" : "") + '"><div class="seats">' + seats + '</div><span class="cnt">' + n + "人</span></div>";
        }).join("");
        return '<div class="room-row"><span class="g">' + label + "</span>" + (boxes || '<span class="none">0人</span>') +
          (r.multi ? '<span class="multi-note">2つの 学年が いっしょに 学ぶ クラス（複式学級）</span>' : "") + "</div>";
      }).join(""));
    }
    function drawHist() {
      var list = UG.$("#hist-list", root);
      list.innerHTML = UG.ruby(st.extraHist.length
        ? st.extraHist.slice().sort(function (a, b) { return a.y - b.y; }).map(function (p) {
            return "<li><span>" + p.y + "年　" + num(p.v) + '人</span><button type="button" class="link" data-del="' + p.y + '">けす</button></li>';
          }).join("")
        : '<li class="empty">まだ 足した データは ないよ。</li>');
    }

    drawChart(first); drawTable(); drawRooms(); drawHist();
    if (first) { st.revealed = true; UG.save(); }

    UG.$("#wide", root).addEventListener("click", function (ev) {
      wide = !wide;
      ev.target.setAttribute("aria-pressed", wide);
      ev.target.innerHTML = UG.ruby(wide ? "2050年までに もどす" : "2070年まで 見る");
      drawChart(false); drawTable();
    });
    UG.$("#year-range", root).addEventListener("input", function (ev) {
      st.viewYear = M.EST_YEARS[+ev.target.value]; UG.save(); drawRooms();
    });
    UG.$("#hist-form", root).addEventListener("submit", function (ev) {
      ev.preventDefault();
      var y = parseInt(UG.$("#hist-y", root).value, 10), v = parseInt(UG.$("#hist-v", root).value, 10);
      if (!(y >= 1950 && y <= 2024) || !(v >= 0 && v <= 5000)) { UG.toast("入れる 年は 1950〜2024、人数は 0〜5000 に してね"); return; }
      st.extraHist = st.extraHist.filter(function (p) { return p.y !== y; });
      st.extraHist.push({ y: y, v: v }); UG.save();
      UG.$("#hist-y", root).value = ""; UG.$("#hist-v", root).value = "";
      drawChart(false); drawHist();
    });
    UG.on(root, "click", "[data-del]", function (ev, el) {
      var y = +el.getAttribute("data-del");
      st.extraHist = st.extraHist.filter(function (p) { return p.y !== y; }); UG.save();
      drawChart(false); drawHist();
    });
  };
})();
