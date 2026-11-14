"""ダウンロードしたままのファイル（zip）から、使うファイルを見つける。

国土数値情報のファイル名は年度や版で変わるので、名前ではなく中身で判定する。
  - 学区：ポリゴンの層（範囲）と、ポイントの層（学校の位置）が同じ zip に入っていることがある
  - メッシュ：CSV と SHP が両方あれば CSV を使う
都道府県コードも中身（行政区域コードの先頭2桁）から決める。
"""
from __future__ import annotations

import pathlib
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass

from . import readers

_TMP: list[tempfile.TemporaryDirectory] = []  # 処理が終わるまで消さない


def _unzip(path: pathlib.Path) -> pathlib.Path:
    """zip を一時フォルダに展開する。中のパスがフォルダの外を指すもの（../ など）は展開しない。"""
    td = tempfile.TemporaryDirectory(prefix="school2050_")
    _TMP.append(td)
    root = pathlib.Path(td.name).resolve()
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            raw = info.filename
            try:
                name = raw.encode("cp437").decode("cp932") if not info.flag_bits & 0x800 else raw
            except (UnicodeEncodeError, UnicodeDecodeError):
                name = raw
            dest = (root / name).resolve()
            if root not in dest.parents and dest != root:
                continue
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
    return root


def _files(path) -> list[pathlib.Path]:
    p = pathlib.Path(path)
    if p.is_file() and p.suffix.lower() == ".zip":
        p = _unzip(p)
    if p.is_dir():
        out = []
        for q in sorted(p.rglob("*")):
            if q.is_file() and q.suffix.lower() == ".zip":
                out += _files(q)
            elif q.is_file():
                out.append(q)
        return out
    return [p]


def _is_polygon_layer(feats) -> bool:
    return bool(feats) and sum(1 for f in feats[:50] if max(len(r) for r in f.rings) >= 4) >= min(len(feats), 50) * 0.8


@dataclass
class DistrictSource:
    polygons: pathlib.Path
    points: pathlib.Path | None
    pref: str | None


@dataclass
class MeshSource:
    table: pathlib.Path
    pref: str | None


def _pref_from_codes(codes) -> str | None:
    c = Counter(str(v).zfill(5)[:2] for v in codes if str(v).strip().isdigit())
    return c.most_common(1)[0][0] if c else None


def find_districts(path) -> DistrictSource:
    """学区のポリゴン層と、（あれば）学校の位置の層を探す。GeoJSON があれば SHP より優先する。"""
    cands = [f for f in _files(path) if f.suffix.lower() in (".geojson", ".json", ".shp")]
    if not cands:
        raise ValueError(f"学区のファイル（.geojson / .shp）が見つかりません: {path}")
    poly, pts = [], []
    for f in cands:
        try:
            feats = readers.read_features(f)
            fields = readers.detect_fields(feats)
        except (ValueError, KeyError, OSError):
            continue
        (poly if _is_polygon_layer(feats) else pts).append((f, feats, fields))
    if not poly:
        raise ValueError(f"学区のポリゴンが見つかりません: {path}")

    def pick(items):
        items.sort(key=lambda t: (t[0].suffix.lower() == ".shp", -len(t[1])))
        return items[0]

    pf, pfeats, pfields = pick(poly)
    pref = _pref_from_codes(f.props.get(pfields.city_code, "") for f in pfeats) if pfields.city_code else None
    return DistrictSource(pf, pick(pts)[0] if pts else None, pref)


def find_mesh(path) -> MeshSource:
    """将来推計人口の表を探す。CSV、SHP の属性（DBF）、GML の順に探す。"""
    files = _files(path)
    cands = ([f for f in files if f.suffix.lower() == ".csv"] or [f for f in files if f.suffix.lower() == ".dbf"]
             or [f for f in files if f.suffix.lower() in (".gml", ".xml") and f.stat().st_size > 2000])
    for f in sorted(cands, key=lambda q: -q.stat().st_size):
        try:
            df = readers.read_table(f)
            mesh, city = readers.detect_code_columns(df)
        except (ValueError, KeyError, OSError):
            continue
        return MeshSource(f, _pref_from_codes(df[city]) if city else None)
    raise ValueError(f"メッシュの表（メッシュコードの列がある CSV / DBF）が見つかりません: {path}")


@dataclass
class SchoolSource:
    points: pathlib.Path
    pref: str | None


def find_schools(path) -> SchoolSource:
    """学校の位置データ（国土数値情報「学校」など、ポイントだけの層）を探す。"""
    for f in _files(path):
        if f.suffix.lower() not in (".geojson", ".json", ".shp"):
            continue
        try:
            feats = readers.read_features(f)
        except (ValueError, KeyError, OSError):
            continue
        if not feats or _is_polygon_layer(feats):
            continue
        keys = list(feats[0].props)
        code = next((k for k in keys if sum(1 for x in feats[:300] if readers.SCHOOL_CODE_RE.match(x.props.get(k, ""))) >= min(len(feats), 300) * 0.8), None)
        name = next((k for k in keys if sum(1 for x in feats[:300] if x.props.get(k, "").endswith("学校")) >= min(len(feats), 300) * 0.5), None)
        if not (code or name):
            continue
        city = next((k for k in keys if sum(1 for x in feats[:300] if x.props.get(k, "").isdigit() and len(x.props.get(k, "")) in (4, 5)) >= min(len(feats), 300) * 0.95), None)
        return SchoolSource(f, _pref_from_codes(x.props.get(city, "") for x in feats) if city else None)
    raise ValueError(f"学校の位置データが見つかりません: {path}")


def classify(path) -> str | None:
    """ファイル1つが学区（'districts'）・メッシュ（'mesh'）・学校の位置（'schools'）のどれかを判定する。"""
    try:
        find_mesh(path)
        return "mesh"
    except ValueError:
        pass
    try:
        find_districts(path)
        return "districts"
    except ValueError:
        pass
    try:
        find_schools(path)
        return "schools"
    except ValueError:
        return None
