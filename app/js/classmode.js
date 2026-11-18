/*
 * わたしの学校2050 — クラスで 見る（クラスモード 第1段階：よそうを 集める）
 * 子どもが ステップ2で 出した コード（名前なし）を 先生が まとめて 貼り、全員の よそうを 映す。
 * 読んだ コードは この画面の あいだだけ メモリに 置く（localStorage には 入れない）。計算は model.js。
 */
(function () {
  "use strict";
  var UG = window.UG, M = UG.model, esc = UG.esc, nr = UG.nr, num = UG.num;
  var GUESS_LABEL = { up: "ふえる", same: "同じくらい", down: "へる" };

  // 画面を 作り直しても 消えないように、ここに 置く（ページを 読みこみ直すと 消える）
  // calib：先生が 決めた 実際の 人数（undefined＝コードの いちばん 多い 値、null＝合わせない、数＝その 値）
  var S = { res: null, groups: [], pick: -1, revealed: false, hideReasons: false, order: [], text: "", calib: undefined };

  function shuffle(n) {
    var a = [];
    for (var i = 0; i < n; i++) a.push(i);
    for (var j = n - 1; j > 0; j--) { var k = Math.floor(Math.random() * (j + 1)), t = a[j]; a[j] = a[k]; a[k] = t; }
    return a;
  }

  function load(text) {
    S.text = text;
    S.res = M.extractGuesses(text);
    S.groups = M.groupGuesses(S.res.items);
    S.pick = S.groups.length === 1 ? 0 : -1;
    S.revealed = false;
    S.calib = undefined;
    S.order = S.pick >= 0 ? shuffle(S.groups[0].items.length) : [];
    // 学校の 名前を 出すために、まじっている 都道府県の データを 読む
    var prefs = {};
    S.groups.forEach(function (g) { prefs[g.pref] = true; });
    return Promise.all(Object.keys(prefs).map(function (p) {
      return UG.loadPref(p).then(null, function () { return null; });
    }));
  }

  function schoolOf(g) {
    return g ? UG.findSchool(g.pref, null, g.school) : null;
  }
  /** 推計を 合わせる 実際の 人数（無ければ null） */
  function calibOf(g) {
    return S.calib === undefined ? M.commonCalib(g.items) : S.calib;
  }

  UG.views["class"] = function (root) {
    var st = UG.state;
    var res = S.res, g = S.pick >= 0 ? S.groups[S.pick] : null, school = schoolOf(g);
    var sample = UG.prefs["00"] && st.prefCode === "00";
    var html = UG.pageHead("ク", "クラスで 見る", "みんなの よそうを ならべて 見よう。コードには 名前は 入って いません。") +
      '<section class="card class-in">' +
        '<label for="class-text">よそうの コードを まとめて はりつける（名前や 日時が まじっていても だいじょうぶ）</label>' +
        '<textarea id="class-text" rows="5" spellcheck="false" data-nr placeholder="WG50-…"></textarea>' +
        '<div class="class-actions">' +
          '<button type="button" class="btn primary" id="class-load">読みこむ</button>' +
          '<button type="button" class="btn ghost" id="class-clear">けす</button>' +
          (sample ? '<button type="button" class="btn ghost" id="class-sample">見本の クラスで ためす</button>' : "") +
        "</div>" +
        (res ? '<p class="class-count" id="class-count">読めた <b>' + res.items.length + "</b>人　読めなかった <b>" + res.bad.length +
          "</b>　同じで のぞいた <b>" + res.dup + "</b></p>" +
          (res.replaced ? '<p class="fine" id="class-replaced">同じ 端末から 来た ' + res.replaced + "件は、新しい ものだけ 数えました。</p>" : "")
          : "") +
        '<p class="fine">読みこんだ コードは この 画面を とじると 消えます（どこにも 送らず、のこしません）。</p>' +
      "</section>";

    if (res && S.groups.length > 1) {
      html += '<section class="card class-pick"><h2>学校が まじって います。1つ えらんでね。</h2><div class="class-schools">' +
        S.groups.map(function (gr, i) {
          var sc = schoolOf(gr);
          return '<button type="button" class="choice' + (i === S.pick ? " on" : "") + '" data-pick="' + i + '" aria-pressed="' + (i === S.pick) + '">' +
            nr(sc ? sc.name + "（" + sc.city.name + "）" : "わからない 学校（" + gr.pref + "・" + gr.school + "）") +
            '<span class="ct">' + gr.items.length + "人</span></button>";
        }).join("") + "</div></section>";
    }

    if (g && !school) {
      html += '<section class="card"><p class="note">この 学校の データが 見つかりません。アプリの データが 新しく なって いるかも しれません。</p></section>';
    }

    if (g && school) {
      var calib = calibOf(g);
      var v50 = M.interp(M.estPoints(school, calib), M.TARGET_YEAR);
      var sum = M.summarizeGuesses(g.items, S.revealed ? v50 : null);
      html +=
        '<section class="card class-result">' +
          '<p class="school-name">' + nr(school.name) + '<span class="city">' + nr(school.city.name) + "</span></p>" +
          // 実際の 人数（ステップ1で 子どもが 入れた 値）で 推計を 合わせる。先生が 直せる
          '<div class="class-calib">' +
            (calib ? '<p id="class-calib-msg">実際の 人数 <b>' + num(calib) + "</b>人に 合わせて います。</p>"
              : '<p id="class-calib-msg">' + (S.calib === null ? "実際の 人数には 合わせて いません。" : "実際の 人数に 合わせる ことも できます。") + "</p>") +
            '<div class="row"><label for="class-calib">実際の 人数</label>' +
              '<input id="class-calib" type="number" inputmode="numeric" min="1" max="3000" value="' + (calib || "") + '"><span>人</span>' +
              '<button type="button" class="btn small" id="class-calib-set">合わせる</button>' +
              (calib ? '<button type="button" class="btn sub" id="class-calib-off">合わせない</button>' : "") +
            "</div>" +
          "</div>" +
          '<div class="class-guess" aria-label="よそうの 数">' +
            ["up", "same", "down"].map(function (k) {
              return '<div class="cg"><span class="lb">' + GUESS_LABEL[k] + '</span><b class="n">' + sum.guess[k] + "</b>人</div>";
            }).join("") +
          "</div>" +
          '<div class="legend"><span class="k hist">これまで</span><span class="k mine">みんなの よそう（1本が 1人）</span>' +
            (S.revealed ? '<span class="k est">データの よそう</span>' : "") + "</div>" +
          '<div id="class-chart"></div>' +
          "<h2>2050年の よそうの 散らばり</h2>" +
          '<div id="class-dots"></div>' +
          '<p class="class-stats">いちばん 少ない <b>' + num(sum.min) + "</b>人　まんなか <b>" + num(sum.median) +
            "</b>人　いちばん 多い <b>" + num(sum.max) + "</b>人</p>" +
          (S.revealed
            ? '<div class="class-vs" id="class-vs"><p>データの よそう（2050年）は <b>' + num(v50) + "</b>人。</p>" +
                '<div class="class-guess">' +
                  [["more", "データより 多い"], ["same", "ほぼ 同じ"], ["less", "データより 少ない"]].map(function (k) {
                    return '<div class="cg"><span class="lb">' + k[1] + '</span><b class="n">' + sum.vsEst[k[0]] + "</b>人</div>";
                  }).join("") +
                "</div></div>"
            : '<div class="class-reveal"><button type="button" class="btn primary" id="class-reveal">データを 見せる</button></div>') +
        "</section>" +
        '<section class="card class-reasons">' +
          '<div class="row-head"><h2>どうして そう 思った？</h2>' +
          '<button type="button" class="btn sub" id="class-hide" aria-pressed="' + S.hideReasons + '">' +
            (S.hideReasons ? "理由を 見せる" : "理由を かくす") + "</button></div>" +
          (S.hideReasons ? '<p class="fine">理由は かくして います。</p>' :
            (function () {
              var list = S.order.map(function (i) { return g.items[i]; }).filter(function (d) { return d.reason; });
              return list.length
                ? '<ul class="reason-list" id="class-reasons">' + list.map(function (d) {
                    return '<li><span class="tg">' + GUESS_LABEL[d.guess] + "</span>" + nr(d.reason) + "</li>";
                  }).join("") + "</ul>"
                : '<p class="fine">理由は 書かれて いません。</p>';
            })()) +
        "</section>";
    }
    html += '<nav class="step-nav"><button type="button" class="btn ghost" data-go="teachers">← 先生・大人の 方へ</button></nav>';
    root.innerHTML = UG.ruby(html);

    var ta = UG.$("#class-text", root);
    ta.value = S.text; // ふりがな処理を 通さないよう、文字は あとから 入れる
    function reload(text) {
      load(text).then(function () { UG.render(); });
    }
    UG.$("#class-load", root).addEventListener("click", function () { reload(ta.value); });
    UG.$("#class-clear", root).addEventListener("click", function () {
      S.res = null; S.groups = []; S.pick = -1; S.text = ""; S.revealed = false; UG.render();
    });
    var sb = UG.$("#class-sample", root);
    if (sb) sb.addEventListener("click", function () {
      // 見本の クラス：練習用の まち（架空）の 学校で、架空の 30人分の コードを 作って 読む
      var sc = UG.findSchool("00", st.cityCode, st.schoolId) || UG.prefs["00"].cities[0].schools[1];
      var est0 = M.estPoints(sc, null);
      var codes = M.sampleClass("00", sc.id, est0[0].v, M.interp(est0, M.TARGET_YEAR), 30, 2050);
      reload(codes.join("\n"));
    });
    UG.on(root, "click", "[data-pick]", function (ev, el) {
      S.pick = +el.getAttribute("data-pick");
      S.revealed = false;
      S.calib = undefined;
      S.order = shuffle(S.groups[S.pick].items.length);
      UG.render();
    });
    var cs = UG.$("#class-calib-set", root);
    if (cs) cs.addEventListener("click", function () {
      var v = parseInt(UG.$("#class-calib", root).value, 10);
      S.calib = v > 0 ? v : null;
      UG.render();
    });
    var co = UG.$("#class-calib-off", root);
    if (co) co.addEventListener("click", function () { S.calib = null; UG.render(); });
    var rv = UG.$("#class-reveal", root);
    if (rv) rv.addEventListener("click", function () { S.revealed = true; UG.render(); });
    var hd = UG.$("#class-hide", root);
    if (hd) hd.addEventListener("click", function () { S.hideReasons = !S.hideReasons; UG.render(); });

    if (g && school) {
      var est2 = M.estPoints(school, calibOf(g)), now2 = est2[0].v;
      var hist2 = M.histPoints(school, []);
      var top = now2;
      g.items.forEach(function (d) { M.DRAW_YEARS.forEach(function (y) { top = Math.max(top, d.draw[y]); }); });
      hist2.forEach(function (p) { top = Math.max(top, p.v); });
      if (S.revealed) est2.forEach(function (p) { if (p.y <= M.TARGET_YEAR) top = Math.max(top, p.v); });
      UG.classChart(UG.$("#class-chart", root), {
        xMin: hist2.length ? Math.min(hist2[0].y, 2015) : 2020, yMax: Math.max(20, M.niceMax(top * 1.1)),
        hist: hist2, now: { y: M.BASE_YEAR, v: now2 }, lines: g.items.map(function (d) { return d.draw; }),
        est: S.revealed ? est2 : null
      });
      UG.dotPlot(UG.$("#class-dots", root), {
        values: g.items.map(function (d) { return d.draw[M.TARGET_YEAR]; }), now: now2,
        est50: S.revealed ? M.interp(est2, M.TARGET_YEAR) : null
      });
    }
  };
})();
