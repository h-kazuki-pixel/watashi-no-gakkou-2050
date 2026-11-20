#!/usr/bin/env python3
"""全都道府県の report_XX.json と app/data/pref_XX.js から、扱いの一覧（docs/COVERAGE.md）を作る。

    python3 tools/coverage_doc.py --app app/data --od opendata --out docs/COVERAGE.md

学校ごとの実際の児童数は使わない（入力は生成物だけ）。
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import sys

PREF_NAMES = None
# 文科省の学校名の先頭の設置者名（「○○市立」など。pipeline/school2050/closures.py の OWNER_RE と同じ形）
OWNER_RE = re.compile(r"^(?:北海道|東京都|大阪府|京都府|[^\s]{2,3}県)?(?:[^市区町村郡\s]{1,6}郡)?[^\s]{1,10}?[市区町村]立(?=.)")


def load_pref(path: pathlib.Path) -> dict:
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("UG.registerPref(") + 16:s.rindex(")")])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app/data")
    ap.add_argument("--od", default="opendata")
    ap.add_argument("--out", default="docs/COVERAGE.md")
    ap.add_argument("--causes", default="tools/unassigned_causes.csv", help="どの学校にも入らなかった子どもの多い市区町村と、地図で見た原因")
    ap.add_argument("--name-fix", help="tools/name_fix_review.py の name_fix.csv（無ければ OD/closures_review/name_fix.csv）。"
                    "「決められない」のまま残った学校を一覧にする")
    a = ap.parse_args()
    app, od = pathlib.Path(a.app), pathlib.Path(a.od)
    prefs = sorted(p.stem.split("_")[1] for p in app.glob("pref_[0-9][0-9].js"))
    rows, approx_c, nothandled, excluded, filled, closed, nopts, geom, fixes, notes = [], [], [], [], [], [], [], [], [], []
    nonsch = []  # 学校ではない区域（report の non_school_areas）
    small = []  # 学区データに無く、補っても2025年の推計が1人未満で出ない学校
    tot = collections.Counter()
    left = []  # (県コード, 県名, どの学校にも入らなかった子ども, メッシュの子ども)
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
        for e in rep.get("filled_missing_dropped_small_schools", []):
            small.append((p, e["city"], f"| {pname} | {names.get(e['city'], e['city'])} | {e['name']} | 1人未満 |"))
        for e in rep.get("schools_without_points", []):
            if e["how"] == "学区データに無い学校":
                small.append((p, e["city"], f"| {pname} | {names.get(e['city'], e['city'])} | {e['name']} | 当たる点が無い（0人） |"))
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
        left.append((p, pname, rep.get("unassigned_2025", 0.0), rep.get("mesh_children_2025", 0.0)))
        for e in rep.get("non_school_areas") or []:
            nonsch.append((pname, names.get(e["city"], e["city"]), e["name"], e.get("est_2025", 0.0), e["reason"]))
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
    w("配分率0.9未満の市区町村では、どの学区にも入らなかった点を補う学校の中でいちばん近い学校に当てる。")
    w("0.9以上の市区町村では、学区データの学校も含めた公立小学校でいちばん近い学校が補う学校になる点だけを当てる（DATA_METHOD.md）。")
    w("")
    w("| 都道府県 | 学校数 | 市区町村 学校 |")
    w("|---|---|---|")
    L.extend(filled)
    w("")
    w("## 学区データに無く、補っても1人未満で出ない学校")
    w("")
    w("学区データに無いので補う学校にしたが、当たった点の2025年の推計が1人未満だった（当たる点が1つも無かったものを含む）ので出していない学校。")
    w("当たる点が無かった学校は、下の「割り当たる点が無くて出なかった学校」にも出ています。")
    w("")
    w("| 都道府県 | 市区町村 | 学校 | 理由 |")
    w("|---|---|---|---|")
    small = sorted(set(small), key=lambda t: (t[0], t[1], t[2]))  # 学校の位置データに同じ学校が2つあるもの（大町市 八坂小中）は1回
    L.extend(r for *_k, r in small)
    w(f"\n計 {len(small)} 校（1人未満 {sum('1人未満' in r for *_k, r in small)}、当たる点が無い {sum('0人' in r for *_k, r in small)}）。")
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
    w("## どの学校にも入らなかった子ども")
    w("")
    ua, mc = sum(x[2] for x in left), sum(x[3] for x in left)
    w(f"2025年の6〜11歳の推計 {mc:,.0f}人のうち、{ua:,.0f}人（{ua / mc * 100:.2f}%）は、どの学校の数字にも入っていません（`report_XX.json` の `unassigned_2025`）。")
    w("メッシュに 4×4 の点を置き、点が入る学区に人口を配る（DATA_METHOD.md「計算」）ので、学区の外に落ちた点の子どもはどこにも足していません。")
    w("学区のある学校の数字は変えない、という決まりのためです（配分率0.9以上の市区町村で学区データに無い学校を補うときも、")
    w("学区データの学校のほうが近い点は、どの学校にも当てません）。")
    w("")
    w("| 都道府県 | 人数（2025年） | 割合 |")
    w("|---|---|---|")
    for x in left:
        w(f"| {x[1]} | {x[2]:,.1f} | {x[2] / x[3] * 100 if x[3] else 0:.2f}% |")
    w("")
    if nonsch:
        w("### 学校ではない区域")
        w("")
        w("学区データの区域のうち、学校名が学校を指さないもの（表 `pipeline/terms/non_school_areas.csv`。DATA_METHOD.md「学校ではない区域」）は、学校として出しません。")
        w("区域の中の点はこの区域に入れたまま（ほかの学校にも補いにも使わない）、その子どもは上の「どの学校にも入らなかった子ども」に数えています。")
        w("")
        w("| 都道府県 | 市区町村 | 学区データの学校名 | 人数（2025年） | 理由 |")
        w("|---|---|---|---|---|")
        for x in nonsch:
            w(f"| {x[0]} | {x[1]} | {x[2]} | {x[3]:,.1f} | {x[4]} |")
        w(f"\n計 {len(nonsch)} 区域、{sum(x[3] for x in nonsch):,.1f}人。")
        w("")
    cp = pathlib.Path(a.causes)
    if cp.exists():
        w("人数の多い市区町村で、どの学区にも入らなかった点を学区の図形と重ねて地図にし、原因を分けました（2026-11-17）。分類：")
        w("ア＝学区データ（令和5年度）より後にできた学校・学区データに無い学校の区域、イ＝学区の図形のすき間・欠け、")
        w("ウ＝子どもが通う公立小学校の無い区域（基地など）、エ＝その他（県境をまたぐメッシュの県の外側の部分、川・海・湖の水面に置かれた点）。")
        w("エは、メッシュの中で人口が一様という仮定から出るもので、その子どもは実際には近くの学区に住んでいるとみられます（近くの学校の数字が少し小さめ）。")
        w("")
        w("| 都道府県 | 市区町村 | 人数（2025年） | 分類 | 見たこと |")
        w("|---|---|---|---|---|")
        pn = {x[0]: x[1] for x in left}
        for r in csv.DictReader(open(cp, encoding="utf-8")):
            w(f"| {pn.get(r['都道府県コード'], r['都道府県コード'])} | {r['市区町村']} | {float(r['2025年の人数']):,.1f} | {r['分類']} | {r['見たこと']} |")
        w("")
        w("市区町村ごとの人数は、`tools/independent_check.py` と同じ計算で、どの学区にも入らず補いにも当たらなかった点を、メッシュの市区町村コードごとに足したもの（県ごとの合計は `unassigned_2025` と一致）。")
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
    # 学区データの名前と学校コードが食い違い、どちらの学校の区域か決められない学校（name_fix.csv の「決められない」の対象の行）
    nf = pathlib.Path(a.name_fix) if a.name_fix else od / "closures_review" / "name_fix.csv"
    if not nf.exists():
        sys.exit(f"{nf} がありません（tools/name_fix_review.py の出力）")
    by_id = {}
    for p in prefs:
        obj = load_pref(app / f"pref_{p}.js")
        for c in obj["cities"]:
            for s in c["schools"]:
                by_id[(p, s["id"])] = (obj["name"], c["name"], s)
    und = []
    with open(nf, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["役割"] != "対象" or r["判定"] != "決められない":
                continue
            hit = by_id.get((r["都道府県"], r["id"]))
            if not hit or hit[2]["name"] != r["アプリの学校名"]:
                sys.exit(f"{nf}: app/data に無い学校です（id・学校名が合わない）: {r['都道府県']} {r['id']} {r['アプリの学校名']}")
            code_name = OWNER_RE.sub("", r["文科省のそのコードの名前"], count=1)
            und.append((r["都道府県"], hit[0], hit[1], r["アプリの学校名"], code_name, r["決められない理由"], hit[2]["est"][0]))
    if und:
        w("## 学区データの名前と学校コードが食い違い、どちらの学校の区域か決められない学校")
        w("")
        w("学区データの1つの区域に、ある学校の名前と、別の学校の学校コード・所在地が入っています。どちらの学校の点もその区域の中にあり、"
          "区域がどちらの学校のものか、2校分なのかを、手元のデータでは決められません。名前も数字も変えていません。")
        w("")
        w("決め方は DATA_METHOD.md「元データの行政区域コードや学校コードの誤り」の5（表は `tools/name_fix_review.py` の `name_fix.csv`）。"
          "理由の (a) はアプリの学校名の学校、(b) は学校コードが指す学校（どちらも国土数値情報「学校」の点と所在地）。")
        w("")
        w("| 都道府県 | 市区町村 | アプリの学校名 | 学校コードが指す学校 | 決められない理由 | 人数（2025年） |")
        w("|---|---|---|---|---|---|")
        for x in sorted(und, key=lambda x: (x[0], x[2], x[3])):
            w(f"| {x[1]} | {x[2]} | {x[3]} | {x[4]} | {x[5]} | {x[6]:,.1f} |")
        w(f"\n計 {len(und)} 校。")
        w("")
    pathlib.Path(a.out).write_text("\n".join(L), encoding="utf-8")
    print(f"{a.out}: {len(prefs)} 都道府県、{tot['cities']} 市区町村、{tot['schools']} 校（おおよその区域 {tot['approx_schools']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
