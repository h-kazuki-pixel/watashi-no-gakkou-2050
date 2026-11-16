"""まとめた区域：メッシュの行政区域コードが、複数の市町村をまとめた1つのコードになっている区域（docs/DATA_METHOD.md）。

福島県の浜通り13市町村は、国の推計（国立社会保障・人口問題研究所 令和5年推計）が13市町村で1つ（浜通り地域）で、
国土数値情報のメッシュでも 07999 という1つのコードで入っている。市町村ごとの推計値は無い。

表：pipeline/terms/fukushima_hamadori.csv
  行政区域コード,市町村名,まとめた区域のコード,扱い,5〜14歳_2020_原数値,5〜14歳_2020_不詳補完値,児童数_2025-05-01,出典
扱いが「出す（注意書きつき）」の市町村は画面に出し、「出さない」の市町村は学校を出力しない（その区域の子どもは
「扱わない区域」として、ほかの市町村の学校に回さない）。
"""
from __future__ import annotations

import csv
import pathlib

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "terms" / "fukushima_hamadori.csv"


def load(path=None) -> dict:
    """{まとめた区域のコード: {市町村コード: {"name", "show", "kids_514_2020", "children_2025"}}}。ファイルが無ければ空。"""
    p = pathlib.Path(path) if path else DEFAULT
    if not p.exists():
        return {}
    out: dict = {}
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            code = (r.get("行政区域コード") or "").strip()
            area = (r.get("まとめた区域のコード") or "").strip()
            if not (code.isdigit() and area.isdigit()):
                continue
            how = (r.get("扱い") or "").strip()
            if how not in ("出す（注意書きつき）", "出さない"):
                raise ValueError(f"{p}: 扱いは「出す（注意書きつき）」か「出さない」: {code} {how}")
            out.setdefault(area.zfill(5), {})[code.zfill(5)] = {
                "name": (r.get("市町村名") or "").strip(), "show": how.startswith("出す"),
                "kids_514_2020": int(r["5〜14歳_2020_原数値"]) if (r.get("5〜14歳_2020_原数値") or "").strip() else None,
                "children_2025": int(r["児童数_2025-05-01"]) if (r.get("児童数_2025-05-01") or "").strip() else None,
            }
    return out
