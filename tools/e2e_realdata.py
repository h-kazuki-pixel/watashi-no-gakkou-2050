#!/usr/bin/env python3
"""パイプラインの出力をアプリが読めることの確認。

  引数なし：合成の学区・メッシュ（みほん市）→ pipeline build → data/pref_99.js → ブラウザで都道府県・市区町村・学校を選んで進む。
            実データ（国土数値情報）と同じ経路を通る。出力は一時フォルダに作り、リポジトリの app/data は汚さない。
  --prefs：リポジトリの app/data（生成済みの実データ）を一時フォルダに写し、県を選んで進む。
           「県コード」か「県コード:市区町村名」をカンマ区切りで（市区町村名が無ければ最初の市区町村）。
           例：python3 tools/e2e_realdata.py --prefs 01,13,14:横浜市,26:京都市東山区,07:いわき市,47
           福島県（07）では、浜通りの扱わない7町村が選べない（disabled）ことと、出す市町村の注意書きも確かめる。
  --kana ：ひらがなで学校をさがす（龍王小・竜王北小・西新小・三入小・横浜市）。引数なしのときも最後に回す。
           読み（kana）がまだ app/data に無ければ「飛ばした」と出す。
  --closures：閉校の印と新しい学校（いわき市 桶売小、吹田市 山田第五小 → 山田第三小、福島市「しょうりょう」）。引数なしのときも回す。
"""
import argparse
import os
import pathlib
import shutil
import sys
import tempfile

from playwright.sync_api import sync_playwright

# Chrome の場所。環境変数 CHROME で指定できる。無ければ Playwright 付属の Chromium を使う
_CHROME = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
LAUNCH = {"args": ["--no-sandbox"], **({"executable_path": _CHROME} if _CHROME else {})}

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "pipeline" / "tests"))
import build_school_data as cli  # noqa: E402
import test_pipeline as fx  # noqa: E402

OUT = ROOT / "tools" / "_shots"
HAMADORI_HIDDEN = {"07542", "07543", "07545", "07546", "07547", "07548", "07564"}


def walk(page, shot_prefix):
    """選んだ学校で、ステップ1 → 4 まで進む（実データ用。数字は決め打ちにしない）"""
    page.click("#start")
    page.wait_for_selector(".now-card")
    est = page.evaluate("UG.ctx().now")
    assert est and est > 0, est
    page.click('[data-guess="down"]'); page.click("#next-btn")
    page.wait_for_selector("svg.chart .pad")
    box = page.locator("svg.chart .pad").bounding_box()
    page.mouse.move(box["x"] + 5, box["y"] + box["height"] * 0.5); page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 135, box["y"] + box["height"] * 0.7, steps=25); page.mouse.up()
    page.click("#next-btn")
    page.wait_for_selector(".verdict"); page.wait_for_timeout(2600)
    page.click("#next-btn")
    page.click("#cmp-box > summary")
    page.wait_for_selector("#cmp-map svg")
    n = page.locator("#cmp-list li").count()
    assert n >= 1, n
    page.screenshot(path=str(OUT / f"{shot_prefix}-4.png"), full_page=True)
    return est, n


def run_real(cases) -> int:
    """リポジトリの app/data を使い、県・市区町村・学校を選んでステップ4まで進む"""
    errors = []
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        shutil.copytree(ROOT / "app", td / "app")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**LAUNCH)
            page = browser.new_page(viewport={"width": 1180, "height": 820})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto((td / "app" / "index.html").as_uri())
            page.wait_for_selector("#sel-pref")
            prefs = page.locator("#sel-pref option").evaluate_all("os => os.map(o => o.value)")
            print("都道府県の選択肢:", len(prefs) - 1, "（れんしゅう用を除く）")
            for case in cases:
                pref, _, city_name = case.partition(":")
                page.evaluate("UG.resetState()")
                page.goto((td / "app" / "index.html").as_uri() + "#home")
                page.reload()
                page.wait_for_selector("#sel-pref")
                page.select_option("#sel-pref", pref)
                page.wait_for_function(f"UG.state.prefCode === '{pref}'")
                opts = page.locator("#sel-city option").evaluate_all(
                    "os => os.map(o => ({v: o.value, t: o.textContent, d: o.disabled}))")
                if city_name:
                    hit = [o for o in opts if not o["d"] and o["t"] == city_name]
                    assert hit, f"{pref}: 市区町村「{city_name}」が選べない"
                    page.select_option("#sel-city", hit[0]["v"])
                    page.wait_for_function(f"UG.state.cityCode === '{hit[0]['v']}'")
                city = page.evaluate("UG.state.cityCode")
                cname = next(o["t"] for o in opts if o["v"] == city)
                if pref == "07":
                    off = [o["t"] for o in opts if o["d"]]
                    hidden = [t for t in off if t.endswith("（このアプリでは あつかって いません）")]
                    assert len(hidden) == len(HAMADORI_HIDDEN), off
                    if city in ("07201", "07209", "07212", "07541", "07544", "07561"):
                        assert "まとめて 計算されて" in page.inner_text(".pick"), "浜通りの注意書きが出ていない"
                    print("  福島県：選べない町村", hidden)
                schools = page.locator(".school-btn").count()
                assert schools >= 1, f"{pref} {cname}: 学校が無い"
                page.locator(".school-btn").first.click()
                sname = page.locator(".school-btn.on .nm").inner_text()
                est, n = walk(page, f"real-{pref}")
                print(f"  {pref} {cname}（{schools}校）{sname}：2025年 {est:.1f}人、比べる学校 {n}")
            browser.close()
    print("errors:", errors)
    return 1 if errors else 0


# ひらがなで さがす（リポジトリの app/data の実データ）。県, 市区町村, 打つ ひらがな, 出るはずの学校
KANA_CASES = [
    ("34", "東広島市", "りゅうおう", "龍王小学校"),
    ("19", "甲斐市", "りゅうおうきた", "竜王北小学校"),
    ("40", "福岡市早良区", "にしじん", "西新小学校"),
    ("34", "広島市", "みいり", "三入小学校"),
]
KANA_TYPING = ("14", "横浜市")  # 平仮名を1文字ずつ打って、一覧が絞れていくこと


def _school_in_data(pref, city_name, school_name=None):
    """app/data から学校を探す（読みが付いているかを、ブラウザを開く前に見る）。"""
    import json
    text = (ROOT / "app" / "data" / f"pref_{pref}.js").read_text(encoding="utf-8")
    obj = json.loads(text[text.index("UG.registerPref(") + len("UG.registerPref("):text.rindex(");")])
    city = next((c for c in obj["cities"] if c["name"] == city_name), None)
    assert city, f"{pref}: 市区町村「{city_name}」が app/data に無い"
    if school_name is None:
        return city, None
    school = next((s for s in city["schools"] if s["name"] == school_name), None)
    assert school, f"{city_name}: 「{school_name}」が app/data に無い"
    return city, school


def run_class_real() -> int:
    """クラスで 見る（実データ）：福岡市早良区の 学校で、宛先を 市長さんに した 提案 → 宛名は「福岡市長さん」。
    子どもの ステップ5の 宛先の ボタンも 同じ。印刷の 1枚を 印刷の メディアで 撮る"""
    city, school = _school_in_data("40", "福岡市早良区", "西新小学校")
    errors = []
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        shutil.copytree(ROOT / "app", td / "app")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**LAUNCH)
            page = browser.new_page(viewport={"width": 1180, "height": 820})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto((td / "app" / "index.html").as_uri())
            page.evaluate("UG.resetState()")
            page.goto((td / "app" / "index.html").as_uri() + "#class")
            page.reload()
            page.wait_for_selector("#class-text")
            codes = page.evaluate("""s => [1, 2, 3].map(i => UG.model.encodeGuess({ pref: '40', school: s, guess: 'down',
                draw: {2030: 600, 2035: 560, 2040: 520, 2045: 480, 2050: 450}, mark: 'fuku0' + i, seq: 2,
                prop: { sort: { c1: 'good', c2: 'bad' }, ideas: ['room_town'], to: i < 3 ? 'mayor' : 'board',
                        proposal: '空いた 教室を 地域の 人も 使える 場所に して ほしいです。' + i } }))""", school["id"])
            page.fill("#class-text", "\n".join(codes))
            page.click("#class-load")
            page.wait_for_selector("#class-props .sort-bars")
            page.click('[data-sheet-to="mayor"]')
            page.click("#class-sheet-make")
            page.wait_for_selector("#class-sheet")
            NO_RT = "sel => [...document.querySelectorAll(sel)].map(e => { const c = e.cloneNode(true); c.querySelectorAll('rt').forEach(r => r.remove()); return c.textContent.replace(/\\s/g, ''); })"
            title = page.evaluate(NO_RT, "#class-sheet .sh-to")[0]
            assert title == "福岡市長さんへ", title
            groups = page.evaluate(NO_RT, "[data-sheet-to]")
            assert groups[0] == "福岡市長さん", groups
            page.emulate_media(media="print")
            page.screenshot(path=str(OUT / "r-class-sheet-sawara.png"), full_page=True)
            pdf = page.pdf(prefer_css_page_size=True, print_background=True)
            (OUT / "r-class-sheet-sawara.pdf").write_bytes(pdf)
            page.emulate_media(media="screen")
            print(f"  福岡市早良区 {school['name']}：印刷の 1枚の 宛名「{title}」")
            # 子どもの ステップ5：宛先の ボタン
            page.evaluate("""s => { UG.resetState(); Object.assign(UG.state, { prefCode: '40', cityCode: '40137', schoolId: s,
                grade: 'e5', guess: 'down', draw: {2030: 600, 2035: 560, 2040: 520, 2045: 480, 2050: 450}, maxStep: 5 });
                UG.save(); UG.go('step5'); }""", school["id"])
            page.wait_for_selector("#card svg")
            chip = page.evaluate(NO_RT, '[data-to="mayor"]')[0]
            assert chip == "福岡市長さん", chip
            assert page.evaluate("UG.cardData().to") == "校長先生"  # 宛先の 初期値
            page.click('[data-to="mayor"]')
            card_to = page.evaluate("UG.cardData().to")
            assert card_to == "福岡市長さん", card_to
            print(f"  子どもの ステップ5の 宛先：「{chip}」、カード：「{card_to}」")
            browser.close()
    print("errors:", errors)
    return 1 if errors else 0


def run_kana() -> int:
    """ひらがなで学校をさがす（実データ）。読み（kana）がまだ無い学校は「飛ばした」と出す。"""
    todo = []
    for pref, cname, q, target in KANA_CASES:
        city, school = _school_in_data(pref, cname, target)
        if not school.get("kana"):
            print(f"  飛ばした（読みがまだ無い）：{cname}で「{q}」→ {target}")
        else:
            todo.append((pref, city, q, target))
    ycity, _ = _school_in_data(*KANA_TYPING)
    ytarget = next((s for s in ycity["schools"] if s.get("kana") and len(s["kana"][0]) >= 6), None)
    if not ytarget:
        print(f"  飛ばした（読みがまだ無い）：{KANA_TYPING[1]}で 平仮名を1文字ずつ打って 一覧が絞れていくこと")
    if not todo and not ytarget:
        return 0
    errors = []
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        shutil.copytree(ROOT / "app", td / "app")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**LAUNCH)
            page = browser.new_page(viewport={"width": 1180, "height": 820})
            page.on("pageerror", lambda e: errors.append(str(e)))

            def open_city(pref, code):
                page.goto((td / "app" / "index.html").as_uri())
                page.evaluate("UG.resetState()")
                page.reload()
                page.wait_for_selector("#sel-pref")
                page.select_option("#sel-pref", pref)
                page.wait_for_function(f"UG.state.prefCode === '{pref}'")
                page.select_option("#sel-city", code)
                page.wait_for_function(f"UG.state.cityCode === '{code}'")

            def names():
                return [t.strip() for t in page.locator("#school-list .school-btn .nm").all_inner_texts()]

            for pref, city, q, target in todo:
                open_city(pref, city["code"])
                page.fill("#q-school", q)
                got = names()
                assert target in got, f"{city['name']}で「{q}」→ {target} が出ない: {got}"
                assert q not in page.inner_text("#school-list"), "読みが画面に出ている"
                print(f"  {city['name']}で「{q}」→ {got}")
                page.screenshot(path=str(OUT / f"r-kana-{pref}-{city['code']}.png"), full_page=True)
            if ytarget:
                open_city(KANA_TYPING[0], ycity["code"])
                total = len(names())
                counts, typed = [], ""
                for ch in ytarget["kana"][0][:6]:
                    typed += ch
                    page.fill("#q-school", typed)
                    counts.append(len(names()))
                    assert ytarget["name"] in names(), f"横浜市「{typed}」で {ytarget['name']} が消えた"
                assert all(a >= b for a, b in zip([total] + counts, counts)), counts  # 打つほど 絞れる（増えない）
                assert counts[-1] < total, (total, counts)
                print(f"  横浜市で「{typed}」を1文字ずつ：{total} → {counts}（{ytarget['name']}）")
                page.screenshot(path=str(OUT / "r-kana-yokohama.png"), full_page=True)
            browser.close()
    print("errors:", errors)
    return 1 if errors else 0


def _plain(page, sel):
    """sel の 文字（ふりがなを 除く）"""
    return page.evaluate("""s => { const e = document.querySelector(s); if (!e) return null; const c = e.cloneNode(true);
      c.querySelectorAll('rt').forEach(r => r.remove()); return c.textContent; }""", sel)


def run_closures() -> int:
    """閉校の印（gone・now・joined）と 新しい学校（newSchools）を 実データで。いわき市 桶売小（now なし）、
    吹田市 山田第五小（now あり・えらぶ ボタン → 山田第三小の joined）、福島市「しょうりょう」→ 松陵義務教育学校、
    手で確かめた閉校の表の いわき市 三阪小（移行先 三和小学校。アプリに無いので ボタンなし）と 小清水町 北陽小（移行先なし）、
    南あわじ市「しち」→ 三原志知小・西淡志知小（どちらも 移行先 志知小学校、ボタンなし。西淡志知小は コードが志知小に引き継がれた学校）、
    浜田市 今市小（④ 学校コードは続いているが 国の一覧で 学校名が 旭小学校。ボタンなし）、
    いわき市 入遠野小（移行先 遠野小学校の id の学校は 上遠野小学校（④）なので、ボタンなし）"""
    icity, oke = _school_in_data("07", "いわき市", "桶売小学校")
    suita, yama5 = _school_in_data("27", "吹田市", "山田第五小学校")
    _, yama3 = _school_in_data("27", "吹田市", "山田第三小学校")
    fcity, _ = _school_in_data("07", "福島市")
    _, misaka = _school_in_data("07", "いわき市", "三阪小学校")
    kcity, hokuyo = _school_in_data("01", "小清水町", "北陽小学校")
    acity, mshichi = _school_in_data("28", "南あわじ市", "三原志知小学校")
    _, sshichi = _school_in_data("28", "南あわじ市", "西淡志知小学校")
    hcity, imaichi = _school_in_data("32", "浜田市", "今市小学校")
    _, iritono = _school_in_data("07", "いわき市", "入遠野小学校")
    for s, want in ((oke, "gone"), (yama5, "gone"), (yama3, "joined"), (misaka, "gone"), (hokuyo, "gone"),
                    (mshichi, "gone"), (sshichi, "gone"), (imaichi, "gone"), (iritono, "gone")):
        if not s.get(want):
            print(f"  飛ばした（印がまだ app/data に無い）：{s['name']}")
            return 0
    errors = []
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        shutil.copytree(ROOT / "app", td / "app")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**LAUNCH)
            page = browser.new_page(viewport={"width": 1180, "height": 820})
            page.on("pageerror", lambda e: errors.append(str(e)))

            def open_city(pref, code, width):
                page.set_viewport_size({"width": width, "height": 820})
                page.goto((td / "app" / "index.html").as_uri())
                page.evaluate("UG.resetState()")
                page.reload()
                page.wait_for_selector("#sel-pref")
                page.select_option("#sel-pref", pref)
                page.wait_for_function(f"UG.state.prefCode === '{pref}'")
                page.select_option("#sel-city", code)
                page.wait_for_function(f"UG.state.cityCode === '{code}'")
                page.wait_for_timeout(300)

            def wide_ok(where):
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"{where}：横に はみ出す"

            def note_height(where):
                """注意（#school-note）の高さと、学校の一覧の上端が画面の上から どれだけ下か（押し下げすぎないかを見る）"""
                h = page.evaluate("""() => ({note: Math.round(document.getElementById('school-note').getBoundingClientRect().height),
                  list: Math.round(document.getElementById('school-list').getBoundingClientRect().top + scrollY)})""")
                print(f"    {where}：注意の高さ {h['note']}px、学校の一覧の上端 {h['list']}px")

            def shot_note(name):
                page.locator("#school-note").scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / name), full_page=True)

            for w in (820, 390):
                # いわき市 桶売小：札と、now なしの文
                open_city("07", icity["code"], w)
                btn = f'[data-school="{oke["id"]}"]'
                assert _plain(page, btn + " .gone-tg") == "いまは この 名前では ないよ", _plain(page, btn)
                page.click(btn)
                t = _plain(page, "#school-note .note.closure")
                assert t == "「桶売小学校」という 名前の 学校は、いまの 国の 学校の 一覧に ありません。ほかの 学校と いっしょに なったり、学校の 名前が かわったり したのかも しれません。どうしてか、おうちの 人や 先生に きいて みよう。ここに 出る 数字は、もとの「桶売小学校」の 区域の 人数です。", t
                assert page.locator("#school-note .pick-now").count() == 0
                wide_ok(f"{w}px いわき市")
                note_height(f"{w}px 桶売小")
                shot_note(f"r-closure-okeuri-{w}.png")
                print(f"  {w}px いわき市 桶売小：{t}")

                # いわき市 三阪小（手で確かめた表。移行先 三和小学校はアプリに無いので、えらぶ ボタンは出ない）
                page.click(f'[data-school="{misaka["id"]}"]')
                t = _plain(page, "#school-note .note.closure")
                assert t == ("「三阪小学校」という 名前の 学校は、いまの 国の 学校の 一覧に ありません。いまは「三和小学校」に なって います。"
                             "ここに 出る 数字は、もとの「三阪小学校」の 区域の 人数です。"), t
                assert page.locator("#school-note .pick-now").count() == 0
                wide_ok(f"{w}px いわき市 三阪小")
                print(f"  {w}px いわき市 三阪小：{t}")

                # いわき市 入遠野小：移行先の 遠野小学校は アプリでは「上遠野小学校」（④の印）なので、ボタンは出さない
                page.click(f'[data-school="{iritono["id"]}"]')
                t = _plain(page, "#school-note .note.closure")
                assert t == ("「入遠野小学校」という 名前の 学校は、いまの 国の 学校の 一覧に ありません。いまは「遠野小学校」に なって います。"
                             "ここに 出る 数字は、もとの「入遠野小学校」の 区域の 人数です。"), t
                assert page.locator("#school-note .pick-now").count() == 0
                wide_ok(f"{w}px いわき市 入遠野小")
                print(f"  {w}px いわき市 入遠野小：{t}")

                # 小清水町 北陽小（手で確かめた表。移行先なし）
                open_city("01", kcity["code"], w)
                page.click(f'[data-school="{hokuyo["id"]}"]')
                t = _plain(page, "#school-note .note.closure")
                assert t == ("「北陽小学校」という 名前の 学校は、いまの 国の 学校の 一覧に ありません。ほかの 学校と いっしょに なったり、"
                             "学校の 名前が かわったり したのかも しれません。どうしてか、おうちの 人や 先生に きいて みよう。"
                             "ここに 出る 数字は、もとの「北陽小学校」の 区域の 人数です。"), t
                assert page.locator("#school-note .pick-now").count() == 0
                wide_ok(f"{w}px 小清水町")
                print(f"  {w}px 小清水町 北陽小：{t}")

                # 南あわじ市「しち」→ 三原志知小と 西淡志知小。どちらも「いまは「志知小学校」に なって います」、ボタンなし
                open_city("28", acity["code"], w)
                page.fill("#q-school", "しち")
                got = [x.strip() for x in page.locator("#school-list .school-btn .nm").all_inner_texts()]
                assert "三原志知小学校" in got and "西淡志知小学校" in got, got
                for sch in (mshichi, sshichi):
                    b = f'[data-school="{sch["id"]}"]'
                    assert _plain(page, b + " .gone-tg") == "いまは この 名前では ないよ", _plain(page, b)
                    page.click(b)
                    page.fill("#q-school", "しち")
                    t = _plain(page, "#school-note .note.closure")
                    assert t == (f"「{sch['name']}」という 名前の 学校は、いまの 国の 学校の 一覧に ありません。いまは「志知小学校」に なって います。"
                                 f"ここに 出る 数字は、もとの「{sch['name']}」の 区域の 人数です。"), t
                    assert page.locator("#school-note .pick-now").count() == 0
                    wide_ok(f"{w}px 南あわじ市 {sch['name']}")
                    print(f"  {w}px 南あわじ市「しち」→ {got}：{sch['name']}：{t}")
                page.screenshot(path=str(OUT / f"r-closure-shichi-{w}.png"), full_page=True)

                # 浜田市 今市小（④）：「いまは「旭小学校」に なって います」、ボタンなし
                open_city("32", hcity["code"], w)
                page.click(f'[data-school="{imaichi["id"]}"]')
                t = _plain(page, "#school-note .note.closure")
                assert t == ("「今市小学校」という 名前の 学校は、いまの 国の 学校の 一覧に ありません。いまは「旭小学校」に なって います。"
                             "ここに 出る 数字は、もとの「今市小学校」の 区域の 人数です。"), t
                assert page.locator("#school-note .pick-now").count() == 0
                wide_ok(f"{w}px 浜田市 今市小")
                print(f"  {w}px 浜田市 今市小：{t}")

                # 吹田市 山田第五小：now ありの文と「「山田第三小学校」を えらぶ」→ 山田第三小が選ばれ、joined の文
                open_city("27", suita["code"], w)
                page.click(f'[data-school="{yama5["id"]}"]')
                t = _plain(page, "#school-note .note.closure")
                assert t == ("「山田第五小学校」という 名前の 学校は、いまの 国の 学校の 一覧に ありません。いまは「山田第三小学校」に なって います。"
                             "ここに 出る 数字は、もとの「山田第五小学校」の 区域の 人数です。"), t
                b = _plain(page, "#school-note .pick-now button")
                assert b == "「山田第三小学校」を えらぶ", b
                wide_ok(f"{w}px 吹田市")
                shot_note(f"r-closure-yamada5-{w}.png")
                page.click("#school-note .pick-now button")
                assert page.evaluate("UG.state.schoolId") == yama3["id"]
                assert _plain(page, "#school-list .school-btn.on .nm") == "山田第三小学校"
                j = _plain(page, "#school-note .note.closure")
                assert j == "「山田第五小学校」だった 区域の 子どもは、この 数字に 入って いません。", j
                wide_ok(f"{w}px 吹田市 山田第三小")
                shot_note(f"r-closure-yamada3-{w}.png")
                print(f"  {w}px 吹田市 山田第五小：{t} ／ ボタン {b} → 山田第三小：{j}")

                # 福島市「しょうりょう」→ 新しい学校 松陵義務教育学校 の行（選べない）。「見つからなかったよ」は出さない
                open_city("07", fcity["code"], w)
                page.fill("#q-school", "しょうりょう")
                rows = [_plain(page, f"#school-list .new-school:nth-of-type({i + 1}) .nm") for i in range(page.locator("#school-list .new-school").count())]
                assert "松陵義務教育学校" in rows, rows
                assert _plain(page, "#school-list .new-school .tg") == "あたらしい 学校。人数は まだ 計算できないよ"
                assert page.locator("#school-list .empty").count() == 0
                assert page.locator("#school-list .new-school button").count() == 0  # from が 空
                assert "しょうりょう" not in page.inner_text("#school-list"), "読みが画面に出ている"
                wide_ok(f"{w}px 福島市")
                page.locator("#school-list").scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f"r-closure-shoryo-{w}.png"), full_page=True)
                print(f"  {w}px 福島市「しょうりょう」→ 学校 {page.locator('#school-list .school-btn').count()}校、新しい学校 {rows}")
            browser.close()
    print("errors:", errors)
    return 1 if errors else 0


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        fx.make_mesh_csv(td / "mesh.csv")
        fx.make_geojson(td / "districts.geojson")
        shutil.copytree(ROOT / "app", td / "app")
        cli.main(["build", "--pref", "99", "--districts", str(td / "districts.geojson"), "--mesh", str(td / "mesh.csv"),
                  "--out", str(td / "app" / "data")])
        errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**LAUNCH)
            page = browser.new_page(viewport={"width": 1180, "height": 820})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto((td / "app" / "index.html").as_uri())
            page.wait_for_selector("#sel-pref")
            page.select_option("#sel-pref", "99")
            page.wait_for_function("UG.state.prefCode === '99'")
            assert page.locator("#sel-city option").all_inner_texts() == ["みほん市東区", "みほん市西区"]
            page.select_option("#sel-city", "99102")
            page.wait_for_function("UG.state.cityCode === '99102'")
            page.fill("#q-school", "きた")
            names = page.locator(".school-btn .nm").all_inner_texts()
            assert names == ["きた小学校"], names
            page.click(".school-btn")
            page.screenshot(path=str(OUT / "r-0-home.png"), full_page=True)
            page.click("#start")
            page.wait_for_selector(".now-card")
            assert "170" in page.inner_text(".big")
            # 学校の実際の人数で補正（170 → 204 は 1.2 倍。2050年は 170×0.6×1.2 = 122.4）
            page.fill("#calib", "204"); page.click("#calib-btn")
            page.wait_for_selector(".now-card")
            v50 = page.evaluate("UG.ctx().v50")
            assert abs(v50 - 122.4) < 1e-6, v50
            page.click('[data-guess="down"]'); page.click("#next-btn")
            page.wait_for_selector("svg.chart .pad")
            box = page.locator("svg.chart .pad").bounding_box()
            page.mouse.move(box["x"] + 5, box["y"] + box["height"] * 0.5); page.mouse.down()
            page.mouse.move(box["x"] + box["width"] - 135, box["y"] + box["height"] * 0.7, steps=25); page.mouse.up()
            page.click("#next-btn")
            page.wait_for_selector(".verdict"); page.wait_for_timeout(2600)
            page.screenshot(path=str(OUT / "r-3.png"), full_page=True)
            page.click("#next-btn")
            page.click("#cmp-box > summary")
            page.wait_for_selector("#cmp-map svg")
            assert page.locator("#cmp-list li").count() == 2
            page.screenshot(path=str(OUT / "r-4.png"), full_page=True)
            # 再読み込みしても、選んだ県のデータを読み直して続きから開ける
            page.reload()
            page.click("#cmp-box > summary")
            page.wait_for_selector("#cmp-map svg")

            # 学区データの無い市：学校の位置で補った県と、補わなかった県
            gap = td / "gap"
            fx._make_gap_downloads(gap)
            cli.main(["build-all", "--input", str(gap), "--out", str(td / "app" / "data")])
            page.evaluate("UG.resetState()")
            page.goto((td / "app" / "index.html").as_uri() + "#home")
            page.reload()
            page.wait_for_selector("#sel-pref")
            page.select_option("#sel-pref", "99")
            page.wait_for_function("UG.state.prefCode === '99'")
            page.select_option("#sel-city", "99102")
            page.wait_for_function("UG.state.cityCode === '99102'")
            assert "おおよその" in page.inner_text(".pick"), "おおよその区域の注意が出ていない"
            page.screenshot(path=str(OUT / "r-approx-home.png"), full_page=True)
            cli.main(["build-all", "--input", str(gap), "--out", str(td / "app" / "data"), "--no-fill"])
            page.evaluate("UG.resetState()")
            page.reload()
            page.wait_for_selector("#sel-pref")
            page.select_option("#sel-pref", "99")
            page.wait_for_function("UG.state.prefCode === '99'")
            opts = page.locator("#sel-city option").all_inner_texts()
            assert opts[-1].endswith("（学区データなし）"), opts
            browser.close()
        print("errors:", errors)
        return 1 if errors else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", help="画面の保存先（省略すると tools/_shots）")
    ap.add_argument("--prefs", help="実データで確かめる県（「県コード」か「県コード:市区町村名」、カンマ区切り）")
    ap.add_argument("--closures", action="store_true", help="閉校の印と新しい学校（実データ）だけを確かめる")
    ap.add_argument("--kana", action="store_true", help="ひらがなで学校をさがす（実データ）だけを確かめる。読みが無ければ飛ばす")
    a = ap.parse_args()
    if a.out:
        OUT = pathlib.Path(a.out)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.kana:
        sys.exit(run_kana())
    if a.closures:
        sys.exit(run_closures())
    if a.prefs:
        sys.exit(run_real(a.prefs.split(",")))
    rc = main()
    print("ひらがなで さがす（app/data の実データ）")
    rc = rc or run_kana()
    print("閉校の印と新しい学校（app/data の実データ）")
    rc = rc or run_closures()
    print("クラスで 見る（app/data の実データ）")
    sys.exit(rc or run_class_real())
