"""パイプラインの検算。答えが手計算できる合成データ（架空の「みほん市」）で、
メッシュコードの変換・点の内外判定・学区への配分・書き出しまでを確かめる。

    python3 -m pytest pipeline/tests -q
"""
import json
import pathlib
import re
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_school_data as cli  # noqa: E402
from school2050 import estimate, export, geo, meshcode, readers, shapefile_min  # noqa: E402

YEARS = readers.EST_YEARS
FACTOR = [1.0, 0.9, 0.8, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4]  # 2025年に対する各年の比

# 2次メッシュ 533945 の南西のすみ（緯度 35°40′、経度 139°37′30″）から、500mメッシュ 8×8 = 64 個
LAT0, LNG0 = 35 + 40 / 60, 139.625
DLAT, DLNG = 1 / 240, 1 / 160


def rect(c0, r0, c1, r1):
    """500mメッシュの列・行（端数可）で指定した長方形のリング。"""
    x0, x1 = LNG0 + c0 * DLNG, LNG0 + c1 * DLNG
    y0, y1 = LAT0 + r0 * DLAT, LAT0 + r1 * DLAT
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


# 年齢階級の比率（0〜4歳, 5〜9歳, 10〜14歳, 15〜19歳）。人数は FACTOR を掛ける
KIDS = (10.0, 10.0, 5.0, 7.0)


def _year_columns(y):
    """国土数値情報 R6 将来推計人口の CSV と同じ並び（1年あたり98項目）。"""
    cols = [f"HITOKU{y}", f"GASSAN{y}"]
    for sx in ("T", "M", "F"):
        cols += [f"P{sx}N_{y}"] + [f"P{sx}{i:02d}_{y}" for i in range(21)]
        cols += [f"P{sx}{c}_{y}" for c in "ABCDE"] + [f"R{sx}{c}_{y}" for c in "ABCDE"]
    return cols


def _year_values(f, secret=None, target=None):
    a, b, c, d = (k * f for k in KIDS)
    total = 400 * f
    vals = {"T": [a, b, c, d], "M": [a / 2, b / 2, c / 2, d / 2], "F": [a / 2, b / 2, c / 2, d / 2]}
    out = [secret or "", target or ""]
    for sx, scale in (("T", 1.0), ("M", 0.5), ("F", 0.5)):
        ages = vals[sx] + [(total * scale - sum(vals[sx])) / 16] * 16  # PX01〜PX20 の20階級
        A = sum(ages[:3])
        out += [total * scale, total * scale] + ages + [A, total * scale * 0.6, total * scale * 0.2, total * scale * 0.1, total * scale * 0.05]
        out += [A / (total * scale), 0.6, 0.2, 0.1, 0.05]
    return out


def make_mesh_csv(path, straddle=False):
    """64個の500mメッシュ（各メッシュ 6〜11歳＝10人×FACTOR）。

    straddle=True のときは、境界の両側の列（列 3・列 4）を、実物と同じく
    "99101_99102" / "99102_99101" のように2つの市区町村にまたがるメッシュにする。

    実物と同じく、秘匿メッシュ（記号 "*"、値は0）と、その人口を引き受けた合算先メッシュ（記号 "@"）を含む。
    行 0・列 0 のメッシュを秘匿し、その人口をとなり（行 0・列 1）が2倍で持つ。
    """
    cols = ["MESH_ID", "SHICODE", "PTN_2020", "PMN_2020", "PFN_2020"]
    for y in YEARS:
        cols += _year_columns(y)
    lines = [",".join(cols)]
    secret_code = meshcode.encode(LAT0 + 0.5 * DLAT, LNG0 + 0.5 * DLNG, 9)
    for r in range(8):
        for c in range(8):
            code = meshcode.encode(LAT0 + (r + 0.5) * DLAT, LNG0 + (c + 0.5) * DLNG, 9)
            city = "99101" if c < 4 else "99102"
            if straddle and c == 3:
                city = "99101_99102"
            elif straddle and c == 4:
                city = "99102_99101"
            row = [code, city, "400", "200", "200"]
            for f in FACTOR:
                if (r, c) == (0, 0):
                    row += ["*", ""] + ["0"] * 96
                elif (r, c) == (0, 1):
                    row += [f"{v:.4f}" if isinstance(v, float) else v for v in _year_values(2 * f, "@", "")]
                else:
                    row += [f"{v:.4f}" if isinstance(v, float) else v for v in _year_values(f)]
            lines.append(",".join(row))
    del secret_code
    # 子どものいないメッシュ（読み飛ばされる）
    empty = meshcode.encode(LAT0 + 20 * DLAT, LNG0 + 0.5 * DLNG, 9)
    lines.append(",".join([empty, "99101", "3", "2", "1"] + (["", ""] + ["0"] * 96) * len(YEARS)))
    pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="cp932")


def district_features():
    """(属性, ポリゴンの座標) の列。期待値（2025年の6〜11歳）はコメントのとおり。"""
    def props(city, code, name, ward):
        return {"A27_001": city, "A27_002": "みほん市", "A27_003": code, "A27_004": name,
                "A27_005": f"テスト県みほん市{ward}1丁目2番3号"}
    return [
        # 西半分 32セル。うち 2×2 セルは「かさなり小」と重なり半分ずつ → 320 − 20 = 300
        (props("99101", "B199110000019", "にし小学校", "東区"), [[rect(0, 0, 4, 8)]]),
        # 2×2 セルが にし小 と重なる → 40 ÷ 2 = 20
        (props("99101", "B199110000028", "かさなり小学校", "東区"), [[rect(1, 1, 3, 3)]]),
        # 東半分の下 3.5 行。2つの地物に分かれている（同じ学校コード）→ 4列 × 3.5行 = 14セル = 140
        (props("99102", "B199110000037", "みなみ小学校", "西区"), [[rect(4, 0, 6, 3.5)]]),
        (props("99102", "B199110000037", "みなみ小学校", "西区"), [[rect(6, 0, 8, 3.5)]]),
        # 東半分の上 4.5 行 = 18セル。1セル分の穴 → 180 − 10 = 170（穴の10人は未配分）
        (props("99102", "B199110000046", "きた小学校", "西区"), [[rect(4, 3.5, 8, 8), rect(5, 5, 6, 6)]]),
    ]


EXPECT_2025 = {"にし小学校": 300.0, "かさなり小学校": 20.0, "みなみ小学校": 140.0, "きた小学校": 170.0}


def make_geojson(path):
    feats = [{"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": g}}
             for p, g in district_features()]
    pathlib.Path(path).write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def raw(tmp_path):
    make_mesh_csv(tmp_path / "500m_mesh_2024_99.csv")
    make_geojson(tmp_path / "A27-23_99.geojson")
    return tmp_path


# ---------------------------------------------------------------- メッシュコード

def test_meshcode_known_values():
    # 東京駅（35.681, 139.767）を含む3次メッシュは 53394611
    assert meshcode.encode(35.681, 139.767, 8) == "53394611"
    lat, lng, dlat, dlng = meshcode.decode("53394611")
    assert lat == pytest.approx(35.675) and lng == pytest.approx(139.7625)
    assert dlat == pytest.approx(1 / 120) and dlng == pytest.approx(1 / 80)
    # 2分の1地域メッシュ：1=南西 2=南東 3=北西 4=北東
    assert meshcode.decode("533946111")[:2] == pytest.approx((35.675, 139.7625))
    assert meshcode.decode("533946112")[:2] == pytest.approx((35.675, 139.7625 + 1 / 160))
    assert meshcode.decode("533946113")[:2] == pytest.approx((35.675 + 1 / 240, 139.7625))
    assert meshcode.decode("533946114")[:2] == pytest.approx((35.675 + 1 / 240, 139.7625 + 1 / 160))
    assert meshcode.decode("5339461142")[2:] == pytest.approx((1 / 480, 1 / 320))


def test_meshcode_roundtrip_and_errors():
    rng = np.random.default_rng(1)
    for _ in range(300):
        lat, lng = rng.uniform(24.1, 45.4), rng.uniform(123.1, 145.7)
        for digits in (8, 9, 10):
            code = meshcode.encode(lat, lng, digits)
            la, lo, dla, dlo = meshcode.decode(code)
            assert la <= lat < la + dla + 1e-12 and lo <= lng < lo + dlo + 1e-12
    for bad in ("5339", "53394611x", "533946115", "53398011"):
        with pytest.raises(ValueError):
            meshcode.decode(bad)


# ---------------------------------------------------------------- 幾何

def test_points_in_rings_concave_and_hole():
    outer = np.array([[0, 0], [4, 0], [4, 4], [2, 4], [2, 2], [0, 2], [0, 0]], float)  # L字
    hole = np.array([[2.5, 0.5], [3.5, 0.5], [3.5, 1.5], [2.5, 1.5], [2.5, 0.5]], float)
    px = np.array([1, 1, 3, 3, 3, 5, 2.1])
    py = np.array([1, 3, 3, 1, 0.2, 1, 3.9])
    assert geo.points_in_rings(px, py, [outer, hole]).tolist() == [True, False, True, False, True, False, True]
    # 辺を小分けにしても結果は同じ
    assert geo.points_in_rings(px, py, [outer, hole], budget=7).tolist() == [True, False, True, False, True, False, True]


def test_area_centroid_simplify():
    sq = np.array(rect(0, 0, 2, 2), float)  # 約 1km 四方
    a = geo.area_km2([sq])
    assert 0.8 < a < 1.2
    cx, cy = geo.centroid([sq])
    assert cx == pytest.approx(LNG0 + DLNG) and cy == pytest.approx(LAT0 + DLAT)
    # 穴の分だけ面積が減る
    hole = np.array(rect(0.5, 0.5, 1.5, 1.5), float)
    assert geo.area_km2([sq, hole]) == pytest.approx(a * 0.75, rel=1e-4)
    # 辺の上に点が並んだ正方形は、四すみだけに間引かれる
    t = np.linspace(0, 1, 26)[:-1]
    dense = np.vstack([np.column_stack([t, 0 * t]), np.column_stack([1 + 0 * t, t]),
                       np.column_stack([1 - t, 1 + 0 * t]), np.column_stack([0 * t, 1 - t])]) * 0.01 + [139.0, 35.0]
    s = geo.simplify_ring(dense, 1e-5)
    assert len(s) == 5 and np.allclose(s[0], s[-1])


# ---------------------------------------------------------------- 読み込みと列の判定

def test_detect_columns(raw):
    df = readers.read_table(raw / "500m_mesh_2024_99.csv")
    mc = readers.detect_mesh_columns(df)
    assert mc.mesh == "MESH_ID" and mc.city == "SHICODE"
    # 男女計（PT）が、男（PM）・女（PF）より先に見つかること
    assert mc.ages[2050] == ("PT01_2050", "PT02_2050", "PT03_2050", "PTA_2050")
    assert sorted(mc.ages) == YEARS
    feats = readers.read_features(raw / "A27-23_99.geojson")
    f = readers.detect_fields(feats)
    assert (f.name, f.city_code, f.school_code, f.owner, f.address) == ("A27_004", "A27_001", "A27_003", "A27_002", "A27_005")


def test_detect_columns_when_total_comes_first(raw):
    """0〜14歳の合計列が年齢階級の列より前にあっても判定できる。"""
    df = readers.read_table(raw / "500m_mesh_2024_99.csv")
    cols = list(df.columns)
    for y in YEARS:
        cols.remove(f"PTA_{y}")
        cols.insert(cols.index(f"PT00_{y}"), f"PTA_{y}")
    mc = readers.detect_mesh_columns(df[cols])
    assert mc.ages[2030] == ("PT01_2030", "PT02_2030", "PT03_2030", "PTA_2030")


def test_secret_mesh_symbols_do_not_break_numbers(raw):
    """秘匿記号 "*" "@" の列は数値として読まれず、年齢階級の判定にも混ざらない。"""
    df = readers.read_table(raw / "500m_mesh_2024_99.csv")
    assert set(df["HITOKU2025"]) == {"", "*", "@"}
    mc = readers.detect_mesh_columns(df)
    assert all("HITOKU" not in c and "GASSAN" not in c for cols in mc.ages.values() for c in cols)


def test_shapefile_roundtrip(raw, tmp_path):
    polys = [[np.array(r, float) for r in g[0]] for _p, g in district_features()]
    rows = [p for p, _g in district_features()]
    shapefile_min.write_shp_polygons(tmp_path / "d.shp", polys)
    shapefile_min.write_dbf(tmp_path / "d.dbf", list(rows[0].keys()), rows)
    feats = readers.read_features(tmp_path / "d.shp")
    assert [f.props["A27_004"] for f in feats] == [p["A27_004"] for p in rows]  # cp932 の日本語が読める
    assert len(feats[4].rings) == 2 and np.allclose(feats[4].rings[1], polys[4][1])
    assert readers.detect_fields(feats).name == "A27_004"
    # DBF をメッシュの表としても読める
    assert list(readers.read_table(tmp_path / "d.dbf").columns) == list(rows[0].keys())


# ---------------------------------------------------------------- 配分

def test_allocation_matches_hand_calculation(raw):
    feats = readers.read_features(raw / "A27-23_99.geojson")
    fields = readers.detect_fields(feats)
    feats = export.merge_same_school(feats, fields, "99")
    assert len(feats) == 4  # みなみ小の2つの地物が1つに
    df = readers.read_table(raw / "500m_mesh_2024_99.csv")
    mt = readers.build_mesh_table(df, readers.detect_mesh_columns(df))
    assert len(mt.codes) == 63  # 子どものいないメッシュ（秘匿メッシュを含む）は除かれる
    assert sorted(set(np.round(mt.kids[:, 0], 6))) == [10.0, 20.0]  # 10×0.8 + 5×0.4、合算先は2倍
    alloc = estimate.allocate(mt.codes, np.hstack([mt.kids, mt.ages]), feats, k=4)
    got = {f.props["A27_004"]: alloc.sums[i] for i, f in enumerate(feats)}
    for name, v in EXPECT_2025.items():
        assert got[name][:10] == pytest.approx([v * f for f in FACTOR]), name
    # 年齢別：0〜9歳は各歳 2人/セル、10〜11歳は 1人/セル。6〜11歳の和は推計と一致する
    nishi = got["にし小学校"][10:]
    assert nishi == pytest.approx([60] * 10 + [30] * 2)  # 秘匿されても合算先が同じ学区なので合計は変わらない
    assert nishi[6:].sum() == pytest.approx(300)
    # 保存則：配分 ＋ 未配分 ＝ メッシュの合計。未配分は穴の1セル分
    assert alloc.unassigned[0] == pytest.approx(10.0)
    assert alloc.sums[:, 0].sum() + alloc.unassigned[0] == pytest.approx(640.0)
    assert alloc.overlap_points == 4 * 16


def test_allocation_resolution_independent(raw):
    """境界がセルの 1/2 にあるので、k=2 でも k=8 でも同じ答えになる。"""
    feats = export.merge_same_school(*(lambda fs: (fs, readers.detect_fields(fs)))(readers.read_features(raw / "A27-23_99.geojson")), "99")
    df = readers.read_table(raw / "500m_mesh_2024_99.csv")
    mt = readers.build_mesh_table(df, readers.detect_mesh_columns(df))
    for k in (2, 8):
        a = estimate.allocate(mt.codes, mt.kids, feats, k=k)
        assert sorted(a.sums[:, 0].round(6)) == sorted(EXPECT_2025.values())


# ---------------------------------------------------------------- コマンドと出力

def load_registered(js_path, fn):
    m = re.search(rf"UG\.{fn}\((.*)\);\s*$", pathlib.Path(js_path).read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1))


def test_cli_build_end_to_end(raw, tmp_path, capsys):
    out, od = tmp_path / "data", tmp_path / "opendata"
    rc = cli.main(["build", "--pref", "99", "--districts", str(raw / "A27-23_99.geojson"),
                   "--mesh", str(raw / "500m_mesh_2024_99.csv"), "--out", str(out), "--opendata", str(od)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schools"] == 4 and report["cities"] == 2
    assert report["unassigned_2025"] == 10.0 and report["conservation_error"] < 1e-6

    pref = load_registered(out / "pref_99.js", "registerPref")
    # 設置主体が同じ「みほん市」で行政区域コードが2つ → 所在地から区名を補う
    assert [c["name"] for c in pref["cities"]] == ["みほん市東区", "みほん市西区"]
    schools = {s["name"]: s for c in pref["cities"] for s in c["schools"]}
    assert {n: s["est"][0] for n, s in schools.items()} == EXPECT_2025
    assert schools["きた小学校"]["est"] == [round(170 * f, 1) for f in FACTOR]
    assert len(schools["きた小学校"]["ages"]) == 12
    assert schools["にし小学校"]["id"] == "B199110000019"
    ring = schools["にし小学校"]["geom"][0]
    assert ring[0] == ring[-1] and len(ring) == 5
    assert len(schools["きた小学校"]["geom"]) == 1  # 穴は地図に描かない
    assert "_dropped" not in pref

    index = load_registered(out / "index.js", "registerIndex")
    assert index == [{"code": "99", "name": "99", "cities": 2, "schools": 4, "generated": pref["generated"]}]
    csv_text = (od / "school_district_children_99.csv").read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0].startswith("pref_code,city_code,city_name,school_id,school_name,lat,lng")
    assert len(csv_text.splitlines()) == 5
    assert json.loads((od / "report_99.json").read_text(encoding="utf-8"))["city_coverage_2025"] == {"99101": 1.0, "99102": 0.969}

    # もう一度実行しても index に重複しない
    cli.main(["build", "--pref", "99", "--districts", str(raw / "A27-23_99.geojson"),
              "--mesh", str(raw / "500m_mesh_2024_99.csv"), "--out", str(out)])
    assert len(load_registered(out / "index.js", "registerIndex")) == 1


def test_cli_explicit_columns_and_inspect(raw, tmp_path, capsys):
    rc = cli.main(["build", "--pref", "99", "--districts", str(raw / "A27-23_99.geojson"),
                   "--mesh", str(raw / "500m_mesh_2024_99.csv"), "--out", str(tmp_path / "d2"),
                   "--age-columns", "PT01_{Y},PT02_{Y},PT03_{Y}", "--name-field", "A27_004"])
    assert rc == 0 and json.loads(capsys.readouterr().out)["allocated_2025"] == 630.0
    cli.main(["inspect", "--districts", str(raw / "A27-23_99.geojson"), "--mesh", str(raw / "500m_mesh_2024_99.csv")])
    text = capsys.readouterr().out
    assert "学校名=A27_004" in text and "5〜9歳=PT02_2050" in text
    with pytest.raises(SystemExit):
        cli.main(["build", "--pref", "99", "--districts", str(raw / "A27-23_99.geojson"),
                  "--mesh", str(raw / "500m_mesh_2024_99.csv"), "--out", str(tmp_path / "d3"),
                  "--age-columns", "X_{Y},Y_{Y},Z_{Y}"])


# ---------------------------------------------------------------- ダウンロードした zip のまま使う

def _make_downloads(folder):
    """国土数値情報のダウンロードを模した zip を作る。
    学区 zip：シェープファイル（ポリゴン、日本語のファイル名）＋ 学校の位置の GeoJSON（ポイント）
    メッシュ zip：CSV と、使わない説明ファイル
    """
    import zipfile
    folder.mkdir(parents=True, exist_ok=True)
    work = folder / "_work"
    work.mkdir()
    polys = [[np.array(r, float) for r in g[0]] for _p, g in district_features()]
    rows = [p for p, _g in district_features()]
    shapefile_min.write_shp_polygons(work / "d.shp", polys)
    shapefile_min.write_dbf(work / "d.dbf", list(rows[0].keys()), rows)
    pts = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": dict(p),
         "geometry": {"type": "Point", "coordinates": [LNG0 + 0.3 * DLNG, LAT0 + 0.3 * DLAT] if "にし" in p["A27_004"]
                      else [LNG0 + 6 * DLNG, LAT0 + 6 * DLAT]}}
        for p in rows]}
    (work / "p.geojson").write_text(json.dumps(pts, ensure_ascii=False), encoding="utf-8")
    with zipfile.ZipFile(folder / "A27-23_99_GML.zip", "w") as z:
        z.write(work / "d.shp", "A27-23_99_GML/小学校区.shp")
        z.write(work / "d.dbf", "A27-23_99_GML/小学校区.dbf")
        z.write(work / "p.geojson", "A27-23_99_GML/A27P-23_99.geojson")
        z.writestr("../evil.txt", "zip の外に書かれてはいけない")
    make_mesh_csv(work / "m.csv")
    with zipfile.ZipFile(folder / "500m_mesh_2024_99_CSV.zip", "w") as z:
        z.write(work / "m.csv", "500m_mesh_2024_99.csv")
        z.writestr("KS-META-mesh.xml", "<meta/>")
    (folder / "メモ.txt").write_text("使わないファイル", encoding="utf-8")
    import shutil
    shutil.rmtree(work)


def test_zip_inputs_are_found_by_content(tmp_path):
    from school2050 import inputs
    _make_downloads(tmp_path / "dl")
    ds = inputs.find_districts(tmp_path / "dl" / "A27-23_99_GML.zip")
    assert ds.polygons.name == "小学校区.shp" and ds.points.name == "A27P-23_99.geojson" and ds.pref == "99"
    ms = inputs.find_mesh(tmp_path / "dl" / "500m_mesh_2024_99_CSV.zip")
    assert ms.table.suffix == ".csv" and ms.pref == "99"
    assert inputs.classify(tmp_path / "dl" / "メモ.txt") is None
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "dl" / "evil.txt").exists()


def test_build_all_from_download_folder(tmp_path, capsys):
    _make_downloads(tmp_path / "dl")
    out = tmp_path / "data"
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(out), "--opendata", str(tmp_path / "od")])
    text = capsys.readouterr().out
    result = json.loads(text[text.index('{\n "built"'):])
    assert rc == 0 and result == {"built": {"99": "ok"}, "missing": {}}
    pref = load_registered(out / "pref_99.js", "registerPref")
    schools = {s["name"]: s for c in pref["cities"] for s in c["schools"]}
    assert {n: s["est"][0] for n, s in schools.items()} == EXPECT_2025
    # 学校の位置は、同じ zip のポイント層から取られる（学区の重心ではない）
    assert schools["にし小学校"]["lng"] == round(LNG0 + 0.3 * DLNG, 5)
    rows = (tmp_path / "od" / "school_district_children_99.csv").read_text(encoding="utf-8-sig").splitlines()
    assert all("学校の位置データ" in r for r in rows[1:])


# ---------------------------------------------------------------- GML しか無いとき

def _csv_to_gml(csv_path, gml_path, named: bool):
    """CSV と同じ値を持つ GML を作る。named=True は要素名に列名（年入り）、False は年の入らない汎用の名前。"""
    df = readers.read_table(csv_path)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<ksj:Dataset xmlns:ksj="http://nlftp.mlit.go.jp/ksj/schemas/ksj-app" '
           'xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:xlink="http://www.w3.org/1999/xlink" gml:id="ds">',
           '<gml:boundedBy><gml:Envelope><gml:lowerCorner>35 139</gml:lowerCorner><gml:upperCorner>36 140</gml:upperCorner></gml:Envelope></gml:boundedBy>']
    for i, row in enumerate(df.itertuples(index=False)):
        out.append(f'<gml:Surface gml:id="s{i}"><gml:patches><gml:PolygonPatch><gml:exterior><gml:LinearRing>'
                   f'<gml:posList>35.0 139.0 35.1 139.0 35.1 139.1 35.0 139.0</gml:posList></gml:LinearRing></gml:exterior></gml:PolygonPatch></gml:patches></gml:Surface>')
        cells = "".join(f"<ksj:{c if named else 'value'}>{v}</ksj:{c if named else 'value'}>" for c, v in zip(df.columns, row))
        out.append(f'<ksj:Mesh gml:id="m{i}"><ksj:range xlink:href="#s{i}"/>{cells}</ksj:Mesh>')
    out.append("</ksj:Dataset>")
    pathlib.Path(gml_path).write_text("\n".join(out), encoding="utf-8")


@pytest.mark.parametrize("named", [True, False])
def test_gml_only_mesh_zip(raw, tmp_path, named, capsys):
    import zipfile
    _csv_to_gml(raw / "500m_mesh_2024_99.csv", tmp_path / "m.xml", named)
    z = tmp_path / "500m_mesh_2024_99_GML.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(tmp_path / "m.xml", "500m_mesh_2024_99.xml")
        zf.writestr("KS-META-mesh.xml", "<meta/>")
    df = readers.read_table(tmp_path / "m.xml")
    assert len(df) == 65 and len(df.columns) == 985
    assert readers.detect_mesh_columns(df).ages[2050] == ("PT01_2050", "PT02_2050", "PT03_2050", "PTA_2050")
    rc = cli.main(["build", "--districts", str(raw / "A27-23_99.geojson"), "--mesh", str(z), "--out", str(tmp_path / "d")])
    assert rc == 0 and json.loads(capsys.readouterr().out)["allocated_2025"] == 630.0


# ---------------------------------------------------------------- 学区データの無い市区町村を補う

def _make_gap_downloads(folder, straddle=False):
    """みほん市西区（99102）の学区が無い県。学校の位置データ（国土数値情報「学校」の形）で補う。"""
    import zipfile
    folder.mkdir(parents=True, exist_ok=True)
    feats = [{"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": g}}
             for p, g in district_features() if p["A27_001"] == "99101"]
    with zipfile.ZipFile(folder / "A27-23_99_GML.zip", "w") as z:
        z.writestr("A27-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))

    def school(code, name, c, r):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + c * DLNG, LAT0 + r * DLAT]},
                "properties": {"P29_001": "99102", "P29_002": code, "P29_003": "16001", "P29_004": name,
                               "P29_005": "テスト県みほん市西区2丁目3番4号"}}
    pts = [school("B199210000015", "うみ小学校", 5.0, 2.0),            # 公立小学校
           school("B199210000024", "やま小学校", 7.0, 7.0),            # 公立小学校
           school("B199310000014", "ひかり学園小学校", 6.0, 4.0),       # 私立（使わない）
           school("C199210000012", "西区中学校", 4.5, 4.0),            # 中学校（使わない）
           {**school("B199210000033", "にし区外小学校", 1.0, 1.0), "properties": {
               "P29_001": "99101", "P29_002": "B199210000033", "P29_003": "16001", "P29_004": "にし区外小学校",
               "P29_005": "テスト県みほん市東区1丁目"}}]                  # 学区のある市（使わない）
    with zipfile.ZipFile(folder / "P29-23_99.zip", "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": pts}, ensure_ascii=False))
    make_mesh_csv(folder / "m.csv", straddle)
    with zipfile.ZipFile(folder / "500m_mesh_2024_99.zip", "w") as z:
        z.write(folder / "m.csv", "500m_mesh_2024_99.csv")
    (folder / "m.csv").unlink()


def test_gap_city_filled_from_school_points(tmp_path, capsys):
    from school2050 import inputs
    _make_gap_downloads(tmp_path / "dl")
    assert inputs.classify(tmp_path / "dl" / "P29-23_99.zip") == "schools"
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["approx_cities"] == {"99102": 2} and report["missing_cities"] == []
    assert report["allocated_2025"] == 640.0 and report["unassigned_2025"] == 0.0
    assert report["conservation_error"] < 1e-6
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    west = next(c for c in pref["cities"] if c["code"] == "99102")
    assert west["approx"] is True and west["name"] == "みほん市西区"
    names = sorted(s["name"] for s in west["schools"])
    assert names == ["うみ小学校", "やま小学校"]
    assert all(s["approx"] and len(s["geom"][0]) >= 4 for s in west["schools"])
    assert sum(s["est"][0] for s in west["schools"]) == pytest.approx(320.0, abs=0.2)
    east = next(c for c in pref["cities"] if c["code"] == "99101")
    assert "approx" not in east
    capsys.readouterr()


def test_gap_fill_with_straddling_meshes_conserves_total(tmp_path, capsys):
    # 列 3（"99101_99102"）は にし小 の学区内なので学区に配分済み。最寄りの学校には二重に足さない。
    # 列 4（"99102_99101"）は学区が無いので、99102 の学校（うみ・やま）のうち近い方に割り当てる。
    _make_gap_downloads(tmp_path / "dl", straddle=True)
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["conservation_error"] < 1e-6                                    # 配分＋未配分＝合計（全年）
    assert report["allocated_2025"] + report["unassigned_2025"] == pytest.approx(report["mesh_children_2025"])
    assert report["allocated_2025"] == pytest.approx(640.0) and report["unassigned_2025"] == pytest.approx(0.0)
    assert report["missing_cities"] == []                                         # 境界のメッシュは市区町村として扱わない
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    west = next(c for c in pref["cities"] if c["code"] == "99102")
    east = next(c for c in pref["cities"] if c["code"] == "99101")
    assert sum(s["est"][0] for s in west["schools"]) == pytest.approx(320.0, abs=0.2)
    assert sum(s["est"][0] for s in east["schools"]) == pytest.approx(320.0, abs=0.2)
    capsys.readouterr()


def test_allocate_nearest_skips_points_already_in_a_district():
    codes = [meshcode.encode(LAT0 + 0.5 * DLAT, LNG0 + (c + 0.5) * DLNG, 9) for c in range(2)]
    values = np.array([[16.0], [16.0]])
    dist = readers.Feature({}, [np.array(rect(0, 0, 0.5, 1))])                 # メッシュ 0 の左半分だけ
    alloc = estimate.allocate(codes, values, [dist], k=4)
    assert alloc.count.shape == (32,) and int((alloc.count > 0).sum()) == 8
    near = estimate.allocate_nearest(codes, ["99101_99102", "99102"], values, [("99102", LNG0, LAT0)], {"99102"},
                                     k=4, count=alloc.count)
    assert alloc.sums[0, 0] == pytest.approx(8.0) and near.sums[0, 0] == pytest.approx(24.0)
    assert alloc.sums.sum() + near.sums.sum() == pytest.approx(values.sum())


def test_gap_city_listed_as_missing_without_school_points(tmp_path, capsys):
    _make_gap_downloads(tmp_path / "dl")
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--no-fill"])
    assert rc == 0
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert [c["code"] for c in pref["cities"]] == ["99101"]
    assert pref["missing"] == [{"code": "99102", "name": ""}]
    capsys.readouterr()


# ---------------------------------------------------------------- おおよその区域の当たり具合（validate-approx）

def _grid_8x8():
    codes = [meshcode.encode(LAT0 + (r + 0.5) * DLAT, LNG0 + (c + 0.5) * DLNG, 9) for r in range(8) for c in range(8)]
    return codes, ["99101"] * 64, np.full((64, 1), 10.0)


def test_compare_nearest_is_zero_when_districts_match_nearest_school():
    # 学区の境目（列 4）が、2つの学校（列 2 と列 6、同じ行）からの距離が等しい線と一致する配置 → ずれは 0
    codes, city, values = _grid_8x8()
    west = readers.Feature({}, [np.array(rect(0, 0, 4, 8))])
    east = readers.Feature({}, [np.array(rect(4, 0, 8, 8))])
    xy = [(LNG0 + 2 * DLNG, LAT0 + 4 * DLAT), (LNG0 + 6 * DLNG, LAT0 + 4 * DLAT)]
    d, n = estimate.compare_nearest(codes, city, values, [west, east], xy, ["99101", "99101"], k=4)
    assert d[:, 0] == pytest.approx([320.0, 320.0])
    assert n[:, 0] == pytest.approx(d[:, 0])
    s = estimate.summarize_rel((n[:, 0] - d[:, 0]) / d[:, 0])
    assert s["median"] == 0 and s["abs_median"] == 0 and s["within_10"] == 1.0 and s["over_30"] == 0.0 and s["schools"] == 2


def test_compare_nearest_detects_shifted_boundary():
    # 西の学校を列 1 に寄せると、距離が等しい線は列 3.5 → 西は 32 → 28 列分（−12.5%）、東は +12.5%
    codes, city, values = _grid_8x8()
    west = readers.Feature({}, [np.array(rect(0, 0, 4, 8))])
    east = readers.Feature({}, [np.array(rect(4, 0, 8, 8))])
    xy = [(LNG0 + 1 * DLNG, LAT0 + 4 * DLAT), (LNG0 + 6 * DLNG, LAT0 + 4 * DLAT)]
    d, n = estimate.compare_nearest(codes, city, values, [west, east], xy, ["99101", "99101"], k=4)
    rel = (n[:, 0] - d[:, 0]) / d[:, 0]
    assert rel == pytest.approx([-0.125, 0.125])
    s = estimate.summarize_rel(rel)
    assert s["abs_median"] == pytest.approx(0.125) and s["within_10"] == 0.0 and s["over_30"] == 0.0


def test_validate_approx_cli_writes_city_summaries(tmp_path, capsys):
    import zipfile
    folder = tmp_path / "dl"
    _make_gap_downloads(folder)
    feats = [{"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": g}}
             for p, g in district_features()]
    with zipfile.ZipFile(folder / "A27-23_99_GML.zip", "w") as z:   # 両方の区の学区を入れる
        z.writestr("A27-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))
    od = tmp_path / "od"
    assert cli.main(["build-all", "--input", str(folder), "--out", str(tmp_path / "d"), "--opendata", str(od)]) == 0
    assert cli.main(["validate-approx", "--input", str(folder), "--opendata", str(od)]) == 0
    report = json.loads((od / "report_99.json").read_text(encoding="utf-8"))
    v = report["validate_approx"]
    assert v["year"] == 2025 and set(v["cities"]) == {"99101", "99102"}
    assert v["pref"]["schools"] == sum(c["schools"] for c in v["cities"].values()) == 4
    assert report["schools"] == 4                                # build の結果は残っている
    text = json.dumps(v, ensure_ascii=False)
    assert "小学校" not in text                                   # 学校名は出さない
    capsys.readouterr()


# ---------------------------------------------------------------- 学区データの利用条件

def _terms_downloads(tmp_path, monkeypatch, with_schools=True):
    """みほん市西区（99102）＝再配布不可、東区（99101）＝条件公開。学区データは両方の区のものを入れる。"""
    import zipfile
    from school2050 import terms
    folder = tmp_path / "dl"
    _make_gap_downloads(folder)
    feats = [{"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": g}}
             for p, g in district_features()]
    with zipfile.ZipFile(folder / "A27-23_99_GML.zip", "w") as z:
        z.writestr("A27-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))
    if not with_schools:
        (folder / "P29-23_99.zip").unlink()
    csv_path = tmp_path / "terms.csv"
    csv_path.write_text("行政コード,自治体名,公開条件,利用条件,特記条件詳細\n"
                        "99101,みほん市東区,01公開,条件公開,詳しくは教育委員会へ\n"
                        "99102,みほん市西区,01公開,商用利用・再配布不可,-\n", encoding="utf-8")
    monkeypatch.setattr(terms, "DEFAULT", csv_path)
    return folder


def test_terms_exclude_no_redistribution_city(tmp_path, monkeypatch, capsys):
    folder = _terms_downloads(tmp_path, monkeypatch)
    rc = cli.main(["build-all", "--input", str(folder), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["excluded_by_terms"] == ["99102"]
    # 除いた区は学区データなしになり、学校の位置からおおよその区域で補われる
    assert report["approx_cities"] == {"99102": 2}
    # 保存則：配分＋未配分＝合計
    assert report["conservation_error"] < 1e-6
    assert report["allocated_2025"] + report["unassigned_2025"] == pytest.approx(report["mesh_children_2025"])
    # 再配布不可の区の学区（みなみ小・きた小のポリゴン）は、アプリ用データにも CSV にも出ない
    js = (tmp_path / "d" / "pref_99.js").read_text(encoding="utf-8")
    od = (tmp_path / "od" / "school_district_children_99.csv").read_text(encoding="utf-8")
    for name in ("みなみ小学校", "きた小学校", "B199110000037", "B199110000046"):
        assert name not in js and name not in od
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    west = next(c for c in pref["cities"] if c["code"] == "99102")
    assert west["approx"] is True and all(s["approx"] for s in west["schools"])
    assert sorted(s["name"] for s in west["schools"]) == ["うみ小学校", "やま小学校"]
    # 条件公開の区には note、それ以外には付かない
    east = next(c for c in pref["cities"] if c["code"] == "99101")
    assert east.get("note") is True and "note" not in west
    assert report["note_cities"] == ["99101"]
    capsys.readouterr()


def test_terms_excluded_city_without_school_points_is_missing(tmp_path, monkeypatch, capsys):
    folder = _terms_downloads(tmp_path, monkeypatch, with_schools=False)
    rc = cli.main(["build-all", "--input", str(folder), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["excluded_by_terms"] == ["99102"] and report["conservation_error"] < 1e-6
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert [c["code"] for c in pref["cities"]] == ["99101"]
    assert pref["missing"] == [{"code": "99102", "name": ""}]
    capsys.readouterr()


def test_terms_csv_rules():
    from school2050 import terms
    t = terms.load()
    assert len(t) > 1000
    assert "40228" in terms.excluded(t)                       # 朝倉市：商用利用・再配布不可
    assert {"40220", "40341"} <= terms.needs_note(t)          # 宗像市・宇美町：条件公開＋特記
    assert "40202" not in terms.excluded(t) | terms.needs_note(t)


def test_detect_fields_when_kindergartens_come_first():
    # 実物の国土数値情報「学校」(P29) は学校種コード順で、先頭に幼稚園（「〜園」）が数百件並ぶ
    def ft(i, name):
        return readers.Feature({"P29_001": "99101", "P29_002": f"X{i:012d}", "P29_003": "16001",
                                "P29_004": name, "P29_005": f"テスト県みほん市東区{i}丁目"}, [np.zeros((1, 2))])
    feats = [ft(i, f"みほん{i}幼稚園") for i in range(450)] + [ft(i, f"みほん{i}小学校") for i in range(450, 1500)]
    assert readers.detect_fields(feats).name == "P29_004"


def test_strip_owner():
    from school2050.export import strip_owner
    assert strip_owner("北九州市立大積小学校") == "大積小学校"
    assert strip_owner("宇美町立宇美小学校") == "宇美小学校"
    assert strip_owner("久留米市立青峰小学校") == "青峰小学校"
    assert strip_owner("立花小学校") == "立花小学校"            # 「立」で始まる名前はそのまま
    assert strip_owner("三並小学校") == "三並小学校"
    assert strip_owner("福岡市立") == "福岡市立"                 # 学校名が残らないときは触らない


def test_city_from_address():
    from school2050.export import city_from_address
    assert city_from_address("福岡県福岡市中央区天神1-8-1") == "福岡市中央区"
    assert city_from_address("福岡県北九州市小倉北区大手町1番1号") == "北九州市小倉北区"
    assert city_from_address("福岡県糟屋郡宇美町宇美1-1-1") == "宇美町"
    assert city_from_address("福岡県久留米市城南町15-3") == "久留米市"
    assert city_from_address("東京都千代田区") == "千代田区"
    assert city_from_address("東京都八王子市元本郷町3-24-1") == "八王子市"
