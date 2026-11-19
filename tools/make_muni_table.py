#!/usr/bin/env python3
"""町字データ（アドレス・ベース・レジストリ 全国 町字マスター）から、市区町村コード → 今の市区町村名の表を作る。

    python3 tools/make_muni_table.py ~/work/abr/mt_town_all.csv.zip > pipeline/terms/muni_names.csv

名前は町字データの city ＋ ward（政令市の区は「横浜市鶴見区」）。政令市を市で1つにまとめた市区町村（市のコード。町字データには無い）は、
pipeline/terms/designated_city_wards.csv で区から市のコードを引き、その区の行の city（「横浜市」）にする。
1つのコードに名前が2つ以上あれば止める（どちらかを選んで進めない）。build はこの表で市区町村名を確かめる（docs/DATA_METHOD.md「市区町村の名前」）。
"""
from __future__ import annotations

import csv
import io
import pathlib
import sys
import zipfile
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from school2050 import wards  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    names = defaultdict(set)
    cities = defaultdict(set)  # 政令市の市のコード → city
    ward_to_city = {c: w.city for c, w in wards.load().items()}
    with zipfile.ZipFile(argv[0]) as z:
        members = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not members:
            raise SystemExit(f"{argv[0]} に CSV がありません")
        for n in members:
            with z.open(n) as fh:
                rd = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"))
                for col in ("lg_code", "city", "ward"):
                    if col not in (rd.fieldnames or []):
                        raise SystemExit(f"町字データに列 {col} がありません（列：{rd.fieldnames}）")
                for r in rd:
                    code = r["lg_code"][:5]
                    names[code].add(r["city"] + r["ward"])
                    if code in ward_to_city:
                        cities[ward_to_city[code]].add(r["city"])
    for code, ns in list(names.items()) + list(cities.items()):
        if len(ns) != 1:
            raise SystemExit(f"{code} に名前が2つ以上あります: {sorted(ns)}")
    out = {**{c: next(iter(v)) for c, v in cities.items()}, **{c: next(iter(v)) for c, v in names.items()}}
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["市区町村コード", "名称"])
    for c in sorted(out):
        w.writerow([c, out[c]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
