#!/usr/bin/env python3
"""政令指定都市の「区 → 市」の対応表（pipeline/terms/designated_city_wards.csv）を作る。

元データ：国土数値情報「行政区域コード」（AdminiBoundary_CD.xlsx、令和6年1月1日現在）
  https://nlftp.mlit.go.jp/ksj/gml/codelist/AdminiBoundary_CD.xlsx
  （総務省「全国地方公共団体コード」に改正情報を加えて国土数値情報が作成したもの）

    python3 tools/make_ward_table.py AdminiBoundary_CD.xlsx > pipeline/terms/designated_city_wards.csv

決め方（コードの並びに頼らない。札幌市の 01110 のように10の位をまたぐ区もあるため）
  - 政令指定都市：市区町村名が「〜市」で、同じ都道府県に「その市の名前＋〜区」という行がある市。
    改定区分が「欠番」の行（政令市になる前の市のコードなど）は、市としては使わない
  - 区：名前が「政令指定都市の名前＋〜区」の行。欠番の区（再編前の区）も、改正後のコードと名称をつけて入れる
必要なのは openpyxl だけ。
"""
from __future__ import annotations

import csv
import datetime
import sys

import openpyxl

COLUMNS = ["区のコード", "区の名称", "市のコード", "市の名称", "状態", "改正年月日", "改正後のコード", "改正後の名称", "改正事由"]


def _date(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        return v.date().isoformat()
    if isinstance(v, (int, float)):  # Excel の日付シリアル値
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))).isoformat()
    return str(v).strip()


def read_rows(path) -> list[dict]:
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    head = next(i for i, r in enumerate(rows) if r and r[0] == "行政区域コード")
    out = []
    for r in rows[head + 1:]:
        if not r or not r[0] or not r[2]:
            continue
        out.append({"code": str(r[0]).strip().zfill(5), "pref": r[1], "name": str(r[2]).strip(), "status": r[5] or "",
                    "date": _date(r[6]), "new_code": str(r[7] or "").strip(), "new_name": str(r[8] or "").strip(),
                    "reason": str(r[10] or "").strip()})
    return out


def build(rows: list[dict]) -> list[dict]:
    live = [r for r in rows if r["status"] != "欠番"]
    cities = {}
    for r in live:
        if r["name"].endswith("市") and any(w["pref"] == r["pref"] and w["code"] != r["code"] and w["name"].startswith(r["name"])
                                           and w["name"].endswith("区") for w in rows):
            cities[r["code"]] = r
    merged: dict = {}
    for w in rows:
        if not w["name"].endswith("区"):
            continue
        city = next((c for c in cities.values() if c["pref"] == w["pref"] and w["name"].startswith(c["name"])
                     and w["name"] != c["name"]), None)
        if not city:
            continue
        key = w["code"]
        if key in merged:  # 再編で2つの区に分かれた区（浜松市北区）は、改正後のコードを「/」でつなぐ
            m = merged[key]
            m["改正後のコード"] += "/" + w["new_code"]
            m["改正後の名称"] += "/" + w["new_name"]
            m["改正事由"] += "／" + w["reason"]
            continue
        merged[key] = {"区のコード": w["code"], "区の名称": w["name"], "市のコード": city["code"], "市の名称": city["name"],
                       "状態": "欠番" if w["status"] == "欠番" else "現行", "改正年月日": w["date"] if w["status"] == "欠番" else "",
                       "改正後のコード": w["new_code"] if w["status"] == "欠番" else "",
                       "改正後の名称": w["new_name"] if w["status"] == "欠番" else "", "改正事由": w["reason"] if w["status"] == "欠番" else ""}
    return [merged[k] for k in sorted(merged)]


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    out = build(read_rows(argv[0]))
    w = csv.DictWriter(sys.stdout, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(out)
    print(f"区 {len(out)}（政令指定都市 {len({r['市のコード'] for r in out})}、欠番の区 {sum(r['状態'] == '欠番' for r in out)}）",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
