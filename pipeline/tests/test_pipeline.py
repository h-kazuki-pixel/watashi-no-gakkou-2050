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
                   "--mesh", str(raw / "500m_mesh_2024_99.csv"), "--out", str(out), "--opendata", str(od),
                   "--retrieved", "2026-11-14"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["retrieved_missing"] is False
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

    # 出典：データごとの名前・ページ・取得日と、加工者
    src = pref["source"]
    assert [d["name"] for d in src["datasets"]] == ["国土数値情報（小学校区データ）", "国土数値情報（500mメッシュ別将来推計人口データ）"]
    assert all(d["retrieved"] == "2026-11-14" and d["url"].startswith("https://nlftp.mlit.go.jp/") for d in src["datasets"])
    assert src["processor"] == "わたしの学校2050（h-kazuki-pixel）"
    assert src["credit"] == ("出典：「国土数値情報（小学校区データ）」（国土交通省）（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A27-2023.html）"
                             "（2026年11月14日取得）、「国土数値情報（500mメッシュ別将来推計人口データ）」（国土交通省）"
                             "（https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-mesh500r6.html）（2026年11月14日取得）を加工して作成。"
                             "加工：わたしの学校2050（h-kazuki-pixel）")
    index = load_registered(out / "index.js", "registerIndex")
    assert index == [{"code": "99", "name": "99", "cities": 2, "schools": 4, "generated": pref["generated"],
                      "datasets": src["datasets"]}]
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


def test_generated_date_makes_rebuild_identical(raw, tmp_path, capsys):
    # --generated で生成日を決めると、同じ入力から1バイトも違わないファイルができる。tools/compare_builds.py は「違いなし」
    sys.path.insert(0, str(ROOT.parent / "tools"))
    import compare_builds
    for d in ("a", "b"):
        assert cli.main(["build", "--pref", "99", "--districts", str(raw / "A27-23_99.geojson"),
                         "--mesh", str(raw / "500m_mesh_2024_99.csv"), "--out", str(tmp_path / d / "app"),
                         "--opendata", str(tmp_path / d / "od"), "--generated", "2026-11-15"]) == 0
    a, b = tmp_path / "a", tmp_path / "b"
    assert (a / "app" / "pref_99.js").read_bytes() == (b / "app" / "pref_99.js").read_bytes()
    assert load_registered(a / "app" / "pref_99.js", "registerPref")["generated"] == "2026-11-15"
    assert compare_builds.compare(a / "app", a / "od", b / "app", b / "od") == ["== 99: 違いなし"]
    # 生成日・実行時間・validate_approx だけが違うときも「違いなし」
    cli.main(["build", "--pref", "99", "--districts", str(raw / "A27-23_99.geojson"), "--mesh", str(raw / "500m_mesh_2024_99.csv"),
              "--out", str(b / "app"), "--opendata", str(b / "od"), "--generated", "2026-12-01"])
    rp = b / "od" / "report_99.json"
    rep = json.loads(rp.read_text(encoding="utf-8")); rep["seconds"] = 99.9; rep["validate_approx"] = {"x": 1}
    rp.write_text(json.dumps(rep), encoding="utf-8")
    assert compare_builds.compare(a / "app", a / "od", b / "app", b / "od") == ["== 99: 違いなし"]
    # 学校の推計が変われば、学校単位で出る
    js = (b / "app" / "pref_99.js").read_text(encoding="utf-8").replace('"est":[300.0,', '"est":[299.0,')
    (b / "app" / "pref_99.js").write_text(js, encoding="utf-8")
    out = compare_builds.compare(a / "app", a / "od", b / "app", b / "od")
    assert out[0] == "== 99: 違い 1 件" and "B199110000019" in out[1] and "2025年 300.0 → 299.0" in out[1]
    with pytest.raises(SystemExit):
        cli.main(["build", "--districts", "x", "--mesh", "y", "--generated", "2026/11/15"])
    capsys.readouterr()


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
    # 実物のシェープファイルと同じく、外側の輪は時計回り、穴の輪は反時計回りで書く（天神山小などで確認した向き）
    polys = [[np.array(r, float)[::-1] if i == 0 else np.array(r, float) for i, r in enumerate(g[0])]
             for _p, g in district_features()]
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


def test_gap_city_name_is_majority_of_addresses(tmp_path, capsys):
    # 実物の形：岐阜県の P29 で、長野県下諏訪町の各種学校（日進学園、学校コード H2…）が岐阜市のコード 21201 で
    # 最初に入っていた。名前を最初の1校で決めると、岐阜市が「下諏訪町」になる。住所から取った名前の多いほうにする
    import zipfile
    _make_gap_downloads(tmp_path / "dl")
    zp = tmp_path / "dl" / "P29-23_99.zip"
    with zipfile.ZipFile(zp) as z:
        doc = json.loads(z.read("P29-23_99.geojson"))
    other = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 6.0 * DLNG, LAT0 + 6.0 * DLAT]},
             "properties": {"P29_001": "99102", "P29_002": "H299336100013", "P29_003": "16001", "P29_004": "べつ県学園",
                            "P29_005": "べつ県すわ郡しも町3310"}}
    doc["features"] = [other] + doc["features"]
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))
    from school2050.export import city_from_address
    assert city_from_address("べつ県すわ郡しも町3310") == "しも町"
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    west = next(c for c in pref["cities"] if c["code"] == "99102")
    assert west["name"] == "みほん市西区"
    assert sorted(s["name"] for s in west["schools"]) == ["うみ小学校", "やま小学校"]   # 各種学校は候補にしない
    capsys.readouterr()


def test_school_without_points_is_listed(tmp_path, capsys):
    # 実物の形：防府市の野島小（島の学校）は、まわりに推計のメッシュが無く、どの点もほかの学校のほうが近い。
    # 区域が作れないので出力しないが、黙って抜かずに report の schools_without_points に出す
    import zipfile
    _make_gap_downloads(tmp_path / "dl")
    zp = tmp_path / "dl" / "P29-23_99.zip"
    with zipfile.ZipFile(zp) as z:
        doc = json.loads(z.read("P29-23_99.geojson"))
    island = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 40.0 * DLNG, LAT0 + 40.0 * DLAT]},
              "properties": {"P29_001": "99102", "P29_002": "B199210000042", "P29_003": "16001", "P29_004": "しま小学校",
                             "P29_005": "テスト県みほん市西区しま158-1"}}
    doc["features"].append(island)
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["schools_without_points"] == [{"city": "99102", "name": "しま小学校", "code": "B199210000042", "how": "おおよその区域"}]
    assert "しま小学校" not in report["dropped_small"]
    assert report["allocated_2025"] == 640.0 and report["conservation_error"] < 1e-6
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    west = next(c for c in pref["cities"] if c["code"] == "99102")
    assert sorted(s["name"] for s in west["schools"]) == ["うみ小学校", "やま小学校"]
    capsys.readouterr()


def test_inspect_accepts_points_only_school_zip(tmp_path, capsys):
    # 国土数値情報「学校」(P29) の zip には学区のポリゴンが無い。inspect --schools に渡しても止まらない
    _make_gap_downloads(tmp_path / "dl")
    dl = tmp_path / "dl"
    rc = cli.main(["inspect", "--districts", str(dl / "A27-23_99_GML.zip"), "--mesh", str(dl / "500m_mesh_2024_99.zip"),
                   "--schools", str(dl / "P29-23_99.zip")])
    text = capsys.readouterr().out
    assert rc == 0 and "[学校]" in text and "P29-23_99.geojson: 5 件" in text and "P29_004" in text


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
    d, n = estimate.compare_nearest(codes, values, [west, east], xy, ["99101", "99101"], k=4)
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
    d, n = estimate.compare_nearest(codes, values, [west, east], xy, ["99101", "99101"], k=4)
    rel = (n[:, 0] - d[:, 0]) / d[:, 0]
    assert rel == pytest.approx([-0.125, 0.125])
    s = estimate.summarize_rel(rel)
    assert s["abs_median"] == pytest.approx(0.125) and s["within_10"] == 0.0 and s["over_30"] == 0.0


def test_compare_nearest_counts_the_same_children_when_districts_cover_part_of_city():
    # 学区が市区町村の一部しか覆わない（下半分の 4 行だけ）。上半分の子どもは学区での推計に入らないので、
    # 近い学校への割り当て直しにも入れない。2通りの合計は、市区町村ごとにも全体でも一致する。
    # 別の市区町村（99102、右半分）と、学区の重なり（列 1〜2）も含める。
    codes, _city, values = _grid_8x8()
    feats = [
        readers.Feature({}, [np.array(rect(0, 0, 2, 4))]),    # 99101 西
        readers.Feature({}, [np.array(rect(1, 0, 4, 4))]),    # 99101 東（列 1〜2 で西と重なる）
        readers.Feature({}, [np.array(rect(4, 0, 6, 4))]),    # 99102 西
        readers.Feature({}, [np.array(rect(6, 0, 8, 3))]),    # 99102 東（さらに一部だけ）
    ]
    xy = [(LNG0 + 0.5 * DLNG, LAT0 + 6 * DLAT), (LNG0 + 3.5 * DLNG, LAT0 + 1 * DLAT),
          (LNG0 + 4.5 * DLNG, LAT0 + 7 * DLAT), (LNG0 + 7.5 * DLNG, LAT0 + 0.5 * DLAT)]
    city = ["99101", "99101", "99102", "99102"]
    d, n = estimate.compare_nearest(codes, values, feats, xy, city, k=4)
    covered = 16 * 10 + (8 + 6) * 10                       # 99101: 4列×4行、99102: 2列×4行＋2列×3行（1マス 10人）
    assert d[:, 0].sum() == pytest.approx(covered) and n[:, 0].sum() == pytest.approx(covered)
    assert d[:2, 0].sum() == pytest.approx(n[:2, 0].sum()) == pytest.approx(160.0)   # 99101
    assert d[2:, 0].sum() == pytest.approx(n[2:, 0].sum()) == pytest.approx(140.0)   # 99102
    assert not np.allclose(d[:, 0], n[:, 0])               # 学校ごとには変わる


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
    # build の結果は残っている。99102 は学区データに無い公立小（うみ・やま）があるが、配分率が 0.97（穴の1セルだけ未配分）で
    # 0.9 以上なので補わない（すき間の点が1校に集まるのを避ける）
    assert report["schools"] == 4 and report["filled_missing_schools"] == {}
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
    (tmp_path / "pending.csv").write_text("行政区域コード,自治体名,理由,出典\n", encoding="utf-8")
    monkeypatch.setattr(terms, "PENDING", tmp_path / "pending.csv")   # 確認待ちの市区町村は無し
    return folder


def test_terms_exclude_no_redistribution_city(tmp_path, monkeypatch, capsys):
    folder = _terms_downloads(tmp_path, monkeypatch)
    rc = cli.main(["build-all", "--input", str(folder), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["excluded_by_terms"] == [{"code": "99102", "name": "みほん市西区", "reason": "利用条件「商用利用・再配布不可」"}]
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
    assert [e["code"] for e in report["excluded_by_terms"]] == ["99102"] and report["conservation_error"] < 1e-6
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
    assert "40202" not in set(terms.excluded(t)) | terms.needs_note(t)
    # 確認が取れるまで使わない市区町村（小田原市）：学区データを使わず、「学区は めやす」も付けない
    p = terms.pending()
    assert set(p) == {"14206"} and "市の確認" in p["14206"]["reason"] and p["14206"]["source"]
    ex = terms.excluded(t, p)
    assert ex["14206"]["reason"].startswith("確認待ち") and "14206" not in terms.needs_note(t, ex)
    assert "14206" in terms.needs_note(t)


def test_detect_fields_when_kindergartens_come_first():
    # 実物の国土数値情報「学校」(P29) は学校種コード順で、先頭に幼稚園（「〜園」）が数百件並ぶ
    def ft(i, name):
        return readers.Feature({"P29_001": "99101", "P29_002": f"X{i:012d}", "P29_003": "16001",
                                "P29_004": name, "P29_005": f"テスト県みほん市東区{i}丁目"}, [np.zeros((1, 2))])
    feats = [ft(i, f"みほん{i}幼稚園") for i in range(450)] + [ft(i, f"みほん{i}小学校") for i in range(450, 1500)]
    assert readers.detect_fields(feats).name == "P29_004"


def _p29_like(counts):
    """国土数値情報「学校」(P29) の形：学校分類コード順（幼稚園 16011・認定こども園 16013 が先頭）、名前は設置者つき。
    counts: [(学校分類コード, 件数, 名前の作り方)]"""
    feats, i = [], 0
    for kind, n, name in counts:
        for _ in range(n):
            feats.append(readers.Feature({"P29_001": "99101", "P29_002": f"X{i:012d}", "P29_003": kind, "P29_004": name(i),
                                          "P29_005": f"テスト県みほん市東区{i}丁目{i % 9 + 1}", "P29_006": "3", "P29_007": "1",
                                          "P29_008": "00", "P29_009": ""}, [np.zeros((1, 2))]))
            i += 1
    return feats


# 岩手県（763件）・青森県（874件）の P29 の学校分類ごとの件数。先頭に「〜園」が並ぶ
P29_IWATE = [("16011", 64, lambda i: f"みほん市立みほん{i}幼稚園"), ("16013", 129, lambda i: f"認定こども園みほん{i}"),
             ("16001", 271, lambda i: f"みほん市立みほん{i}小学校"), ("16002", 149, lambda i: f"みほん市立みほん{i}中学校"),
             ("16004", 79, lambda i: f"テスト県立みほん{i}高等学校"), ("16012", 17, lambda i: f"テスト県立みほん{i}特別支援学校"),
             ("16007", 9, lambda i: f"みほん{i}大学"), ("16015", 7, lambda i: f"みほん{i}学院"), ("16016", 32, lambda i: f"みほん{i}専門学校"),
             ("16006", 4, lambda i: f"みほん{i}短期大学部"), ("16005", 1, lambda i: "みほん工業高等専門学校"),
             ("16014", 1, lambda i: "みほん市立みほん義務教育学校")]
P29_AOMORI = [("16011", 85, lambda i: f"みほん{i}幼稚園"), ("16013", 247, lambda i: f"認定こども園みほん{i}幼稚園"),
              ("16001", 249, lambda i: f"みほん市立みほん{i}小学校"), ("16002", 153, lambda i: f"みほん市立みほん{i}中学校"),
              ("16004", 64, lambda i: f"テスト県立みほん{i}高等学校"), ("16012", 21, lambda i: f"テスト県立みほん{i}特別支援学校"),
              ("16007", 14, lambda i: f"みほん{i}大学"), ("16015", 10, lambda i: f"みほん{i}学院"), ("16016", 25, lambda i: f"みほん{i}専門学校"),
              ("16006", 5, lambda i: f"みほん{i}短期大学部"), ("16005", 1, lambda i: "みほん工業高等専門学校")]


@pytest.mark.parametrize("counts,n", [(P29_IWATE, 763), (P29_AOMORI, 874)])
def test_detect_fields_on_p29_with_many_kindergartens(counts, n):
    # 岩手県（400〜799件）は、以前は先頭の400件だけを見ていた。青森県（800件以上）は「〜園」が3割を超え、学校名の割合が 0.6 を下回った
    feats = _p29_like(counts)
    assert len(feats) == n
    f = readers.detect_fields(feats)
    assert f.name == "P29_004" and f.city_code == "P29_001" and f.address == "P29_005"


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


# ---------------------------------------------------------------- 休校の学校（国土数値情報「学校」の休校区分）

def _set_closed(zip_path, values: dict, extra=()):
    """P29 の zip の学校に休校区分（P29_007）を入れる。values: {学校名に含む文字: 値}。extra: 足す地物"""
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith(".geojson"))
        doc = json.loads(z.read(name))
    for f in doc["features"]:
        f["properties"]["P29_007"] = next((v for k, v in values.items() if k in f["properties"]["P29_004"]), "1")
    doc["features"] += list(extra)
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr(name, json.dumps(doc, ensure_ascii=False))


def test_closed_field_and_values():
    def ft(**p):
        return readers.Feature(p, [np.zeros((1, 2))])
    assert cli.closed_field([ft(P29_006="3", P29_007="1"), ft(P29_006="3", P29_007="9"), ft(P29_006="3", P29_007="")]) == "P29_007"
    assert cli.closed_field([ft(休校区分="2"), ft(休校区分="1")]) == "休校区分"
    assert cli.closed_field([ft(P29_007="開校")]) is None and cli.closed_field([ft(P29_006="3")]) is None
    assert [cli.is_closed(v) for v in ("0", "1", "2", "9", "")] == [False, False, True, True, False]


def test_closed_schools_are_not_candidates(tmp_path, capsys):
    # 学区データなしの区（99102）：やま小が休校区分 9（製品仕様書で休校中）→ おおよその区域の候補にしない。
    # 学区のある区（99101）：にし小が休校中（2）でも、学区データにあるので学区の学校として使う（学校コードが違うので名前で突き合わせる）
    _make_gap_downloads(tmp_path / "dl")
    east = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 0.3 * DLNG, LAT0 + 0.3 * DLAT]},
            "properties": {"P29_001": "99101", "P29_002": "B199210000079", "P29_003": "16001", "P29_004": "みほん市立にし小学校",
                           "P29_005": "テスト県みほん市東区1丁目", "P29_007": "2"}}
    _set_closed(tmp_path / "dl" / "P29-23_99.zip", {"やま": "9"}, [east])
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["approx_cities"] == {"99102": 1}
    assert sorted(report["closed_schools_excluded"], key=lambda s: s["city"]) == [
        {"city": "99101", "name": "にし小学校", "value": "2", "how": "学区データにあるので学区の学校として使う"},
        {"city": "99102", "name": "やま小学校", "value": "9", "how": "おおよその区域の候補から外した"}]
    assert report["conservation_error"] < 1e-6 and report["unassigned_2025"] == 0.0
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    by = {s["name"]: s for c in pref["cities"] for s in c["schools"]}
    assert "やま小学校" not in by and by["うみ小学校"]["est"][0] == pytest.approx(320.0, abs=0.2)
    assert by["にし小学校"]["est"][0] == EXPECT_2025["にし小学校"] and "approx" not in by["にし小学校"]
    capsys.readouterr()


def test_closed_school_is_not_filled_as_missing(tmp_path, capsys):
    # 学区データに無い「きた小」が休校中（2）なら補わない。その区域の子どもは未配分のまま
    _missing_school_downloads(tmp_path / "dl")
    _set_closed(tmp_path / "dl" / "P29-23_99.zip", {"きた小": "2"})
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["filled_missing_schools"] == {}
    assert report["closed_schools_excluded"] == [{"city": "99102", "name": "きた小学校", "value": "2", "how": "補う学校の候補から外した"}]
    assert report["unassigned_2025"] == pytest.approx(180.0) and report["conservation_error"] < 1e-6
    capsys.readouterr()


# ---------------------------------------------------------------- 学区データが市のコードで入っている政令市

WARD_TABLE = ("区のコード,区の名称,市のコード,市の名称,状態,改正年月日,改正後のコード,改正後の名称,改正事由\n"
              "99101,みほん市東区,99100,みほん市,現行,,,,\n"
              "99102,みほん市西区,99100,みほん市,欠番,2024-01-01,99103,みほん市中央区,再編後は中央区\n"
              "99103,みほん市中央区,99100,みほん市,現行,,,,\n")


def _ward_table(tmp_path, monkeypatch):
    from school2050 import wards
    p = tmp_path / "wards.csv"
    p.write_text(WARD_TABLE, encoding="utf-8")
    monkeypatch.setattr(wards, "DEFAULT", p)


def _city_coded_downloads(folder, district_city="99100"):
    """学区データは市のコード（99100）、メッシュと学校の位置（P29）は区のコード（99101・99102）。静岡市・浜松市の形。"""
    import zipfile
    folder.mkdir(parents=True, exist_ok=True)
    feats = []
    for p, g in district_features():
        p = dict(p, A27_001=district_city, A27_002="みほん市立")
        feats.append({"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": g}})
    with zipfile.ZipFile(folder / "A27-23_99_GML.zip", "w") as z:
        z.writestr("A27-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))

    def school(city, code, name, c, r):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + c * DLNG, LAT0 + r * DLAT]},
                "properties": {"P29_001": city, "P29_002": code, "P29_003": "16001", "P29_004": "みほん市立" + name,
                               "P29_005": "テスト県みほん市" + ("東区" if city == "99101" else "西区") + "1丁目", "P29_007": "1"}}
    pts = [school("99101", "B199110000019", "にし小学校", 0.3, 0.3), school("99101", "B199110000028", "かさなり小学校", 2.0, 2.0),
           school("99102", "B199110000037", "みなみ小学校", 6.0, 2.0), school("99102", "B199110000046", "きた小学校", 6.0, 6.0)]
    with zipfile.ZipFile(folder / "P29-23_99.zip", "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": pts}, ensure_ascii=False))
    make_mesh_csv(folder / "m.csv", straddle=True)
    with zipfile.ZipFile(folder / "500m_mesh_2024_99.zip", "w") as z:
        z.write(folder / "m.csv", "500m_mesh_2024_99.csv")
    (folder / "m.csv").unlink()


def test_ward_mapper_and_detection():
    from school2050 import wards
    table = {"99101": wards.Ward("99101", "みほん市東区", "99100", "みほん市", False),
             "99102": wards.Ward("99102", "みほん市西区", "99100", "みほん市", True, "99103", "みほん市中央区")}
    found = wards.find_city_coded({"99100", "99200"}, ["99101", "99102_99101", "99200"], {"99101", "99102"}, table)
    assert list(found) == ["99100"] and found["99100"].mesh_wards == ["99101", "99102"]
    assert found["99100"].obsolete_wards == ["99102"]
    f = wards.mapper(found, table)
    assert f("99101") == "99100" and f("99102_99101") == "99100" and f("99101_99200") == "99100_99200" and f("99200") == "99200"
    # 学区データが区のコード（福岡県の形）や、メッシュに市のコードがあるときは対象にしない
    assert wards.find_city_coded({"99101", "99102"}, ["99101", "99102"], {"99101"}, table) == {}
    assert wards.find_city_coded({"99100"}, ["99100", "99101"], None, table) == {}
    # P29 に市のコードがある・区のコードが無いときも対象にしない
    assert wards.find_city_coded({"99100"}, ["99101"], {"99100"}, table) == {}
    assert wards.find_city_coded({"99100"}, ["99101"], {"99300"}, table) == {}
    assert wards.obsolete_split(["99102", "99101", "99300"], table) == {"99102": "みほん市西区 → みほん市中央区"}


def test_city_coded_designated_city_is_one_city(tmp_path, monkeypatch, capsys):
    _ward_table(tmp_path, monkeypatch)
    _city_coded_downloads(tmp_path / "dl")
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["city_coded_districts"] == {"99100": {"name": "みほん市", "mesh_wards": ["99101", "99102"],
                                                         "school_wards": ["99101", "99102"], "obsolete_wards": ["99102"]}}
    # 区は「学区データなし」にならない（おおよその区域で補わない）。配分率は市の単位
    assert report["approx_cities"] == {} and report["filled_missing_schools"] == {} and report["missing_cities"] == []
    assert set(report["city_coverage_2025"]) == {"99100"} and report["obsolete_ward_cities"] == {}
    assert report["conservation_error"] < 1e-6 and report["unassigned_2025"] == 10.0
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert [(c["code"], c["name"], len(c["schools"])) for c in pref["cities"]] == [("99100", "みほん市", 4)]
    by = {s["name"]: s for s in pref["cities"][0]["schools"]}
    assert {n: s["est"][0] for n, s in by.items()} == EXPECT_2025
    assert not any(s.get("approx") for s in by.values())
    # 学校の位置は P29 から（学校コードで突き合わせ）
    assert by["きた小学校"]["lng"] == round(LNG0 + 6 * DLNG, 5)
    capsys.readouterr()


def test_ward_coded_districts_stay_by_ward_and_warn_obsolete(tmp_path, monkeypatch, capsys):
    # 学区データが区のコードなら、今までどおり区で分ける。欠番の区で出すときは警告（report の obsolete_ward_cities）
    _ward_table(tmp_path, monkeypatch)
    _make_gap_downloads(tmp_path / "dl")
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["city_coded_districts"] == {} and report["approx_cities"] == {"99102": 2}
    assert report["obsolete_ward_cities"] == {"99102": "みほん市西区 → みほん市中央区"}
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert [c["code"] for c in pref["cities"]] == ["99101", "99102"]
    capsys.readouterr()


def test_designated_city_ward_table_covers_all_cities():
    from school2050 import wards
    t = wards.load()
    cities = {w.city: w.city_name for w in t.values()}
    assert len(cities) == 20 and cities["22100"] == "静岡市" and cities["01100"] == "札幌市"
    assert t["01110"].city == "01100"                      # 10の位をまたぐ区
    assert t["27128"].city == "27100" and t["27141"].city == "27140"  # 大阪市と堺市
    assert t["40131"].city == "40130" and not t["40131"].obsolete
    assert t["22135"].obsolete and t["22135"].new_codes == "22138/22139"   # 浜松市北区（再編で2つに分かれた）
    assert t["22140"].city == "22130" and not t["22140"].obsolete
    assert "13101" not in t                                 # 東京23区は政令市の区ではない


# ---------------------------------------------------------------- 学区データに入っていない学校を補う

def _missing_school_downloads(folder):
    """みほん市西区（99102）の学区データに「きた小」が無い県（みなみ小だけがある）。
    みほん市東区（99101）は学区データで全部覆われている。学校の位置データには、きた小・みなみ小がある。"""
    import zipfile
    folder.mkdir(parents=True, exist_ok=True)
    feats = [{"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": g}}
             for p, g in district_features() if p["A27_004"] != "きた小学校"]
    with zipfile.ZipFile(folder / "A27-23_99_GML.zip", "w") as z:
        z.writestr("A27-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))

    def school(code, name, c, r):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + c * DLNG, LAT0 + r * DLAT]},
                "properties": {"P29_001": "99102", "P29_002": code, "P29_003": "16001", "P29_004": name,
                               "P29_005": "テスト県みほん市西区2丁目3番4号"}}
    pts = [school("B199210000042", "みほん市立みなみ小学校", 6.0, 3.0),   # 学区データにある（学校コードが違うので名前で突き合わせる）
           school("B199210000051", "みほん市立きた小学校", 6.0, 6.0),     # 学区データに無い → 補う
           school("B199210000060", "みほん市立みなみ小学校北分校", 5.0, 4.0),  # 分校（補わない）
           school("B199310000014", "ひかり学園小学校", 6.0, 5.0)]         # 私立（使わない）
    with zipfile.ZipFile(folder / "P29-23_99.zip", "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": pts}, ensure_ascii=False))
    make_mesh_csv(folder / "m.csv")
    with zipfile.ZipFile(folder / "500m_mesh_2024_99.zip", "w") as z:
        z.write(folder / "m.csv", "500m_mesh_2024_99.csv")
    (folder / "m.csv").unlink()


def test_missing_school_filled_without_changing_district_schools(tmp_path, capsys):
    # 西区の学区はみなみ小（下 3.5 行）だけで、配分率は 140 / 320 ＝ 0.44（0.9 未満なので補う）。
    # 上 4.5 行（18セル＝180人）はどの学区にも入らない。その点を「補う学校の中で」いちばん近い学校に当てる。
    # 学区のあるみなみ小は、その点にいちばん近くても候補にしない。分校も補わないので、180人すべてがきた小に入る。
    _missing_school_downloads(tmp_path / "dl")
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["filled_missing_schools"] == {"99102": 1} and report["approx_cities"] == {}
    assert report["allocated_2025"] == pytest.approx(640.0) and report["unassigned_2025"] == pytest.approx(0.0)
    assert report["conservation_error"] < 1e-6                     # 配分＋補った分＋未配分＝メッシュの合計（全年）
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    west = next(c for c in pref["cities"] if c["code"] == "99102")
    assert "approx" not in west                                    # 市区町村ではなく、補った学校だけが approx
    by = {s["name"]: s for c in pref["cities"] for s in c["schools"]}
    assert by["きた小学校"]["approx"] is True and by["きた小学校"]["est"][0] == pytest.approx(180.0, abs=0.05)
    assert "ひかり学園小学校" not in by and "みなみ小学校北分校" not in by
    for n in ("にし小学校", "かさなり小学校", "みなみ小学校"):
        assert "approx" not in by[n] and by[n]["est"][0] == pytest.approx(EXPECT_2025[n])

    # 補わない場合と比べて、学区のある学校の値は1つも変わらない
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d0"), "--no-fill"])
    assert rc == 0
    pref0 = load_registered(tmp_path / "d0" / "pref_99.js", "registerPref")
    by0 = {s["name"]: s for c in pref0["cities"] for s in c["schools"]}
    assert set(by0) == {"にし小学校", "かさなり小学校", "みなみ小学校"}
    for n, s0 in by0.items():
        assert by[n]["est"] == s0["est"] and by[n]["ages"] == s0["ages"]
    capsys.readouterr()


# ---------------------------------------------------------------- 学区の図形の乱れ（全国予行で見つけた形）

def _feat(props, polys):
    """GeoJSON の MultiPolygon と同じ形の地物（部分ごとに [外側の輪, 穴の輪…]）。"""
    ps = [[np.array(r, float) for r in p] for p in polys]
    return readers.Feature(props, [r for p in ps for r in p], ps)


def _alloc_2025(feats):
    codes, _city, values = _grid_8x8()
    return estimate.allocate(codes, values, feats, k=4).sums[:, 0]


def _repair(feats):
    from school2050 import shapes
    return shapes.repair(feats, key=lambda f: f.props["name"], label=lambda f: {"city": "99101", "name": f.props["name"]})


def test_duplicate_hole_ring_is_counted_once():
    # 鶴巻小（千葉県旭市）の形：同じ穴の輪が2回入っている。偶奇規則では2つの穴が打ち消し合い、穴の中の子どもを数えてしまう
    a = _feat({"name": "A"}, [[rect(0, 0, 4, 4), rect(1, 1, 2, 2), rect(1, 1, 2, 2)]])
    issues = _repair([a])
    assert issues["duplicate_rings"] == [{"city": "99101", "name": "A", "rings_removed": 1}]
    assert len(a.polys[0]) == 2 and len(a.rings) == 2
    assert _alloc_2025([a])[0] == pytest.approx(150.0)             # 16セル − 穴1セル


def test_hole_outside_outer_not_in_other_district_becomes_exclave():
    # 天神山小（石川県七尾市）の形：となりの飛び地（列 2）が、外側の輪（列 0〜1）の「穴」として入っている。どの学区にも入っていない
    a = _feat({"name": "A"}, [[rect(0, 0, 2, 2), rect(2, 0, 3, 2)]])
    b = _feat({"name": "B"}, [[rect(4, 0, 6, 2)]])
    issues = _repair([a, b])
    [e] = issues["hole_outside_outer"]
    assert e["name"] == "A" and e["outside_share"] == pytest.approx(1.0, abs=0.02) and e["outside_in_other_districts"] == 0.0
    assert "飛び地" in e["how"]
    assert list(_alloc_2025([a, b])) == pytest.approx([60.0, 40.0])  # 4セル ＋ 飛び地2セル


def test_hole_outside_outer_inside_other_district_stays_hole():
    # はみ出した部分がほかの学校の学区に入っていれば、穴のまま（区域に入れない）
    a = _feat({"name": "A"}, [[rect(0, 0, 2, 2), rect(2, 0, 3, 2)]])
    b = _feat({"name": "B"}, [[rect(2, 0, 3, 2)]])
    issues = _repair([a, b])
    assert issues["hole_outside_outer"][0]["outside_in_other_districts"] == pytest.approx(1.0)
    assert "穴のまま" in issues["hole_outside_outer"][0]["how"]
    assert list(_alloc_2025([a, b])) == pytest.approx([40.0, 20.0])


def test_hole_partly_inside_outer_keeps_inner_part_as_hole():
    # 御浜小（三重県御浜町）の形：穴の輪（列 2〜3）の一部（列 2）は外側の輪（列 0〜2）の内側で、そこはほかの学校（B）の学区。
    # 外に出た部分（列 3）はどの学区にも入らない → 列 3 は飛び地として入れ、列 2 は穴のまま抜く
    a = _feat({"name": "A"}, [[rect(0, 0, 3, 2), rect(2, 0, 4, 2)]])
    b = _feat({"name": "B"}, [[rect(2, 0, 3, 2)]])
    issues = _repair([a, b])
    assert issues["hole_outside_outer"][0]["outside_share"] == pytest.approx(0.5, abs=0.02)
    assert list(_alloc_2025([a, b])) == pytest.approx([60.0, 20.0])


def test_hole_touching_outer_is_not_reported():
    # 碩台小（長崎県島原市）の形：穴の輪が外側の輪に接している（頂点が外側の輪の上にある）だけなら、普通の穴
    a = _feat({"name": "A"}, [[rect(0, 0, 4, 4), rect(0, 0, 2, 2)]])
    assert _repair([a])["hole_outside_outer"] == []
    assert _alloc_2025([a])[0] == pytest.approx(120.0)


def test_overlapping_parts_counted_once_and_reported():
    # 大和小（鹿児島県大和村）の形：同じ学校の2つの部分が重なっている。重なり（列 1）は1回だけ数える（偶奇規則では抜けていた）
    from school2050 import shapes
    a = _feat({"name": "A", "_city": "99101"}, [[rect(0, 0, 2, 2)], [rect(1, 0, 3, 2)]])
    assert _alloc_2025([a])[0] == pytest.approx(60.0)
    assert shapes.overlapping_parts([a], lambda f: {"city": f.props["_city"], "name": f.props["name"]}) == [
        {"city": "99101", "name": "A", "pairs": 1, "overlap_km2": pytest.approx(0.5, rel=0.05)}]   # 1列×2行＝2セル（1セル約0.25km²）


def test_shapefile_rings_grouped_by_orientation(tmp_path):
    # シェープファイルには部分の区切りが無い。外側の輪（時計回り）と逆向きの輪は穴、同じ向きの輪は別の部分（御浜小の shp はこちら）
    outer = np.array(rect(0, 0, 4, 4), float)[::-1]
    hole = np.array(rect(1, 1, 2, 2), float)
    other = np.array(rect(5, 0, 6, 1), float)[::-1]
    shapefile_min.write_shp_polygons(tmp_path / "d.shp", [[outer, hole, other]])
    shapefile_min.write_dbf(tmp_path / "d.dbf", ["A27_004"], [{"A27_004": "A小学校"}])
    [f] = readers.read_features(tmp_path / "d.shp")
    assert [len(p) for p in f.polys] == [2, 1]
    assert _alloc_2025([f])[0] == pytest.approx(160.0)             # 16 − 1 ＋ 1


# ---------------------------------------------------------------- 学区データのある学校のピン（学校の位置データから）

def test_locate_uses_code_only_when_city_matches():
    pts = {("code", "B108210000010"): ("08201", (140.4, 36.4), "水戸市"),   # 水戸市の学校コード
           ("name", "08204", "上大野小学校"): (139.7, 36.2)}               # 古河市の上大野小
    # 古河市（08204）の学区データの上大野小には、水戸市の学校コードが入っている → 名前で引く
    assert export.locate(pts, "B108210000010", "08204", "上大野小学校") == (139.7, 36.2)
    assert export.locate(pts, "B108210000010", "08201", "上大野小学校") == (140.4, 36.4)
    assert export.locate(pts, "", "08204", "古河市立上大野小学校") == (139.7, 36.2)
    assert export.locate(pts, "B100000000000", "08204", "下大野小学校") is None


def test_build_all_pins_district_schools_from_school_points(tmp_path, capsys):
    # みなみ小は学校の位置データにある（学校コードは違うので名前で引く）。にし小の学校コードは、別の市区町村（99102）の学校に
    # 付いているので使わない。にし小・かさなり小は位置データに無いので、学区の重心にして report に出す
    _missing_school_downloads(tmp_path / "dl")
    import zipfile
    zp = tmp_path / "dl" / "P29-23_99.zip"
    doc = json.loads(zipfile.ZipFile(zp).read("P29-23_99.geojson"))
    doc["features"].append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 7.9 * DLNG, LAT0 + 0.1 * DLAT]},
                            "properties": {"P29_001": "99102", "P29_002": "B199110000019", "P29_003": "16001",
                                           "P29_004": "みほん市立べつ小学校", "P29_005": "テスト県みほん市西区"}})
    zp.unlink()
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    by = {s["name"]: s for c in pref["cities"] for s in c["schools"]}
    assert (by["みなみ小学校"]["lng"], by["みなみ小学校"]["lat"]) == (round(LNG0 + 6 * DLNG, 5), round(LAT0 + 3 * DLAT, 5))
    assert by["にし小学校"]["lng"] != round(LNG0 + 7.9 * DLNG, 5)
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert sorted(e["name"] for e in report["location_fallback"]) == ["かさなり小学校", "にし小学校"]
    assert report["location_outside_district"] == []
    capsys.readouterr()


# ---------------------------------------------------------------- 元データのコードの誤り

def test_owner_of():
    assert cli.owner_of("稲沢市立下津小学校") == "稲沢市"
    assert cli.owner_of("双葉郡広野町立広野小学校") == "広野町"      # 郡名は外す
    assert cli.owner_of("相馬郡新地町立新地小学校") == "新地町"
    assert cli.owner_of("新宿区立四谷小学校") == "新宿区"
    assert cli.owner_of("牧之原市菊川市学校組合立牧之原小学校") is None  # 組合立は判定しない
    assert cli.owner_of("下津小学校") is None and cli.owner_of("立花小学校") is None


def test_candidate_with_other_city_owner_is_excluded(tmp_path, capsys):
    # 愛知県の P29 の形：稲沢市立下津小学校が一宮市のコードで入っている。おおよその区域の候補に使わない
    import zipfile
    _make_gap_downloads(tmp_path / "dl")
    zp = tmp_path / "dl" / "P29-23_99.zip"
    doc = json.loads(zipfile.ZipFile(zp).read("P29-23_99.geojson"))
    for f in doc["features"]:
        if f["properties"]["P29_001"] == "99102":
            f["properties"]["P29_004"] = "みほん市立" + f["properties"]["P29_004"]
    doc["features"].append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 7.5 * DLNG, LAT0 + 0.5 * DLAT]},
                            "properties": {"P29_001": "99102", "P29_002": "B199210000042", "P29_003": "16001",
                                           "P29_004": "となり市立しもつ小学校", "P29_005": "テスト県となり市1丁目"}})
    zp.unlink()
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["owner_mismatch_excluded"] == [{"city": "99102", "name": "となり市立しもつ小学校", "owner": "となり市",
                                                   "city_owner": "みほん市"}]
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert "しもつ小学校" not in {s["name"] for c in pref["cities"] for s in c["schools"]}
    capsys.readouterr()


def _typo_downloads(tmp_path):
    """石川県の P29 の形：珠洲市の若山小学校が「珠州市立若山小学校」（設置者の名前の誤記）。ほかの学校は「珠洲市立」"""
    import zipfile
    _make_gap_downloads(tmp_path / "dl")
    zp = tmp_path / "dl" / "P29-23_99.zip"
    doc = json.loads(zipfile.ZipFile(zp).read("P29-23_99.geojson"))
    for f in doc["features"]:
        if f["properties"]["P29_001"] == "99102":
            f["properties"]["P29_004"] = "みほん市立" + f["properties"]["P29_004"]
    doc["features"].append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 7.5 * DLNG, LAT0 + 0.5 * DLAT]},
                            "properties": {"P29_001": "99102", "P29_002": "B199210000042", "P29_003": "16001",
                                           "P29_004": "みぼん市立わかやま小学校", "P29_005": "テスト県みほん市西区わかやま町"}})
    zp.unlink()
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))


def _fix_table(path, rows):
    path.write_text("データ名,学校コード,項目,元の値,直した値,根拠\n" + "".join(",".join(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_source_correction_table_fixes_owner_typo(tmp_path, capsys, monkeypatch):
    from school2050 import corrections
    _typo_downloads(tmp_path)
    # 表が無い・空のとき：誤記のまま、設置者が合わないので候補から外れる
    monkeypatch.setattr(corrections, "DEFAULT", _fix_table(tmp_path / "none.csv", []))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d0"), "--opendata", str(tmp_path / "od0")])
    r0 = json.loads((tmp_path / "od0" / "report_99.json").read_text(encoding="utf-8"))
    assert rc == 0 and [e["name"] for e in r0["owner_mismatch_excluded"]] == ["みぼん市立わかやま小学校"] and r0["source_corrections"] == []
    # 表で直すと候補になり、使った訂正が report に出る
    monkeypatch.setattr(corrections, "DEFAULT", _fix_table(tmp_path / "fix.csv", [
        ["P29", "B199210000042", "P29_004", "みぼん市立わかやま小学校", "みほん市立わかやま小学校", "所在地がみほん市"],
        ["P29", "B188888888888", "P29_004", "べつ県の学校", "べつ県の学校2", "この県には無い行"]]))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert rc == 0 and report["owner_mismatch_excluded"] == []
    assert report["source_corrections"] == [{"data": "P29", "code": "B199210000042", "field": "P29_004",
                                             "from": "みぼん市立わかやま小学校", "to": "みほん市立わかやま小学校"}]
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert "わかやま小学校" in {s["name"] for c in pref["cities"] for s in c["schools"]}
    capsys.readouterr()


def test_source_correction_table_rules(tmp_path):
    from school2050 import corrections
    feats = [readers.Feature({"P29_002": "B1X", "P29_004": "珠州市立若山小学校"}, [np.zeros((1, 2))]),
             readers.Feature({"P29_002": "B1Y", "P29_004": "珠洲市立若山小学校"}, [np.zeros((1, 2))])]
    rows = corrections.load(_fix_table(tmp_path / "t.csv", [
        ["P29", "B1X", "P29_004", "珠州市立若山小学校", "珠洲市立若山小学校", "所在地"],
        ["P29", "B1Y", "P29_004", "珠州市立若山小学校", "珠洲市立若山小学校", "元データが直ったとき"]]))
    corrections.reset()
    assert corrections.apply(feats, "P29", rows) == 1
    assert [f.props["P29_004"] for f in feats] == ["珠洲市立若山小学校", "珠洲市立若山小学校"]
    assert len(corrections.applied()) == 1
    assert corrections.apply(feats, "P29", rows) == 0                    # 2回目はもう直っている
    bad = [readers.Feature({"P29_002": "B1X", "P29_004": "べつの名前"}, [np.zeros((1, 2))])]
    with pytest.raises(SystemExit, match="合いません"):
        corrections.apply(bad, "P29", rows)                              # 表が古い
    with pytest.raises(SystemExit, match="ありません"):
        corrections.load(tmp_path / "missing.csv")
    with pytest.raises(ValueError, match="空の列"):
        corrections.load(_fix_table(tmp_path / "e.csv", [["P29", "B1X", "P29_004", "a", "b", ""]]))


def test_district_school_with_other_city_code_keeps_name_and_gets_local_id(tmp_path, capsys):
    # 古河市の形：学区データ（99101 にし小）の学校コードが、P29 では別の市区町村（99102）の学校のもの
    import zipfile
    _make_gap_downloads(tmp_path / "dl")
    zp = tmp_path / "dl" / "P29-23_99.zip"
    doc = json.loads(zipfile.ZipFile(zp).read("P29-23_99.geojson"))
    doc["features"].append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 6.5 * DLNG, LAT0 + 0.5 * DLAT]},
                            "properties": {"P29_001": "99102", "P29_002": "B199110000019", "P29_003": "16001",
                                           "P29_004": "べつ小学校", "P29_005": "テスト県みほん市西区"}})
    zp.unlink()
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["district_code_other_city"] == [{"city": "99101", "name": "にし小学校", "code": "B199110000019", "code_city": "99102"}]
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    ids = [s["id"] for c in pref["cities"] for s in c["schools"]]
    by = {(c["code"], s["name"]): s for c in pref["cities"] for s in c["schools"]}
    assert by[("99101", "にし小学校")]["id"].startswith("99101-")   # 学校コード（べつ小のもの）を id に使わない
    assert len(ids) == len(set(ids))
    capsys.readouterr()


def test_same_school_with_wrong_p29_city_keeps_code_as_id(tmp_path, capsys):
    # 福岡県の形：P29 で「大野城市立下大利小学校」が太宰府市のコードで入っている。学校コードは学区データの学校そのもの（設置者が同じ）。
    # 別の市区町村の学校のコードではないので、id は学校コードのまま
    import zipfile
    _make_gap_downloads(tmp_path / "dl")
    zp = tmp_path / "dl" / "P29-23_99.zip"
    doc = json.loads(zipfile.ZipFile(zp).read("P29-23_99.geojson"))
    doc["features"].append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 1.5 * DLNG, LAT0 + 4.5 * DLAT]},
                            "properties": {"P29_001": "99102", "P29_002": "B199110000019", "P29_003": "16001",
                                           "P29_004": "みほん市立にし小学校", "P29_005": "テスト県みほん市東区"}})
    zp.unlink()
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["district_code_other_city"] == []
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    by = {(c["code"], s["name"]): s for c in pref["cities"] for s in c["schools"]}
    assert by[("99101", "にし小学校")]["id"] == "B199110000019"
    capsys.readouterr()


# ---------------------------------------------------------------- 義務教育学校

def test_public_compulsory_school_is_a_candidate(tmp_path, capsys):
    # 京都市東山区の形：公立の学校が義務教育学校（学校コードの先頭 C2）だけ。おおよその区域の候補に入れ、名前はそのまま出す
    import zipfile
    _make_gap_downloads(tmp_path / "dl")
    zp = tmp_path / "dl" / "P29-23_99.zip"
    doc = json.loads(zipfile.ZipFile(zp).read("P29-23_99.geojson"))
    doc["features"] = [f for f in doc["features"] if f["properties"]["P29_004"] != "やま小学校"]
    doc["features"].append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [LNG0 + 7 * DLNG, LAT0 + 7 * DLAT]},
                            "properties": {"P29_001": "99102", "P29_002": "C299210000011", "P29_003": "16014",
                                           "P29_004": "みほん市立やま小中学校", "P29_005": "テスト県みほん市西区"}})
    zp.unlink()
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("P29-23_99.geojson", json.dumps(doc, ensure_ascii=False))
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    west = next(c for c in pref["cities"] if c["code"] == "99102")
    assert sorted(s["name"] for s in west["schools"]) == ["うみ小学校", "やま小中学校"]
    assert export.strip_owner("大熊町立学び舎ゆめの森") == "学び舎ゆめの森"
    capsys.readouterr()


def test_pending_confirmation_city_is_approx(tmp_path, monkeypatch, capsys):
    # 小田原市の形：利用の前に市の確認が要る。確認が取れるまで学区データを使わず、おおよその区域にする
    from school2050 import terms
    folder = _terms_downloads(tmp_path, monkeypatch)
    (tmp_path / "terms.csv").write_text("行政コード,自治体名,公開条件,利用条件,特記条件詳細\n"
                                        "99102,みほん市西区,01公開,条件公開,利用開始前に利用内容について市の確認を受けること。\n",
                                        encoding="utf-8")
    (tmp_path / "pending.csv").write_text("行政区域コード,自治体名,理由,出典\n99102,みほん市西区,市の確認が要る,テスト\n", encoding="utf-8")
    rc = cli.main(["build-all", "--input", str(folder), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["excluded_by_terms"] == [{"code": "99102", "name": "みほん市西区", "reason": "確認待ち：市の確認が要る"}]
    assert report["approx_cities"] == {"99102": 2} and report["note_cities"] == []
    capsys.readouterr()


# ---------------------------------------------------------------- まとめた区域（福島県浜通り 07999 の形）

def test_combined_area_hides_towns_without_moving_children(tmp_path, monkeypatch, capsys):
    # メッシュの行政区域コードが、2つの区をまとめた 99999 だけ（浜通りの 07999 と同じ形）。東区（99101）は出す、西区（99102）は出さない。
    # 西区の学区（みなみ小 140・きた小 170）と、どの学区にも入らない点のうち西区の学校がいちばん近い点（きた小の穴 10）は
    # 「扱わない区域」（320）。東区の学校には回さない
    import zipfile
    from school2050 import combined
    folder = tmp_path / "dl"
    _missing_school_downloads(folder)
    feats = [{"type": "Feature", "properties": p, "geometry": {"type": "MultiPolygon", "coordinates": g}} for p, g in district_features()]
    (folder / "A27-23_99_GML.zip").unlink()
    with zipfile.ZipFile(folder / "A27-23_99_GML.zip", "w") as z:
        z.writestr("A27-23_99.geojson", json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))
    make_mesh_csv(tmp_path / "m.csv")
    lines = (tmp_path / "m.csv").read_text(encoding="cp932").splitlines()
    out = [lines[0]] + [",".join([r.split(",")[0], "99999"] + r.split(",")[2:]) for r in lines[1:]]
    (folder / "500m_mesh_2024_99.zip").unlink()
    with zipfile.ZipFile(folder / "500m_mesh_2024_99.zip", "w") as z:
        z.writestr("500m_mesh_2024_99.csv", ("\n".join(out) + "\n").encode("cp932"))
    table = tmp_path / "area.csv"
    table.write_text("行政区域コード,市町村名,まとめた区域のコード,扱い,5〜14歳_2020_原数値,5〜14歳_2020_不詳補完値,児童数_2025-05-01,出典\n"
                     "99101,みほん市東区,99999,出す（注意書きつき）,500,500,300,テスト\n"
                     "99102,みほん市西区,99999,出さない,10,10,200,テスト\n", encoding="utf-8")
    monkeypatch.setattr(combined, "DEFAULT", table)
    rc = cli.main(["build-all", "--input", str(folder), "--out", str(tmp_path / "d"), "--opendata", str(tmp_path / "od")])
    assert rc == 0
    report = json.loads((tmp_path / "od" / "report_99.json").read_text(encoding="utf-8"))
    assert report["not_handled_2025"] == pytest.approx(320.0)
    assert report["allocated_2025"] == pytest.approx(320.0) and report["unassigned_2025"] == pytest.approx(0.0)
    assert report["conservation_error"] < 1e-6                        # 配分＋未配分＋扱わない区域＝メッシュの合計
    area = report["combined_areas"]["99999"]
    assert area["99102"]["not_handled_2025"] == pytest.approx(320.0) and area["99102"]["schools"] == 0
    assert area["99101"]["est_2025"] == pytest.approx(320.0) and area["99101"]["ratio_2025"] == pytest.approx(320 / 300, abs=0.001)
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert [c["code"] for c in pref["cities"]] == ["99101"] and pref["cities"][0]["combined"] is True
    assert pref["missing"] == [{"code": "99102", "name": "みほん市西区", "nothandled": True}]
    assert {s["name"]: s["est"][0] for s in pref["cities"][0]["schools"]} == {"にし小学校": 300.0, "かさなり小学校": 20.0}
    capsys.readouterr()


# ---------------------------------------------------------------- 黙って別の値で続けない

def test_non_numeric_mesh_value_stops(raw):
    df = readers.read_table(raw / "500m_mesh_2024_99.csv")
    mc = readers.detect_mesh_columns(df)
    col = mc.ages[2030][1]
    df.loc[5, col] = "x"
    with pytest.raises(ValueError, match="数値でない値"):
        readers.build_mesh_table(df, mc)
    df.loc[5, col] = ""                                       # 空欄は0（秘匿メッシュ）として続ける
    readers.build_mesh_table(df, mc)


def test_missing_terms_table_stops(tmp_path, monkeypatch, capsys):
    from school2050 import terms
    _make_gap_downloads(tmp_path / "dl")
    monkeypatch.setattr(terms, "DEFAULT", tmp_path / "none.csv")
    with pytest.raises(SystemExit, match="利用条件の一覧"):
        cli.cmd_build(cli.argparse.Namespace(**{**vars(cli.argparse.Namespace()), "districts": str(tmp_path / "dl" / "A27-23_99_GML.zip"),
                      "mesh": str(tmp_path / "dl" / "500m_mesh_2024_99.zip"), "schools": None, "pref": "99", "fill_schools": None,
                      "name_field": None, "city_field": None, "code_field": None, "owner_field": None, "address_field": None,
                      "age_columns": None, "k": 4, "min_children": 1.0, "out": str(tmp_path / "d"), "opendata": None,
                      "city_names": None, "generated": None}))
    capsys.readouterr()


def test_unreadable_school_points_stop(tmp_path):
    # validate-approx・build で学校の位置データの属性を判定できないとき、学区の重心で黙って代えずに止める
    p = tmp_path / "p.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"a": "1"}, "geometry": {"type": "Point", "coordinates": [130, 33]}}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="属性を判定できません"):
        cli._school_points(str(p), "99")


def test_build_all_reads_retrieved_dates_per_pref(tmp_path, capsys):
    # 取得日はダウンロードしたときに記録し、build-all に渡す（--input の retrieved.csv）。生成のたびに変わらない
    _make_gap_downloads(tmp_path / "dl")
    (tmp_path / "dl" / "retrieved.csv").write_text("都道府県コード,取得日\n99,2026-11-14\n", encoding="utf-8")
    rc = cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(tmp_path / "d")])
    assert rc == 0
    pref = load_registered(tmp_path / "d" / "pref_99.js", "registerPref")
    assert [d["retrieved"] for d in pref["source"]["datasets"]] == ["2026-11-14"] * 3   # 学校データも使ったので3つ
    capsys.readouterr()
