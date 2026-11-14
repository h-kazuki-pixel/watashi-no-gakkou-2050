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
        page.click("#start")

        page.wait_for_selector(".now-card")
        with_note("step1")
        assert page.is_disabled("#next-btn")
        page.click('[data-guess="down"]')
        page.fill("#reason", "空き家がふえているから")
        shot("1-gimon"); bare("step1")
        page.click("#next-btn")

        page.wait_for_selector("svg.chart .pad")
        assert page.is_disabled("#next-btn")
        shot("2-yosou-before", full=False)
        draw_line(0.62, 0.74, 140, 30)
        assert not page.is_disabled("#next-btn"), "線を描いても次へ進めない"
        drawn = page.evaluate("UG.state.draw")
        assert len(drawn) == 5, drawn
        shot("2-yosou"); bare("step2")
        page.click("#next-btn")

        page.wait_for_selector(".verdict")
        page.wait_for_timeout(2600)
        shot("3-shiraberu"); bare("step3")
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
