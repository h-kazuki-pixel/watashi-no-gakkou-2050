#!/usr/bin/env python3
"""tools/national_dryrun.py の結果（県ごとのフォルダ）をまとめて、県コード順の集計表（CSV と Markdown）を作る。

    python3 tools/dryrun_summary.py --work /path/to/work --out /path/to/summary

出力：summary.csv、summary.md（集計表・外れ値の上位・県ごとの注意）。学校名は、学校コードが無く位置も無い学校など、
確認に要るものだけを Markdown の注意に出す（推計の値と学校名の組は出さない）。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from school2050.export import PREF_NAMES  # noqa: E402

WATCH = {"14206": "小田原市"}  # 表に印を付ける市区町村
GEOM: dict = {}   # --geom（学区の形の問題の数え上げ）
FIRST: dict = {}  # 予行をやり直した県の、初回の失敗


def load(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def row_for(d: pathlib.Path) -> dict:
    pref = d.name
    st = load(d / "status.json") or {}
    ex = load(d / "extra.json") or {}
    rp = load(d / "od" / f"report_{pref}.json") or {}
    mesh, sch, dis, out, loc = (ex.get(k) or {} for k in ("mesh", "schools", "districts", "output", "location"))
    approx = rp.get("approx_cities") or {}
    cov = rp.get("city_coverage_2025") or {}
    low = {k: v for k, v in cov.items() if "_" not in k and v < 0.9 and k not in approx}
    cc = rp.get("city_coded_districts") or {}
    city_schools = out.get("city_schools") or {}
    va = (rp.get("validate_approx") or {}).get("pref") or {}
    ind = (st.get("steps") or {}).get("independent_check") or {}
    if ind.get("rc") == "未対応":
        ind_s = "未対応"
    elif ind.get("result") == "一致":
        ind_s = "一致"
    elif ind.get("result"):
        ind_s = (f"不一致（アプリだけ{ind.get('only_app')}・検算だけ{ind.get('only_check')}・区分{ind.get('meta')}・"
                 f"0.06人超 学区{ind.get('bad_district')}/おおよそ{ind.get('bad_approx')}、最大{ind.get('worst')}人）")
    else:
        ind_s = str(ind.get("rc", ""))
    fail = []
    for k, v in (st.get("downloads") or {}).items():
        if not v.get("ok"):
            fail.append(f"download:{k}: {v.get('status') or ''} {v.get('error', '')}".strip())
    for k, v in (st.get("steps") or {}).items():
        if v.get("rc") not in (0, "未対応", "skipped"):
            fail.append(f"{k}: {v.get('error_last') or v.get('error_first') or v.get('rc')}")
    def ex_codes(r):  # excluded_by_terms は、以前はコードの並び、いまは {code, name, reason} の並び
        return {e["code"] if isinstance(e, dict) else e for e in (r.get("excluded_by_terms") or [])}
    flags = [f"{n}（{c}）: " + (f"{city_schools[c][1]}校" if c in city_schools else "出力に無い")
             + ("・除外" if c in ex_codes(rp) else "") + ("・めやす" if c in (rp.get("note_cities") or []) else "")
             + ("・おおよそ" if c in approx else "")
             for c, n in WATCH.items() if c[:2] == pref]
    return {
        "県コード": pref, "県": PREF_NAMES.get(pref, pref),
        "メッシュ形式": mesh.get("format", ""), "学区データ": "A27-23（令和5年度）" if (st.get("downloads") or {}).get("districts", {}).get("ok") else "取れない",
        "市区町村": rp.get("cities", ""), "学校": rp.get("schools", ""),
        "おおよその市区町村": len(approx), "おおよその学校": sum(approx.values()) if approx else 0,
        "missing": len(rp.get("missing_cities") or []),
        "補った学校": sum((rp.get("filled_missing_schools") or {}).values()),
        "保存則の誤差": rp.get("conservation_error", ""), "未配分の割合": rp.get("unassigned_share_2025", ""),
        "配分率0.9未満の数": len(low), "配分率0.9未満の最小": min(low.values()) if low else "",
        "市のコードの政令市": "・".join(f"{v['name']}{city_schools.get(c, ['', '?'])[1]}校" for c, v in cc.items()),
        "再編前の区で出す": "・".join(f"{c}" for c in (rp.get("obsolete_ward_cities") or {})),
        "P29_007（公立小）": " ".join(f"{k or '空'}:{v}" for k, v in (sch.get("p29_007_public_elementary") or {}).items()),
        "休校で外した": len(rp.get("closed_schools_excluded") or []),
        "義務教育学校C2": sch.get("compulsory_c2", ""), "C2うちおおよそ": len(sch.get("compulsory_c2_in_approx_cities") or []),
        "位置なし（コード無・P29無）": loc.get("no_code_and_not_in_p29", ""), "P29に無い学区の学校": loc.get("not_in_p29", ""),
        "重心ピン（今の生成）": out.get("centroid_pins", ""),
        "利用条件で除外": len(rp.get("excluded_by_terms") or []), "めやす": len(rp.get("note_cities") or []),
        "pref_js_KB": round(out["pref_js_bytes"] / 1024) if out.get("pref_js_bytes") else "",
        "validate学校": va.get("schools", ""), "validate絶対ずれ中央値": va.get("abs_median", ""),
        "independent_check": ind_s,
        "秒（DL/inspect/build/validate/indep）": "/".join(str(round(x)) if isinstance(x, (int, float)) else "-" for x in (
            sum(v.get("seconds") or 0 for v in (st.get("downloads") or {}).values()),
            *[((st.get("steps") or {}).get(k) or {}).get("seconds") for k in ("inspect", "build", "validate_approx", "independent_check")])),
        "容量MB（zip/出力）": "/".join(f"{(st.get('disk') or {}).get(k, 0) / 1e6:.0f}" for k in ("zips_bytes", "outputs_bytes")) if st.get("disk") else "",
        "形の問題（重複リング/穴が外/部分の重なり）": "/".join(str(len((GEOM.get(pref) or {}).get(k, []))) for k in ("duplicate_rings", "hole_outside_outer", "overlapping_parts")) if GEOM else "",
        "初回の失敗": FIRST.get(pref, ""),
        "印": " ".join(flags),
        "失敗": " / ".join(fail),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--geom", help="学区の形の問題（県コード → duplicate_rings / hole_outside_outer / overlapping_parts）の JSON")
    a = ap.parse_args(argv)
    work, out = pathlib.Path(a.work), pathlib.Path(a.out)
    if a.geom:
        GEOM.update(json.loads(pathlib.Path(a.geom).read_text(encoding="utf-8")))
    for d in work.iterdir():
        f = d / "status_first.json"
        if f.exists():
            s0 = json.loads(f.read_text(encoding="utf-8"))
            bad = [f"{k}: {v.get('error_last') or v.get('rc')}" for k, v in (s0.get("steps") or {}).items() if v.get("rc") not in (0, "skipped", "未対応")]
            FIRST[d.name] = " / ".join(b[:80] for b in bad)
    out.mkdir(parents=True, exist_ok=True)
    rows = [row_for(d) for d in sorted(work.iterdir()) if d.is_dir() and re.fullmatch(r"\d{2}", d.name) and (d / "status.json").exists()]
    if not rows:
        raise SystemExit("結果がありません")
    cols = list(rows[0].keys())
    with (out / "summary.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        md.append("| " + " | ".join(str(r[c]).replace("|", "／") for c in cols) + " |")
    # 外れ値の上位5
    def top(key, rev=True, fn=float):
        vals = [(fn(r[key]), r["県"]) for r in rows if r[key] not in ("", None)]
        return sorted(vals, reverse=rev)[:5]
    share = [(r["おおよその学校"] / r["学校"] if r["学校"] else 0, r["県"]) for r in rows]
    md += ["", "### 外れ値の上位5",
           "- 未配分の割合: " + "、".join(f"{n} {v:.4f}" for v, n in top("未配分の割合")),
           "- 配分率0.9未満の最小（低い順）: " + "、".join(f"{n} {v}" for v, n in top("配分率0.9未満の最小", rev=False)),
           "- 配分率0.9未満の市区町村の数: " + "、".join(f"{n} {int(v)}" for v, n in top("配分率0.9未満の数")),
           "- おおよその区域の学校の割合: " + "、".join(f"{n} {v:.2f}" for v, n in sorted(share, reverse=True)[:5]),
           "- validate 絶対ずれの中央値: " + "、".join(f"{n} {v}" for v, n in top("validate絶対ずれ中央値")),
           "- pref_XX.js の大きさ（KB）: " + "、".join(f"{n} {int(v)}" for v, n in top("pref_js_KB"))]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(rows)}県: {out / 'summary.csv'}, {out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
