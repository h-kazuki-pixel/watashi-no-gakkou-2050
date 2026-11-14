/*
 * わたしの学校2050 — 起動と画面の切り替え
 * URL の #step3 などで画面を表す。入力内容はこの端末の中にだけ保存する。
 */
(function () {
  "use strict";
  var UG = window.UG, M = UG.model;
  var ORDER = ["home", "step1", "step2", "step3", "step4", "step5"];

  function drawn() {
    return M.DRAW_YEARS.every(function (y) { return UG.state.draw[y] != null; });
  }
  /** いまの進み具合で開ける画面に直す */
  function resolve(step) {
    if (step === "teachers") return step;
    if (ORDER.indexOf(step) < 0) return "home";
    if (step !== "home" && !UG.ctx()) return "home";
    if (ORDER.indexOf(step) >= 3 && !drawn()) return "step2";
    return step;
  }

  UG.go = function (step) {
    var st = UG.state;
    st.step = resolve(step);
    var i = ORDER.indexOf(st.step);
    if (i > st.maxStep) st.maxStep = i;
    UG.save();
    if (location.hash.slice(1) !== st.step) {
      try { location.hash = st.step; } catch (e) { /* 埋め込み先によっては変更できない */ }
    }
    UG.render(true);
  };

  UG.render = function (toTop) {
    var st = UG.state, old = UG.$("#view");
    // 画面ごとにイベントの受け口を作り直す（前の画面のハンドラが残って二重に動くのを防ぐ）
    var root = old.cloneNode(false);
    old.parentNode.replaceChild(root, old);
    st.step = resolve(st.step);
    root.className = "view view-" + st.step;
    UG.views[st.step](root);
    UG.renderChrome();
    if (toTop) {
      // 画面の切り替えでは一瞬で先頭へ。html の scroll-behavior: smooth のままだと、
      // 長い画面から切り替えたときに上までゆっくり戻り、その間は見出しが上のバーの下に隠れる。
      // （html の style を一時的に auto にする方法は、Chromium では効かなかった）
      try { window.scrollTo({ top: 0, left: 0, behavior: "instant" }); } catch (e) { window.scrollTo(0, 0); }
      var h = root.querySelector("h1");
      if (h) { h.setAttribute("tabindex", "-1"); try { h.focus({ preventScroll: true }); } catch (e) { /* 古いブラウザ */ } }
    }
  };

  /** ヘッダー（ステップのタブ・ふりがな・サンプル表示） */
  UG.renderChrome = function () {
    var st = UG.state, c = UG.ctx();
    var cur = ORDER.indexOf(st.step);
    UG.$$("#tabs [data-go]").forEach(function (b) {
      var i = ORDER.indexOf(b.getAttribute("data-go"));
      var open = !!c && i <= Math.max(st.maxStep, 1) && (i < 3 || drawn());
      b.disabled = !open;
      b.classList.toggle("on", i === cur);
      b.classList.toggle("done", open && i < cur);
      if (i === cur) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    var bar = UG.$("#sample-bar");
    bar.hidden = !(c && c.sample && st.step !== "home" && st.step !== "teachers");
    document.body.classList.toggle("no-ruby", !st.furigana);
    UG.$("#furi").checked = !!st.furigana;
  };

  function start(seed) {
    UG.loadState(seed);
    var st = UG.state;
    UG.$$("[data-ruby]").forEach(function (el) { el.innerHTML = UG.ruby(el.innerHTML); });
    var h = location.hash.slice(1);
    if (h && (ORDER.indexOf(h) >= 0 || h === "teachers")) st.step = h;

    document.addEventListener("click", function (ev) {
      var t = ev.target.closest ? ev.target.closest("[data-go]") : null;
      if (t && !t.disabled) { ev.preventDefault(); UG.go(t.getAttribute("data-go")); }
      var r = ev.target.closest ? ev.target.closest("[data-reset]") : null;
      if (r) { UG.resetState(); UG.go("home"); UG.toast("さいしょから はじめます"); }
    });
    UG.$("#furi").addEventListener("change", function (ev) {
      st = UG.state; st.furigana = ev.target.checked; UG.save(); UG.renderChrome();
    });
    window.addEventListener("hashchange", function () {
      var n = location.hash.slice(1);
      if (n && n !== UG.state.step && (ORDER.indexOf(n) >= 0 || n === "teachers")) UG.go(n);
    });
    // 画面の向きや幅が変わってグラフの組み方が変わるときは描き直す
    var wasNarrow = window.innerWidth < 600, rt = null;
    window.addEventListener("resize", function () {
      clearTimeout(rt);
      rt = setTimeout(function () {
        var nowNarrow = window.innerWidth < 600;
        if (nowNarrow !== wasNarrow) { wasNarrow = nowNarrow; UG.render(); }
      }, 200);
    });
    if (window.claude && window.claude.hot && window.claude.hot.snapshot) {
      window.claude.hot.snapshot(function () { return JSON.parse(JSON.stringify(UG.state)); });
    }

    // 実データの都道府県を使っていた場合は読み込んでから表示する
    if (st.prefCode !== "00" && !UG.prefs[st.prefCode]) {
      UG.loadPref(st.prefCode).then(function () { UG.render(); }, function () {
        st.prefCode = "00"; st.cityCode = "00000"; st.schoolId = null; UG.render();
      });
    } else {
      UG.render();
    }
  }

  var hot = window.claude && window.claude.hot;
  if (hot && hot.ready) hot.ready(start);
  else start((hot && hot.data) || {});
})();
