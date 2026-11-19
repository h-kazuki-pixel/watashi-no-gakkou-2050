#!/usr/bin/env python3
"""アプリの id → もとの学校コード（A27 か P29）の表を、県を作り直して取る（make-closures の入力）。

id は学校コードが基本だが、学校コードが空・県内で重なる・別の市区町村の学校のコードの学校は「市区町村コード-番号」になり、
app/data からはもとのコードが分からない（docs/DATA_METHOD.md「元データの行政区域コードや学校コードの誤り」の3）。
この道具は、その県だけ build-all を作業用フォルダに作り直し、export.build_pref に渡る学区（features）から、
同じ規則で id を付け直して、もとの学校コードと学区データの元の属性を書き出す。app/data と opendata には書かない。

    python3 tools/capture_school_codes.py --pref 07 --work WORK [--generated 2026-11-17]

できるもの（WORK/）
  ids_07.csv     pref,id,city,name,raw_code,why,approx,fill,props（props は id が学校コードでない学校だけ、元の属性の JSON）
  app/ od/       作り直した pref_07.js・report_07.json・school_district_children_07.csv（compare_builds で比べられる）
作り直した学校の集合が build_pref の出力と違えば止まる。zip は TMPDIR に展開される（呼ぶ側で1つのフォルダに決め、終わったら消す）。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEADER = ["pref", "id", "city", "name", "raw_code", "why", "approx", "fill", "props"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pref", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--input", default=str(ROOT / "data_raw"), help="国土数値情報の zip のフォルダ")
    ap.add_argument("--generated", help="生成日（今の app/data と比べるときは同じ日にする）")
    a = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / "pipeline"))
    import build_school_data as bsd  # noqa: E402
    from school2050 import export  # noqa: E402

    pref = a.pref.zfill(2)
    work = pathlib.Path(a.work)
    ind = work / "in" / pref
    ind.mkdir(parents=True, exist_ok=True)
    raw = pathlib.Path(a.input)
    for name in (f"A27-23_{pref}_GML.zip", f"500m_mesh_2024_{pref}_GML.zip", f"P29-23_{pref}_GML.zip"):
        src = raw / name
        if not src.exists():
            raise SystemExit(f"元データがありません: {src}")
        dst = ind / name
        if not dst.exists():
            dst.symlink_to(src.resolve())
    if (raw / "retrieved.csv").exists():
        (ind / "retrieved.csv").write_text((raw / "retrieved.csv").read_text(encoding="utf-8"), encoding="utf-8")

    captured = []
    orig = export.build_pref

    def wrap(pref_code, features, fields, sums, years, n_years, school_points=None, city_overrides=None, source=None,
             min_children=1.0, generated=None):
        obj, rows = orig(pref_code, features, fields, sums, years, n_years, school_points, city_overrides, source,
                         min_children, generated=generated)
        # export.build_pref と同じ規則で id を付け直す
        used = set()
        for i, f in enumerate(features):
            if f.props.get("_non_school") or sums[i, 0] < min_children:
                continue
            raw_code = f.props.get(fields.school_code, "") if fields.school_code else ""
            sid, why = raw_code, ""
            if not sid:
                why = "学校コードが空"
            elif sid in used:
                why = "県内で学校コードが重なる"
            elif f.props.get("_code_other_city"):
                why = f"学校コードが別の市区町村（{f.props['_code_other_city']}）の学校のもの"
            if why:
                sid = f"{f.props['_city']}-{i:04d}"
            used.add(sid)
            props = ""
            if sid != raw_code:
                props = json.dumps({k: v for k, v in f.props.items() if not k.startswith("_")}, ensure_ascii=False)
            captured.append({"pref": pref_code, "id": sid, "city": f.props["_city"], "name": f.props.get(fields.name, ""),
                             "raw_code": raw_code, "why": why, "approx": "1" if f.props.get("_approx") else "",
                             "fill": "1" if f.props.get("_fill") else "", "props": props})
        ids = {s["id"] for c in obj["cities"] for s in c["schools"]}
        got = {r["id"] for r in captured if r["pref"] == pref_code}
        if ids != got:
            raise SystemExit(f"{pref_code}: 付け直した id が build_pref の出力と合いません（{len(ids ^ got)}件）")
        return obj, rows

    export.build_pref = wrap
    args = ["build-all", "--input", str(ind), "--out", str(work / "app"), "--opendata", str(work / "od")]
    if a.generated:
        args += ["--generated", a.generated]
    rc = bsd.main(args)
    if not captured:
        raise SystemExit(f"{pref}: 学校が1校も取れませんでした")
    out = work / f"ids_{pref}.csv"
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(captured)
    print(f"{out}: {len(captured)}行（build-all の終了コード {rc}）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
