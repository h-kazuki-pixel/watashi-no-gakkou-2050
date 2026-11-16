"""政令指定都市の区と市。学区データが市のコードで入っている政令市を見つけ、区を市にまとめる。

国土数値情報の小学校区データ（A27）は、政令市を「市のコード」（静岡市 22100）で収録していることがある。
一方、将来推計人口のメッシュと学校の位置（P29）は「区のコード」（22101 など）で入っている。
このままでは、区は「学区データの無い市区町村」に見え、市のコードはメッシュに無い。そこで、
  - 学区データの行政区域コードが政令市の市のコードで、メッシュ（と P29）にはそのコードが無く、その市の区のコードがある
ときに、その政令市を「市のコードの学区」として扱い、メッシュと P29 の区のコードを市のコードに読み替える。
配分率、学区データなしの判定、補う学校の候補の範囲は、市の単位になる。画面の市区町村も市で1つになる。
学区データが区のコードで入っている政令市や、学区データの無い政令市（福岡市・北九州市など）は、今までどおり区で分ける。

対応表：pipeline/terms/designated_city_wards.csv（区のコード,区の名称,市のコード,市の名称,状態,…）。
国土数値情報「行政区域コード」（AdminiBoundary_CD.xlsx、令和6年1月1日現在）から tools/make_ward_table.py で作る。
状態が「欠番」の区は、再編などで今は使われていないコード（浜松市の再編前の7区など）。
"""
from __future__ import annotations

import csv
import pathlib
from dataclasses import dataclass, field

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "terms" / "designated_city_wards.csv"


@dataclass
class Ward:
    code: str
    name: str
    city: str
    city_name: str
    obsolete: bool
    new_codes: str = ""
    new_names: str = ""


def load(path=None) -> dict:
    """区のコード → Ward。ファイルが無ければ止める（政令市の判定ができないまま進めない）。"""
    p = pathlib.Path(path) if path else DEFAULT
    if not p.exists():
        raise SystemExit(f"政令指定都市の区と市の対応表がありません: {p}")
    out = {}
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            code = (r.get("区のコード") or "").strip()
            if code.isdigit():
                out[code.zfill(5)] = Ward(code.zfill(5), r["区の名称"], r["市のコード"].zfill(5), r["市の名称"],
                                          r["状態"] == "欠番", r.get("改正後のコード", ""), r.get("改正後の名称", ""))
    return out


@dataclass
class CityCoded:
    """学区データが市のコードで入っている政令市。"""
    city: str
    name: str
    mesh_wards: list = field(default_factory=list)     # メッシュにあった区のコード
    school_wards: list = field(default_factory=list)   # 学校の位置（P29）にあった区のコード
    obsolete_wards: list = field(default_factory=list)  # そのうち欠番（再編前など）の区

    def to_report(self) -> dict:
        return {"name": self.name, "mesh_wards": self.mesh_wards, "school_wards": self.school_wards,
                "obsolete_wards": self.obsolete_wards}


def split_codes(code: str) -> list:
    return [c for c in str(code).split("_") if c]


def find_city_coded(district_cities: set, mesh_cities: list, school_cities: set | None, table: dict) -> dict:
    """学区データの行政区域コードのうち、政令市の市のコードで、メッシュ（と学校の位置）には無く、
    その市の区のコードがあるものを返す。{市のコード: CityCoded}"""
    mesh_single = {c for code in mesh_cities for c in split_codes(code)}
    by_city: dict = {}
    for w in table.values():
        by_city.setdefault(w.city, []).append(w)
    out = {}
    for c in sorted(district_cities):
        wards = by_city.get(c)
        if not wards or c in mesh_single:
            continue
        mw = sorted(w.code for w in wards if w.code in mesh_single)
        if not mw:
            continue
        sw = sorted(w.code for w in wards if school_cities and w.code in school_cities)
        if school_cities is not None and (c in school_cities or not sw):
            continue
        obs = sorted({w.code for w in wards if w.obsolete and (w.code in mesh_single or w.code in (school_cities or set()))})
        out[c] = CityCoded(c, wards[0].city_name, mw, sw, obs)
    return out


def mapper(city_coded: dict, table: dict):
    """区のコード（"22101"、境界のメッシュの "22101_22102" も）を、市のコードに読み替える関数。対象外のコードはそのまま。"""
    to_city = {w.code: w.city for w in table.values() if w.city in city_coded}

    def f(code):
        if code is None:
            return code
        parts = []
        for c in split_codes(code):
            c2 = to_city.get(c, c)
            if c2 not in parts:
                parts.append(c2)
        return "_".join(parts)
    return f


def obsolete_split(city_codes, table: dict) -> dict:
    """画面に区で分けて出す市区町村のうち、欠番の区（再編前のコード）。{区のコード: "改正後の名称"}"""
    return {c: f"{table[c].name} → {table[c].new_names}" for c in sorted(city_codes) if c in table and table[c].obsolete}
