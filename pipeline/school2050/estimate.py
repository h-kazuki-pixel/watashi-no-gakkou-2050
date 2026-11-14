"""メッシュ別の人口を、学区ポリゴンに配分して合計する。

方法（面積按分の点サンプリング近似）
  1. 各メッシュのセルに k×k 個の点を等間隔に置く（既定 k=4。500mメッシュなら約125m間隔）。
  2. 点ごとに、どの学区ポリゴンの内側かを調べる。
  3. メッシュの人口を点の数で等分し、点が入っている学区に足す。
     - 複数の学区に入る点（学区が重なっている所）は、その学区の数で等分する。
     - どの学区にも入らない点（学区データが無い区域など）は「未配分」として集計する。
メッシュの中で人口が一様に分布しているという仮定は、面積按分と同じ。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geo, meshcode


@dataclass
class Allocation:
    sums: np.ndarray        # (学区の数, 特徴量の数)
    unassigned: np.ndarray  # (特徴量の数,) どの学区にも入らなかった分
    mesh_assigned: np.ndarray  # (メッシュの数,) 学区に配分できた割合 0〜1
    overlap_points: int     # 複数の学区に入った点の数
    total_points: int
    count: np.ndarray       # (メッシュの数 × k × k,) 点ごとの、入っている学区の数。0 は未配分の点


def allocate(codes: list, values: np.ndarray, districts: list, k: int = 4, log=None) -> Allocation:
    """codes: メッシュコード / values: (N, F) / districts: リングのリストを持つオブジェクトの列（.rings）。"""
    n = len(codes)
    values = np.asarray(values, dtype=float)
    f = values.shape[1]
    sums = np.zeros((len(districts), f))
    if n == 0:
        return Allocation(sums, np.zeros(f), np.zeros(0), 0, 0, np.zeros(0, dtype=np.int32))

    lat0, lng0, dlat, dlng = meshcode.decode_many(codes)
    off = (np.arange(k) + 0.5) / k
    # 点の座標（メッシュ n の (i, j) 番目）
    py = (lat0[:, None, None] + off[None, :, None] * dlat[:, None, None]) + np.zeros((1, 1, k))
    px = (lng0[:, None, None] + off[None, None, :] * dlng[:, None, None]) + np.zeros((1, k, 1))
    px, py = px.reshape(-1), py.reshape(-1)
    pm = np.repeat(np.arange(n), k * k)

    order = np.argsort(px, kind="stable")
    pxs, pys = px[order], py[order]
    count = np.zeros(px.shape[0], dtype=np.int32)
    hits = []
    for d, dist in enumerate(districts):
        if not dist.rings:
            continue
        minx, miny, maxx, maxy = geo.bbox(dist.rings)
        lo, hi = np.searchsorted(pxs, minx, "left"), np.searchsorted(pxs, maxx, "right")
        if hi <= lo:
            continue
        cand = np.nonzero((pys[lo:hi] >= miny) & (pys[lo:hi] <= maxy))[0] + lo
        if cand.size == 0:
            continue
        inside = geo.points_in_rings(pxs[cand], pys[cand], dist.rings)
        sel = order[cand[inside]]
        if sel.size:
            count[sel] += 1
            hits.append((d, sel))
        if log and (d + 1) % 200 == 0:
            log(f"  学区 {d + 1}/{len(districts)} まで処理")

    w0 = 1.0 / (k * k)
    for d, sel in hits:
        w = w0 / count[sel]
        sums[d] = (values[pm[sel]] * w[:, None]).sum(axis=0)

    assigned = np.bincount(pm[count > 0], minlength=n) * w0
    unassigned = (values * (1.0 - assigned)[:, None]).sum(axis=0)
    return Allocation(sums, unassigned, assigned, int((count > 1).sum()), int(px.shape[0]), count)


def split_cities(code: str) -> list:
    """メッシュの行政区域コード。境界をまたぐメッシュは "40133_40134" のように「_」で並ぶので、リストにする。"""
    return [c.strip().zfill(5) for c in str(code).split("_") if c.strip()]


@dataclass
class NearestAllocation:
    sums: np.ndarray          # (学校の数, 特徴量の数)
    hulls: list               # 学校ごとの、割り当てた点の凸包（表示用のおおよその区域）
    mesh_mask: np.ndarray     # この方法で配分したメッシュ


def allocate_nearest(codes: list, mesh_city: list, values: np.ndarray, schools: list, cities: set, k: int = 4,
                     count: np.ndarray | None = None) -> NearestAllocation:
    """学区データの無い市区町村で、各点を「そのメッシュの市区町村の中でいちばん近い学校」に割り当てる。

    schools: (行政区域コード, 経度, 緯度) の列。cities: この方法を使う市区町村のコード。
    距離は経度に cos(緯度) を掛けた平面近似。点が属する市区町村はメッシュの市区町村コードで決める。
    境界をまたぐメッシュ（"40133_40134"）は、そのうち cities に入る市区町村すべての学校を候補にする。
    count: allocate() の点ごとの学区の数（同じ k で作ったもの）。渡すと count == 0 の点だけを使い、
    学区に配分済みの点を二重に数えない。
    ボロノイ分割と同じ考え方で、境界は「2つの学校からの距離が等しい線」になる。
    """
    values = np.asarray(values, dtype=float)
    f = values.shape[1]
    sums = np.zeros((len(schools), f))
    hulls: list = [None] * len(schools)
    # メッシュごとの候補の市区町村（cities に入るものだけ）。空なら、この方法では配分しない
    cand = [tuple(sorted(set(split_cities(c)) & set(cities))) for c in mesh_city]
    mask = np.array([bool(c) for c in cand], dtype=bool)
    if not mask.any() or not schools:
        return NearestAllocation(sums, hulls, mask)
    idx = np.nonzero(mask)[0]
    lat0, lng0, dlat, dlng = meshcode.decode_many([codes[i] for i in idx])
    off = (np.arange(k) + 0.5) / k
    py = (lat0[:, None, None] + off[None, :, None] * dlat[:, None, None] + np.zeros((1, 1, k))).reshape(-1)
    px = (lng0[:, None, None] + off[None, None, :] * dlng[:, None, None] + np.zeros((1, k, 1))).reshape(-1)
    pm = np.repeat(idx, k * k)
    if count is not None:
        # allocate() と同じ並び（メッシュ順 → 行 → 列）なので、全体での点の番号はこうなる
        gidx = pm * (k * k) + np.tile(np.arange(k * k), idx.size)
        free = np.asarray(count)[gidx] == 0
    else:
        free = np.ones(px.shape[0], dtype=bool)
    groups: dict = {}  # 候補の組 → 番号
    pg = np.repeat([groups.setdefault(cand[i], len(groups)) for i in idx], k * k)  # 点 → 候補の組の番号
    sch_city = np.array([s[0] for s in schools])
    sx = np.array([s[1] for s in schools], dtype=float)
    sy = np.array([s[2] for s in schools], dtype=float)
    kx = np.cos(np.radians(float(np.mean(py))))
    owner = np.full(px.shape[0], -1)
    for group, gi in groups.items():
        sel_p = np.nonzero((pg == gi) & free)[0]
        sel_s = np.nonzero(np.isin(sch_city, list(group)))[0]
        if sel_p.size == 0 or sel_s.size == 0:
            continue
        for a in range(0, sel_p.size, 20000):
            chunk = sel_p[a:a + 20000]
            d2 = ((px[chunk, None] - sx[None, sel_s]) * kx) ** 2 + (py[chunk, None] - sy[None, sel_s]) ** 2
            owner[chunk] = sel_s[np.argmin(d2, axis=1)]
    w = 1.0 / (k * k)
    ok = owner >= 0
    np.add.at(sums, owner[ok], values[pm[ok]] * w)
    for j in np.unique(owner[ok]):
        pts = np.column_stack([px[owner == j], py[owner == j]])
        hulls[j] = convex_hull(pts)
    # 学校の無い市区町村のメッシュは配分していないので、mask から外す
    covered = np.zeros(len(codes), dtype=bool)
    covered[np.unique(pm[ok])] = True
    return NearestAllocation(sums, hulls, mask & covered)


def convex_hull(pts: np.ndarray) -> np.ndarray:
    """点の凸包（閉じたリング）。Andrew の単調連鎖法。"""
    p = np.unique(np.round(pts, 7), axis=0)
    if len(p) < 3:
        return np.vstack([p, p[:1]])
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in p[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    h = np.array(lower[:-1] + upper[:-1])
    return np.vstack([h, h[:1]])
