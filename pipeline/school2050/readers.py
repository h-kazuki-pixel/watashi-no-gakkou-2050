"""国土数値情報の読み込みと、列（属性）の自動判定。

国土数値情報は年度によって属性コードやファイル名が変わる。決め打ちにせず、
  - 学区：値の中身（「〜小学校」で終わる、5桁のコード、学校コードの形）から属性を判定
  - メッシュ：「0〜4歳 ＋ 5〜9歳 ＋ 10〜14歳 ＝ 0〜14歳」が成り立つ列の並びを探して年齢階級の列を特定
という方法をとり、判定結果は必ず表示する。合わないときは引数で明示できる。
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import geo, shapefile_min

EST_YEARS = [2025, 2030, 2035, 2040, 2045, 2050, 2055, 2060, 2065, 2070]
SCHOOL_CODE_RE = re.compile(r"^[A-H]\d{12}$")  # 文部科学省 学校コード（13桁）


# ---------------------------------------------------------------- 学区（ポリゴン）

@dataclass
class Feature:
    props: dict
    rings: list  # list[np.ndarray (n,2)]  [経度, 緯度]。すべての輪（外側と穴）
    polys: list | None = None  # 部分ごとの [外側の輪, 穴の輪…]。無ければ rings から組み立てる（shapes.polys_of）


def read_features(path) -> list[Feature]:
    """GeoJSON またはシェープファイルを読み、属性とリングを返す。"""
    p = pathlib.Path(path)
    suf = p.suffix.lower()
    if suf in (".geojson", ".json"):
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "cp932"):
            try:
                doc = json.loads(raw.decode(enc))
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        else:
            raise ValueError(f"GeoJSON として読めません: {p}")
        out = []
        for f in doc.get("features", []):
            g = f.get("geometry") or {}
            polys = None
            if g.get("type") == "Point":
                rings = [np.asarray([g["coordinates"][:2]], dtype=float)]
            else:
                polys = geo.polys_from_geojson(g)
                rings = [r for p in polys for r in p]
            if rings:
                out.append(Feature({k: ("" if v is None else str(v).strip()) for k, v in (f.get("properties") or {}).items()},
                                   rings, polys))
        return out
    if suf == ".shp":
        shapes = shapefile_min.read_shp(p)
        _cols, recs = shapefile_min.read_dbf(p.with_suffix(".dbf"))
        # シェープファイルは部分の区切りが無いので、輪の向き（外側と穴は逆向き）で部分を組み立てる
        return [Feature(r, s, geo.polys_from_rings(s) if max(len(q) for q in s) >= 4 else None)
                for s, r in zip(shapes, recs) if s and r is not None]
    raise ValueError(f"対応していない形式です（.geojson / .shp）: {p}")


@dataclass
class DistrictFields:
    name: str | None = None
    city_code: str | None = None
    school_code: str | None = None
    owner: str | None = None
    address: str | None = None

    def describe(self) -> str:
        return (f"学校名={self.name}, 行政区域コード={self.city_code}, 学校コード={self.school_code}, "
                f"設置主体={self.owner}, 所在地={self.address}")


def detect_fields(features: list[Feature]) -> DistrictFields:
    """属性の中身から、どの属性が学校名・行政区域コードなどにあたるかを判定する。"""
    if not features:
        raise ValueError("地物が1件もありません")
    keys = list(features[0].props.keys())
    # 先頭だけだと、学校種の順に並んだデータ（国土数値情報「学校」は幼稚園が先）で判定を誤るので、全体から等間隔に取る。
    # 件数が 400〜799 件のとき、間隔を len // 400（＝1）にすると先頭の400件だけになるので、位置を i × 件数 / 400 で決める
    n = len(features)
    sample = features if n <= 400 else [features[i * n // 400] for i in range(400)]

    def share(key, pred):
        vals = [f.props.get(key, "") for f in sample]
        vals = [v for v in vals if v != ""]
        return (sum(1 for v in vals if pred(v)) / len(vals)) if vals else 0.0

    out = DistrictFields()
    best = 0.0
    for k in keys:  # 学校名：「学校」「分校」などで終わる。国土数値情報「学校」には幼稚園・認定こども園（「〜園」）も入っている
        s = share(k, lambda v: v.endswith(("学校", "分校", "学園", "校", "園")) and not v[-1].isdigit() and len(v) <= 40)
        if s > best and s >= 0.6:
            best, out.name = s, k
    for k in keys:  # 行政区域コード：5桁（先頭の0が落ちた4桁も許す）
        if share(k, lambda v: v.isdigit() and len(v) in (4, 5)) >= 0.95:
            out.city_code = k
            break
    for k in keys:
        if share(k, lambda v: bool(SCHOOL_CODE_RE.match(v))) >= 0.8:
            out.school_code = k
            break
    for k in keys:  # 所在地：都道府県名か市区町村名で始まり、数字を含む
        if k == out.name:
            continue
        if share(k, lambda v: bool(re.search(r"[市区町村]", v)) and bool(re.search(r"[0-9０-９一二三四五六七八九十]", v)) and len(v) >= 6) >= 0.6:
            out.address = k
            break
    for k in keys:  # 設置主体：「〜市」「〜町」「〜村」「〜区」「〜立」「〜組合」などで、種類が少ない
        if k in (out.name, out.address, out.city_code, out.school_code):
            continue
        vals = [f.props.get(k, "") for f in sample if f.props.get(k, "")]
        if not vals:
            continue
        ok = sum(1 for v in vals if re.search(r"(市|区|町|村|立|組合)$", v)) / len(vals)
        if ok >= 0.8 and len(set(vals)) <= max(3, len(vals) // 2):
            out.owner = k
            break
    if not out.name:
        raise ValueError("学校名にあたる属性を判定できませんでした。--name-field で指定してください。属性: " + ", ".join(keys))
    return out


# ---------------------------------------------------------------- メッシュ（将来推計人口）

def read_table(path) -> pd.DataFrame:
    """CSV または DBF（シェープファイルの属性）を、すべて文字列の DataFrame として読む。"""
    p = pathlib.Path(path)
    suf = p.suffix.lower()
    if suf == ".csv":
        last = None
        for enc in ("utf-8-sig", "cp932"):
            try:
                return pd.read_csv(p, dtype=str, encoding=enc, keep_default_na=False)
            except UnicodeDecodeError as e:
                last = e
        raise ValueError(f"CSV の文字コードを判定できません: {p}（{last}）")
    if suf in (".gml", ".xml"):
        from .gml_table import read_gml_table
        return read_gml_table(p)
    if suf in (".dbf", ".shp"):
        cols, recs = shapefile_min.read_dbf(p.with_suffix(".dbf"))
        return pd.DataFrame([r for r in recs if r is not None], columns=cols, dtype=str)
    raise ValueError(f"対応していない形式です（.csv / .dbf / .shp / .gml）: {p}")


def _num(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series.str.replace(",", "", regex=False), errors="coerce").fillna(0.0).to_numpy(dtype=float)


@dataclass
class MeshColumns:
    mesh: str
    city: str | None
    ages: dict = field(default_factory=dict)  # 年 → (0〜4歳, 5〜9歳, 10〜14歳, 0〜14歳) の列名

    def describe(self) -> str:
        lines = [f"メッシュコード={self.mesh}, 行政区域コード={self.city}"]
        for y in sorted(self.ages):
            a, b, c, t = self.ages[y]
            lines.append(f"  {y}年: 0〜4歳={a}, 5〜9歳={b}, 10〜14歳={c}（合計が {t} と一致）")
        return "\n".join(lines)


def detect_code_columns(df: pd.DataFrame) -> tuple[str, str | None]:
    """メッシュコードの列（8〜10桁の数字）と、行政区域コードの列（4〜5桁の数字）を中身から判定する。"""
    cols = list(df.columns)
    head = df.head(2000)

    def digits_share(c, lens):
        v = head[c].str.strip()
        return float(((v.str.len().isin(lens)) & v.str.isdigit()).mean()) if len(v) else 0.0

    mesh = next((c for c in cols if digits_share(c, (8, 9, 10)) >= 0.99), None)
    if mesh is None:
        raise ValueError("メッシュコードの列（8〜10桁の数字）が見つかりません。列: " + ", ".join(cols[:20]) + " …")
    def city_share(c):
        # 境界をまたぐメッシュは "40133_40134" のように「_」で並ぶので、それも行政区域コードとして数える
        v = head[c].str.strip()
        return float(v.str.fullmatch(r"\d{4,5}(?:_\d{4,5})*").mean()) if len(v) else 0.0

    city = next((c for c in cols if c != mesh and city_share(c) >= 0.95), None)
    return mesh, city


def detect_mesh_columns(df: pd.DataFrame, years=EST_YEARS) -> MeshColumns:
    cols = list(df.columns)
    mesh, city = detect_code_columns(df)

    found = {}
    for y in years:
        ycols = [c for c in cols if re.search(rf"(?<!\d){y}(?!\d)", c)]
        if len(ycols) < 4:
            continue
        sub = df[ycols].head(20000)
        nums = {c: _num(sub[c]) for c in ycols}
        hit = None
        # 「となり合う3列の和」が、別の1列と（ほぼすべての行で）一致する組を探す。
        # 0〜4・5〜9・10〜14歳 と 0〜14歳 の関係だけがこれを満たす（列の順番や名前には依存しない）。
        # 3列とも「中身のある数字」であること。秘匿記号の列（空や "*"）は0として読まれるため、
        # 「空＋空＋総数＝総数」を年齢の内訳と取り違えないよう、ほとんどが0の列は使わない。
        live = {c: float((nums[c] > 0).mean()) for c in ycols}
        for i in range(0, len(ycols) - 2):
            trio = ycols[i:i + 3]
            if min(live[c] for c in trio) < 0.3:
                continue
            s3 = nums[ycols[i]] + nums[ycols[i + 1]] + nums[ycols[i + 2]]
            for j in range(len(ycols)):
                if i <= j <= i + 2:
                    continue
                tot = nums[ycols[j]]
                mask = tot > 0
                if mask.sum() < 5:
                    continue
                ok = np.abs(s3[mask] - tot[mask]) <= np.maximum(0.02, tot[mask] * 0.002)
                # 合計の列は、3列のどれか1つと同じ値の列であってはならない
                same = any(np.allclose(nums[c][mask], tot[mask]) for c in trio)
                if ok.mean() >= 0.97 and not same:
                    hit = (ycols[i], ycols[i + 1], ycols[i + 2], ycols[j])
                    break
            if hit:
                break
        if hit:
            found[y] = hit
    if not found:
        raise ValueError(
            "年齢階級の列を自動で特定できませんでした（「3列の和＝0〜14歳」が成り立つ並びが無い）。\n"
            "inspect コマンドで列名を確認し、--age-columns で指定してください。")
    return MeshColumns(mesh, city, found)


def parse_age_columns(spec: str, years=EST_YEARS) -> dict:
    """--age-columns 'PT01_{Y},PT02_{Y},PT03_{Y}' のような指定を年ごとの列名に展開する。"""
    parts = [s.strip() for s in spec.split(",")]
    if len(parts) != 3:
        raise ValueError("--age-columns は「0〜4歳,5〜9歳,10〜14歳」の3つを {Y} つきで指定します")
    return {y: tuple(p.replace("{Y}", str(y)) for p in parts) + (None,) for y in years}


@dataclass
class MeshTable:
    codes: list
    city: list | None
    kids: np.ndarray   # (N, 年数) 6〜11歳
    ages: np.ndarray   # (N, 12)   基準年の0〜11歳（各歳）
    years: list


def build_mesh_table(df: pd.DataFrame, mc: MeshColumns, years=EST_YEARS) -> MeshTable:
    """6〜11歳 ＝（5〜9歳）× 4/5 ＋（10〜14歳）× 2/5。5歳階級の中は各歳に等しく分かれていると仮定する。"""
    miss = [y for y in years if y not in mc.ages]
    if miss:
        raise ValueError(f"次の年の列が見つかりません: {miss}")
    n = len(df)
    kids = np.zeros((n, len(years)))
    for i, y in enumerate(years):
        _a, b, c, _t = mc.ages[y]
        kids[:, i] = _num(df[b]) * 0.8 + _num(df[c]) * 0.4
    a, b, c, _t = mc.ages[years[0]]
    a04, a59, a1014 = _num(df[a]), _num(df[b]), _num(df[c])
    ages = np.column_stack([a04 / 5.0] * 5 + [a59 / 5.0] * 5 + [a1014 / 5.0] * 2)
    codes = df[mc.mesh].str.strip().tolist()
    # 各コードを5桁にそろえる（"40133_40134" は1つずつ）
    city = ["_".join(x.strip().zfill(5) for x in v.split("_")) for v in df[mc.city].str.strip()] if mc.city else None
    keep = (kids.sum(axis=1) + ages.sum(axis=1)) > 0
    idx = np.nonzero(keep)[0]
    return MeshTable([codes[i] for i in idx], [city[i] for i in idx] if city else None, kids[idx], ages[idx], list(years))
