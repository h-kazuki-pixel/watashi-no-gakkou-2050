#!/usr/bin/env python3
"""別の実装による検算：アプリの学校別推計（pref_XX.js）を、元データから計算し直して学校ごとに比べる。

パイプライン（pipeline/）のコードは一切読み込まない。docs/DATA_METHOD.md に書かれた手順だけを実装している。
メッシュは XML の要素名（populationOfAge5To9In2025 など）で読むので、列の位置の判定にも頼らない。

  python3 independent_check.py \
      --mesh 500m_mesh_2024_40.xml --districts A27-23_40.geojson --schools P29-23_40.geojson \
      --pref-js app/data/pref_40.js --exclude 40228

zip はあらかじめ展開しておく。必要なのは numpy だけ。
比べるもの：学校の集合、市区町村、おおよその区域かどうか、2025〜2070年の推計（10個）、0〜11歳の各歳（12個）。
おおよその区域は2種類：学区データの無い市区町村の学校と、学区データのある市区町村で学区データに入っていない公立小学校
（どの学区にも入らなかった点のうち、同じ市区町村の公立小学校すべての中でいちばん近いのがその学校だった点を足す）。
距離は、経度の差に点ごとの緯度の cos を掛ける（--lat-scale point。mean は以前のパイプラインの、県全体で1つの値）。
学区データのある学校が 0.06人を超えて違えば終了コード 1。おおよその区域の学校は、2つの学校からほぼ同じ距離にある点の
割り当てが入れ替わることがあるので、違いの数と大きさを報告する（--strict を付けると、これも 1 件で終了コード 1）。
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict

import numpy as np

YEARS = list(range(2025, 2075, 5))
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
    m = re.match(r"^.{1,12}?(?:市|町|村|区|組合)立(.+(?:学校|学園|分校))$", name or "")
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


def in_geom(x, y, geom):
    res = np.zeros(x.shape, bool)
    for poly in polygons(geom):
        ins = in_ring(x, y, poly[0])
        for hole in poly[1:]:
            ins &= ~in_ring(x, y, hole)
        res |= ins
    return res


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

    # 学区への配分
    feats = [f for f in json.load(open(args.districts, encoding="utf-8"))["features"] if f["properties"]["A27_001"] not in exclude]
    hits, count = [], np.zeros(px.shape[0], int)
    for f in feats:
        outer = np.array([p for poly in polygons(f["geometry"]) for p in poly[0]])
        idx = np.nonzero((px >= outer[:, 0].min()) & (px <= outer[:, 0].max()) & (py >= outer[:, 1].min()) & (py <= outer[:, 1].max()))[0]
        ins = idx[in_geom(px[idx], py[idx], f["geometry"])]
        hits.append(ins)
        count[ins] += 1
    est = {}
    for f, ins in zip(feats, hits):
        w = w0 / count[ins]
        sid = f["properties"]["A27_003"]
        if sid in est:  # 同じ学校が複数の図形に分かれているとき
            est[sid]["e"] += (kids[pm[ins]] * w[:, None]).sum(0)
            est[sid]["a"] += (V[pm[ins], :, 0] * w[:, None]).sum(0)
        else:
            est[sid] = dict(name=f["properties"]["A27_004"], city=f["properties"]["A27_001"], approx=False,
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

    # おおよその区域：公立小学校（学校コードの先頭2文字が B1、5文字目が 2）のうち、いちばん近い学校
    pts = json.load(open(args.schools, encoding="utf-8"))["features"]
    public = [(f["properties"]["P29_002"], strip_owner(f["properties"]["P29_004"]), f["properties"]["P29_001"],
               *f["geometry"]["coordinates"][:2])
              for f in pts if f["properties"]["P29_002"][:2] == "B1" and f["properties"]["P29_002"][4] == "2"]
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
        est[s[0]] = dict(name=s[1], city=s[2], approx=True, e=near[i], a=neara[i])

    # 学区データのある市区町村で、学区データに入っていない公立小学校（学校コード、無ければ（市区町村, 設置者を外した名前））
    dcity = {f["properties"]["A27_001"] for f in feats} - gap
    have_code = {f["properties"]["A27_003"] for f in feats}
    have_name = {(f["properties"]["A27_001"], strip_owner(f["properties"]["A27_004"])) for f in feats}
    T = [s for s in public if s[2] in dcity]
    miss = {i for i, s in enumerate(T) if s[0] not in have_code and (s[2], s[1]) not in have_name}
    if args.no_fill_missing:
        miss = set()
    tcity = np.array([s[2] for s in T])
    tx, ty = np.array([s[3] for s in T], float), np.array([s[4] for s in T], float)
    fill, filla = np.zeros((len(T), len(YEARS))), np.zeros((len(T), 3))
    unassigned = 0.0
    for js in left:
        combo = mcity[pm[js[0]]]
        cand = np.nonzero(np.isin(tcity, [c for c in combo.split("_") if c in dcity]))[0] if miss else np.zeros(0, int)
        if cand.size == 0:
            unassigned += (kids[pm[js], 0] * w0).sum()
            continue
        k = np.cos(np.radians(py[js, None])) if args.lat_scale == "point" else kx
        d2 = ((px[js, None] - tx[None, cand]) * k) ** 2 + (py[js, None] - ty[None, cand]) ** 2
        o = cand[np.argmin(d2, axis=1)]
        hit = np.isin(o, list(miss))  # いちばん近いのが補う学校だった点だけを足す。ほかは未配分のまま
        np.add.at(fill, o[hit], kids[pm[js[hit]]] * w0)
        np.add.at(filla, o[hit], V[pm[js[hit]], :, 0] * w0)
        unassigned += (kids[pm[js[~hit]], 0] * w0).sum()
    for i in sorted(miss):
        s = T[i]
        est[s[0]] = dict(name=s[1], city=s[2], approx=True, e=fill[i], a=filla[i])
    filled = defaultdict(list)
    for i in sorted(miss):
        filled[T[i][2]].append((T[i][1], round(float(fill[i, 0]), 1)))

    total = kids[:, 0].sum()
    allocated = sum(v["e"][0] for v in est.values())
    print(f"メッシュ {n}件、6〜11歳の合計（2025年）{total:.1f}、配分 {allocated:.1f}、未配分 {unassigned:.1f}（{unassigned / total:.4f}）、"
          f"保存則の誤差 {total - allocated - unassigned:.4f}")
    print(f"学区のある学校 {sum(not v['approx'] for v in est.values())}、学区データなしの市区町村 {len(gap)}（学校 {len(S)}）")
    print(f"学区データがあるのに配分率が0.9未満の市区町村: {low}")
    print(f"学区データに無いので補った学校（2025年の推計）: {dict(filled)}")

    # アプリのデータと比べる
    s = open(args.pref_js, encoding="utf-8").read()
    app = json.loads(s[s.index("UG.registerPref(") + 16:s.rindex(")")])
    app_s = {sc["id"]: (c["code"], sc) for c in app["cities"] for sc in c["schools"]}
    mine = {k for k, v in est.items() if v["e"][0] >= 1.0}  # 2025年の推計が1人未満の学校は出力されない
    only_app, only_mine = sorted(set(app_s) - mine), sorted(mine - set(app_s))
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
    fail = bool(only_app or only_mine or bad_meta or bad_d or (args.strict and bad_a))
    print("結果:", "不一致あり" if fail else "一致")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
