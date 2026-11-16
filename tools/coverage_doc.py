#!/usr/bin/env python3
"""全都道府県の report_XX.json と app/data/pref_XX.js から、扱いの一覧（docs/COVERAGE.md）を作る。

    python3 tools/coverage_doc.py --app app/data --od opendata --out docs/COVERAGE.md

学校ごとの実際の児童数は使わない（入力は生成物だけ）。
"""
import argparse
import collections
import json
import pathlib
import sys

PREF_NAMES = None


def load_pref(path: pathlib.Path) -> dict:
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("UG.registerPref(") + 16:s.rindex(")")])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app/data")
    ap.add_argument("--od", default="opendata")
    ap.add_argument("--out", default="docs/COVERAGE.md")
    a = ap.parse_args()
    app, od = pathlib.Path(a.app), pathlib.Path(a.od)
    prefs = sorted(p.stem.split("_")[1] for p in app.glob("pref_[0-9][0-9].js"))
    rows, approx_c, nothandled, excluded, filled, closed, nopts, geom, fixes, notes = [], [], [], [], [], [], [], [], [], []
    tot = collections.Counter()
    gen = set()
    for p in prefs:
        obj = load_pref(app / f"pref_{p}.js")
        rp = od / f"report_{p}.json"
        if not rp.exists():
            sys.exit(f"{rp} がありません")
        rep = json.loads(rp.read_text(encoding="utf-8"))
        gen.add(obj.get("generated"))
        pname = obj["name"]
        names = {c["code"]: c["name"] for c in obj["cities"]}
        names.update({m["code"]: m["name"] for m in obj.get("missing", [])})
        names.update({e["code"]: e["name"] for e in rep.get("excluded_by_terms", [])})
        n_s = sum(len(c["schools"]) for c in obj["cities"])
        n_a = sum(1 for c in obj["cities"] for s in c["schools"] if s.get("approx"))
        ac = [c for c in obj["cities"] if c.get("approx")]
        n_ac_s = sum(len(c["schools"]) for c in ac)
        fl = [(c["name"], s["name"]) for c in obj["cities"] if not c.get("approx") for s in c["schools"] if s.get("approx")]
        nd = sum(1 for m in obj.get("missing", []) if not m.get("nothandled"))
        rows.append((p, pname, len(obj["cities"]), n_s, len(ac), n_a, nd))
        tot.update(cities=len(obj["cities"]), schools=n_s, approx_cities=len(ac), approx_schools=n_a, nodata=nd,
                   approx_city_schools=n_ac_s, filled=len(fl))
        if ac:
            approx_c.append(f"| {pname} | {len(ac)} | {n_ac_s} | " + "、".join(f"{c['name']}（{len(c['schools'])}）" for c in ac) + " |")
        for m in obj.get("missing", []):
            if m.get("nothandled"):
                nothandled.append(f"| {pname} | {m['code']} | {m['name']} |")
        for e in rep.get("excluded_by_terms", []):
            excluded.append(f"| {pname} | {e['code']} | {e['name']} | {e['reason']} |")
        if fl:
            filled.append(f"| {pname} | {len(fl)} | " + "、".join(f"{c} {s}" for c, s in fl) + " |")
        for e in rep.get("closed_schools_excluded", []):
            if e["how"].startswith("学区データにある"):
                closed.append(f"| {pname} | {names.get(e['city'], e['city'])} | {e['name']} | {e['value']} |")
        for e in rep.get("schools_without_points", []):
            nopts.append(f"| {pname} | {names.get(e['city'], e['city'])} | {e['name']} | {e['how']} |")
        for kind, lst in (rep.get("geometry_issues") or {}).items():
            for e in lst:
                how = e.get("how") or {
                    "duplicate_rings": f"同じ輪の2つ目からを取り除いた（{e.get('rings_removed', '?')}個）",
                    "overlapping_parts": f"重なりを1回だけ数えた（約{e.get('overlap_km2', '?')}km²）"}.get(kind, "")
                geom.append((pname, names.get(e["city"], e["city"]), e["name"], kind, how))
        for e in rep.get("source_corrections", []):
            fixes.append(f"| {pname} | {e['data']} | {e['code']} | {e['field']} | {e['from']} | {e['to']} |")
        nc = rep.get("note_cities") or []
        if nc:
            notes.append(f"| {pname} | " + "、".join(names.get(c, c) for c in nc) + " |")

    kind_ja = {"duplicate_rings": "同じ輪の重複", "hole_outside_outer": "外に出た穴", "overlapping_parts": "部分の重なり"}
    L = []
    w = L.append
    w("# 全国の扱いの一覧（COVERAGE）")
    w("")
    w(f"`tools/coverage_doc.py` が、生成した `app/data/pref_XX.js` と `report_XX.json` から作った一覧です（生成日 {', '.join(sorted(g for g in gen if g))}）。")
    w("計算の決まりは [DATA_METHOD.md](DATA_METHOD.md)、推計の当たり具合は [ACCURACY.md](ACCURACY.md)。学校ごとの実際の児童数は使っていません。")
    w("")
    w("## 全国の合計")
    w("")
    w("| 都道府県 | 市区町村 | 学校 | うち おおよその区域の学校 | おおよその区域の市区町村（学校） | 学区データに入っていなかった学校（補った） | 学区データも学校の位置も無い市区町村 | 扱わない市区町村 |")
    w("|---|---|---|---|---|---|---|---|")
    w(f"| {len(prefs)} | {tot['cities']} | {tot['schools']} | {tot['approx_schools']} | {tot['approx_cities']}（{tot['approx_city_schools']}） | {tot['filled']} | {tot['nodata']} | {len(nothandled)} |")
    w("")
    w("「市区町村」は画面で選べる単位です。政令市で学区データが市のコードで入っているところは、区に分けず市で1つです。")
    w("")
    w("## 都道府県ごと")
    w("")
    w("| コード | 都道府県 | 市区町村 | 学校 | おおよその区域の市区町村 | おおよその区域の学校 | 学区データなしで選べない市区町村 |")
    w("|---|---|---|---|---|---|---|")
    for r in rows:
        w("| " + " | ".join(str(x) for x in r) + " |")
    w("")
    w("## おおよその区域の市区町村")
    w("")
    w("学区データが無い（または利用条件・確認待ちで使わない）市区町村。学校の位置から、いちばん近い学校で区域を作っています。かっこは学校数。")
    w("")
    w("| 都道府県 | 市区町村数 | 学校数 | 市区町村 |")
    w("|---|---|---|---|")
    L.extend(approx_c)
    w("")
    w("## 扱わない市区町村")
    w("")
    w("福島県の浜通りで、2020年の国勢調査の5〜14歳人口が2025年5月1日の児童数より少ない町村（DATA_METHOD.md「まとめた区域」）。画面では選べません。")
    w("")
    w("| 都道府県 | コード | 市区町村 |")
    w("|---|---|---|")
    L.extend(nothandled)
    w("")
    w("## 利用条件などで学区データを使わなかった市区町村")
    w("")
    w("| 都道府県 | コード | 市区町村 | 理由 |")
    w("|---|---|---|---|")
    L.extend(excluded)
    w("")
    w("## 「学区は めやす」と表示する市区町村")
    w("")
    w("利用条件が「条件公開」か、特記条件のある市区町村。")
    w("")
    w("| 都道府県 | 市区町村 |")
    w("|---|---|")
    L.extend(notes)
    w("")
    w("## 学区データに入っていなかったので補った学校")
    w("")
    w("学区データのある市区町村で、学区データに無い公立小学校を、学校の位置から補った学校（おおよその区域）。")
    w("")
    w("| 都道府県 | 学校数 | 市区町村 学校 |")
    w("|---|---|---|")
    L.extend(filled)
    w("")
    w("## 学区データにあるが、休校区分が休校の学校")
    w("")
    w("学区データにある学校は、学区の学校としてそのまま使っています（休校区分は国土数値情報「学校」の値。9＝その他の休校など）。")
    w("")
    w("| 都道府県 | 市区町村 | 学校 | 休校区分 |")
    w("|---|---|---|---|")
    L.extend(closed)
    w(f"\n計 {len(closed)} 校。")
    w("")
    w("## 割り当たる点が無くて出なかった学校")
    w("")
    w("| 都道府県 | 市区町村 | 学校 | どちらの補い |")
    w("|---|---|---|---|")
    L.extend(nopts)
    w("")
    w("## 乱れた図形")
    w("")
    w("| 都道府県 | 市区町村 | 学校 | 乱れ | 扱い |")
    w("|---|---|---|---|---|")
    for g in geom:
        w(f"| {g[0]} | {g[1]} | {g[2]} | {kind_ja.get(g[3], g[3])} | {g[4]} |")
    w("")
    w("## 訂正した元データの誤記")
    w("")
    w("表は `pipeline/terms/source_corrections.csv`。")
    w("")
    w("| 都道府県 | データ | 学校コード | 項目 | 元の値 | 直した値 |")
    w("|---|---|---|---|---|---|")
    L.extend(fixes)
    w("")
    pathlib.Path(a.out).write_text("\n".join(L), encoding="utf-8")
    print(f"{a.out}: {len(prefs)} 都道府県、{tot['cities']} 市区町村、{tot['schools']} 校（おおよその区域 {tot['approx_schools']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
