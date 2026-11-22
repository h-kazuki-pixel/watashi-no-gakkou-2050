/*
 * わたしの学校2050 — クラスで 見る（クラスモード 第1段階：よそうを 集める／第2段階：提案を 集める）
 * 子どもが ステップ2・5で 出した コード（名前なし）を 先生が まとめて 貼り、全員の よそうと 提案を 映す。
 * 提案は 宛先ごとに 印刷用の 1枚に できる。
 * 読んだ コードは この画面の あいだだけ メモリに 置く（localStorage には 入れない）。計算は model.js。
 */
(function () {
  "use strict";
  var UG = window.UG, M = UG.model, esc = UG.esc, nr = UG.nr, num = UG.num;
  var GUESS_LABEL = { up: "ふえる", same: "同じくらい", down: "へる" };

  // 画面を 作り直しても 消えないように、ここに 置く（ページを 読みこみ直すと 消える）
  // calib：先生が 決めた 実際の 人数（undefined＝コードの いちばん 多い 値、null＝合わせない、数＝その 値）
  // propsOpen：提案の 一覧を ひらいて いるか。noPrint：「印刷に 入れない」に した コード。sheetTo・sheetShown・className：印刷の 1枚
  var S = { res: null, groups: [], pick: -1, revealed: false, hideReasons: true, order: [], text: "", calib: undefined,
    propsOpen: false, noPrint: {}, sheetTo: null, sheetShown: false, className: "" };

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
    resetProps();
    S.order = S.pick >= 0 ? shuffle(S.groups[0].items.length) : [];
    // 学校の 名前を 出すために、まじっている 都道府県の データを 読む
    var prefs = {};
    S.groups.forEach(function (g) { prefs[g.pref] = true; });
    return Promise.all(Object.keys(prefs).map(function (p) {
      return UG.loadPref(p).then(null, function () { return null; });
    }));
  }

  function resetProps() {
    S.propsOpen = false; S.noPrint = {}; S.sheetTo = null; S.sheetShown = false;
  }
  function schoolOf(g) {
    return g ? UG.findSchool(g.pref, null, g.school) : null;
  }
  /** 推計を 合わせる 実際の 人数（無ければ null） */
  function calibOf(g) {
    return S.calib === undefined ? M.commonCalib(g.items) : S.calib;
  }


  /* ---------------- みんなの 提案（第2段階） ---------------- */
  var SORT_LABEL = [["good", "いいね"], ["bad", "しんぱい"], ["mid", "どちらとも"]];
  function toTitle(to, school) {
    // 市長さんは model.mayorLabel と 同じ 決まり（福岡市早良区 → 福岡市長さん）。子どもの カードの 宛先とも そろう
    return UG.toLabel(to, school.city.name) ? UG.toLabelHtml(to, school.city.name) : "宛先の ない 提案";
  }
  function textOf(list, id) {
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i].t;
    return id;
  }
  function ideaText(id) { return textOf(UG.IDEAS, id); }
  function wishText(id) { return textOf(UG.WISHES, id); }
  var ideaOrder = function () { return UG.IDEAS.map(function (k) { return k.id; }); };
  var wishOrder = function () { return UG.WISHES.map(function (k) { return k.id; }); };
  /** 集計のうち、order に ある id だけ（ほかの 版の アプリや 書きかえた コードの 知らない id は 数えず 出さない） */
  function known(tally, order) { return tally.filter(function (x) { return order.indexOf(x.id) >= 0; }); }
  function ideaRank(items) { var o = ideaOrder(); return known(M.ideaTally(items, o), o); }
  function wishRank(items) { var o = wishOrder(); return known(M.wishTally(items, o), o); }
  function sortBars(tally) {
    var max = 1;
    UG.SORT_CARDS.forEach(function (k) { var t = tally[k.id]; max = Math.max(max, t.good + t.bad + t.mid); });
    return '<ul class="sort-bars">' + UG.SORT_CARDS.map(function (k) {
      var t = tally[k.id];
      return "<li><span class=\"lb\">" + k.t + '</span><span class="bar" aria-hidden="true">' +
        SORT_LABEL.map(function (o) {
          return t[o[0]] ? '<i class="' + o[0] + '" style="width:' + (t[o[0]] / max * 100).toFixed(1) + '%"></i>' : "";
        }).join("") + '</span><span class="ns">' +
        SORT_LABEL.map(function (o) { return o[1] + " <b>" + t[o[0]] + "</b>"; }).join("　") + "</span></li>";
    }).join("") + "</ul>";
  }
  /** 人数の 多い 順の 一覧（アイデアと、もっと 知りたい データで 同じ 形）。opt: { text, id, none } */
  function rankList(tally, opt) {
    var max = tally.length ? tally[0].n : 1;
    return tally.length ? '<ol class="idea-rank"' + (opt.id ? ' id="' + opt.id + '"' : "") + ">" + tally.map(function (x) {
      return "<li><span class=\"lb\">" + opt.text(x.id) + '</span><span class="bar" aria-hidden="true"><i style="width:' +
        (x.n / max * 100).toFixed(1) + '%"></i></span><span class="n"><b>' + x.n + "</b>人</span></li>";
    }).join("") + "</ol>" : '<p class="fine">' + opt.none + "</p>";
  }
  function ideaList(tally) { return rankList(tally, { text: ideaText, none: "えらばれた アイデアは ありません。" }); }
  function wishList(tally) { return rankList(tally, { text: wishText, id: "class-wishes", none: "えらばれた データは ありません。" }); }
  /** 同じ 文は 1行に まとめて 人数を 付けた 一覧（子どもが 書いた 文） */
  function ownList(texts, id) {
    return '<ul class="own-ideas" id="' + id + '">' + mergeSame(texts.map(function (t) { return { prop: { proposal: t } }; })).map(function (x) {
      return "<li>" + nr(x.text) + (x.n > 1 ? "（" + x.n + "人）" : "") + "</li>";
    }).join("") + "</ul>";
  }

  /** 同じ 文の 提案は 1つに まとめて 人数を 付ける（印刷の 1枚を みじかく する） */
  function mergeSame(items) {
    var map = {}, out = [];
    items.forEach(function (d) {
      var t = d.prop.proposal;
      if (!map[t]) { map[t] = { text: t, n: 0 }; out.push(map[t]); }
      map[t].n++;
    });
    return out;
  }
  /** 宛先ごとの 印刷用の 1枚（ふりがなは UG.ruby に まかせる）。この 中の 文字は 画面の ふりがなの 切りかえに したがう */
  function sheetHtml(g, school, to) {
    var calib = calibOf(g);
    var est = M.estPoints(school, calib), now = est[0].v, v50 = M.interp(est, M.TARGET_YEAR), pct = M.shownPct(now, v50);
    var withP = g.items.filter(function (d) { return d.prop; });
    var props = (M.proposalsByTo(g.items, []).filter(function (x) { return x.to === to; })[0] || { items: [] }).items
      .filter(function (d) { return !S.noPrint[d.code]; });
    var sample = !!school.pref.sample;
    var wishes = wishRank(g.items).slice(0, 3);
    return '<article class="class-sheet" id="class-sheet">' +
      '<h1 class="sh-to">' + toTitle(to, school) + "へ</h1>" +
      '<p class="sh-from">' + nr(school.name) + (S.className ? "　" + nr(S.className) : "") +
        "　" + g.items.length + "人（提案を 書いた 人 " + withP.length + "人）より</p>" +
      (sample ? '<p class="fine">これは 練習用の 架空の まち・学校です。</p>' : "") +
      "<h2>データで わかった こと</h2>" +
      "<p>" + nr(school.name) + "の 学区に 住む 子どもは、2025年の " + num(now) + "人から 2050年には " + num(v50) + "人（" +
        UG.pctText(pct) + "）に なる 計算です。" +
        (calib ? "（学校の 実際の 人数 " + num(calib) + "人に 合わせて 計算）" : "") + "</p>" +
      "<h2>人数が 少なく なると？　いいこと・しんぱいな こと</h2>" + sortBars(M.sortTally(g.items)) +
      "<h2>やってみたい アイデア（えらんだ 人が 多い 5つ）</h2>" + ideaList(ideaRank(g.items).slice(0, 5)) +
      // もっと 知りたい データ：多い 3つだけ（子どもが 自由に 書いた 文は 印刷に 入れない）
      (wishes.length ? '<p class="sh-wishes"><b>もっと 知りたい データ：</b>' + wishes.map(function (x) {
        return wishText(x.id) + "（" + x.n + "人）";
      }).join("、") + "</p>" : "") +
      "<h2>わたしたちの 提案</h2>" +
      (props.length ? '<ul class="sh-props">' + mergeSame(props).map(function (x) {
          return "<li>" + nr(x.text) + (x.n > 1 ? "（" + x.n + "人）" : "") + "</li>";
        }).join("") + "</ul>"
        : '<p class="fine">この 宛先への 提案は ありません。</p>') +
      '<p class="sh-credit">子どもの 名前は 入って いません。推計は 前提つきの 計算で、決まった 未来では ありません。<br>' +
        "出典：国土数値情報（国土交通省）を 加工して 作成。加工：" + esc(UG.PROCESSOR) + "</p>" +
    "</article>";
  }

  function proposalsHtml(g, school) {
    var withP = g.items.filter(function (d) { return d.prop; });
    var out = '<section class="card class-props" id="class-props"><h2>みんなの 提案</h2>';
    if (!withP.length) return out + '<p class="fine" id="class-props-none">ステップ5の コードを はると、ここに 出るよ。</p></section>';
    var order = UG.TO.map(function (t) { return t.id; });
    var byTo = M.proposalsByTo(g.items, order);
    var own = M.ownIdeas(g.items), ownWish = M.ownWishes(g.items);
    out += '<p class="fine">提案の 入った コード <b>' + withP.length + "</b>人ぶん。</p>" +
      "<h3>いいこと？ しんぱいな こと？</h3>" +
      '<p class="sort-legend"><span class="k good">いいね</span><span class="k bad">しんぱい</span><span class="k mid">どちらとも</span></p>' +
      sortBars(M.sortTally(g.items)) +
      "<h3>えらばれた アイデア</h3>" + ideaList(ideaRank(g.items)) +
      (own.length ? "<h3>じぶんの アイデア</h3>" + ownList(own, "class-own") : "") +
      "<h3>もっと 知りたい データ</h3>" + wishList(wishRank(g.items)) +
      (ownWish.length ? ownList(ownWish, "class-own-wish") : "") +
      '<div class="row-head"><h3>提案（' + byTo.reduce(function (n, x) { return n + x.items.length; }, 0) + "件）</h3>" +
        '<button type="button" class="btn sub" id="class-props-open" aria-expanded="' + S.propsOpen + '">' +
        (S.propsOpen ? "とじる" : "ひらく") + "</button></div>" +
      (S.propsOpen
        ? '<p class="fine">映す 前に、先生が 読んで たしかめてね。「印刷に 入れない」に した 提案は、印刷の 1枚に 入りません（この 画面の あいだだけ）。</p>' +
          byTo.map(function (x) {
            return '<div class="to-group"><h4>' + toTitle(x.to, school) + "へ（" + x.items.length + "件）</h4><ul class=\"prop-list\">" +
              x.items.map(function (d) {
                var off = !!S.noPrint[d.code];
                return '<li class="' + (off ? "off" : "") + '"><span class="tx">' + nr(d.prop.proposal) + "</span>" +
                  '<label class="np"><input type="checkbox" data-noprint="' + esc(d.code) + '"' + (off ? " checked" : "") + ">印刷に 入れない</label></li>";
              }).join("") + "</ul></div>";
          }).join("")
        : "") +
      // 宛先ごとに 印刷する
      '<div class="class-print" id="class-print"><h3>宛先ごとに 印刷する</h3>' +
        (byTo.length
          ? '<div class="chips" role="group" aria-label="宛先">' + byTo.map(function (x) {
              return '<button type="button" class="chip' + (S.sheetTo === x.to ? " on" : "") + '" data-sheet-to="' + esc(x.to) + '" aria-pressed="' + (S.sheetTo === x.to) + '">' +
                toTitle(x.to, school) + "</button>";
            }).join("") + "</div>" +
            '<div class="row"><label for="class-name">クラスの 名前（書かなくても よい。のこしません）</label>' +
            '<input id="class-name" type="text" maxlength="20" placeholder="れい：5年2組" data-nr></div>' +
            '<div class="row"><button type="button" class="btn" id="class-sheet-make"' + (S.sheetTo == null ? " disabled" : "") + ">印刷用の 1枚を 作る</button></div>"
          : '<p class="fine">提案の 文が まだ ありません。</p>') +
      "</div>";
    if (S.sheetTo != null && byTo.some(function (x) { return x.to === S.sheetTo; }) && S.sheetShown) {
      out += '<div class="class-sheet-wrap" id="class-sheet-wrap">' + sheetHtml(g, school, S.sheetTo) +
        '<div class="row sheet-actions">' +
          (UG.inViewer()
            ? '<button type="button" class="btn primary" id="class-sheet-save">ファイルで 保存する</button>' +
              '<button type="button" class="btn" id="class-sheet-copy">文を コピーする</button>'
            : '<button type="button" class="btn primary" id="class-sheet-print">印刷する</button>' +
              '<button type="button" class="btn" id="class-sheet-copy">文を コピーする</button>') +
        "</div></div>";
    }
    return out + "</section>";
  }

  /** 印刷用の 1枚を、それだけで 開ける HTML に する（Claude の 画面の 中など、印刷が 使えない ときの 逃げ道） */
  function sheetFile(raw) {
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>' + esc(UG.plain(raw.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)[1])) +
      "</title><style>body{font-family:'BIZ UDPGothic','Hiragino Sans','Noto Sans JP',sans-serif;color:#1d2b4f;max-width:180mm;margin:12mm auto;line-height:1.7}" +
      "h1{font-size:22px}h2{font-size:15px;border-bottom:2px solid #1d2b4f;margin-top:14px}.bar{display:none}.fine,.sh-credit{font-size:12px}" +
      "@page{size:A4 portrait;margin:12mm}</style></head><body>" + raw + "</body></html>";
  }

  UG.views["class"] = function (root) {
    var st = UG.state;
    var res = S.res, g = S.pick >= 0 ? S.groups[S.pick] : null, school = schoolOf(g);
    var sample = UG.prefs["00"] && st.prefCode === "00";
    var html = UG.pageHead("ク", "クラスで 見る", "みんなの よそうを ならべて 見よう。コードには 名前は 入って いません。") +
      '<section class="card class-in">' +
        '<label for="class-text">ステップ2・5の コードを まとめて はりつける（名前や 日時が まじっていても だいじょうぶ）</label>' +
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
          '<h2 class="class-h">みんなの よそう</h2>' +
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
          (S.hideReasons ? '<p class="fine">理由は かくして います。先生が 読んで たしかめてから「理由を 見せる」で 出せます。</p>' :
            (function () {
              var list = S.order.map(function (i) { return g.items[i]; }).filter(function (d) { return d.reason; });
              return list.length
                ? '<ul class="reason-list" id="class-reasons">' + list.map(function (d) {
                    return '<li><span class="tg">' + GUESS_LABEL[d.guess] + "</span>" + nr(d.reason) + "</li>";
                  }).join("") + "</ul>"
                : '<p class="fine">理由は 書かれて いません。</p>';
            })()) +
        "</section>" +
        proposalsHtml(g, school);
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
      S.res = null; S.groups = []; S.pick = -1; S.text = ""; S.revealed = false; S.hideReasons = true; resetProps(); UG.render();
    });
    var sb = UG.$("#class-sample", root);
    if (sb) sb.addEventListener("click", function () {
      // 見本の クラス：練習用の まち（架空）の 学校で、架空の 30人分の コードを 作って 読む
      var sc = UG.findSchool("00", st.cityCode, st.schoolId) || UG.prefs["00"].cities[0].schools[1];
      var est0 = M.estPoints(sc, null);
      var codes = M.sampleClass("00", sc.id, est0[0].v, M.interp(est0, M.TARGET_YEAR), 30, 2050,
        ideaOrder());
      reload(codes.join("\n"));
    });
    UG.on(root, "click", "[data-pick]", function (ev, el) {
      S.pick = +el.getAttribute("data-pick");
      S.revealed = false;
      S.calib = undefined;
      resetProps();
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

    // みんなの 提案
    var po = UG.$("#class-props-open", root);
    if (po) po.addEventListener("click", function () { S.propsOpen = !S.propsOpen; UG.render(); });
    UG.on(root, "change", "[data-noprint]", function (ev, el) {
      var code = el.getAttribute("data-noprint");
      if (el.checked) S.noPrint[code] = true; else delete S.noPrint[code];
      el.closest("li").classList.toggle("off", el.checked);
      if (S.sheetShown) UG.render();
    });
    UG.on(root, "click", "[data-sheet-to]", function (ev, el) {
      S.sheetTo = el.getAttribute("data-sheet-to"); S.sheetShown = false; UG.render();
    });
    var cn = UG.$("#class-name", root);
    if (cn) {
      cn.value = S.className;
      cn.addEventListener("input", function () { S.className = cn.value; });
    }
    var mk = UG.$("#class-sheet-make", root);
    if (mk) mk.addEventListener("click", function () {
      S.sheetShown = true; UG.render();
      var w = UG.$("#class-sheet-wrap");
      if (w) w.scrollIntoView({ block: "start" });
    });
    var sp = UG.$("#class-sheet-print", root);
    if (sp) sp.addEventListener("click", function () { window.print(); });
    var raw = g && school && S.sheetShown && S.sheetTo != null ? sheetHtml(g, school, S.sheetTo) : "";
    var sc2 = UG.$("#class-sheet-copy", root);
    if (sc2) sc2.addEventListener("click", function () {
      var text = UG.plain(raw.replace(/<\/(h1|h2|p|li)>/g, "\n").replace(/<br>/g, "\n")).replace(/\n{3,}/g, "\n\n").trim();
      UG.copyText(text).then(function (ok) { UG.toast(ok ? "印刷用の 文を コピーしました" : "コピーできませんでした"); });
    });
    var ss = UG.$("#class-sheet-save", root);
    if (ss) ss.addEventListener("click", function () {
      UG.saveFile("teian-matome.html", new Blob([sheetFile(raw)], { type: "text/html" })).then(function (ok) {
        if (ok) UG.toast("ファイルを 保存しました。開いて 印刷してね");
      }, function () { UG.toast("保存できませんでした。文を コピーしてね"); });
    });

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
