/*
 * わたしの学校2050 — 画面（4 なぜ？／5 ていあん／先生・大人の方へ）
 */
(function () {
  "use strict";
  var UG = window.UG, M = UG.model, esc = UG.esc, nr = UG.nr, num = UG.num, V = UG.views;
  var head = UG.pageHead, nav = UG.stepNav;

  UG.QUIZ = [
    {
      id: "q1",
      q: "「2050年に ◯人」という データの よそうは、かならず その とおりに なる？",
      opts: ["かならず そう なる", "「いまの ながれが つづいたら」の 計算なので、かわる ことも ある", "てきとうに きめた 数字なので、あてに ならない"],
      ans: 1,
      exp: "よそう（推計）は、これまでの データと「こう なるだろう」という 前提から 計算した もの。前提が かわれば 結果も かわる。でも てきとう では なく、きちんと した 計算だよ。"
    },
    {
      id: "q2",
      q: "ある 学校の 子どもが 400人から 300人に なった。何% へった？",
      opts: ["25%", "75%", "100%"],
      ans: 0,
      exp: "へった 人数は 100人。もとの 400人の うちの 100人だから、100 ÷ 400 ＝ 0.25。つまり 25% へった。「もとの 数で わる」のが コツ。"
    },
    {
      id: "q3", charts: true,
      q: "2つの グラフは 同じ データ。右の ほうが 大きく へって 見えるのは なぜ？",
      opts: ["右の グラフの ほうが 新しい データだから", "右の グラフは、たてじくが 0から はじまって いないから", "右の グラフは 線が 太いから"],
      ans: 1,
      exp: "たてじくの はじまりを 0に しないと、小さな ちがいが 大きく 見える。グラフを 見る ときは、まず じくの 数字を たしかめよう。"
    }
  ];

  UG.SORT_CARDS = [
    { id: "c1", t: "先生が ひとりひとりを よく 見てくれる" },
    { id: "c2", t: "クラスがえが できない" },
    { id: "c3", t: "全校の みんなの 名前が わかる" },
    { id: "c4", t: "サッカーや 合唱など、大人数で やる ことが むずかしい" },
    { id: "c5", t: "発表や リーダーの 出番が ふえる" },
    { id: "c6", t: "いろいろな 考えの 友だちに 出会いにくい" },
    { id: "c7", t: "使わない 教室が ふえる" },
    { id: "c8", t: "学校が いっしょに なると、通う 道が 遠く なる 子が いる" }
  ];

  UG.IDEAS = [
    { id: "room_study", t: "空いた 教室を 図書室や 自習室に する" },
    { id: "room_town", t: "空いた 教室を 地域の 人も 使える 場所に する" },
    { id: "room_kids", t: "空いた 教室を 放課後の 子どもの 居場所に する" },
    { id: "online", t: "ほかの 学校と オンラインで いっしょに 授業を する" },
    { id: "events", t: "近くの 学校と 行事を いっしょに する" },
    { id: "bus", t: "通学の バスを 走らせる" },
    { id: "family", t: "子育て しやすい まちに して、ひっこして くる 家族を ふやす" },
    { id: "pr", t: "まちの よい ところを 調べて 発信する" },
    { id: "play", t: "子どもが 遊べる 場所を ふやす" }
  ];
  UG.MAX_IDEAS = 3;

  /* 文部科学省「令和6年度 廃校施設等活用状況実態調査」活用用途（複数回答、%） */
  UG.REUSE = [
    [55.1, "べつの 学校の 校舎"],
    [22.2, "体育館や グラウンド（スポーツ）"],
    [15.9, "会社・お店・仕事を はじめる 人の 場所"],
    [15.8, "公民館・図書館・資料館など"],
    [9.7, "お年よりや 子どもの 施設・病院"],
    [7.0, "自然体験や 交流の 施設"],
    [5.9, "市役所などの 建物"],
    [3.0, "災害に そなえる 倉庫"]
  ];

  UG.TO = [
    { id: "mayor", label: null },
    { id: "board", label: "教育委員会の みなさん" },
    { id: "principal", label: "校長先生" },
    { id: "town", label: "地域の みなさん" },
    { id: "family", label: "おうちの 人" }
  ];
  UG.toLabel = function (id, cityName) {
    if (id === "mayor") {
      var m = /(市|区|町|村)$/.exec(cityName || "");
      return (m ? m[1] : "市") + "長さん";
    }
    for (var i = 0; i < UG.TO.length; i++) if (UG.TO[i].id === id) return UG.TO[i].label;
    return "";
  };

  function level(pct) {
    if (pct == null) return null;
    return pct >= 0 ? 0 : pct >= -20 ? 1 : pct >= -40 ? 2 : pct >= -60 ? 3 : 4;
  }
  UG.changeLevel = level;

  /* ====================== 4 なぜ？ ====================== */
  V.step4 = function (root) {
    var st = UG.state, c = UG.ctx();
    var ages = M.cohortInts(M.agesFor(c.school, st.calib), c.now);
    var agesMax = Math.max.apply(null, ages) || 1;

    /** 変化率。選んだ学校は、ほかの画面と同じ値（補正を入れたときも同じ）にする */
    function pctOf(s) { return s.id === c.school.id ? c.pct : M.shownPct(s.est[0], s.est[5]); }
    var others = c.city.schools.map(function (s) {
      return { s: s, pct: pctOf(s) };
    }).filter(function (o) { return o.pct != null; }).sort(function (a, b) { return b.pct - a.pct; });
    var barMax = 60;
    others.forEach(function (o) { barMax = Math.max(barMax, Math.abs(o.pct)); });
    var rank = 0;
    others.forEach(function (o, i) { if (o.s.id === c.school.id) rank = i + 1; });

    root.innerHTML = UG.ruby(
      head(4, "「なぜ？」を さぐろう", "数字の うらには しくみが ある。3つの 実験と クイズで たしかめよう。") +

      '<section class="card age-card">' +
        '<h2><span class="no">A</span>みらいが 計算できる わけ</h2>' +
        "<p>いま 0さいの 赤ちゃんは、6年後に 1年生に なる。だから 6年後までの 1年生の 数は、もう だいたい わかっている。ボタンで 年を 進めてみよう。</p>" +
        '<div class="ages" id="ages" role="img" aria-label="年れいごとの 子どもの 数"></div>' +
        '<div class="row"><button type="button" class="btn small" id="age-next">1年 進める</button>' +
          '<button type="button" class="btn small ghost" id="age-prev">1年 もどす</button>' +
          '<button type="button" class="btn small ghost" id="age-reset">2025年に もどす</button></div>' +
        '<p class="readout" id="age-out" aria-live="polite"></p>' +
      "</section>" +

      '<section class="card sim-card">' +
        '<h2><span class="no">B</span>もしも、まちが かわったら</h2>' +
        "<p>みらいは きまって いない。つまみを 動かして、緑の 線が どう かわるか 見てみよう。</p>" +
        '<div class="sliders">' +
          '<div class="slider"><label for="sim-move">毎年、小学生が あと <b id="sim-move-v"></b>人 ひっこして くる</label>' +
            '<input id="sim-move" type="range" min="0" max="20" step="1" value="' + st.sim.move + '"></div>' +
          '<div class="slider"><label for="sim-birth">生まれる 赤ちゃんの 数が <b id="sim-birth-v"></b> に なる</label>' +
            '<input id="sim-birth" type="range" min="-30" max="50" step="5" value="' + st.sim.birth + '"></div>' +
        "</div>" +
        '<div class="legend"><span class="k est">データの よそう</span><span class="k alt">もしもの 線</span></div>' +
        '<div id="sim-chart"></div>' +
        '<p class="readout" id="sim-out" aria-live="polite"></p>' +
        '<p class="fine">しくみを たしかめる ための かんたんな 計算です。ひっこして きた 子は 6年間 通い、生まれる 数の 変化は 6年後の 1年生から あらわれる、と 考えています。</p>' +
      "</section>" +

      '<section class="card compare-card">' +
        '<h2><span class="no">C</span>同じ まちの 学校と くらべる</h2>' +
        "<p>" + nr(c.city.name) + "の 小学校を、2025年から 2050年の 変化で ならべたよ。" +
          (others.length > 1 ? nr(c.school.name) + "は " + others.length + "校の うち、へり方が 小さい ほうから <b>" + rank + "番目</b>。" : "") + "</p>" +
        '<div class="compare"><div class="mapbox" id="cmp-map"></div><ol class="cmp-list" id="cmp-list">' +
          others.map(function (o) {
            var w = (Math.abs(o.pct) / barMax) * 100;
            return '<li class="' + (o.s.id === c.school.id ? "me" : "") + '"><span class="nm">' + nr(o.s.name) + "</span>" +
              '<span class="bar"><i class="lv' + level(o.pct) + '" style="width:' + w.toFixed(1) + '%"></i></span>' +
              '<span class="pv">' + (Math.round(o.pct) > 0 ? "+" : Math.round(o.pct) < 0 ? "−" : "") + Math.abs(Math.round(o.pct)) + "%</span>" +
              (o.s.tag ? '<span class="tg">' + o.s.tag + "</span>" : "") + "</li>";
          }).join("") +
        "</ol></div>" +
        '<ul class="map-legend" aria-label="色の 意味"><li><i class="lv0"></i>ふえる・同じ</li><li><i class="lv1"></i>20%まで へる</li><li><i class="lv2"></i>40%まで へる</li><li><i class="lv3"></i>60%まで へる</li><li><i class="lv4"></i>60%より へる</li></ul>' +
        '<p class="think"><b>考えてみよう</b>　同じ まちでも、場所に よって ちがうのは なぜだろう。駅や お店は 近い？ 新しい 家は 多い？ 地図や まち歩きで たしかめよう。</p>' +
      "</section>" +

      '<section class="card quiz-card">' +
        '<h2><span class="no">D</span>データたんていクイズ</h2>' +
        '<div id="quiz"></div>' +
      "</section>" +
      nav("step3", "もどる", "step5", "まちに ていあん する")
    );

    function drawAges() {
      var k = st.ageStep, cur = M.ageStep(ages, k), res = M.elementaryAfter(ages, k);
      UG.$("#ages", root).innerHTML = UG.ruby(
        '<div class="bars">' + cur.map(function (v, j) {
          var h = v == null ? 55 : Math.max(3, (v / agesMax) * 100);
          return '<div class="col' + (j >= 6 ? " el" : "") + (v == null ? " unk" : "") + '"><span class="val">' + (v == null ? "？" : v) + "</span>" +
            '<i style="height:' + h.toFixed(0) + '%"></i><span class="ag">' + j + "</span></div>";
        }).join("") + "</div>" +
        '<div class="ages-axis"><span class="pre">入学前（0〜5さい）</span><span class="el">小学生（6〜11さい）</span></div>'
      );
      var y = 2025 + k, out;
      if (res.known) {
        out = (k === 0 ? "2025年" : k + "年後（" + y + "年）") + "の 小学生は <span class=\"nw\">やく <b>" + num(res.sum) + "人</b></span>" + (k > 0 ? "（ひっこしが ないと したら）。" : "。");
        if (k > 0) out += "データの よそうは " + num(M.interp(c.est, y)) + "人。差は ひっこしなどを 考えた ぶんだよ。";
        if (k === 6) out += "<br><mark>ここまでは、いま いる 子どもだけで 計算できる。</mark>";
      } else {
        out = y + "年の 小学生には、まだ 生まれて いない 子（？）が まざる。<mark>何人 生まれるかは だれにも わからない。だから「よそう」が ひつように なる。</mark>";
      }
      UG.$("#age-out", root).innerHTML = UG.ruby(out);
      UG.$("#age-next", root).disabled = k >= 11;
      UG.$("#age-prev", root).disabled = k <= 0;
    }

    function drawSim() {
      var mv = st.sim.move, bi = st.sim.birth;
      UG.$("#sim-move-v", root).textContent = mv;
      UG.$("#sim-birth-v", root).innerHTML = UG.ruby(bi === 0 ? "いまの まま" : Math.abs(bi) + "% " + (bi > 0 ? "多め" : "少なめ"));
      var alt = M.simPoints(c.est, mv, bi), changed = mv !== 0 || bi !== 0;
      var top = c.now;
      alt.forEach(function (p) { if (p.y <= 2050) top = Math.max(top, p.v); });
      UG.lineChart(UG.$("#sim-chart", root), {
        xMin: 2020, xMax: 2050, yMax: Math.max(20, M.niceMax(top * 1.15)), hist: [], now: { y: 2025, v: c.now },
        est: c.est, alt: changed ? alt : null, target: 2050, aria: "データの よそうと、もしもの 線"
      });
      var a = M.interp(alt, 2050), plan = M.classPlan(a), d = Math.round(a) - Math.round(c.v50);
      UG.$("#sim-out", root).innerHTML = UG.ruby(changed
        ? "2050年は <b class=\"alt\">" + num(a) + "人</b>（データの よそうより " + (d >= 0 ? "+" : "−") + num(Math.abs(d)) + "人）。クラスは 全校で " + plan.classCount + "クラスに なる。"
        : "つまみを 動かすと、もしもの 線が 出るよ。");
    }

    function drawQuiz() {
      UG.$("#quiz", root).innerHTML = UG.ruby(UG.QUIZ.map(function (q, qi) {
        var picked = st.quiz[q.id], answered = picked != null;
        var charts = q.charts
          ? '<div class="quiz-charts"><figure>' + UG.miniAxisChart([520, 505, 490, 480, 470, 455], 0, 600, "たてじくが 0から はじまる グラフ") + "<figcaption>左</figcaption></figure>" +
            "<figure>" + UG.miniAxisChart([520, 505, 490, 480, 470, 455], 440, 520, "たてじくが 440から はじまる グラフ") + "<figcaption>右</figcaption></figure></div>"
          : "";
        return '<div class="quiz-q"><p class="q"><span class="qn">Q' + (qi + 1) + "</span>" + q.q + "</p>" + charts +
          '<div class="quiz-opts">' + q.opts.map(function (o, oi) {
            var cls = answered ? (oi === q.ans ? " right" : oi === picked ? " wrong" : "") : "";
            return '<button type="button" class="opt' + cls + '" data-q="' + q.id + '" data-o="' + oi + '"' + (answered ? " disabled" : "") + ">" + o + "</button>";
          }).join("") + "</div>" +
          (answered ? '<p class="exp"><b>' + (picked === q.ans ? "正解！" : "おしい！") + "</b>　" + q.exp + "</p>" : "") + "</div>";
      }).join(""));
    }

    /** くらべる一覧を、えらんだ 学校が 見える 位置まで 送る（一覧の 中だけ。画面全体は 動かさない）。
     *  学校の 多い まち（横浜市 338校）では、えらんだ 学校が 一覧の 先頭から 見えない ところに あるため */
    function showMe() {
      var list = UG.$("#cmp-list", root), me = list && list.querySelector("li.me");
      if (!me || list.scrollHeight <= list.clientHeight) return;
      var off = me.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop;
      list.scrollTop = Math.max(0, off - (list.clientHeight - me.offsetHeight) / 2);
    }

    drawAges(); drawSim(); drawQuiz(); showMe();
    UG.townMap(UG.$("#cmp-map", root), c.city, {
      selected: c.school.id, showNames: true,
      value: function (s) { return level(pctOf(s)); }
    });

    UG.$("#age-next", root).addEventListener("click", function () { st.ageStep = Math.min(11, st.ageStep + 1); UG.save(); drawAges(); });
    UG.$("#age-prev", root).addEventListener("click", function () { st.ageStep = Math.max(0, st.ageStep - 1); UG.save(); drawAges(); });
    UG.$("#age-reset", root).addEventListener("click", function () { st.ageStep = 0; UG.save(); drawAges(); });
    UG.$("#sim-move", root).addEventListener("input", function (ev) { st.sim.move = +ev.target.value; UG.save(); drawSim(); });
    UG.$("#sim-birth", root).addEventListener("input", function (ev) { st.sim.birth = +ev.target.value; UG.save(); drawSim(); });
    UG.on(root, "click", ".opt", function (ev, el) {
      st.quiz[el.getAttribute("data-q")] = +el.getAttribute("data-o"); UG.save(); drawQuiz();
    });
  };

  /* ====================== 5 ていあん ====================== */
  V.step5 = function (root) {
    var st = UG.state, c = UG.ctx();
    var toName = function (id) { return UG.toLabel(id, c.city.name); };
    var evidence = nr(c.school.name) + "の 子どもは、2025年の " + num(c.now) + "人から 2050年には " + num(c.v50) + "人（" + UG.pctText(c.pct) + "）に なる 計算です。";
    var sortLead = c.pct != null && c.pct >= -5
      ? "わたしの 学校は あまり へらない 計算。でも 同じ まちには へる 学校も ある。人数が 少ない 学校に ついて、きみは どう 感じる？"
      : "人数が 少なく なると、学校は どう なるだろう。きみは どう 感じる？";

    root.innerHTML = UG.ruby(
      head(5, "まちに ていあん しよう", "データで わかった ことを もとに、きみの 考えを カードに まとめよう。") +

      '<section class="card sort-card">' +
        '<h2><span class="no">A</span>いいこと？ しんぱいな こと？</h2>' +
        "<p>" + sortLead + " 正解は ないよ。友だちと くらべて みよう。</p>" +
        '<ul class="sort-list">' + UG.SORT_CARDS.map(function (k) {
          var v = st.sort[k.id];
          return "<li><span>" + k.t + '</span><span class="tri" role="group" aria-label="' + esc(UG.plain(k.t)) + '">' +
            [["good", "いいね"], ["bad", "しんぱい"], ["mid", "どちらとも"]].map(function (o) {
              return '<button type="button" class="' + o[0] + (v === o[0] ? " on" : "") + '" data-sort="' + k.id + '" data-v="' + o[0] + '" aria-pressed="' + (v === o[0]) + '">' + o[1] + "</button>";
            }).join("") + "</span></li>";
        }).join("") + "</ul>" +
        '<p class="readout" id="sort-out"></p>' +
      "</section>" +

      '<section class="card idea-card">' +
        '<h2><span class="no">B</span>やってみたい アイデアを えらぶ</h2>' +
        "<p>3つまで えらべるよ。じぶんの アイデアも 書けるよ。</p>" +
        '<div class="ideas" id="ideas">' + UG.IDEAS.map(function (k) {
          var on = st.ideas.indexOf(k.id) >= 0;
          return '<button type="button" class="idea' + (on ? " on" : "") + '" data-idea="' + k.id + '" aria-pressed="' + on + '">' + k.t + "</button>";
        }).join("") + "</div>" +
        '<label for="own-idea">じぶんの アイデア</label>' +
        '<input id="own-idea" type="text" maxlength="40" value="' + esc(st.ownIdea) + '" placeholder="れい：校庭で 月に 1回、朝市を ひらく">' +
        '<div class="hint-box"><h3>ヒント：使われなく なった 校舎は、全国で こう 使われている</h3>' +
          '<ul class="reuse">' + UG.REUSE.map(function (r) {
            return "<li><span>" + r[1] + '</span><span class="bar"><i style="width:' + (r[0] / 55.1 * 100).toFixed(1) + '%"></i></span><b>' + r[0] + "%</b></li>";
          }).join("") + "</ul>" +
          '<p class="fine">1つの 校舎に 2つ以上の 使い道が ある 場合も 数えています。出典：文部科学省「令和6年度 廃校施設等活用状況実態調査」</p></div>' +
      "</section>" +

      '<section class="card write-card">' +
        '<h2><span class="no">C</span>ていあんを 書く</h2>' +
        '<p class="label">だれに 伝える？</p>' +
        '<div class="chips" role="group" aria-label="伝える 相手">' + UG.TO.map(function (t) {
          return '<button type="button" class="chip' + (st.to === t.id ? " on" : "") + '" data-to="' + t.id + '" aria-pressed="' + (st.to === t.id) + '">' + toName(t.id) + "</button>";
        }).join("") + "</div>" +
        '<p class="label">理由に なる データ（カードに 入るよ）</p>' +
        '<p class="evidence">' + evidence + "</p>" +
        '<label for="proposal">きみの ていあん</label>' +
        '<textarea id="proposal" rows="3" maxlength="110" placeholder="れい：空いた 教室を 図書室に して、地域の 人も 入れる ように して ほしいです。">' + esc(st.proposal) + "</textarea>" +
        '<label for="nick">ニックネーム（書かなくても だいじょうぶ。本当の 名前は 書かないでね）</label>' +
        '<input id="nick" type="text" maxlength="12" value="' + esc(st.nick) + '">' +
      "</section>" +

      '<section class="card out-card">' +
        '<h2><span class="no">D</span>みらい ていあんカード</h2>' +
        '<div class="card-frame" id="card"></div>' +
        '<div class="row">' +
          '<button type="button" class="btn primary" id="save-png">画像で 保存する</button>' +
          (UG.inViewer() ? "" : '<button type="button" class="btn" id="print">印刷する</button>') +
          '<button type="button" class="btn" id="copy">文を コピーする</button>' +
        "</div>" +
        '<p class="fine">カードは 先生や おうちの 人と いっしょに、伝えたい 相手に とどけよう。</p>' +
      "</section>" +

      '<section class="card done-card">' +
        '<span class="stamp big" aria-hidden="true">たんけん 修了</span>' +
        "<div><h2>きみが 今日 使った「データの 力」</h2>" +
        '<ol class="skills"><li><b>問う</b><br>「2050年は 何人？」と 問いを 立てた</li><li><b>よそうする</b><br>じぶんの 考えを 線で あらわした</li>' +
        "<li><b>集める・読む</b><br>国の データを 読み、むかしの 人数を しらべた</li><li><b>くらべる</b><br>しくみと 場所の ちがいから 理由を 考えた</li>" +
        "<li><b>伝える</b><br>データを 理由に して ていあん した</li></ol>" +
        "<p>この 5つの 進め方は、世界中で 使われている 調べ方（PPDAC）と 同じだよ。</p></div>" +
      "</section>" +
      nav("step4", "もどる", "home", "ほかの 学校も しらべる")
    );

    function drawSort() {
      var g = 0, b = 0, n = 0;
      UG.SORT_CARDS.forEach(function (k) { var v = st.sort[k.id]; if (v) n++; if (v === "good") g++; if (v === "bad") b++; });
      UG.$("#sort-out", root).innerHTML = UG.ruby(n
        ? "いいね <b>" + g + "</b>こ、しんぱい <b>" + b + "</b>こ、どちらとも <b>" + (n - g - b) + "</b>こ。人に よって 感じ方は ちがう。"
        : "");
    }
    function drawCard() {
      UG.$("#card", root).innerHTML = UG.cardSVG(UG.cardData());
    }
    drawSort(); drawCard();

    UG.on(root, "click", "[data-sort]", function (ev, el) {
      var id = el.getAttribute("data-sort"), v = el.getAttribute("data-v");
      st.sort[id] = st.sort[id] === v ? null : v; UG.save();
      UG.$$('[data-sort="' + id + '"]', root).forEach(function (b) {
        var on = st.sort[id] === b.getAttribute("data-v"); b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
      });
      drawSort();
    });
    UG.on(root, "click", "[data-idea]", function (ev, el) {
      var id = el.getAttribute("data-idea"), i = st.ideas.indexOf(id);
      if (i >= 0) st.ideas.splice(i, 1);
      else if (st.ideas.length >= UG.MAX_IDEAS) { UG.toast("えらべるのは 3つまで。どれかを はずしてね"); return; }
      else st.ideas.push(id);
      UG.save();
      var on = st.ideas.indexOf(id) >= 0;
      el.classList.toggle("on", on); el.setAttribute("aria-pressed", on);
      drawCard();
    });
    UG.on(root, "click", "[data-to]", function (ev, el) {
      st.to = el.getAttribute("data-to"); UG.save();
      UG.$$("[data-to]", root).forEach(function (b) { var on = b === el; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
      drawCard();
    });
    [["#own-idea", "ownIdea"], ["#proposal", "proposal"], ["#nick", "nick"]].forEach(function (p) {
      UG.$(p[0], root).addEventListener("input", function (ev) { st[p[1]] = ev.target.value; UG.save(); drawCard(); });
    });

    UG.$("#save-png", root).addEventListener("click", function () {
      UG.cardPNG(UG.cardSVG(UG.cardData())).then(function (blob) {
        return UG.saveFile("mirai-teian-card.png", blob);
      }).then(function (ok) {
        if (ok) UG.toast("カードを 保存しました");
      }, function () {
        UG.toast("保存できませんでした。画面を 写真に とって のこしてね");
      });
    });
    var pr = UG.$("#print", root);
    if (pr) pr.addEventListener("click", function () { window.print(); });
    UG.$("#copy", root).addEventListener("click", function () {
      UG.copyText(UG.cardText(UG.cardData())).then(function (ok) {
        UG.toast(ok ? "ていあんの 文を コピーしました" : "コピーできませんでした");
      });
    });
  };

  /* ====================== 先生・大人の方へ ====================== */
  /** 先生向けページの出典。data/index.js の datasets（名前・ページ・取得日）から作る。
   *  出典（データと取得日）がまったく同じ都道府県は1行にまとめる。半分より多い県が同じなら「○都道府県（△を除く）」と書く */
  UG.sourceList = function () {
    var ja = function (iso) { var p = (iso || "").split("-"); return p.length === 3 ? (+p[0]) + "年" + (+p[1]) + "月" + (+p[2]) + "日" : ""; };
    var list = UG.index.filter(function (p) { return p.datasets && p.datasets.length; });
    var groups = [], byKey = {};
    list.forEach(function (p) {
      var key = JSON.stringify(p.datasets);
      if (!byKey[key]) { byKey[key] = { ds: p.datasets, prefs: [] }; groups.push(byKey[key]); }
      byKey[key].prefs.push(p);
    });
    return groups.map(function (g) {
      var label;
      if (g.prefs.length > 1 && g.prefs.length * 2 > list.length) {
        var others = list.filter(function (p) { return g.prefs.indexOf(p) < 0; });
        label = g.prefs.length + "都道府県" + (others.length ? "（" + others.map(function (p) { return esc(p.name); }).join("・") + "を除く）" : "");
      } else {
        label = g.prefs.map(function (p) { return esc(p.name); }).join("・");
      }
      return "<li><b>" + label + "</b>：出典：" + g.ds.map(function (d) {
        return "「" + esc(d.name) + "」（国土交通省）（<a href=\"" + esc(d.url) + "\" target=\"_blank\" rel=\"noopener\">" + esc(d.url) + "</a>）" +
          (d.retrieved ? "（" + ja(d.retrieved) + "取得）" : "");
      }).join("、") + "を加工して作成。加工：" + esc(UG.PROCESSOR) + "</li>";
    }).join("");
  };

  V.teachers = function (root) {
    var tpl = document.getElementById("tpl-teachers");
    root.innerHTML = tpl ? tpl.innerHTML : "";
    var src = UG.$("#src-prefs", root);
    if (src) src.innerHTML = UG.sourceList();
    var back = UG.$("[data-go]", root);
    if (back && !UG.state.schoolId) back.setAttribute("data-go", "home");
  };
})();
