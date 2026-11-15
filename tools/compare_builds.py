#!/usr/bin/env python3
"""2回の生成（build / build-all）の出力を比べ、違う所を学校単位で出す。

    python3 tools/compare_builds.py --old-app OLD/app/data --old-od OLD/opendata \
                                    --new-app app/data --new-od opendata [--pref 40]

比べるもの（県ごと）
  pref_XX.js                       … 市区町村（名前・印）と学校（名前・位置・推計・各歳・区域）
  school_district_children_XX.csv  … 学校ごとの行
  report_XX.json                   … 検査の値
次の欄は生成のたびに変わるので比べない：
  pref_XX.js の generated（生成日）、report_XX.json の seconds（実行時間）と validate_approx（validate-approx が書き足す）

違いが無ければ「違いなし」と出して 0 で終わる。違いがあれば 1 で終わる。
学校は id（学校コード）で突き合わせる。学校名は手元の確認用で、出力を公開物に貼らないこと。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys

IGNORE_PREF = {"generated"}
IGNORE_REPORT = {"seconds", "validate_approx"}


def load_pref(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    m = re.search(r"UG\.registerPref\((.*)\);\s*$", path.read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1))


def load_csv(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {r["school_id"]: r for r in csv.DictReader(fh)}


def load_report(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k not in IGNORE_REPORT}


def _schools(pref: dict) -> dict:
    out = {}
    for c in pref["cities"]:
        for s in c["schools"]:
            out[s["id"]] = {**s, "_city": c["code"], "_city_name": c["name"]}
    return out


def diff_pref(old: dict, new: dict) -> list[str]:
    lines = []
    for k in sorted((set(old) | set(new)) - IGNORE_PREF - {"cities"}):
        if old.get(k) != new.get(k):
            lines.append(f"  [県] {k}: {json.dumps(old.get(k), ensure_ascii=False)} → {json.dumps(new.get(k), ensure_ascii=False)}")
    oc = {c["code"]: c for c in old["cities"]}
    nc = {c["code"]: c for c in new["cities"]}
    for code in sorted(set(oc) | set(nc)):
        a, b = oc.get(code), nc.get(code)
        if a is None:
            lines.append(f"  [市区町村] 増えた {code} {b['name']}（{len(b['schools'])}校）")
            continue
        if b is None:
            lines.append(f"  [市区町村] 無くなった {code} {a['name']}（{len(a['schools'])}校）")
            continue
        for k in sorted((set(a) | set(b)) - {"schools"}):
            if a.get(k) != b.get(k):
                lines.append(f"  [市区町村] {code} {a['name']} {k}: {a.get(k)} → {b.get(k)}")
        if len(a["schools"]) != len(b["schools"]):
            lines.append(f"  [市区町村] {code} {a['name']} 学校数: {len(a['schools'])} → {len(b['schools'])}")
    os_, ns = _schools(old), _schools(new)
    for sid in sorted(set(os_) | set(ns)):
        a, b = os_.get(sid), ns.get(sid)
        if a is None:
            lines.append(f"  [学校] 増えた {sid} {b['_city_name']} {b['name']}（2025年 {b['est'][0]}）")
            continue
        if b is None:
            lines.append(f"  [学校] 無くなった {sid} {a['_city_name']} {a['name']}（2025年 {a['est'][0]}）")
            continue
        keys = [k for k in sorted((set(a) | set(b)) - {"_city_name"}) if a.get(k) != b.get(k)]
        if keys:
            what = []
            for k in keys:
                if k == "est":
                    what.append(f"2025年 {a['est'][0]} → {b['est'][0]}" + ("" if a["est"][1:] == b["est"][1:] else "（ほかの年も）"))
                elif k in ("geom", "ages"):
                    what.append(f"{k} が違う")
                else:
                    what.append(f"{k}: {a.get(k)} → {b.get(k)}")
            lines.append(f"  [学校] 変わった {sid} {a['_city_name']} {a['name']}：" + "、".join(what))
    return lines


def diff_csv(old: dict, new: dict) -> list[str]:
    lines = []
    for sid in sorted(set(old) | set(new)):
        a, b = old.get(sid), new.get(sid)
        if a is None or b is None:
            r = a or b
            lines.append(f"  [CSV] {'増えた' if a is None else '無くなった'}行 {sid} {r.get('city_name', '')} {r.get('school_name', '')}")
            continue
        keys = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        if keys:
            lines.append(f"  [CSV] 変わった行 {sid} {a.get('school_name', '')}：" + "、".join(f"{k}: {a.get(k)} → {b.get(k)}" for k in keys))
    return lines


def diff_report(old: dict, new: dict) -> list[str]:
    lines = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            for kk in sorted(set(a) | set(b)):
                if a.get(kk) != b.get(kk):
                    lines.append(f"  [検査] {k}.{kk}: {json.dumps(a.get(kk), ensure_ascii=False)} → {json.dumps(b.get(kk), ensure_ascii=False)}")
        else:
            lines.append(f"  [検査] {k}: {json.dumps(a, ensure_ascii=False)} → {json.dumps(b, ensure_ascii=False)}")
    return lines


def compare(old_app, old_od, new_app, new_od, prefs=None) -> list[str]:
    old_app, old_od, new_app, new_od = map(pathlib.Path, (old_app, old_od, new_app, new_od))
    if not prefs:
        found = {p.stem[5:] for d in (old_app, new_app) for p in d.glob("pref_*.js")}
        prefs = sorted(found)
    out = []
    for pref in prefs:
        lines = []
        for kind, load, diff, a, b in (
                ("pref", load_pref, diff_pref, old_app / f"pref_{pref}.js", new_app / f"pref_{pref}.js"),
                ("csv", load_csv, diff_csv, old_od / f"school_district_children_{pref}.csv", new_od / f"school_district_children_{pref}.csv"),
                ("report", load_report, diff_report, old_od / f"report_{pref}.json", new_od / f"report_{pref}.json")):
            x, y = load(a), load(b)
            if x is None and y is None:
                continue
            if x is None or y is None:
                lines.append(f"  [{kind}] {'前' if x is None else 'あと'}に無い: {a if x is None else b}")
                continue
            lines += diff(x, y)
        out.append(f"== {pref}: " + ("違いなし" if not lines else f"違い {len(lines)} 件"))
        out += lines
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old-app", required=True, help="前の pref_XX.js のフォルダ")
    ap.add_argument("--old-od", required=True, help="前の report_XX.json・CSV のフォルダ")
    ap.add_argument("--new-app", required=True)
    ap.add_argument("--new-od", required=True)
    ap.add_argument("--pref", action="append", help="比べる県コード（くり返し指定できる）。省略するとすべて")
    a = ap.parse_args(argv)
    lines = compare(a.old_app, a.old_od, a.new_app, a.new_od, a.pref)
    print("\n".join(lines))
    return 0 if all(not l.startswith("  ") for l in lines) else 1


if __name__ == "__main__":
    sys.exit(main())
