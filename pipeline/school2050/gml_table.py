"""国土数値情報の GML（JPGIS）から、メッシュの属性を表として読む。

GML の要素名は年度で変わりうるので決め打ちにしない。
  1. gml:id を持ち、8〜10桁のメッシュコードを含む要素を「1メッシュ」とみなす
  2. その中の葉要素（子を持たない要素）を、文書の順に列として並べる（座標の要素は除く）
  3. 列名に年（2025 など）が入っていれば、そのまま使う（あとの判定は CSV と同じ）
  4. 入っていなければ、公式コード表の並び（CSV の985列、SHP の343列）と数が合うときだけ、その名前を当てる
ファイルが大きくても読めるよう、iterparse で1メッシュずつ処理して捨てる。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pandas as pd

YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060, 2065, 2070]
_MESH_RE = re.compile(r"^\d{8,10}$")
_GEOM = {"pos", "posList", "coordinates", "lowerCorner", "upperCorner"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def official_columns(with_sex: bool) -> list[str]:
    """公式コード表の列名（CSV は男女別あり＝985列、SHP 属性は男女計のみ＝343列）。"""
    cols = ["MESH_ID", "SHICODE", "PTN_2020"] + (["PMN_2020", "PFN_2020"] if with_sex else [])
    for y in YEARS:
        cols += [f"HITOKU{y}", f"GASSAN{y}"]
        for sx in (("T", "M", "F") if with_sex else ("T",)):
            cols += [f"P{sx}N_{y}"] + [f"P{sx}{i:02d}_{y}" for i in range(21)]
            cols += [f"P{sx}{c}_{y}" for c in "ABCDE"] + [f"R{sx}{c}_{y}" for c in "ABCDE"]
    return cols


def _leaves(el) -> list[tuple[str, str]]:
    out = []
    for e in el.iter():
        if e is el or len(e):
            continue
        name = _local(e.tag)
        if name in _GEOM:
            continue
        txt = (e.text or "").strip()
        if not txt and any(k.endswith("href") for k in e.attrib):  # 図形への参照
            continue
        out.append((name, txt))
    return out


def read_gml_table(path) -> pd.DataFrame:
    rows: list[list[str]] = []
    names: list[str] | None = None
    stack = []
    for ev, el in ET.iterparse(str(path), events=("start", "end")):
        if ev == "start":
            stack.append(el)
            continue
        stack.pop()
        if not any(_local(k) == "id" for k in el.attrib):
            continue
        lv = _leaves(el)
        if len(lv) < 20 or not any(_MESH_RE.match(v) for _n, v in lv[:5]):
            continue
        if names is None:
            names = [n for n, _v in lv]
        if len(lv) == len(names):
            rows.append([v for _n, v in lv])
        el.clear()
        if stack:  # 読み終えたメッシュを親から外して、メモリを使い続けないようにする
            try:
                stack[-1].remove(el)
            except ValueError:
                pass
    if not rows:
        raise ValueError(f"GML の中にメッシュの属性が見つかりません: {path}")
    cols = _name_columns(names, rows[0])
    return pd.DataFrame(rows, columns=cols, dtype=str)


def _name_columns(names: list[str], first: list[str]) -> list[str]:
    has_year = sum(1 for n in names if re.search(r"20[2-7][05]", n)) >= 30
    if has_year and len(set(names)) == len(names):
        return names
    for with_sex in (True, False):
        off = official_columns(with_sex)
        if len(names) == len(off):
            return off
    # 名前が重複していても列として扱えるよう、番号を付ける
    seen: dict = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out
