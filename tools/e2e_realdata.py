#!/usr/bin/env python3
"""パイプラインの出力をアプリが読めることの確認（合成データ「みほん市」を使う）。

  合成の学区・メッシュ → pipeline build → data/pref_99.js → ブラウザで都道府県・市区町村・学校を選んで進む
実データ（国土数値情報）と同じ経路を通る。出力は一時フォルダに作り、リポジトリの app/data は汚さない。
"""
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

OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tools" / "_shots"
OUT.mkdir(parents=True, exist_ok=True)


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
            page.wait_for_selector("#cmp-map svg")
            assert page.locator("#cmp-list li").count() == 2
            page.screenshot(path=str(OUT / "r-4.png"), full_page=True)
            # 再読み込みしても、選んだ県のデータを読み直して続きから開ける
            page.reload()
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
    sys.exit(main())
