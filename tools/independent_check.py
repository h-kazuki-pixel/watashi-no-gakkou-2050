#!/usr/bin/env python3
"""別の実装による検算：アプリの学校別推計（pref_XX.js）を、元データから計算し直して学校ごとに比べる。

パイプライン（pipeline/）のコードは一切読み込まない。docs/DATA_METHOD.md に書かれた手順だけを実装している。
メッシュは XML の要素名（populationOfAge5To9In2025 など）で読むので、列の位置の判定にも頼らない。

  python3 independent_check.py \
      --mesh 500m_mesh_2024_40.xml --districts A27-23_40.geojson --schools P29-23_40.geojson \
      --pref-js app/data/pref_40.js --exclude 40228

zip はあらかじめ展開しておく。必要なのは numpy だけ。
比べるもの：学校の集合、市区町村、おおよその区域かどうか、2025〜2070年の推計（10個）、0〜11歳の各歳（12個）。
学区の区域は、学校ごとに部分（ポリゴン）を集め、部分ごとの「外側の輪 − 穴の輪」を合わせたもの（重なりは1回）。
同じ輪の重複は除き、外側の輪の外にはみ出した穴は、はみ出した部分がほかの学区に半分以上入っていなければ飛び地として入れる
（DATA_METHOD.md「学区の図形」）。
おおよその区域は2種類：学区データの無い市区町村の学校と、学区データのある市区町村で学区データに入っていない公立小学校。
後者は、配分率が 0.9 未満の市区町村だけで、名前が「分校」で終わる学校は除く。どの学区にも入らなかった点を、
「補う学校の中で」いちばん近い学校に当てる（学区のある学校は候補にしない。学区のある学校の線引きは正しいとみなす）。
距離は、経度の差に点ごとの緯度の cos を掛ける（--lat-scale point。mean は以前のパイプラインの、県全体で1つの値）。
学校の位置データ（P29）から学校を選ぶときは、休校区分（P29_007 か名前に「休校」を含む属性）が 0（調査なし）・1（開校中）
以外の学校（2・9＝休校中。製品仕様書では 9、コードリストのページでは 2）を使わない。学区データの学校は休校区分に関係なく使う。
政令市の学区データが市のコードで入っているとき（学区データに市のコードがあり、メッシュと P29 にはそのコードが無く、
その市の区のコードがある）は、メッシュと P29 の区のコードを市のコードに読み替える。区と市の対応は
pipeline/terms/designated_city_wards.csv（国土数値情報「行政区域コード」から作った表。データとして読む）。
学区データのある学校が 0.06人を超えて違えば終了コード 1。おおよその区域の学校は、2つの学校からほぼ同じ距離にある点の
割り当てが入れ替わることがあるので、違いの数と大きさを報告する（--strict を付けると、これも 1 件で終了コード 1）。
"""
import argparse
import csv
import json
import pathlib
import math
import re
import sys
from collections import defaultdict

import numpy as np

YEARS = list(range(2025, 2075, 5))
WARD_TABLE = pathlib.Path(__file__).resolve().parents[1] / "pipeline" / "terms" / "designated_city_wards.csv"
AREA_TABLE = pathlib.Path(__file__).resolve().parents[1] / "pipeline" / "terms" / "fukushima_hamadori.csv"
K = 4  # メッシュ1つにつき K×K の点


def parse_mesh(path):
    """メッシュコード、市区町村コード、(0〜4歳, 5〜9歳, 10〜14歳) × 年 を、要素名で読む。"""
    want = {}
    for y in YEARS:
        want[f"populationOfAge0To4In{y}"] = (0, y)
        want[f"populationOfAge5To9In{y}"] = (1, y)
        want[f"populationOfAge10To14In{y}"] = (2, y)
    rx = re.compile(r"<ksj:(\w+)[^>]*>([^<]*)</ksj:")
    codes, city, vals, seen = [], [], [], set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "<ksj:" not in line:
                continue
            m = rx.search(line)
            if not m:
                continue
            tag, v = m.group(1), m.group(2).strip()
            if tag == "meshCode":
                codes.append(v)
                city.append("")
                vals.append(np.zeros((3, len(YEARS))))
            elif tag == "administrativeAreaCode":
                city[-1] = v
            elif tag in want:
                a, y = want[tag]
                vals[-1][a, YEARS.index(y)] = float(v) if v else 0.0
                seen.add(tag)
    if len(seen) != len(want):
        sys.exit(f"メッシュに必要な要素が足りません（{len(seen)}/{len(want)}）")
    if len(set(codes)) != len(codes) or any(len(c) != 9 for c in codes):
        sys.exit("メッシュコードが重複しているか、9桁（500mメッシュ）ではありません")
    return codes, city, np.array(vals)


def strip_owner(name):
    """学校名の先頭の設置者（「岡垣町立」など）を外す。「立花小学校」のように「立」で始まる名前はそのまま。"""
    m = re.match(r"^.{1,12}?(?:市|町|村|区|組合)立(.+(?:学校|学園|分校|森))$", name or "")
    return m.group(1) if m else (name or "")


def mesh_sw(code):
    """500mメッシュ（9桁）の南西の角の経度・緯度。"""
    p, u, q, v, r, w, m = int(code[0:2]), int(code[2:4]), int(code[4]), int(code[5]), int(code[6]), int(code[7]), int(code[8])
    lat = p / 1.5 + q * 5 / 60 + r * 30 / 3600 + (15 / 3600 if m in (3, 4) else 0)
    lon = 100 + u + v * 7.5 / 60 + w * 45 / 3600 + (22.5 / 3600 if m in (2, 4) else 0)
    return lon, lat


def in_ring(x, y, ring):
    r = np.asarray(ring, dtype=float)
    x1, y1, x2, y2 = r[:-1, 0], r[:-1, 1], r[1:, 0], r[1:, 1]
    inside = np.zeros(x.shape, bool)
    for i in range(len(x1)):
        if y1[i] == y2[i]:
            continue
        c = (y1[i] > y) != (y2[i] > y)
        if not c.any():
            continue
        xi = (x2[i] - x1[i]) * (y[c] - y1[i]) / (y2[i] - y1[i]) + x1[i]
        idx = np.nonzero(c)[0]
        inside[idx[x[c] < xi]] ^= True
    return inside


def polygons(geom):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]




def in_polys(x, y, polys):
    """部分ごとに「外側の輪 − 穴の輪」を作り、部分を合わせた区域の内側か（重なりは1回）。"""
    res = np.zeros(x.shape, bool)
    for poly in polys:
        ins = in_ring(x, y, poly[0])
        for hole in poly[1:]:
            ins &= ~in_ring(x, y, hole)
        res |= ins
    return res


def ring_id(ring):
    """座標の並びが同じ輪かを比べる鍵。始点と向きは問わない。"""
    pts = [tuple(round(float(v), 9) for v in p[:2]) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    best = None
    for seq in (pts, pts[::-1]):
        for i in range(len(seq)):
            cand = tuple(seq[i:] + seq[:i])
            if best is None or cand < best:
                best = cand
    return best


def box(rings):
    a = np.vstack([np.asarray(r, float)[:, :2] for r in rings])
    return a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()


def school_areas(all_feats, key):
    """DATA_METHOD.md「学区の図形」：学校ごとに部分を集め、同じ輪の重複を除き、外に出た穴を扱う。
    返り値: ({学校: [部分…]}, {"duplicate_rings": [学校], "hole_outside_outer": [(学校, はみ出し割合, ほかの学区の割合, 入れたか)]})"""
    raw = defaultdict(list)
    for f in all_feats:
        for poly in polygons(f["geometry"]):
            raw[key(f)].append([np.asarray(r, float)[:, :2] for r in poly])
    boxes = {k: box([p[0] for p in v]) for k, v in raw.items()}
    out, dups, holes = {}, [], []
    for k, polys in raw.items():
        so, sh, kept = set(), set(), []
        removed = 0
        for p in polys:
            o = ring_id(p[0])
            if o in so:
                removed += 1
                continue
            so.add(o)
            q = [p[0]]
            for h in p[1:]:
                hid = ring_id(h)
                if hid in sh:
                    removed += 1
                    continue
                sh.add(hid)
                q.append(h)
            kept.append(q)
        if removed:
            dups.append(k)
        extra = []
        for p in kept:
            for h in p[1:]:
                x0, y0, x1, y1 = box([h])
                gx, gy = np.meshgrid(np.linspace(x0, x1, 200), np.linspace(y0, y1, 200))
                gx, gy = gx.ravel(), gy.ravel()
                inh = in_ring(gx, gy, h)
                if not inh.any():
                    continue
                outside = inh & ~in_ring(gx, gy, p[0])
                share = outside.sum() / inh.sum()
                if share <= 0.01:
                    continue
                ox, oy = gx[outside], gy[outside]
                cov = np.zeros(ox.shape, bool)
                for k2, polys2 in raw.items():
                    b = boxes[k2]
                    if k2 == k or b[0] > x1 or b[2] < x0 or b[1] > y1 or b[3] < y0:
                        continue
                    cov |= in_polys(ox, oy, polys2)
                other = cov.mean()
                take = other < 0.5
                if take:
                    extra.append([h, p[0]])  # 穴の輪 − 外側の輪 を飛び地として足す
                holes.append((k, round(float(share), 3), round(float(other), 3), take))
        out[k] = kept + extra
    return out, {"duplicate_rings": dups, "hole_outside_outer": holes}


def ward_to_city():
    """区のコード → 市のコード（政令指定都市。欠番の区も入る）。"""
    with open(WARD_TABLE, encoding="utf-8-sig", newline="") as f:
        return {r["区のコード"]: r["市のコード"] for r in csv.DictReader(f)}


def recode(code, table):
    """"22101_22102" のような市区町村コードの並びを、表で読み替えて重複を除く。"""
    out = []
    for c in code.split("_"):
        c = table.get(c, c)
        if c not in out:
            out.append(c)
    return "_".join(out)


def closed_key(props_list):
    """休校区分の属性名：P29_007 か、名前に「休校」を含み、中身が1桁の数字（空欄を除く）だけのもの。"""
    keys = list(props_list[0]) if props_list else []
    for k in [k for k in keys if k == "P29_007"] + [k for k in keys if "休校" in k]:
        vals = {str(p.get(k) or "") for p in props_list} - {""}
        if vals and all(len(v) == 1 and v.isdigit() for v in vals):
            return k
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--districts", required=True)
    ap.add_argument("--schools", required=True)
    ap.add_argument("--pref-js", required=True)
    ap.add_argument("--exclude", default="", help="利用条件で学区を使わない市区町村コード（カンマ区切り）")
    ap.add_argument("--lat-scale", choices=["mean", "point"], default="point",
                    help="距離の経度の縮め方。point＝点ごとの緯度（パイプラインと同じ）、mean＝対象の点の緯度の平均で1つ（以前の方法）")
    ap.add_argument("--no-fill-missing", action="store_true",
                    help="学区データのある市区町村で、学区データに無い学校を補わない（以前のパイプラインと比べるとき）")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    exclude = {c for c in args.exclude.split(",") if c}

    codes, mcity, V = parse_mesh(args.mesh)
    n = len(codes)
    kids = V[:, 1, :] * 4 / 5 + V[:, 2, :] * 2 / 5  # 6〜11歳
    sw = np.array([mesh_sw(c) for c in codes])
    dl, db = 22.5 / 3600, 15 / 3600
    off = (np.arange(K) + 0.5) / K
    px = (sw[:, 0, None, None] + off[None, None, :] * dl + np.zeros((1, K, 1))).reshape(-1)
    py = (sw[:, 1, None, None] + off[None, :, None] * db + np.zeros((1, 1, K))).reshape(-1)
    pm = np.repeat(np.arange(n), K * K)
    w0 = 1.0 / (K * K)

    all_feats = json.load(open(args.districts, encoding="utf-8"))["features"]
    feats = [f for f in all_feats if f["properties"]["A27_001"] not in exclude]
    pts = json.load(open(args.schools, encoding="utf-8"))["features"]

    # 政令市の学区データが市のコードで入っているとき：メッシュと P29 の区のコードを市のコードに読み替える
    w2c = ward_to_city()
    dcodes = {f["properties"]["A27_001"] for f in feats}
    mesh_codes = {c for m in mcity for c in m.split("_")}
    p29_codes = {f["properties"]["P29_001"] for f in pts}
    city_coded = sorted(c for c in dcodes if c not in mesh_codes and c not in p29_codes
                        and any(w2c.get(m) == c for m in mesh_codes) and any(w2c.get(p) == c for p in p29_codes))
    table = {w: c for w, c in w2c.items() if c in city_coded}
    if city_coded:
        mcity = [recode(m, table) for m in mcity]
        for f in pts:
            f["properties"]["P29_001"] = recode(f["properties"]["P29_001"], table)
    print(f"学区データが市のコードで入っている政令市: {city_coded}")

    # 学区の区域：学校ごと（学校コード、無ければ（市区町村, 学校名）。浜松市の鏡山小など）に部分を集めて1つの区域にする。
    # 外に出た穴の「ほかの学校の学区」には、利用条件で除く前の学区データを全部使う
    # 学校は（学校コード, 市区町村）で区別する。学校コードの無い学校は（市区町村, 学校名）
    def skey(f):
        p = f["properties"]
        return f'{p["A27_003"]}@{p["A27_001"]}' if p["A27_003"] else f'{p["A27_001"]}|{p["A27_004"]}'
    areas, shape_issues = school_areas(all_feats, skey)
    print(f"学区の図形：同じ輪の重複 {shape_issues['duplicate_rings']}、外に出た穴 {shape_issues['hole_outside_outer']}")
    info = {}
    for f in feats:
        info.setdefault(skey(f), (f["properties"]["A27_004"], f["properties"]["A27_001"]))

    # 学区への配分
    hits, count = [], np.zeros(px.shape[0], int)
    for sid in info:
        polys = areas[sid]
        x0, y0, x1, y1 = box([p[0] for p in polys])
        idx = np.nonzero((px >= x0) & (px <= x1) & (py >= y0) & (py <= y1))[0]
        ins = idx[in_polys(px[idx], py[idx], polys)]
        hits.append(ins)
        count[ins] += 1
    est = {}
    for sid, ins in zip(info, hits):
        w = w0 / count[ins]
        est[sid] = dict(name=info[sid][0], city=info[sid][1], approx=False,
                        e=(kids[pm[ins]] * w[:, None]).sum(0), a=(V[pm[ins], :, 0] * w[:, None]).sum(0))

    # 学区データなしの市区町村：1つの市区町村だけのメッシュで、学区に配分できた子どもが5%未満
    frac = ((count > 0).reshape(n, -1) * w0).sum(1)
    tot, got = defaultdict(float), defaultdict(float)
    for i in range(n):
        if "_" not in mcity[i]:
            tot[mcity[i]] += kids[i, 0]
            got[mcity[i]] += kids[i, 0] * frac[i]
    gap = {c for c in tot if tot[c] > 0 and got[c] / tot[c] < 0.05}
    low = {c: round(float(got[c] / tot[c]), 3) for c in sorted(tot) if tot[c] > 0 and c not in gap and got[c] / tot[c] < 0.9}

    # おおよその区域：公立の小学校・義務教育学校（学校コードの先頭2文字が B1 か C2、5文字目が 2）のうち、いちばん近い学校。
    # 休校区分が 0・1 以外（2・9＝休校中など）の学校は使わない
    ck = closed_key([f["properties"] for f in pts])
    def closed(f):
        v = str(f["properties"].get(ck) or "") if ck else ""
        return v != "" and v not in ("0", "1")
    # 公立の小学校（学校コードの先頭 B1）と義務教育学校（先頭 C2）。5文字目が 2（公立）
    pub_all = [f for f in pts if f["properties"]["P29_002"][:2] in ("B1", "C2") and f["properties"]["P29_002"][4] == "2"]
    # 設置者の名前（「○○市立」など。郡名は外す。組合立は見ない）が、その市区町村の公立学校の設置者でいちばん多いものと違う学校は使わない
    def owner(name):
        if re.match(r"^.{0,12}組合立", name or ""):
            return None
        m = re.match(r"^(.{1,12}?(?:市|町|村|区))立", name or "")
        return re.sub(r"^.+郡", "", m.group(1)) if m else None
    tally = defaultdict(lambda: defaultdict(int))
    for f in pts:
        p = f["properties"]
        if (p["P29_002"] or "")[4:5] == "2" or not p["P29_002"]:
            o = owner(p["P29_004"])
            if o:
                tally[p["P29_001"]][o] += 1
    major = {}
    for c, t in tally.items():
        top = sorted(t.items(), key=lambda kv: -kv[1])
        if len(top) == 1 or top[0][1] > top[1][1]:
            major[c] = top[0][0]
    wrong = [f for f in pub_all if owner(f["properties"]["P29_004"]) and f["properties"]["P29_001"] in major
             and owner(f["properties"]["P29_004"]) != major[f["properties"]["P29_001"]]]
    print(f"設置者の名前が市区町村と合わないので使わない学校: {[(f['properties']['P29_001'], f['properties']['P29_004']) for f in wrong]}")
    pub_all = [f for f in pub_all if f not in wrong]
    print(f"休校区分の属性: {ck}。使わない公立小学校: {[(f['properties']['P29_001'], strip_owner(f['properties']['P29_004']), f['properties'][ck]) for f in pub_all if closed(f)]}")
    public = [(f["properties"]["P29_002"], strip_owner(f["properties"]["P29_004"]), f["properties"]["P29_001"],
               *f["geometry"]["coordinates"][:2])
              for f in pub_all if not closed(f)]
    # まとめた区域（DATA_METHOD.md「まとめた区域」）：メッシュに 07999 のようなまとめたコードがあるとき、
    # 「出さない」町村の学区の子どもと、どの学区にも入らない点のうち、13市町村の公立小・義務教育学校（休校を除く）で
    # いちばん近いのが「出さない」町村の学校である点の子どもは、扱わない区域（どこにも配分しない）
    areas = defaultdict(dict)
    if AREA_TABLE.exists():
        with open(AREA_TABLE, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                areas[r["まとめた区域のコード"]][r["行政区域コード"]] = r["扱い"].startswith("出す")
    not_handled, nh_by = 0.0, defaultdict(float)
    for area, members in areas.items():
        hidden = {c for c, show in members.items() if not show}
        if not hidden or not any(area in m.split("_") for m in mcity):
            continue
        for k in [k for k, v in est.items() if v["city"] in hidden]:
            not_handled += est[k]["e"][0]
            nh_by[est[k]["city"]] += est[k]["e"][0]
            del est[k]
        sch = [(f["properties"]["P29_001"], *f["geometry"]["coordinates"][:2]) for f in pts
               if (f["properties"]["P29_002"] or "")[:2] in ("B1", "C2") and f["properties"]["P29_002"][4] == "2"
               and not closed(f) and f["properties"]["P29_001"] in members]
        js = np.array([j for j in np.nonzero(count == 0)[0] if area in mcity[pm[j]].split("_")], dtype=int)
        if not sch or js.size == 0:
            continue
        ax, ay = np.array([s[1] for s in sch], float), np.array([s[2] for s in sch], float)
        d2 = ((px[js, None] - ax[None, :]) * np.cos(np.radians(py[js, None]))) ** 2 + (py[js, None] - ay[None, :]) ** 2
        own = [sch[o][0] for o in np.argmin(d2, axis=1)]
        sel = np.array([o in hidden for o in own], bool)
        for j, o in zip(js[sel], np.array(own)[sel]):
            nh_by[o] += kids[pm[j], 0] * w0
        not_handled += float((kids[pm[js[sel]], 0] * w0).sum())
        count[js[sel]] += 1  # ほかの補いにも使わない
    if nh_by:
        print(f"扱わない区域（2025年）: {{{', '.join(f'{c}: {v:.1f}' for c, v in sorted(nh_by.items()))}}}、計 {not_handled:.1f}")

    S = [s for s in public if s[2] in gap]
    scity = np.array([s[2] for s in S])
    sx, sy = np.array([s[3] for s in S], float), np.array([s[4] for s in S], float)
    near, neara = np.zeros((len(S), len(YEARS))), np.zeros((len(S), 3))
    touches = np.array([any(c in gap for c in m.split("_")) for m in mcity])
    kx = math.cos(math.radians(float(py[np.repeat(touches, K * K)].mean()))) if touches.any() else 1.0
    groups = defaultdict(list)
    for j in np.nonzero(count == 0)[0]:
        groups[mcity[pm[j]]].append(j)
    left = []  # 学区データなしの市区町村の学校に当たらなかった点
    for combo, js in groups.items():
        js = np.array(js)
        cand = np.nonzero(np.isin(scity, [c for c in combo.split("_") if c in gap]))[0]
        if cand.size == 0:
            left.append(js)
            continue
        k = np.cos(np.radians(py[js, None])) if args.lat_scale == "point" else kx
        d2 = ((px[js, None] - sx[None, cand]) * k) ** 2 + (py[js, None] - sy[None, cand]) ** 2
        o = cand[np.argmin(d2, axis=1)]
        np.add.at(near, o, kids[pm[js]] * w0)
        np.add.at(neara, o, V[pm[js], :, 0] * w0)
    for i, s in enumerate(S):
        est[f"{s[0]}@{s[2]}"] = dict(name=s[1], city=s[2], approx=True, e=near[i], a=neara[i])

    # 学区データのある市区町村（配分率 0.9 未満）で、学区データに入っていない公立小学校
    # （学校コード、無ければ（市区町村, 設置者を外した名前）で突き合わせる。「分校」で終わる学校は除く）
    dcity = ({f["properties"]["A27_001"] for f in feats} - gap) & set(low)
    have_code = {f["properties"]["A27_003"] for f in feats}
    have_name = {(f["properties"]["A27_001"], strip_owner(f["properties"]["A27_004"])) for f in feats}
    T = [s for s in public if s[2] in dcity and s[0] not in have_code and (s[2], s[1]) not in have_name
         and not s[1].endswith("分校")]
    if args.no_fill_missing:
        T = []
    miss = set(range(len(T)))
    tcity = np.array([s[2] for s in T])
    tx, ty = np.array([s[3] for s in T], float), np.array([s[4] for s in T], float)
    fill, filla = np.zeros((len(T), len(YEARS))), np.zeros((len(T), 3))
    unassigned = 0.0
    for js in left:
        combo = mcity[pm[js[0]]]
        cand = np.nonzero(np.isin(tcity, [c for c in combo.split("_") if c in dcity]))[0] if T else np.zeros(0, int)
        if cand.size == 0:
            unassigned += (kids[pm[js], 0] * w0).sum()
            continue
        k = np.cos(np.radians(py[js, None])) if args.lat_scale == "point" else kx
        d2 = ((px[js, None] - tx[None, cand]) * k) ** 2 + (py[js, None] - ty[None, cand]) ** 2
        o = cand[np.argmin(d2, axis=1)]  # 補う学校の中でいちばん近い学校
        np.add.at(fill, o, kids[pm[js]] * w0)
        np.add.at(filla, o, V[pm[js], :, 0] * w0)
    for i in sorted(miss):
        s = T[i]
        est[f"{s[0]}@{s[2]}"] = dict(name=s[1], city=s[2], approx=True, e=fill[i], a=filla[i])
    filled = defaultdict(list)
    for i in sorted(miss):
        filled[T[i][2]].append((T[i][1], round(float(fill[i, 0]), 1)))

    total = kids[:, 0].sum()
    allocated = sum(v["e"][0] for v in est.values())
    print(f"メッシュ {n}件、6〜11歳の合計（2025年）{total:.1f}、配分 {allocated:.1f}、未配分 {unassigned:.1f}（{unassigned / total:.4f}）、"
          f"扱わない区域 {not_handled:.1f}、保存則の誤差 {total - allocated - unassigned - not_handled:.4f}")
    print(f"学区のある学校 {sum(not v['approx'] for v in est.values())}、学区データなしの市区町村 {len(gap)}（学校 {len(S)}）")
    print(f"学区データがあるのに配分率が0.9未満の市区町村: {low}")
    print(f"学区データに無いので補った学校（2025年の推計）: {dict(filled)}")

    # アプリのデータと比べる
    s = open(args.pref_js, encoding="utf-8").read()
    app = json.loads(s[s.index("UG.registerPref(") + 16:s.rindex(")")])
    # アプリの学校は（id が学校コードなら）（学校コード, 市区町村）で、id が「市区町村コード-番号」なら（市区町村, 学校名）で突き合わせる。
    # 学区データの学校コードが P29 では別の市区町村の学校のもの（古河市）は、id に学校コードを使っていないことも確かめる
    # 別の市区町村の学校のコード＝P29 でそのコードの学校の市区町村が違い、設置者の名前も学区データの設置者と違うもの
    # （大野城市立下大利小が太宰府市のコードで入っているような、P29 の行政区域コードだけの誤りは当たらない）
    p29_city = {f["properties"]["P29_002"]: f["properties"]["P29_001"] for f in pts if f["properties"]["P29_002"]}
    p29_owner = {f["properties"]["P29_002"]: owner(f["properties"]["P29_004"]) for f in pts if f["properties"]["P29_002"]}
    a27_owner = {skey(f): re.sub(r"^.+郡", "", re.sub(r"立$", "", f["properties"]["A27_002"] or "")) for f in feats}
    mine = {k for k, v in est.items() if v["e"][0] >= 1.0}  # 2025年の推計が1人未満の学校は出力されない
    by_name = {f'{v["city"]}|{v["name"]}': k for k, v in est.items() if k in mine}
    app_s, only_app, foreign_id = {}, [], []
    for c in app["cities"]:
        for sc in c["schools"]:
            k = f'{sc["id"]}@{c["code"]}' if re.match(r"^[A-H]\d{12}$", sc["id"]) else None
            if k is None or k not in mine:
                k = by_name.get(f'{c["code"]}|{sc["name"]}') if k is None else k
            if k is None or k not in mine or k in app_s:
                only_app.append((c["code"], sc["name"]))
                continue
            app_s[k] = (c["code"], sc)
            code = k.split("@")[0] if "@" in k else ""
            if (code and not est[k]["approx"] and p29_city.get(code, c["code"]) != c["code"]
                    and p29_owner.get(code) != a27_owner.get(k) and sc["id"] == code):
                foreign_id.append(k)
    only_mine = sorted(mine - set(app_s))
    print(f"学区データの学校コードが別の市区町村の学校のもの（id に使っていてはいけない）: 違反 {foreign_id}")
    bad_d, bad_a, bad_meta, worst = [], [], [], 0.0
    for k in set(app_s) & mine:
        code, sc = app_s[k]
        d = float(np.abs(np.array(sc["est"]) - est[k]["e"]).max())
        g = est[k]["a"]
        ages = np.r_[np.repeat(g[0] / 5, 5), np.repeat(g[1] / 5, 5), np.repeat(g[2] / 5, 2)]
        da = float(np.abs(np.array(sc["ages"]) - ages).max()) if "ages" in sc else 0.0
        if code != est[k]["city"] or bool(sc.get("approx")) != est[k]["approx"]:
            bad_meta.append(k)
        if max(d, da) > 0.06:
            (bad_a if est[k]["approx"] else bad_d).append((round(max(d, da), 2), sc["name"], code))
            worst = max(worst, d, da)
    print(f"アプリ {len(app_s)}校、検算 {len(mine)}校。アプリだけ {len(only_app)}、検算だけ {len(only_mine)}、市区町村や区分の違い {len(bad_meta)}")
    print(f"0.06人を超えて違う学校：学区のある学校 {len(bad_d)}、おおよその区域の学校 {len(bad_a)}（最大 {worst:.2f}人）")
    for row in sorted(bad_d + bad_a, reverse=True)[:20]:
        print("  ", row)
    fail = bool(only_app or only_mine or bad_meta or bad_d or foreign_id or (args.strict and bad_a))
    print("結果:", "不一致あり" if fail else "一致")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
