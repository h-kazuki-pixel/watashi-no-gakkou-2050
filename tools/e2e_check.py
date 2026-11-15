#!/usr/bin/env python3
"""ブラウザで全ステップを通す動作確認（スモークテスト）。

使い方:  python3 tools/e2e_check.py [出力フォルダ]
  - コンソールエラーが出ないこと
  - 5ステップを最後まで進められること
  - 子ども向け画面に「ふりがなのない漢字」が残っていないこと
を確かめ、各画面のスクリーンショットを保存する。
"""
import json
import os
import pathlib
import shutil
import sys

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
      if (tag === 'ruby' || tag === 'rt' || tag === 'svg' || p.hasAttribute('data-nr') || p.classList.contains('teachers')) { skip = true; break; }
      p = p.parentElement;
    }
    if (skip) continue;
    const m = n.textContent.match(/[\\u4e00-\\u9fff々]/g);
    if (m) out.push([m.join(''), n.textContent.trim().slice(0, 40)]);
  }
  return out;
}
"""


def main() -> int:
    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**LAUNCH)
        page = browser.new_page(viewport={"width": 1180, "height": 820})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text else None)
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

        def bare(step):
            for chars, ctx in page.evaluate(FIND_BARE_KANJI):
                rest = "".join(c for c in chars if c not in ALLOW)
                if rest:
                    problems.append(f"[{step}] ふりがななし: {rest} … {ctx}")

        page.goto(URL)
        page.wait_for_selector(".school-btn")

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
        tp = tctx.new_page(); tp.goto(URL); tp.wait_for_selector(".school-btn")
        tp.click('[data-school="S2"]'); tp.click('[data-grade="e5"]'); tp.click("#start")
        tp.click('[data-guess="down"]'); tp.click("#next-btn"); tp.wait_for_selector("svg.chart .pad")
        assert tp.evaluate("matchMedia('(pointer: coarse)').matches")
        assert tp.locator(".kbd-hint").count() == 1 and not tp.is_visible(".kbd-hint"), "タッチの端末でキーボードの案内が出ている"
        assert tp.evaluate("document.querySelector('svg.chart [role=slider][tabindex=\"0\"]') !== null"), "丸をキーボードで選べない"
        tctx.close()
        shot("2-yosou"); bare("step2")
        page.click("#next-btn")

        page.wait_for_selector(".verdict")
        page.wait_for_timeout(2600)
        shot("3-shiraberu"); bare("step3")
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
          const r = document.createRange(); r.selectNodeContents(n); const lines = new Set([...r.getClientRects()].filter(x => x.width > 1).map(x => Math.round(x.bottom / 6)));
          return {text: n.textContent, lines: lines.size, inside: f.getBoundingClientRect().right <= t.right - 2, size: getComputedStyle(b).fontSize}; })""")
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
        page.click("#next-btn")

        page.wait_for_selector("#card svg")
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

        page.click('[data-go="teachers"]')
        page.wait_for_selector(".teachers")
        shot("9-teachers")

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

        problems += [f"console: {e}" for e in errors]
        browser.close()

    print(json.dumps(problems, ensure_ascii=False, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
