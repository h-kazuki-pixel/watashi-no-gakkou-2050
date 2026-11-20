#!/usr/bin/env python3
"""ブラウザで全ステップを通す動作確認（スモークテスト）。

使い方:  python3 tools/e2e_check.py [出力フォルダ]
  - コンソールエラーが出ないこと
  - 5ステップを最後まで進められること
  - 子ども向け画面に「ふりがなのない漢字」が残っていないこと
  - 自分以外の http/https の宛先へ通信しないこと、同梱の3書体が読みこまれること（file:// と http の両方）
を確かめ、各画面のスクリーンショットを保存する。
"""
import functools
import http.server
import json
import os
import pathlib
import shutil
import sys
import threading
import urllib.parse

from playwright.sync_api import sync_playwright

# Chrome の場所。環境変数 CHROME で指定できる。無ければ Playwright 付属の Chromium を使う
_CHROME = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
LAUNCH = {"args": ["--no-sandbox"], **({"executable_path": _CHROME} if _CHROME else {})}

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tools" / "_shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = (ROOT / "app" / "index.html").as_uri()

# 数字のあとの「年」「人」や、学年チップの「小」「中」はふりがななしでよい
ALLOW = set("年人小中")

FIND_BARE_KANJI = """
() => {
  const out = [];
  const walker = document.createTreeWalker(document.getElementById('view'), NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    let p = n.parentElement, skip = false;
    while (p) {
      const tag = p.tagName.toLowerCase();
      if (tag === 'ruby' || tag === 'rt' || tag === 'svg' || tag === 'textarea' || p.hasAttribute('data-nr') || p.classList.contains('teachers')) { skip = true; break; }
      p = p.parentElement;
    }
    if (skip) continue;
    const m = n.textContent.match(/[\\u4e00-\\u9fff々]/g);
    if (m) out.push([m.join(''), n.textContent.trim().slice(0, 40)]);
  }
  return out;
}
"""

# 同梱の書体（app/css/app.css の @font-face）。document.fonts で、この3つが loaded になること
FONT_FACES = [("BIZ UDPGothic", "400"), ("BIZ UDPGothic", "700"), ("Yusei Magic", "400")]
FONT_STATUS = """async () => { await document.fonts.ready;
  return [...document.fonts].map(f => [f.family.replace(/"/g, ''), String(f.weight), f.status]); }"""


def watch_requests(ctx, own_origin, out):
    """ctx（ブラウザのコンテキスト）の通信のうち、自分以外の http/https の宛先を out に足す。
    own_origin は "http://127.0.0.1:8000" のような自分の宛先。file:// なら None（http/https はすべて外部）"""
    def on_request(req):
        u = urllib.parse.urlsplit(req.url)
        if u.scheme in ("http", "https") and f"{u.scheme}://{u.netloc}" != own_origin:
            out.append(req.url)
    ctx.on("request", on_request)


def check_fonts(page, where):
    """同梱の3書体が loaded になっているか。足りないものを文字列で返す"""
    faces = page.evaluate(FONT_STATUS)
    # 同じ名前・太さの書体がすべて loaded で、1つ以上あること（ファイルが無いと error になる）
    return [f"[{where}] 書体が読みこまれない: {f} {w}（{faces}）" for f, w in FONT_FACES
            if not any(x[:2] == [f, w] for x in faces) or any(x[:2] == [f, w] and x[2] != "loaded" for x in faces)]


def check_http(browser):
    """app/ をローカルの HTTP サーバーで配ったときも、外部に通信せず、3書体が読みこまれること（GitHub Pages と同じ形）"""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(ROOT / "app"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    own = f"http://127.0.0.1:{srv.server_address[1]}"
    out, ext = [], []
    try:
        ctx = browser.new_context(viewport={"width": 1180, "height": 820})
        watch_requests(ctx, own, ext)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: out.append(f"[http] {e}"))
        pg.goto(own + "/index.html"); pg.wait_for_selector(".school-btn")
        out += check_fonts(pg, "http")
        ctx.close()
    finally:
        srv.shutdown()
    return out + [f"[http] 外部への通信: {u}" for u in ext]


# 印の無い学校の 一覧と 注意（閉校の印を足す前の 作り方。今と1文字も変わらないことを比べる）
OLD_HOME = """() => { const st = UG.state, p = UG.prefs[st.prefCode], c = p.cities.find(x => x.code === st.cityCode);
  const nr = UG.nr, esc = UG.esc, num = UG.num;
  const list = c.schools.map(s => '<button type="button" class="school-btn' + (s.id === st.schoolId ? " on" : "") + '" data-school="' + esc(s.id) + '" aria-pressed="' + (s.id === st.schoolId) + '">' +
    '<span class="nm">' + nr(s.name) + "</span>" + (s.tag ? '<span class="tg">' + s.tag + "</span>" : "") +
    '<span class="ct">' + num(s.est[0]) + "人</span></button>").join("");
  const sc = c.schools.find(s => s.id === st.schoolId) || null;
  const t = c.approx ? "" : UG.approxNote(c, sc);
  const note = t ? '<p class="note">' + t + "</p>" : "";
  const html = h => { const d = document.createElement('div'); d.innerHTML = UG.ruby(h); return d.innerHTML; };  // ブラウザの書き出し方にそろえる
  return [html(list) === document.getElementById('school-list').innerHTML, html(note) === document.getElementById('school-note').innerHTML]; }"""

# 合成の印（みらい市。テストの間だけ。練習用の数字は変えない）
MARKS_ON = """() => { const c = UG.prefs['00'].cities[0], by = {}; c.schools.forEach(s => by[s.id] = s);
  by.S3.gone = true; by.S3.now = { name: by.S4.name, id: 'S4' };
  by.S4.joined = [{ id: 'S3', name: by.S3.name }];
  by.S5.gone = true;
  by.S1.gone = true; by.S1.now = { name: 'みらい義務教育学校' };
  UG.prefs['00'].newSchools = [
    { muni: c.code, name: 'みらい義務教育学校', kana: ['みらいぎむきょういくがっこう'], from: ['S1', 'S9'] },
    { muni: c.code, name: 'あおば学園', kana: ['あおばがくえん'], from: [] },
    { muni: 'zz', name: 'ほかの まちの 学校', from: ['S3'] }];
  UG.render(); }"""
MARKS_OFF = """() => { const c = UG.prefs['00'].cities[0];
  c.schools.forEach(s => { delete s.gone; delete s.now; delete s.joined; }); delete UG.prefs['00'].newSchools; UG.render(); }"""
NOTE_GONE_NOW = "「中央小学校」という 名前の 学校は、いまは ありません。国の 学校の 一覧では、いまは「川ぞえ小学校」に なって います。ここに 出る 数字は、もとの「中央小学校」の 区域の 人数です。"
NOTE_GONE = "「山の上小学校」という 名前の 学校は、いまは ありません（国の 学校の 一覧より）。ここに 出る 数字は、もとの「山の上小学校」の 区域の 人数です。"
NOTE_JOINED = "「中央小学校」だった 区域の 子どもは、この 数字に 入って いません。"
NEW_TAG = "あたらしい 学校。人数は まだ 計算できないよ"
NO_HSCROLL = "() => document.documentElement.scrollWidth <= innerWidth"


def closures(page, shot, bare, plain, problems):
    """閉校の印（gone・now・joined）と 新しい学校（newSchools）。みらい市は印なし → 今と同じ。合成の印 → 札・注意・ボタン・新しい学校の行"""
    # 印の無い みらい市：一覧と注意が 今と1文字も変わらない（えらぶ前・えらんだ後）
    sel = page.evaluate("UG.state.schoolId")
    page.evaluate("UG.state.schoolId = null; UG.render()")
    assert page.evaluate(OLD_HOME) == [True, True], "印の無い一覧・注意が変わった（えらぶ前）"
    page.click('[data-school="S3"]')
    assert page.evaluate(OLD_HOME) == [True, True], "印の無い一覧・注意が変わった（えらんだ後）"
    assert page.locator(".gone-tg, .new-school, .note.closure, .pick-now").count() == 0

    page.evaluate(MARKS_ON)
    tags = page.evaluate("""() => [...document.querySelectorAll('#school-list .school-btn')].map(b => {
      const c = b.cloneNode(true); c.querySelectorAll('rt').forEach(r => r.remove());
      return [b.dataset.school, [...c.querySelectorAll('.tg')].map(t => t.textContent)]; })""")
    by = dict(tags)
    assert by["S3"][-1] == "いまは この 名前では ないよ" and len(by["S3"]) == 2, by["S3"]  # s.tag と 両方
    assert by["S5"][-1] == "いまは この 名前では ないよ" and by["S1"][-1] == "いまは この 名前では ないよ", by
    assert "いまは この 名前では ないよ" not in by["S2"] + by["S4"] + by["S6"], by
    assert [t[0] for t in tags] == ["S1", "S2", "S3", "S4", "S5", "S6"], tags  # 並び順は 変えない
    # 中央小（gone＋now＋id）：注意と「「川ぞえ小学校」を えらぶ」
    assert plain("#school-note .note.closure") == NOTE_GONE_NOW, plain("#school-note .note.closure")
    assert plain("#school-note .pick-now button") == "「川ぞえ小学校」を えらぶ", plain("#school-note .pick-now button")
    bare("home-gone-now")
    # 新しい学校の行：一覧の最後。選べない（ボタンではない）。人数は「—」。from は この まちの 学校だけ
    rows = page.evaluate("""() => [...document.querySelectorAll('#school-list .new-school')].map(r => {
      const c = r.cloneNode(true); c.querySelectorAll('rt').forEach(x => x.remove());
      return { nm: c.querySelector('.nm').textContent, tg: c.querySelector('.tg').textContent, ct: c.querySelector('.ct').textContent,
               tag: r.tagName, from: [...c.querySelectorAll('[data-pick]')].map(b => [b.dataset.pick, b.textContent]),
               lab: (c.querySelector('.from .lab') || {}).textContent || null, last: !r.nextElementSibling }; })""")
    assert [r["nm"] for r in rows] == ["みらい義務教育学校", "あおば学園"], rows
    assert all(r["tg"] == NEW_TAG and r["ct"] == "—" and r["tag"] == "DIV" for r in rows), rows
    assert rows[0]["from"] == [["S1", "みなと小学校"]] and rows[0]["lab"] == "もとの 学校で しらべる：", rows[0]
    assert rows[1]["from"] == [] and rows[1]["lab"] is None and rows[1]["last"], rows[1]
    assert page.evaluate("document.querySelector('#school-list').lastElementChild.classList.contains('new-school')")
    shot("0-home-closure-gone-now")
    for w in (390, 820):
        page.set_viewport_size({"width": w, "height": 820}); page.wait_for_timeout(300)
        if not page.evaluate(NO_HSCROLL):
            problems.append(f"{w}px 幅で 閉校の印の ホームが 横に はみ出す")
        page.locator("#school-note").scroll_into_view_if_needed()
        shot(f"0-home-closure-{w}")
    page.set_viewport_size({"width": 1180, "height": 820}); page.wait_for_timeout(300)
    # 「えらぶ」を押すと 川ぞえ小が 選ばれ、joined の文が出る
    page.click("#school-note .pick-now button")
    assert page.evaluate("UG.state.schoolId") == "S4"
    assert plain("#school-note .note.closure") == NOTE_JOINED, plain("#school-note .note.closure")
    assert page.locator("#school-note .pick-now").count() == 0
    bare("home-joined")
    # 山の上小（gone だけ）
    page.click('[data-school="S5"]')
    assert plain("#school-note .note.closure") == NOTE_GONE, plain("#school-note .note.closure")
    assert page.locator("#school-note .pick-now").count() == 0
    bare("home-gone")
    # みなと小（gone＋now で id なし）：ボタンなし
    page.click('[data-school="S1"]')
    assert "いまは「みらい義務教育学校」に なって います。" in plain("#school-note .note.closure")
    assert page.locator("#school-note .pick-now").count() == 0
    # さがす：新しい学校だけ当たるときは「見つからなかったよ」を出さない。ひらがなは読みで
    page.fill("#q-school", "あおば")
    assert page.locator("#school-list .school-btn").count() == 0 and page.locator("#school-list .empty").count() == 0
    assert page.locator("#school-list .new-school").count() == 1
    page.fill("#q-school", "みらいぎむ")
    assert [t.strip() for t in page.locator("#school-list .new-school .nm").all_inner_texts()] == ["みらい義務教育学校"]
    bare("home-new-search")
    for w in (390, 820):
        page.set_viewport_size({"width": w, "height": 820}); page.wait_for_timeout(300)
        if not page.evaluate(NO_HSCROLL):
            problems.append(f"{w}px 幅で 新しい学校の行が 横に はみ出す")
        page.fill("#q-school", "みらいぎむ")  # 幅を変えると 画面を 作り直すので、さがす 文字を 入れ直す
        page.locator("#school-list").scroll_into_view_if_needed()
        shot(f"0-home-new-school-{w}")
    page.set_viewport_size({"width": 1180, "height": 820}); page.wait_for_timeout(300)
    page.fill("#q-school", "ぞぞぞ")
    assert page.locator("#school-list .empty").count() == 1
    # もとの 学校を 押すと その学校が 選ばれ、さがす欄は 空になる
    page.fill("#q-school", "みらいぎむ")
    page.click('#school-list .new-school [data-pick="S1"]')
    assert page.evaluate("UG.state.schoolId") == "S1" and page.input_value("#q-school") == ""
    assert page.locator("#school-list .school-btn.on").count() == 1
    # ステップ1：同じ注意を出し、ボタンは出さない
    page.click('[data-school="S3"]')
    page.click("#start"); page.wait_for_selector(".now-card")
    assert plain(".now-card .note.closure") == NOTE_GONE_NOW, plain(".now-card .note.closure")
    assert page.locator(".now-card [data-pick], .now-card .pick-now").count() == 0
    bare("step1-gone-now")
    for w in (390, 820):
        page.set_viewport_size({"width": w, "height": 820}); page.wait_for_timeout(300)
        if not page.evaluate(NO_HSCROLL):
            problems.append(f"{w}px 幅で ステップ1の 閉校の注意が 横に はみ出す")
    page.set_viewport_size({"width": 1180, "height": 820}); page.wait_for_timeout(300)
    shot("1-gimon-closure")
    page.evaluate("UG.go('home')"); page.wait_for_selector(".school-btn")
    page.evaluate(MARKS_OFF)
    assert page.locator(".gone-tg, .new-school, .note.closure, .pick-now").count() == 0
    page.evaluate("UG.state.schoolId = null; UG.render()")
    assert page.evaluate(OLD_HOME) == [True, True], "印を消しても 一覧・注意が 元に もどらない"
    if sel:
        page.click(f'[data-school="{sel}"]')


CMP_TAGS = """() => [...document.querySelectorAll('#cmp-list li')].map(li => { const c = li.cloneNode(true);
  c.querySelectorAll('rt').forEach(r => r.remove());
  return [c.querySelector('.nm').textContent, [...c.querySelectorAll('.tg')].map(t => t.textContent)]; })"""
CMP_HTML = "() => document.getElementById('cmp-list').innerHTML"
CMP_HTML_NO_GONE = """() => { const c = document.getElementById('cmp-list').cloneNode(true);
  c.querySelectorAll('.gone-tg').forEach(t => t.remove()); return c.innerHTML; }"""


def cmp_closures(page, shot, bare, problems):
    """ステップ4の比較の一覧：gone の学校に ホームと同じ札。s.tag もあれば両方。印の無い学校は 今と同じ"""
    before = page.evaluate(CMP_HTML)
    assert "gone-tg" not in before and page.locator("#cmp-list .gone-tg").count() == 0
    page.evaluate("""() => { const c = UG.prefs['00'].cities[0];
      c.schools.forEach(s => { if (s.id === 'S3' || s.id === 'S5') s.gone = true; }); UG.render(); }""")
    page.wait_for_selector("#cmp-list li")
    tags = dict(page.evaluate(CMP_TAGS))
    gone_tag = page.evaluate("UG.GONE_TAG")
    assert gone_tag == "いまは この 名前では ないよ"
    for nm in ("中央小学校", "山の上小学校"):
        assert tags[nm][-1] == gone_tag and len(tags[nm]) == 2, (nm, tags[nm])  # s.tag と 両方
    for nm in ("みなと小学校", "さくら台小学校", "川ぞえ小学校", "ひがし小学校"):
        assert gone_tag not in tags[nm], (nm, tags[nm])
    # 札を 除けば 印を 付ける 前と 1文字も 同じ（並び・数字・ほかの 札は 変えない）
    assert page.evaluate(CMP_HTML_NO_GONE) == before, "比較の一覧が 札の ほかにも 変わった"
    bare("step4-gone")
    for w in (390, 820):
        page.set_viewport_size({"width": w, "height": 820}); page.wait_for_timeout(400)
        if not page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"):
            problems.append(f"{w}px 幅で ステップ4の 比較の一覧が 横に はみ出す")
        page.locator("#cmp-list").scroll_into_view_if_needed()
        shot(f"4-naze-cmp-gone-{w}", full=False)
    page.set_viewport_size({"width": 1180, "height": 820}); page.wait_for_timeout(400)
    page.evaluate("""() => { UG.prefs['00'].cities[0].schools.forEach(s => { delete s.gone; }); UG.render(); }""")
    page.wait_for_selector("#cmp-list li")
    assert page.evaluate(CMP_HTML) == before, "印を 消しても 比較の一覧が 元に もどらない"


def main() -> int:
    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**LAUNCH)
        page = browser.new_page(viewport={"width": 1180, "height": 820})
        external = []  # 自分以外の http/https の宛先への通信（file:// で開くので、http/https はすべて外部）
        watch_requests(page.context, None, external)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "ERR_" not in m.text else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        def shot(name, full=True):
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)

        LINE_DONE = "Object.keys(UG.state.draw).length === UG.model.DRAW_YEARS.length"

        def draw_line(fy0, fy1, right_margin, steps):
            """グラフをなぞり、全部の年に値が入る（線が描けた）ことを条件に待つ。
            幅を変えた直後は、アプリが 200ms 遅れて画面を描き直す（main.js の resize）。それがなぞっている途中に
            重なると、線は最初の1点だけになる（20回に1回ほど落ちた原因）。そのときは新しいグラフにもう一度なぞる。"""
            for _ in range(3):
                box = page.locator("svg.chart .pad").bounding_box()
                x0, x1 = box["x"] + 6, box["x"] + box["width"] - right_margin
                y0, y1 = box["y"] + box["height"] * fy0, box["y"] + box["height"] * fy1
                page.mouse.move(x0, y0); page.mouse.down()
                for i in range(1, steps + 1):
                    t = i / steps
                    page.mouse.move(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
                page.mouse.up()
                try:
                    page.wait_for_function(LINE_DONE, timeout=2000)
                    return
                except Exception:
                    continue
            raise AssertionError("3回なぞっても線が描けない: " + json.dumps(page.evaluate("UG.state.draw")))

        def plain(sel):
            """sel の 文字（ふりがなを 除く）"""
            return page.evaluate("""s => { const e = document.querySelector(s); if (!e) return null; const c = e.cloneNode(true);
              c.querySelectorAll('rt').forEach(r => r.remove()); return c.textContent; }""", sel)

        def bare(step):
            for chars, ctx in page.evaluate(FIND_BARE_KANJI):
                rest = "".join(c for c in chars if c not in ALLOW)
                if rest:
                    problems.append(f"[{step}] ふりがななし: {rest} … {ctx}")

        page.goto(URL)
        page.wait_for_selector(".school-btn")
        problems += check_fonts(page, "file://")

        # ことばの途中で改行しない：ルビを含む語は <span class="w">（nowrap）で包む。空白は語の外、句読点は語の中
        wrap = page.evaluate("""() => [
          UG.ruby('計算を それに 合わせるよ。'), UG.ruby('おうちの 人に 聞く'), UG.ruby('学校'), UG.ruby('「データの 力」を')]""")
        assert '<span class="w">' in wrap[0] and wrap[0].count('<span class="w">') == 2, wrap[0]
        assert wrap[0].endswith("</span><wbr>"), wrap[0]                       # 「合わせるよ。」の後は改行してよい
        assert 'の <span class="w">' in wrap[1] or "の <ruby" in wrap[1], wrap[1]  # 「 人」の空白は語の外
        assert '<span class="w">' not in wrap[2], wrap[2]                        # ルビ1つだけの語は包まない
        assert '<span class="w"><ruby data-g="1">力<rt>ちから</rt></ruby>」を</span>' in wrap[3], wrap[3]  # 閉じかっこの後の「を」も同じ語
        # 句読点の後は、空白が無くても改行してよい（<wbr>）。ふりがなの無い文でも。WebKit は keep-all のとき
        # 「なるだろう。つまみを」の「。」の後で改行せず、前の行の右が大きく空いた（iPhone で見つかった）
        brk = page.evaluate("""() => [UG.ruby('どう なるだろう。つまみを うごかして'), UG.ruby('かわると、クラスは'),
          UG.ruby('「なぜ？」を さがす'), UG.ruby('おわり。'), UG.ruby('いいよ。 つぎ'), UG.ruby('ほんとう？！ うん')]""")
        assert "なるだろう。<wbr>つまみを" in brk[0], brk[0]          # 句点の後
        assert "かわると、<wbr>クラスは" in brk[1], brk[1]            # 読点の後
        assert "<wbr>" not in brk[2], brk[2]                        # 閉じかっこの前（「を」の前でも）は折らない
        assert "<wbr>" not in brk[3] and "<wbr>" not in brk[4], brk[3:5]  # 文の終わり・空白の前には足さない
        assert "<wbr>" not in brk[5], brk[5]                        # 「？！」の間では折らない
        assert page.evaluate("UG.ruby('計算を それに 合わせるよ。つぎ')").count("<wbr>") == 1  # ルビの語の後でも1つだけ
        shot("0-home-empty")
        bare("home")

        # 学校を さがす（ひらがなでも）。サンプルには読み（kana）が無いので、ここで一時的に付ける。読みは画面に出さない
        NO_RT = "sel => { const e = document.querySelector(sel).cloneNode(true); e.querySelectorAll('rt').forEach(r => r.remove()); return e.textContent; }"
        label = page.evaluate(f"({NO_RT})('label[for=q-school]')")
        assert label == "学校の 名前で さがす", label  # 長いラベルは PC幅で左の列を広げ、選択欄を細くするので短く
        assert page.get_attribute("#q-school", "placeholder") == "ひらがなでも いいよ"
        # 選択欄の文字が切れていない（タブレット〜PC幅）：選んでいる項目の文字＋矢印のぶんが箱に収まる。
        # 以前の長いラベル「…（ひらがなでも いいよ）」は 900px 幅で 29px はみ出していた
        for width in (600, 768, 900, 1024, 1180):
            page.set_viewport_size({"width": width, "height": 820})
            for sel in ("#sel-pref", "#sel-city"):
                cut = page.evaluate(f"""() => {{ const s = document.querySelector('{sel}'); const c = document.createElement('canvas').getContext('2d');
                  c.font = getComputedStyle(s).font;
                  return c.measureText(s.options[s.selectedIndex].text).width + 40 - s.clientWidth; }}""")
                if cut > 0:
                    problems.append(f"{width}px 幅で {sel} の文字が切れる（{cut:.0f}px）")
        page.set_viewport_size({"width": 1180, "height": 820})
        page.evaluate("""() => UG.prefs['00'].cities[0].schools.forEach(s => {
          if (s.id === 'S3') s.kana = ['ちゅうおうしょうがっこう'];
          if (s.id === 'S5') s.kana = ['やまのうえしょうがっこう']; })""")

        def found(q):
            page.fill("#q-school", q)
            return [t.strip() for t in page.locator("#school-list .school-btn .nm").all_inner_texts()]
        assert found("ちゅうおう") == ["中央小学校"], found("ちゅうおう")
        assert found("ﾔﾏﾉ") == ["山の上小学校"], found("ﾔﾏﾉ")          # 半角カナ → 平仮名。読みの途中からでも出る
        assert found("みなと") == ["みなと小学校"], found("みなと")      # 名前の かな
        assert found("山の") == ["山の上小学校"], found("山の")
        assert "しょうがっこう" not in page.inner_text("#school-list"), "読みが画面に出ている"
        found("ちゅうおう")
        shot("0-home-search-kana")
        bare("home-search")
        assert found("ぞぞぞ") == []
        msg = page.evaluate(f"({NO_RT})('#school-list .empty')")
        assert msg == "見つからなかったよ。もう 少し みじかく 入れるか、けして 一覧から えらんでね。", msg
        shot("0-home-search-none")
        bare("home-search-none")
        found("")
        page.evaluate("() => UG.prefs['00'].cities[0].schools.forEach(s => { delete s.kana; })")
        page.click('[data-school="S2"]')
        page.click('[data-grade="e5"]')
        assert "35さい" in page.inner_text("#age-out"), page.inner_text("#age-out")
        shot("0-home")

        # 学区データの利用条件が「条件公開」の市区町村（city.note）の注意。サンプルにはないので一時的に付ける
        def with_note(step):
            page.evaluate("Object.values(UG.prefs).forEach(p => p.cities.forEach(c => c.note = true)); UG.render()")
            assert "教育委員会" in page.inner_text("#view"), f"[{step}] note の注意が出ない"
            bare(step + "-note")
            page.evaluate("Object.values(UG.prefs).forEach(p => p.cities.forEach(c => delete c.note)); UG.render()")
            assert "教育委員会" not in page.inner_text("#view"), f"[{step}] note が無いのに注意が出る"
        with_note("home")

        # 学区データのある市区町村で、学区データに入っていないので補った学校（学校だけが approx）の注意（ホーム・ステップ1）と、
        # ステップ3の「この 数字は どこから 来たの？」の文。
        # サンプルにはないので、選んだ学校に一時的に付ける。まち全体の注意（APPROX_NOTE）は出ないこと
        SCHOOL_APPROX = ("Object.values(UG.prefs).forEach(p => p.cities.forEach(c => c.schools.forEach(s => {"
                         " if (s.id === UG.state.schoolId) { if (%s) s.approx = true; else delete s.approx; } }))); UG.render()")
        def with_school_approx(step):
            page.evaluate(SCHOOL_APPROX % "true")
            plain = page.evaluate("""() => { const v = document.getElementById('view').cloneNode(true);
                v.querySelectorAll('rt').forEach(r => r.remove()); return v.textContent; }""")
            if step != "step3":  # 注意はホームとステップ1に出す
                assert "地図データに 入って いません" in plain, f"[{step}] 補った学校の注意が出ない"
            if step == "home":  # 印の無い学校では、注意の HTML は閉校の印を足す前と同じ
                assert page.evaluate(OLD_HOME) == [True, True], "[home] 補った学校の注意が変わった"
            assert "この まちは 学区の 地図データが ない" not in plain, f"[{step}] まち全体の注意が出ている"
            if step == "step3":  # 「この 数字は どこから 来たの？」の箱はステップ3にある
                assert "この 学校に 近い ますめを たしている" in plain, f"[{step}] 「どこから 来たの？」の文が出ない"
            bare(step + "-school-approx")
            page.evaluate(SCHOOL_APPROX % "false")
            plain = page.evaluate("""() => { const v = document.getElementById('view').cloneNode(true);
                v.querySelectorAll('rt').forEach(r => r.remove()); return v.textContent; }""")
            assert "地図データに 入って いません" not in plain and "この 学校に 近い ますめ" not in plain, \
                f"[{step}] approx が無いのに注意が出る"
        with_school_approx("home")
        closures(page, shot, bare, plain, problems)
        page.click('[data-school="S2"]')
        page.click("#start")

        page.wait_for_selector(".now-card")
        with_note("step1")
        with_school_approx("step1")

        # 実際の人数を入れる欄：おおよその区域の学校（まちが approx、または学校が approx）では、しらべて入れることをすすめる文。
        # 学区データのある学校では「知っていたら 入れてね」。入力欄の薄い字（placeholder）は出さない
        LABEL = "() => { const l = document.querySelector('label[for=calib]').cloneNode(true); l.querySelectorAll('rt').forEach(r => r.remove()); return l.textContent; }"
        def calib_label(step, expr_on, expr_off):
            page.evaluate(expr_on + "; UG.render()")
            t = page.evaluate(LABEL)
            assert "先生に 聞いたり しらべたり して、入れて みよう" in t and "知っていたら" not in t, f"[{step}] おおよその区域の文にならない: {t}"
            assert not page.get_attribute("#calib", "placeholder")  # 薄い字は出さない
            plain = page.evaluate("() => { const v = document.getElementById('view').cloneNode(true); v.querySelectorAll('rt').forEach(r => r.remove()); return v.textContent; }")
            assert "人数が かなり ちがう ことも あります。" in plain, f"[{step}] 注意の最後の1文が無い"
            bare(step)
            page.evaluate(expr_off + "; UG.render()")
            t = page.evaluate(LABEL)
            assert "知っていたら 入れてね" in t and "先生に" not in t, f"[{step}] 学区データのある学校の文にならない: {t}"
            assert not page.get_attribute("#calib", "placeholder")  # 薄い字は出さない
        # 練習用の「みらい市」では入力欄を出さないので、この確認の間だけ実データの扱いにする
        page.evaluate("UG.prefs['00'].sample = false; UG.render()")
        assert "知っていたら 入れてね" in page.evaluate(LABEL)
        calib_label("step1-calib-city-approx",
                    "Object.values(UG.prefs).forEach(p => p.cities.forEach(c => c.approx = true))",
                    "Object.values(UG.prefs).forEach(p => p.cities.forEach(c => delete c.approx))")
        calib_label("step1-calib-school-approx",
                    "Object.values(UG.prefs).forEach(p => p.cities.forEach(c => c.schools.forEach(s => { if (s.id === UG.state.schoolId) s.approx = true; })))",
                    "Object.values(UG.prefs).forEach(p => p.cities.forEach(c => c.schools.forEach(s => delete s.approx)))")
        page.evaluate("UG.prefs['00'].sample = true; UG.render()")
        assert page.locator("#calib").count() == 0
        assert page.is_disabled("#next-btn")
        page.click('[data-guess="down"]')
        page.fill("#reason", "空き家がふえているから")
        shot("1-gimon"); bare("step1")
        page.click("#next-btn")

        page.wait_for_selector("svg.chart .pad")
        assert page.is_disabled("#next-btn")
        shot("2-yosou-before", full=False)

        # 「いま ○人」と「ここから 右へ なぞってね →」の文字の枠が重ならない（広い画面とスマホ幅、いまの人数が少ない・多い）
        NO_OVERLAP = """() => { const a = document.querySelector('svg.chart .lab-now').getBoundingClientRect();
          const h = document.querySelector('svg.chart .hint').getBoundingClientRect();
          return [a.right <= h.left || h.right <= a.left || a.bottom <= h.top || h.bottom <= a.top,
                  document.querySelector('svg.chart .lab-now').textContent]; }"""
        def labels_apart(where):
            ok, lab = page.evaluate(NO_OVERLAP)
            assert ok, f"[step2 {where}] 「{lab}」と案内の文が重なる"
        # 「かきなおす」：高さ 44px 以上。よそうの数字と同じ行の右端。幅が足りないときだけ下の行（右寄せ）。枠からはみ出さない
        REDO = """() => { const b = document.getElementById('redo').getBoundingClientRect();
          const r = document.getElementById('readout').getBoundingClientRect();
          const row = document.querySelector('.readout-row').getBoundingClientRect();
          const card = document.querySelector('.chart-card').getBoundingClientRect();
          return {h: b.height, same: b.top < r.bottom && r.top < b.bottom, below: b.top >= r.bottom - 1,
                  right: Math.abs(b.right - row.right) <= 1, inside: b.left >= card.left && b.right <= card.right && r.right <= card.right + 0.5,
                  fits: r.width + b.width + 12 <= row.width + 1, page: document.documentElement.scrollWidth <= innerWidth,
                  text: document.getElementById('readout').textContent}; }"""
        def redo_ok(where, same_row):
            r = page.evaluate(REDO)
            assert r["h"] >= 44, f"[step2 {where}] かきなおす の高さが {r['h']}px"
            assert r["right"] and r["inside"] and r["page"], f"[step2 {where}] かきなおす の位置・はみ出し {r}"
            if same_row is True:
                assert r["same"], f"[step2 {where}] かきなおす が「{r['text']}」と同じ行にない {r}"
            elif same_row is False:
                assert r["below"], f"[step2 {where}] かきなおす が下の行に回っていない {r}"
        redo_ok("1180px 線の前", True)
        labels_apart("1180px")
        est0 = page.evaluate("UG.ctx().school.est[0]")
        for w, v in ((390, None), (320, 1589), (320, 3)):
            page.set_viewport_size({"width": w, "height": 820})
            if v is not None:  # いまの人数を一時的に変える（4桁・1桁）。表示だけで、保存はしない
                page.evaluate(f"UG.ctx().school.est[0] = {v}; UG.render()")
            page.wait_for_function("!!document.querySelector('svg.chart .hint')")
            page.wait_for_timeout(300)  # main.js の resize の描き直し（200ms）を待つ
            labels_apart(f"{w}px いま{v or ''}")
            redo_ok(f"{w}px 線の前", True if w == 390 else None)
        page.evaluate(f"UG.ctx().school.est[0] = {est0}; UG.render()")
        page.set_viewport_size({"width": 1180, "height": 820})
        page.wait_for_timeout(300)
        # 「いま ○人」は、線を かいても これまでの線に 重ならない（黒い線が 左上から 来るので 点の 下に 置く）
        draw_line(0.735, 0.75, 140, 30)
        now_lab = page.evaluate("""() => ({lab: +document.querySelector('svg.chart .lab-now').getAttribute('y'),
          pt: +document.querySelector('svg.chart .p-now').getAttribute('cy')})""")
        assert now_lab["lab"] > now_lab["pt"], f"[step2] 「いま」が これまでの線に 重なる側に ある: {now_lab}"
        page.click("#redo")
        page.evaluate("scrollTo({top: 0, behavior: 'instant'})")  # 押すときに動いた分を戻す（全体のスクリーンショットの途中に見出しが写る）
        draw_line(0.62, 0.74, 140, 30)
        assert not page.is_disabled("#next-btn"), "線を描いても次へ進めない"
        drawn = page.evaluate("UG.state.draw")
        assert len(drawn) == 5, drawn
        redo_ok("1180px 線のあと", True)
        # 4桁のよそう・320px：数字の行に入りきらなければ、ボタンは下の行へ。はみ出さない
        page.set_viewport_size({"width": 320, "height": 820})
        page.evaluate("UG.state.draw[2050] = 1589; UG.render()")
        page.wait_for_timeout(300)
        redo_ok("320px 4桁", False if not page.evaluate(REDO)["fits"] else True)
        assert "1,589" in page.inner_text("#readout")
        page.evaluate(f"UG.state.draw = {json.dumps(drawn)}; UG.save(); UG.render()")
        page.set_viewport_size({"width": 1180, "height": 820})
        page.wait_for_timeout(300)
        # キーボードの案内：マウスの端末では出す。タッチの端末（pointer: coarse）では出さない
        assert page.is_visible(".kbd-hint"), "キーボードの案内が出ない"
        tctx = browser.new_context(viewport={"width": 390, "height": 820}, has_touch=True)
        watch_requests(tctx, None, external)
        tp = tctx.new_page(); tp.goto(URL); tp.wait_for_selector(".school-btn")
        tp.click('[data-school="S2"]'); tp.click('[data-grade="e5"]'); tp.click("#start")
        tp.click('[data-guess="down"]'); tp.click("#next-btn"); tp.wait_for_selector("svg.chart .pad")
        assert tp.evaluate("matchMedia('(pointer: coarse)').matches")
        assert tp.locator(".kbd-hint").count() == 1 and not tp.is_visible(".kbd-hint"), "タッチの端末でキーボードの案内が出ている"
        assert tp.evaluate("document.querySelector('svg.chart [role=slider][tabindex=\"0\"]') !== null"), "丸をキーボードで選べない"
        tctx.close()
        shot("2-yosou"); bare("step2")

        # クラスモード（子ども）：線を かいたら「先生に よそうを わたす」→ コードと「コピー」
        assert page.is_visible("#handoff-btn") and not page.is_visible("#handoff-box")
        hb, nb = page.locator("#handoff-btn").bounding_box(), page.locator("#next-btn").bounding_box()
        assert hb["width"] * hb["height"] < nb["width"] * nb["height"], "「先生に よそうを わたす」が「データと くらべる」より大きい"
        page.click("#handoff-btn")
        handoff_code = page.input_value("#handoff-code")
        dec = page.evaluate("c => UG.model.decodeGuess(c)", handoff_code)
        assert dec["ok"] and [dec["pref"], dec["school"], dec["guess"], dec["reason"]] == ["00", "S2", "down", "空き家がふえているから"], dec
        assert dec["draw"]["2050"] == round(drawn["2050"]), (dec["draw"], drawn)
        # 端末の印（でたらめな6文字。state に入れ、名前は入れない）と、作った順の番号
        mark = page.evaluate("UG.state.classMark")
        assert len(mark) == 6 and dec["mark"] == mark and dec["seq"] >= 1 and dec["calib"] is None, dec
        assert page.input_value("#handoff-code") == handoff_code  # 中身が変わらなければ番号を進めない
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.click("#handoff-copy")
        page.wait_for_selector("#toast.show")
        assert "コピーしました" in page.inner_text("#toast"), page.inner_text("#toast")
        try:
            clip = page.evaluate("navigator.clipboard.readText()")
            assert clip == handoff_code, clip
        except Exception as e:  # file:// でクリップボードを読めない環境では、トーストだけで確かめる
            if "assert" in type(e).__name__.lower():
                raise
        shot("2-yosou-handoff"); bare("step2-handoff")
        page.click("#next-btn")

        page.wait_for_selector(".verdict")
        page.wait_for_timeout(2600)
        shot("3-shiraberu"); bare("step3")
        # スタンプの文字は丸の中に収まる（「はっけん賞」が1行で丸からはみ出していた）。3種類、広い画面とスマホ幅
        STAMP_FITS = """() => { const s = document.querySelector('.verdict .stamp'), t = s.firstElementChild;
          return {ratio: t.offsetWidth / s.clientWidth, lines: s.querySelectorAll('br').length, text: t.textContent}; }"""
        draw_s3 = page.evaluate("UG.state.draw")
        est50_s3 = page.evaluate("UG.ctx().v50")
        for w in (1180, 390):
            page.set_viewport_size({"width": w, "height": 820}); page.wait_for_timeout(300)
            for v in (est50_s3, est50_s3 * 1.2, est50_s3 * 2):
                page.evaluate("v => { UG.model.DRAW_YEARS.forEach(y => { UG.state.draw[y] = v; }); UG.render(); }", v)
                page.wait_for_selector(".verdict .stamp")
                r = page.evaluate(STAMP_FITS)
                assert r["lines"] == 1 and r["ratio"] <= 0.86, f"[step3 {w}px] スタンプの文字が丸からはみ出す: {r}"
        page.set_viewport_size({"width": 1180, "height": 820}); page.wait_for_timeout(300)
        page.evaluate("d => { UG.state.draw = d; UG.save(); UG.render(); }", draw_s3)
        page.wait_for_selector(".verdict")
        # ステップ3の「人数が かわると、…どう なるだろう。つまみを …」は、句読点の後で改行できる
        assert "なるだろう。<wbr>" in page.inner_html("#view"), "ステップ3の文の句点の後に <wbr> がない"
        # 箱の「数字＋単位」（1,589人・やく 265人・48クラス）は1行で、箱からはみ出さない（4桁・320px）。3つの数字は同じ大きさ
        est_s3 = page.evaluate("UG.ctx().school.est.slice()")
        page.set_viewport_size({"width": 320, "height": 820})
        page.evaluate("UG.ctx().school.est.forEach(function (v, i, a) { a[i] = 1589 - i * 30; }); UG.render()")
        page.wait_for_timeout(400)
        tiles = page.evaluate("""() => [...document.querySelectorAll('#tiles .fit')].map(f => {
          const n = f.querySelector('.nw') && f.querySelector('.pre') ? f.querySelector('.nw') : f, rs = [...n.getClientRects()];
          const t = f.parentElement.getBoundingClientRect(), b = f.querySelector('b');
          // 行の数：要素自身の箱の数と、文字の箱の top を「数字の高さの半分」以上の差で分けた数の、大きいほう。
          // 数字（b）と単位（人）は字の大きさが違い下端が数px ずれるので、下端を丸めて数えると書体しだいで2行と数えてしまう
          const bh = b.getBoundingClientRect().height, r = document.createRange(); r.selectNodeContents(n);
          const tops = [...r.getClientRects()].filter(x => x.width > 1).map(x => x.top).sort((x, y) => x - y);
          let rows = 0, cur = -Infinity; tops.forEach(y => { if (y - cur >= bh / 2) { rows++; cur = y; } });
          return {text: n.textContent, lines: Math.max(rs.length, rows), boxes: rs.length, rows, inside: f.getBoundingClientRect().right <= t.right - 2, size: getComputedStyle(b).fontSize}; })""")
        assert any("1," in t["text"] for t in tiles), tiles
        for t in tiles:
            assert t["lines"] == 1 and t["inside"], f"[step3 320px] 箱の数字が折れる・はみ出す: {t}"
        assert len({t["size"] for t in tiles}) == 1, f"[step3 320px] 箱の数字の大きさがそろっていない: {tiles}"
        page.evaluate(f"UG.ctx().school.est.splice(0, 10, ...{json.dumps(est_s3)}); UG.render()")
        page.set_viewport_size({"width": 1180, "height": 820})
        page.wait_for_timeout(400)
        with_school_approx("step3")
        page.fill("#hist-y", "1990"); page.fill("#hist-v", "960"); page.click("#hist-form button")
        page.locator("#year-range").fill("9")
        page.locator("#year-range").dispatch_event("input")
        assert "2070年" in page.inner_text("#year-out")
        page.click("#wide")
        box = page.locator("svg.chart .hoverpad").first.bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.5)
        shot("3-shiraberu-2070"); bare("step3b")
        page.click("#next-btn")

        page.wait_for_selector("#ages .bars")
        for _ in range(7):
            page.click("#age-next")
        page.locator("#sim-move").fill("8"); page.locator("#sim-move").dispatch_event("input")
        page.locator("#sim-birth").fill("20"); page.locator("#sim-birth").dispatch_event("input")
        page.click('.opt[data-q="q1"][data-o="1"]')
        page.click('.opt[data-q="q2"][data-o="1"]')
        page.click('.opt[data-q="q3"][data-o="1"]')
        shot("4-naze"); bare("step4")
        cmp_closures(page, shot, bare, problems)
        page.click("#next-btn")

        page.wait_for_selector("#card svg")
        # 事例帳（cases.js）：7件、id が 重ならない、ideas は UG.IDEAS に ある、出典は https
        cases = page.evaluate("""() => ({ ids: UG.CASES.map(k => k.id), ideas: UG.IDEAS.map(k => k.id),
          bad: UG.CASES.filter(k => !k.ideas.length || k.ideas.some(i => !UG.IDEAS.some(x => x.id === i))).map(k => k.id),
          urls: [].concat(...UG.CASES.map(k => k.src.map(s => s.url))) })""")
        assert len(cases["ids"]) == 7 and len(set(cases["ids"])) == 7, cases["ids"]
        assert not cases["bad"], f"UG.IDEAS に 無い ideas: {cases['bad']}"
        assert cases["urls"] and all(u.startswith("https://") for u in cases["urls"]), cases["urls"]
        # 最初は 閉じている。開いて room_kids を えらぶと kyohoku が 先頭（near）、details は 開いた まま。外すと もとの 順
        order = lambda: page.evaluate("[...document.querySelectorAll('#case-list li')].map(l => l.getAttribute('data-case'))")
        assert page.evaluate("UG.state.ideas") == [] and not page.evaluate("document.getElementById('cases').open"), "事例帳が 最初から 開いている"
        # summary の 文字は 分かち書きの 空白が 残る（描画どおりの innerText を、ふりがなを 消して 読む。flex だと 語ごとに 切れて 空白が 落ちる）
        sum_t = page.evaluate("""() => { document.body.classList.add('no-ruby'); const t = document.querySelector('#cases summary').innerText;
          document.body.classList.remove('no-ruby'); return t; }""")
        assert sum_t == f"全国の 使い方の 例を 見る（{len(cases['ids'])}つ）", repr(sum_t)
        assert order() == cases["ids"], order()
        page.click("#cases summary")
        assert page.evaluate("document.getElementById('cases').open")
        page.click('[data-idea="room_kids"]')
        assert order()[0] == "kyohoku" and "near" in page.get_attribute('#case-list li[data-case="kyohoku"]', "class"), order()
        assert page.locator('#case-list li[data-case="kyohoku"] .tag.near').count() == 1
        assert page.evaluate("document.getElementById('cases').open"), "アイデアを えらぶと 事例帳が 閉じた"
        near_ids = page.evaluate("[...document.querySelectorAll('#case-list li.near')].map(l => l.getAttribute('data-case'))")
        assert near_ids == [k for k in cases["ids"] if k in ("kyohoku",)], near_ids  # room_kids に 近いのは kyohoku だけ
        page.click('[data-idea="room_kids"]')
        assert order() == cases["ids"] and page.locator("#case-list li.near").count() == 0, order()
        assert page.locator("#cases a").count() == 0, "子どもの 画面の 事例帳に リンクが ある"
        now_ids = page.evaluate("UG.CASES.filter(k => k.kind === 'now').map(k => k.id)")
        now_tags = page.evaluate("""() => [...document.querySelectorAll('#case-list li')].filter(l => l.querySelector('.tag').textContent.startsWith('いまも')).map(l => l.getAttribute('data-case'))""")
        assert now_ids == ["kobe"] and sorted(now_tags) == sorted(now_ids), (now_ids, now_tags)
        bare("step5-cases")
        page.locator("#cases").screenshot(path=str(OUT / "5-cases.png"))
        page.click('[data-sort="c1"][data-v="good"]'); page.click('[data-sort="c2"][data-v="bad"]')
        page.click('[data-idea="room_town"]'); page.click('[data-idea="online"]')
        page.fill("#own-idea", "校庭で月に1回、朝市をひらく")
        page.fill("#proposal", "空いた教室を図書室にして、地域の人も入れるようにしてほしいです。子どもとお年よりがいっしょに本を読める場所にしたいです。")
        page.fill("#nick", "そら")
        shot("5-teian"); bare("step5")
        page.locator("#card").screenshot(path=str(OUT / "5-card.png"))
        png_ok = page.evaluate("UG.cardPNG(UG.cardSVG(UG.cardData())).then(b => b.size)")
        assert png_ok > 20000, png_ok
        text = page.evaluate("UG.cardText(UG.cardData())")
        (OUT / "card.txt").write_text(text, encoding="utf-8")

        # 画面を行き来しても、ボタンが二重に反応しないこと（古いハンドラが残っていないこと）
        page.evaluate("UG.go('step4')"); page.evaluate("UG.go('step5')")
        page.click('[data-idea="bus"]')
        assert page.evaluate("UG.state.ideas") == ["room_town", "online", "bus"], page.evaluate("UG.state.ideas")
        page.click('[data-idea="bus"]')
        assert page.evaluate("UG.state.ideas") == ["room_town", "online"]

        # 提案を書く → 再読みこみ → ステップ5に戻る：箱の中身が書いたとおりで「<」を含まない。提案カード（画面・印刷）と文も同じ。
        # 以前は UG.ruby が <textarea> の中身にもふりがなを付け、箱に <span class="w"><ruby …> が出ていた
        PROP = "空いた 教室を 使う。みんなで 本を 読む、地域の 人も 来る"
        page.fill("#proposal", PROP)
        page.fill("#own-idea", "校庭で {朝|あさ}市")   # {漢字|よみ} の形を書いても、入力欄の文は変わらない
        def step5_texts():
            return page.evaluate("""() => ({box: document.getElementById('proposal').value, idea: document.getElementById('own-idea').value,
              card: document.querySelector('#card svg').textContent, data: UG.cardData().proposal, text: UG.cardText(UG.cardData())})""")
        def check_step5(where):
            t = step5_texts()
            assert t["box"] == PROP, f"[{where}] 提案の箱の中身が変わった: {t['box']!r}"
            assert t["idea"] == "校庭で {朝|あさ}市", f"[{where}] アイデアの入力欄の中身が変わった: {t['idea']!r}"
            assert t["data"] == PROP and PROP in t["text"], f"[{where}] 提案カードの文が変わった: {t['data']!r}"
            card = t["card"].replace(" ", "")
            for part in ("空いた", "教室を", "使う"):
                assert part in card, f"[{where}] 提案カード（画面・印刷）に「{part}」が無い"
            for v in (t["box"], t["data"], t["text"], t["card"]):
                assert "<" not in v and "\u0003" not in v, f"[{where}] タグかよけ印が混ざった: {v!r}"
        check_step5("書いた直後")
        page.reload(); page.wait_for_selector("#view")
        page.evaluate("UG.go('step5')"); page.wait_for_selector("#card svg")
        check_step5("再読みこみ後")
        page.click("#proposal"); page.keyboard.press("ControlOrMeta+End"); page.keyboard.press("Backspace"); page.keyboard.type("る")
        assert page.evaluate("UG.state.proposal") == PROP, page.evaluate("UG.state.proposal")  # 消して打ち直しても文のまま
        # 以前のふぐあいで、タグごと保存されてしまった提案は、読みこむときにもとの文にもどす
        page.evaluate("""() => { const k = 'ug2050:v1', v = JSON.parse(localStorage.getItem(k));
          v.proposal = '<span class="w"><ruby data-g="1">空<rt>あ</rt></ruby>いた</span> <span class="w"><ruby data-g="2">教室<rt>きょうしつ</rt></ruy>を</span> '
            + '<span class="w"><ruby data-g="3">使<rt>つか</rt></ruby>う。</span><wbr>みんなで 本を 読む、<wbr>地域の 人も 来る';
          v.ownIdea = '校庭で \u0003r1\u0004市'; localStorage.setItem(k, JSON.stringify(v)); }""")
        page.reload(); page.wait_for_selector("#view"); page.evaluate("UG.go('step5')"); page.wait_for_selector("#card svg")
        assert page.input_value("#proposal") == PROP, page.input_value("#proposal")
        assert page.input_value("#own-idea") == "校庭で 市", page.input_value("#own-idea")
        page.fill("#own-idea", "校庭で月に1回、朝市をひらく")
        page.fill("#proposal", "空いた教室を図書室にして、地域の人も入れるようにしてほしいです。子どもとお年よりがいっしょに本を読める場所にしたいです。")

        # ステップ5の 8枚の カードは model の SORT_IDS と 同じ順・同じ id（コードに 入れる 並び）
        assert page.evaluate("UG.SORT_CARDS.map(k => k.id)") == page.evaluate("UG.model.SORT_IDS")
        assert page.evaluate("(() => { const c = document.querySelector('[data-to=mayor]').cloneNode(true); c.querySelectorAll('rt').forEach(r => r.remove()); return c.textContent.replace(/\\s/g, ''); })()") == "みらい市長さん"
        # クラスモード 第2段階（子ども）：提案を 書いたら「先生に 提案を わたす」→ 提案つきの コード（名前・学年は 入らない）
        assert page.is_visible("#handoff-btn") and not page.is_visible("#handoff-box")
        page.click("#handoff-btn")
        code5 = page.input_value("#handoff-code")
        d5 = page.evaluate("c => UG.model.decodeGuess(c)", code5)
        assert d5["ok"] and d5["prop"], d5
        assert d5["prop"]["ideas"] == ["room_town", "online"] and d5["prop"]["to"] == "mayor", d5["prop"]
        assert d5["prop"]["sort"] == {"c1": "good", "c2": "bad"} and d5["prop"]["ownIdea"] == "校庭で月に1回、朝市をひらく", d5["prop"]
        assert d5["mark"] == mark and d5["seq"] > dec["seq"], (d5["mark"], d5["seq"], dec["seq"])
        assert "そら" not in json.dumps(d5, ensure_ascii=False) and "e5" not in json.dumps(d5)
        note5 = page.evaluate("(() => { const e = document.querySelector('#handoff-box .fine').cloneNode(true); e.querySelectorAll('rt').forEach(r => r.remove()); return e.textContent; })()")
        assert "名前は 入って いないよ。書いた 文は 先生が 読むよ。" in note5, note5
        hb5, sv5 = page.locator("#handoff-btn").bounding_box(), page.locator("#save-png").bounding_box()
        assert hb5["width"] * hb5["height"] < sv5["width"] * sv5["height"], "「先生に 提案を わたす」が 目立ちすぎる"
        page.locator(".out-card").screenshot(path=str(OUT / "5-teian-handoff.png"))
        bare("step5-handoff")
        # もっと 知りたい データ：3つまで（4つ目は えらばず toast）。コードに 入り、提案カード（画像・文）には 入らない
        assert d5["prop"]["wishes"] == [] and d5["prop"]["ownWish"] == "", d5["prop"]
        assert page.locator("#wishes [data-wish]").count() == 6
        assert page.evaluate("document.querySelector('#proposal').compareDocumentPosition(document.querySelector('#wishes')) & 4"), "もっと 知りたい データが 提案の 箱の 前に ある"
        assert page.evaluate("document.querySelector('#wishes').compareDocumentPosition(document.querySelector('#nick')) & 4"), "もっと 知りたい データが ニックネームの 後に ある"
        for w in ("akiya", "move", "baby"):
            page.click(f'[data-wish="{w}"]')
        page.click('[data-wish="past"]')
        assert page.evaluate("UG.state.wishes") == ["akiya", "move", "baby"], page.evaluate("UG.state.wishes")
        assert page.get_attribute('[data-wish="past"]', "aria-pressed") == "false" and page.get_attribute('[data-wish="baby"]', "aria-pressed") == "true"
        assert "えらべるのは 3つまで。どれかを はずしてね" in plain("#toast"), plain("#toast")
        page.fill("#own-wish", "通学路の 歩道の 広さ")
        assert page.get_attribute("#own-wish", "maxlength") == "30"
        d5w = page.evaluate("c => UG.model.decodeGuess(c)", page.input_value("#handoff-code"))
        assert d5w["prop"]["wishes"] == ["akiya", "move", "baby"] and d5w["prop"]["ownWish"] == "通学路の 歩道の 広さ", d5w["prop"]
        card_all = page.evaluate("document.querySelector('#card svg').textContent + UG.cardText(UG.cardData())").replace(" ", "")
        for t in ("空き家の数", "赤ちゃんの数", "通学路の歩道の広さ"):
            assert t not in card_all, f"提案カードに「もっと 知りたい データ」が 入った: {t}"
        bare("step5-wishes")
        page.locator(".write-card").screenshot(path=str(OUT / "5-wishes.png"))
        # 提案を 消して アイデアも 外すと かくれる。もっと 知りたい データ だけでも 出る
        page.evaluate("UG.state.proposal = ''; UG.state.ownIdea = ''; UG.state.ideas = []; UG.state.wishes = []; UG.state.ownWish = ''; UG.render()")
        assert not page.is_visible("#handoff-btn"), "提案が 無いのに「先生に 提案を わたす」が出ている"
        page.click('[data-wish="past"]')
        assert page.is_visible("#handoff-btn"), "もっと 知りたい データを えらんでも「先生に 提案を わたす」が出ない"
        page.click('[data-wish="past"]')
        assert not page.is_visible("#handoff-btn")
        page.fill("#own-wish", "まちの 公園の 数")
        assert page.is_visible("#handoff-btn"), "ほかに 知りたい データを 書いても「先生に 提案を わたす」が出ない"
        page.evaluate("UG.state.ideas = ['room_town', 'online']; UG.state.wishes = ['akiya', 'move', 'baby']; UG.state.ownWish = '通学路の 歩道の 広さ'; UG.render()")
        page.fill("#own-idea", "校庭で月に1回、朝市をひらく")
        page.fill("#proposal", "空いた教室を図書室にして、地域の人も入れるようにしてほしいです。子どもとお年よりがいっしょに本を読める場所にしたいです。")

        state5 = page.evaluate("JSON.stringify(UG.state)")  # タッチの 端末の 確かめに 使う（線を かき おえた 状態）
        page.click('[data-go="teachers"]')
        page.wait_for_selector(".teachers")
        shot("9-teachers")
        # 事例帳の 出典：例ごとに 1行（7つ）、リンクは 16個。すべて https・新しい タブ。{ が 残らない
        src_cases = page.evaluate("""() => { const u = document.getElementById('src-cases'); return { li: u.querySelectorAll(':scope > li').length,
          a: [...u.querySelectorAll('a')].map(a => [a.href, a.target, a.rel]), text: u.textContent }; }""")
        assert src_cases["li"] == 7 and len(src_cases["a"]) == 16, (src_cases["li"], len(src_cases["a"]))
        assert all(h.startswith("https://") and t == "_blank" and "noopener" in r for h, t, r in src_cases["a"]), src_cases["a"]
        assert "{" not in src_cases["text"] and "|" not in src_cases["text"], src_cases["text"]
        # 町字データ（学校名の読み）の出典は、読みを付けた県（data/index.js の kana: true）があるときだけ出す。
        # app/data の実物に読みがあってもなくても確かめられるよう、いったん全県の kana を外してから付け直す。
        kana_codes = page.evaluate("UG.index.filter(p => p.kana).map(p => p.code)")
        page.evaluate("UG.index.forEach(p => { delete p.kana; }); UG.render()")
        assert page.locator("#src-kana").is_hidden(), "読みが無いのに町字データの出典が出ている"
        page.evaluate("UG.index[0].kana = true; UG.render()")
        page.wait_for_selector("#src-kana", state="visible")
        assert "アドレス・ベース・レジストリ" in page.inner_text("#src-kana")
        page.locator("#src-kana").screenshot(path=str(OUT / "9-teachers-kana-credit.png"))
        page.evaluate("delete UG.index[0].kana; UG.render()")
        assert page.locator("#src-kana").is_hidden()
        page.evaluate("codes => { UG.index.forEach(p => { if (codes.includes(p.code)) p.kana = true; }); UG.render(); }", kana_codes)
        assert page.locator("#src-kana").is_hidden() == (not kana_codes), "data/index.js の kana: true と出典の出る・出ないが合わない"

        # クラスモード（先生）：先生向けページから「クラスで 見る」
        page.click('#class-howto button[data-go="class"]')
        page.wait_for_selector("#class-text")
        assert page.evaluate("location.hash") == "#class"
        bare("class-empty")
        # 3人分。鈴木さんは 同じ端末から2回（古いほうは数えない）、佐藤さんのコードは 途中で改行されている。
        # 2人は 実際の人数 280人（ステップ1）を入れている
        others = page.evaluate("""() => [
          UG.model.encodeGuess({ pref: '00', school: 'S2', guess: 'up', draw: {2030: 320, 2035: 333, 2040: 351, 2045: 372, 2050: 401}, reason: '駅の 近くに マンションが できたから', calib: 280, mark: 'suzuki', seq: 4 }),
          UG.model.encodeGuess({ pref: '00', school: 'S2', guess: 'same', draw: {2030: 300, 2035: 302, 2040: 299, 2045: 303, 2050: 305}, reason: '', calib: 280, mark: 'satou1', seq: 1 }),
          UG.model.encodeGuess({ pref: '00', school: 'S2', guess: 'down', draw: {2030: 200, 2035: 150, 2040: 120, 2045: 100, 2050: 90}, reason: 'まちがえた', mark: 'suzuki', seq: 2 })]""")
        pasted = (f"山田 花子 2026/11/20 10:31\n{handoff_code}\n\n鈴木 一郎 10:30\n{others[2]}\n鈴木 一郎 10:32\nよそうです {others[0]}\n"
                  f"{handoff_code}\n佐藤 10:35\n{others[1][:40]}\n{others[1][40:]}\nWG50-こわれた {others[1][:30]}")
        page.fill("#class-text", pasted)
        page.click("#class-load")
        page.wait_for_selector("#class-chart svg")
        cnt = page.evaluate("(() => { const e = document.querySelector('#class-count').cloneNode(true); e.querySelectorAll('rt').forEach(r => r.remove()); return e.textContent; })()")
        assert cnt.split() == ["読めた", "3人", "読めなかった", "1", "同じで", "のぞいた", "1"], cnt
        assert "同じ 端末から 来た 1件は、新しい ものだけ 数えました" in page.evaluate(
            "(() => { const e = document.querySelector('#class-replaced').cloneNode(true); e.querySelectorAll('rt').forEach(r => r.remove()); return e.textContent; })()")
        assert "まちがえた" not in page.inner_text("#view")
        # 実際の人数：コードの いちばん多い calib（280人）に 合わせる
        assert "280" in page.inner_text("#class-calib-msg") and page.input_value("#class-calib") == "280"
        assert page.locator("#class-chart .l-class").count() == 3
        assert page.locator("#class-dots .dp-dot").count() == 3
        # 「データを 見せる」の前は、推計（赤い線・数）を出さない
        assert page.locator("#view .l-est, #view .p-est, #view .dp-est, #class-vs").count() == 0, "見せる前に推計が出ている"
        est50 = page.evaluate("Math.round(UG.model.interp(UG.model.estPoints(UG.findSchool('00', null, 'S2'), 280), 2050))")
        est50_raw = page.evaluate("Math.round(UG.model.interp(UG.model.estPoints(UG.findSchool('00', null, 'S2'), null), 2050))")
        assert f"{est50}人" not in page.inner_text("#view"), "見せる前に推計の数が出ている"
        assert page.locator("#class-reasons li").count() == 2  # 理由のある2人。名前は出ない
        # 提案の 入った コードが 無ければ、「みんなの 提案」は 案内だけ
        assert page.is_visible("#class-props-none") and page.locator("#class-props .sort-bars").count() == 0
        assert "山田" not in page.inner_text("#view") and "鈴木" not in page.inner_text("#view")
        bare("class")
        shot("c-1-class")
        page.set_viewport_size({"width": 820, "height": 1180})
        page.wait_for_timeout(300)
        shot("c-1-class-820")
        over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if over > 1:
            problems.append(f"クラスで 見る（820px）で横スクロール: {over}px")
        page.set_viewport_size({"width": 1180, "height": 820})
        page.wait_for_timeout(300)
        page.click("#class-reveal")
        page.wait_for_selector("#class-vs")
        assert page.locator("#class-chart .l-est").count() == 1 and page.locator("#class-dots .dp-est").count() == 1
        vs = page.inner_text("#class-vs")
        assert f"{est50:,}" in vs, vs
        bare("class-reveal")
        shot("c-2-reveal")
        # 「合わせない」→ 推計は もとの値。先生が 値を直すと その値で
        page.click("#class-calib-off")
        assert f"{est50_raw:,}" in page.inner_text("#class-vs"), page.inner_text("#class-vs")
        assert "合わせて いません" in page.evaluate("(() => { const e = document.querySelector('#class-calib-msg').cloneNode(true); e.querySelectorAll('rt').forEach(r => r.remove()); return e.textContent; })()")
        bare("class-calib-off")
        page.fill("#class-calib", "306"); page.click("#class-calib-set")
        assert f"{est50_raw:,}" in page.inner_text("#class-vs")  # 306人＝推計の2025年と同じ → 同じ推計
        page.fill("#class-calib", "280"); page.click("#class-calib-set")
        assert f"{est50:,}" in page.inner_text("#class-vs")
        page.click("#class-hide")
        assert page.locator("#class-reasons").count() == 0, "理由を かくせない"
        page.click("#class-hide")
        assert page.locator("#class-reasons li").count() == 2
        # 学校が まじったら、学校ごとの数を出して えらぶ
        mixed = page.evaluate("UG.model.encodeGuess({ pref: '00', school: 'S3', guess: 'down', draw: {2030: 1, 2035: 2, 2040: 3, 2045: 4, 2050: 5}, reason: '' })")
        page.fill("#class-text", pasted + "\n" + mixed)
        page.click("#class-load")
        page.wait_for_selector("[data-pick]")
        picks = [t.replace("\n", " ") for t in page.locator("[data-pick]").all_inner_texts()]
        assert len(picks) == 2 and "3人" in picks[0] and "1人" in picks[1], picks
        assert page.locator("#class-chart").count() == 0
        bare("class-pick")
        shot("c-0-pick", full=False)
        page.click('[data-pick="1"]')
        page.wait_for_selector("#class-chart svg")
        assert page.locator("#class-chart .l-class").count() == 1
        # ステップ5の コード：同じ 端末の ステップ2の コードと 入れかわり、提案が出る
        page.fill("#class-text", f"山田 花子\n{handoff_code}\n山田 花子（ていあん）\n{code5}")
        page.click("#class-load")
        page.wait_for_selector("#class-props .sort-bars")
        assert page.locator("#class-replaced").count() == 1
        assert page.locator("#class-chart .l-class").count() == 1
        assert page.locator("#class-props .prop-list").count() == 0, "提案の一覧が最初から開いている"
        page.click("#class-props-open")
        assert page.locator("#class-props .prop-list li").count() == 1
        assert "空いた教室を図書室にして" in page.inner_text("#class-props .prop-list")
        assert "そら" not in page.inner_text("#view")
        # 見本の クラス（みらい市だけ）
        page.click("#class-sample")
        page.wait_for_function("document.querySelectorAll('#class-chart .l-class').length >= 25")
        n_sample = page.locator("#class-chart .l-class").count()
        assert page.locator("#class-dots .dp-dot").count() == n_sample
        assert f"読めた{n_sample}人" in page.evaluate("(() => { const e = document.querySelector('#class-count').cloneNode(true); e.querySelectorAll('rt').forEach(r => r.remove()); return e.textContent.replace(/\\s/g, ''); })()")
        bare("class-sample")
        shot("c-3-sample")
        page.set_viewport_size({"width": 820, "height": 1180})
        page.wait_for_timeout(300)
        shot("c-3-sample-820")
        page.click("#class-reveal"); page.wait_for_selector("#class-vs")
        shot("c-4-sample-reveal-820")
        page.set_viewport_size({"width": 1180, "height": 820})

        # みんなの 提案（見本の クラス）：いいね・しんぱい、アイデアの順位、じぶんの アイデア、宛先ごとの 提案（最初は 閉じている）
        assert page.locator("#class-props .sort-bars li").count() == 8
        assert page.locator("#class-props .idea-rank li").count() >= 5
        assert page.locator("#class-own li").count() >= 2  # 同じ ものは「（○人）」で まとめる
        # もっと 知りたい データ：じぶんの アイデアの 後に、候補の 順位（idea-rank と 同じ 形）と 自由な 文（同じ 文は まとめる）
        assert page.locator("#class-wishes.idea-rank li").count() >= 4
        assert page.evaluate("document.querySelector('#class-own').compareDocumentPosition(document.querySelector('#class-wishes')) & 4")
        own_wish_rows = [r.replace(" ", "") for r in page.locator("#class-own-wish li").all_inner_texts()]
        assert own_wish_rows and len(own_wish_rows) == len(set(own_wish_rows)), own_wish_rows
        assert any("まちの公園の数" in r for r in own_wish_rows), own_wish_rows
        wish_top3 = page.evaluate("""() => { const r = UG.model.extractGuesses(document.getElementById('class-text').value).items;
          return UG.model.wishTally(r, UG.WISHES.map(k => k.id)).slice(0, 3).map(x => [UG.WISHES.find(k => k.id === x.id).t, x.n]); }""")
        assert page.locator("#class-props .prop-list").count() == 0, "提案の一覧が最初から開いている"
        bare("class-props")
        page.locator("#class-props").screenshot(path=str(OUT / "c-5-props-closed.png"))
        page.click("#class-props-open")
        groups = page.locator(".to-group h4").all_inner_texts()
        assert len(groups) >= 4, groups
        mayor_n = page.locator(".to-group").first.locator("li").count()
        assert "みらい市長さんへ" in page.inner_text(".to-group h4 >> nth=0").replace("\n", ""), groups
        first_prop = page.inner_text(".to-group >> nth=0 >> li >> nth=0 >> .tx")
        mayor_texts = page.locator(".to-group >> nth=0 >> .tx").all_inner_texts()
        page.check(".to-group >> nth=0 >> [data-noprint] >> nth=0")
        assert "off" in page.get_attribute(".to-group >> nth=0 >> li >> nth=0", "class")
        bare("class-props-open")
        page.locator("#class-props").screenshot(path=str(OUT / "c-5-props-open.png"))
        page.set_viewport_size({"width": 820, "height": 1180}); page.wait_for_timeout(300)
        page.locator("#class-props").screenshot(path=str(OUT / "c-5-props-820.png"))
        page.set_viewport_size({"width": 1180, "height": 820}); page.wait_for_timeout(300)
        # 宛先ごとに 印刷する
        assert page.is_disabled("#class-sheet-make")
        page.click('[data-sheet-to="mayor"]')
        page.fill("#class-name", "5年2組")
        page.click("#class-sheet-make")
        page.wait_for_selector("#class-sheet")
        sheet = page.inner_text("#class-sheet")
        sheet_plain = page.evaluate("(() => { const e = document.querySelector('#class-sheet').cloneNode(true); e.querySelectorAll('rt').forEach(r => r.remove()); return e.textContent; })()")
        assert "みらい市長さんへ" in sheet_plain.replace(" ", ""), sheet_plain[:80]
        assert "5年2組" in sheet_plain and "さくら台小学校" in sheet_plain
        # 印刷に 入れない 1件を 除いた 人数。同じ 文は 1行に まとめて「（○人）」
        rest = mayor_texts[1:]
        rows = page.locator("#class-sheet .sh-props li").all_inner_texts()
        assert len(rows) == len(set(rest)), (rows, rest)
        tot = sum(int(_m.group(1)) if (_m := __import__("re").search(r"（(\d+)人）$", r)) else 1 for r in rows)
        assert tot == len(rest) == mayor_n - 1, (tot, len(rest), mayor_n)
        assert "出典" in sheet_plain and "わたしの学校2050" in sheet_plain
        assert page.locator("#class-sheet .sort-bars li").count() == 8 and page.locator("#class-sheet .idea-rank li").count() == 5
        assert "えらんだ人が多い5つ" in sheet_plain.replace(" ", ""), sheet_plain
        # もっと 知りたい データ：多い 3つだけ。子どもが 自由に 書いた 文は 入れない
        sw = plain("#class-sheet .sh-wishes").replace(" ", "")
        want = "もっと知りたいデータ：" + "、".join(f"{t.replace(' ', '')}（{n}人）" for t, n in wish_top3)
        assert sw == want, (sw, want)
        for t in ("まちの公園の数", "通学路の歩道の広さ"):
            assert t not in sheet_plain.replace(" ", ""), f"印刷の 1枚に 自由な 文が 入った: {t}"
        assert "5年2組" not in page.evaluate("JSON.stringify(Object.assign({}, localStorage))"), "クラスの名前が保存されている"
        bare("class-sheet")
        page.locator("#class-sheet").screenshot(path=str(OUT / "c-6-sheet.png"))
        # 印刷の メディア：印刷用の 1枚だけが 出る。A4 縦
        page.emulate_media(media="print")
        hidden = page.evaluate("""() => ['.top', '.class-in', '.class-result', '.class-reasons', '#class-print', '.sheet-actions']
          .map(s => [s, document.querySelector(s) && getComputedStyle(document.querySelector(s)).display])""")
        assert all(d in (None, "none") for _, d in hidden), hidden
        assert page.evaluate("getComputedStyle(document.querySelector('#class-sheet')).display") != "none"
        page.screenshot(path=str(OUT / "c-7-print.png"), full_page=True)
        pdf = page.pdf(prefer_css_page_size=True, print_background=True)
        (OUT / "c-7-print.pdf").write_bytes(pdf)
        import re as _re
        pages = len(_re.findall(rb"/Type\s*/Page[^s]", pdf))
        print("印刷用の 1枚：PDF", pages, "ページ")
        if pages > 1:
            problems.append(f"印刷用の 1枚が {pages}ページに なる")
        page.emulate_media(media="screen")
        # 5つの 宛先 すべて A4 縦 1ページ
        tos = page.evaluate("[...document.querySelectorAll('[data-sheet-to]')].map(b => b.getAttribute('data-sheet-to'))")
        assert sorted(tos) == sorted(["mayor", "board", "principal", "town", "family"]), tos
        for to in tos:
            page.click(f'[data-sheet-to="{to}"]'); page.click("#class-sheet-make"); page.wait_for_selector("#class-sheet")
            page.emulate_media(media="print")
            n = len(_re.findall(rb"/Type\s*/Page[^s]", page.pdf(prefer_css_page_size=True, print_background=True)))
            page.emulate_media(media="screen")
            print(f"印刷用の 1枚（{to}）：PDF", n, "ページ")
            if n != 1:
                problems.append(f"印刷用の 1枚（{to}）が {n}ページに なる")
        page.click('[data-sheet-to="mayor"]'); page.click("#class-sheet-make"); page.wait_for_selector("#class-sheet")
        # Claude の 画面の 中（印刷できない）では、ファイルで 保存する・文を コピーする
        page.evaluate("window.claude = {}; UG.render()")
        assert page.locator("#class-sheet-print").count() == 0 and page.locator("#class-sheet-save").count() == 1
        page.evaluate("delete window.claude; UG.render()")
        assert page.locator("#class-sheet-print").count() == 1
        # 読んだ コードは 保存しない
        assert "WG50" not in page.evaluate("JSON.stringify(Object.assign({}, localStorage))"), "コードが localStorage に入っている"
        # 知らない id（ほかの 版の アプリ・書きかえた コード）の アイデアと もっと 知りたい データは、数えず 出さない。
        # 本物より 多く 入れて、絞らなければ 順位の 上に 出る ように する
        bogus = page.evaluate("""() => { const s = UG.state, out = [];
          for (let i = 0; i < 20; i++) out.push(UG.model.encodeGuess({ pref: '00', school: s.schoolId, guess: 'down',
            draw: Object.assign({}, s.draw), reason: '', mark: 'bogus' + String(i).padStart(2, '0'), seq: 1,
            prop: { ideas: ['bogus_id'], wishes: ['bogus_id'], to: 'mayor', proposal: 'ためしの 提案' } }));
          return out.join('\\n'); }""")
        assert page.evaluate("c => UG.model.decodeGuess(c.split('\\n')[0]).prop.wishes", bogus) == ["bogus_id"]
        page.fill("#class-text", page.input_value("#class-text") + "\n" + bogus)
        page.click("#class-load"); page.wait_for_selector("#class-props .sort-bars")
        page.click('[data-sheet-to="mayor"]'); page.click("#class-sheet-make"); page.wait_for_selector("#class-sheet")
        view_html = page.inner_html("#view")
        assert "bogus" not in view_html, "知らない id が 先生の 画面か 印刷の 1枚に 出た"
        assert page.locator("#class-sheet .idea-rank li").count() == 5
        top = page.evaluate("""() => { const r = UG.model.extractGuesses(document.getElementById('class-text').value).items,
            w = UG.WISHES.map(k => k.id), i = UG.IDEAS.map(k => k.id);
          return { w: UG.model.wishTally(r, w).filter(x => w.includes(x.id)).slice(0, 3).map(x => [UG.WISHES.find(k => k.id === x.id).t, x.n]),
                   raw: UG.model.wishTally(r, w)[0].id, ideaRaw: UG.model.ideaTally(r, i)[0].id }; }""")
        assert top["raw"] == "bogus_id" and top["ideaRaw"] == "bogus_id", top  # 絞らなければ いちばん 上に 来る
        sw2 = plain("#class-sheet .sh-wishes").replace(" ", "")
        assert sw2 == "もっと知りたいデータ：" + "、".join(f"{t.replace(' ', '')}（{n}人）" for t, n in top["w"]), (sw2, top)
        # 実データの県では「見本の クラスで ためす」を出さない
        assert page.evaluate("UG.state.prefCode") == "00"

        # スマートフォン幅
        page.set_viewport_size({"width": 390, "height": 800})
        page.evaluate("UG.go('step3')")
        page.wait_for_selector(".verdict")
        shot("m-3-shiraberu")
        page.evaluate("UG.go('home')")
        shot("m-0-home")
        over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if over > 1:
            problems.append(f"スマホ幅で横スクロールが発生: {over}px")

        # 学校を選びなおすと、その学校についての作業はリセットされる
        page.set_viewport_size({"width": 1180, "height": 820})
        page.click('[data-school="S5"]')
        assert page.evaluate("[UG.state.schoolId, Object.keys(UG.state.draw).length, UG.state.grade]") == ["S5", 0, "e5"]
        assert [t.strip() for t in page.locator(".school-btn.on .nm").all_inner_texts()] == ["山の上小学校"]
        page.click("#start"); page.click('[data-guess="same"]'); page.click("#next-btn")
        page.wait_for_selector("svg.chart .pad")
        draw_line(0.8, 0.85, 140, 20)
        page.click("#next-btn"); page.wait_for_selector(".verdict"); page.wait_for_timeout(2500)
        shot("3-small-school"); bare("small")

        # 「さいしょから やりなおす」は 2回で 消す：1回目は 消えない、すぐの 2回目（0.5秒未満）も 消えない、
        # 5秒で もとの 文字に もどる、0.5秒 以上 あけた 2回目で 消えて home へ
        RESET = "[data-reset]"
        label0 = page.inner_text(RESET)
        page.click(RESET)
        assert page.inner_text(RESET).replace(" ", "") == "もう1回おすと、ぜんぶきえるよ", page.inner_text(RESET)
        assert "armed" in page.get_attribute(RESET, "class")
        assert page.evaluate("getComputedStyle(document.querySelector('[data-reset]')).color") == "rgb(224, 49, 49)"
        assert page.evaluate("UG.state.schoolId") == "S5", "1回目で 消えた"
        page.evaluate("document.querySelector('[data-reset]').click()")  # すぐの 2回目
        assert page.evaluate("UG.state.schoolId") == "S5", "すぐの 2回目で 消えた"
        page.wait_for_timeout(5200)
        assert page.inner_text(RESET) == label0 and "armed" not in page.get_attribute(RESET, "class"), "5秒たっても もどらない"
        assert page.evaluate("UG.state.schoolId") == "S5"
        page.click(RESET); page.wait_for_timeout(600); page.click(RESET)
        assert page.evaluate("[UG.state.schoolId, UG.state.step, Object.keys(UG.state.draw).length]") == [None, "home", 0], "2回目で 消えない"
        assert "さいしょから はじめます" in plain("#toast"), plain("#toast")
        assert page.inner_text(RESET) == label0

        # タッチの 端末（820×1180）：押せる ものの 高さが 44px 以上
        tctx = browser.new_context(viewport={"width": 820, "height": 1180}, has_touch=True)
        watch_requests(tctx, None, external)
        tp = tctx.new_page(); tp.goto(URL); tp.wait_for_selector(".school-btn")
        assert tp.evaluate("matchMedia('(pointer: coarse)').matches")
        tp.evaluate("s => { localStorage.setItem('ug2050:v1', s); }", state5)
        tp.reload(); tp.wait_for_selector("#view")
        TALL = """sel => [...document.querySelectorAll(sel)].filter(e => e.offsetParent !== null).map(e => e.getBoundingClientRect().height)"""
        def tall(where, sels):
            for sel in sels:
                hs = tp.evaluate(TALL, sel)
                if not hs:
                    problems.append(f"[タッチ {where}] {sel} が 見つからない")
                elif min(hs) < 44:
                    problems.append(f"[タッチ {where}] {sel} の 高さが 44px より 小さい: {min(hs):.1f}px")
        tp.evaluate("UG.go('home')"); tp.wait_for_selector(".picker select")
        tall("home", [".picker select", ".tabs button", "[data-reset]"])
        tp.evaluate("UG.go('step3')"); tp.wait_for_selector(".verdict")
        tall("step3", [".btn.small"])
        tp.evaluate("UG.go('step5')"); tp.wait_for_selector("#card svg")
        tall("step5", [".tri button", ".tabs button", ".btn.sub", "[data-reset]", "#cases summary"])  # .btn.small は ステップ3で（ここでは 閉じた 箱の 中）
        tp.click("#cases summary")
        assert tp.evaluate("document.getElementById('cases').open")
        over_t = tp.evaluate("""() => ({ page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          cases: Math.max(...[...document.querySelectorAll('#cases, #case-list li')].map(e => e.getBoundingClientRect().right)) - document.documentElement.clientWidth })""")
        if over_t["page"] > 1 or over_t["cases"] > 1:
            problems.append(f"[タッチ 820px] 事例帳が 横に はみ出す: {over_t}")
        tp.screenshot(path=str(OUT / "t-5-teian-touch.png"), full_page=True)
        tctx.close()

        problems += [f"console: {e}" for e in errors]
        problems += [f"[file://] 外部への通信: {u}" for u in external]
        problems += check_http(browser)
        browser.close()

    print(json.dumps(problems, ensure_ascii=False, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
