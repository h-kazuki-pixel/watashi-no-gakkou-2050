"""ポリゴンの最小限の幾何計算（numpy のみ。shapely / GDAL は不要）。

座標は [経度, 緯度] の順（GeoJSON・シェープファイルと同じ）。
学区は数km程度の広がりなので、距離と面積は「経度 × cos(緯度)」の平面近似で扱う。
"""
from __future__ import annotations

import math

import numpy as np

Ring = np.ndarray  # shape (n, 2)


def rings_from_geojson(geom: dict | None) -> list[Ring]:
    """GeoJSON の Polygon / MultiPolygon から、すべてのリング（外周と穴）を取り出す。"""
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        polys = [c]
    elif t == "MultiPolygon":
        polys = c
    elif t == "GeometryCollection":
        out: list[Ring] = []
        for g in geom.get("geometries", []):
            out += rings_from_geojson(g)
        return out
    else:
        return []
    rings = []
    for poly in polys:
        for ring in poly:
            a = np.asarray(ring, dtype=float)
            if a.ndim == 2 and a.shape[0] >= 3:
                rings.append(a[:, :2])
    return rings


def polys_from_geojson(geom: dict | None) -> list[list[Ring]]:
    """GeoJSON の Polygon / MultiPolygon を、部分（外側の輪 1つ ＋ 穴の輪）ごとに取り出す。"""
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "GeometryCollection":
        return [p for g in geom.get("geometries", []) for p in polys_from_geojson(g)]
    polys = [c] if t == "Polygon" else c if t == "MultiPolygon" else []
    out = []
    for poly in polys:
        rings = [np.asarray(r, dtype=float)[:, :2] for r in poly if np.asarray(r).ndim == 2 and len(r) >= 3]
        if rings:
            out.append(rings)
    return out


def polys_from_rings(rings: list[Ring]) -> list[list[Ring]]:
    """部分の区切りが無いリングの並び（シェープファイル、凸包）を、部分ごとに組み立てる。

    シェープファイルの決まりでは、外側の輪と穴の輪は向きが逆（外側が時計回り）。いちばん大きい輪の向きを外側の向きとし、
    同じ向きの輪を外側、逆向きの輪を穴とする。穴は、頂点のいちばん多くが内側にある外側の輪に付ける（無ければいちばん大きい外側の輪）。"""
    if not rings:
        return []
    areas = [ring_signed_area(r) for r in rings]
    big = max(range(len(rings)), key=lambda i: abs(areas[i]))
    sign = 1 if areas[big] >= 0 else -1
    outers = [i for i in range(len(rings)) if areas[i] * sign >= 0]
    polys = {i: [rings[i]] for i in outers}
    for i in range(len(rings)):
        if i in polys:
            continue
        r = rings[i]
        best, best_n = big, -1
        for j in outers:
            n = int(points_in_rings(r[:, 0], r[:, 1], [rings[j]]).sum())
            if n > best_n:
                best, best_n = j, n
        polys[best].append(r)
    return [polys[i] for i in outers]


def points_in_polys(px: np.ndarray, py: np.ndarray, polys: list[list[Ring]]) -> np.ndarray:
    """点が区域の内側かどうか。区域＝部分ごとの「外側の輪 − 穴」を合わせたもの（部分が重なる所も内側。二重には数えない）。"""
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    inside = np.zeros(px.shape[0], dtype=bool)
    for poly in polys:
        todo = np.nonzero(~inside)[0]
        if todo.size == 0:
            break
        m = points_in_rings(px[todo], py[todo], [poly[0]])
        for hole in poly[1:]:
            sel = np.nonzero(m)[0]
            if sel.size == 0:
                break
            m[sel] &= ~points_in_rings(px[todo][sel], py[todo][sel], [hole])
        inside[todo[m]] = True
    return inside


def ring_key(ring: Ring) -> tuple:
    """同じ輪かどうかを比べるための鍵（始点と向きによらない）。"""
    r = np.round(np.asarray(ring, dtype=float), 9)
    if len(r) > 1 and np.array_equal(r[0], r[-1]):
        r = r[:-1]
    if len(r) == 0:
        return ()
    pts = [tuple(p) for p in r]
    i = min(range(len(pts)), key=lambda k: pts[k])
    a = pts[i:] + pts[:i]
    b = [a[0]] + a[1:][::-1]
    return tuple(min(a, b))


def bbox(rings: list[Ring]) -> tuple[float, float, float, float]:
    xs = np.concatenate([r[:, 0] for r in rings])
    ys = np.concatenate([r[:, 1] for r in rings])
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def points_in_rings(px: np.ndarray, py: np.ndarray, rings: list[Ring], budget: int = 2_000_000) -> np.ndarray:
    """点がポリゴンの内側かどうか（偶奇規則。穴や複数ポリゴンもリングをまとめて数えれば正しく扱える）。

    点の数 × 辺の数 の行列を一度に作るとメモリを使いすぎるので、辺を小分けにして処理する。
    """
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    inside = np.zeros(px.shape[0], dtype=bool)
    if px.shape[0] == 0:
        return inside
    step = max(1, budget // px.shape[0])
    pxc, pyc = px[:, None], py[:, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        for ring in rings:
            x1, y1 = ring[:, 0], ring[:, 1]
            x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
            for s in range(0, len(x1), step):
                a1, b1, a2, b2 = x1[s:s + step], y1[s:s + step], x2[s:s + step], y2[s:s + step]
                cross = (b1 > pyc) != (b2 > pyc)
                xi = (a2 - a1) * (pyc - b1) / (b2 - b1) + a1
                inside ^= (np.count_nonzero(cross & (pxc < xi), axis=1) % 2).astype(bool)
    return inside


def _coslat(rings: list[Ring]) -> float:
    lat = float(np.mean(np.concatenate([r[:, 1] for r in rings])))
    return math.cos(math.radians(lat))


def ring_signed_area(ring: Ring) -> float:
    """度の2乗での符号つき面積（靴ひも公式）。"""
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def area_km2(rings: list[Ring]) -> float:
    """おおよその面積（km²）。偶奇規則に合わせ、外周（面積最大）以外で内側にあるリングは穴として引く。"""
    if not rings:
        return 0.0
    k = _coslat(rings)
    deg_km = 111.32
    total = 0.0
    areas = [abs(ring_signed_area(r)) for r in rings]
    order = np.argsort(areas)[::-1]
    for idx_pos, i in enumerate(order):
        r = rings[i]
        # 自分より大きいリングの内側にあれば穴
        depth = 0
        for j in order[:idx_pos]:
            if points_in_rings(r[:1, 0], r[:1, 1], [rings[j]])[0]:
                depth += 1
        total += areas[i] * (1 if depth % 2 == 0 else -1)
    return total * k * deg_km * deg_km


def area_km2_polys(polys: list[list[Ring]]) -> float:
    """部分ごとの（外側の輪 − 穴）の面積の和（km²）。部分どうしの重なりは2回数える（表示用のおおよその値）。"""
    if not polys:
        return 0.0
    k = _coslat([p[0] for p in polys])
    total = sum(abs(ring_signed_area(p[0])) - sum(abs(ring_signed_area(h)) for h in p[1:]) for p in polys)
    return total * k * 111.32 * 111.32


def centroid(rings: list[Ring]) -> tuple[float, float]:
    """面積が最大のリングの重心（経度, 緯度）。学校の位置が分からないときの代わりに使う。"""
    r = max(rings, key=lambda q: abs(ring_signed_area(q)))
    x, y = r[:, 0], r[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y2 - x2 * y
    a = float(np.sum(cr)) / 2.0
    if abs(a) < 1e-15:
        return float(x.mean()), float(y.mean())
    cx = float(np.sum((x + x2) * cr)) / (6.0 * a)
    cy = float(np.sum((y + y2) * cr)) / (6.0 * a)
    return cx, cy


def simplify_ring(ring: Ring, tol_deg: float) -> Ring:
    """Douglas–Peucker 法でリングを間引く（アプリの地図表示用）。閉じたリングを返す。"""
    pts = ring
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    n = len(pts)
    if n <= 4:
        return np.vstack([pts, pts[:1]])
    k = math.cos(math.radians(float(pts[:, 1].mean())))
    q = np.column_stack([pts[:, 0] * k, pts[:, 1]])
    # 始点から最も遠い点で2つの開いた折れ線に分け、それぞれを間引く
    far = int(np.argmax(np.hypot(q[:, 0] - q[0, 0], q[:, 1] - q[0, 1])))
    keep = np.zeros(n + 1, dtype=bool)
    qq = np.vstack([q, q[:1]])
    keep[[0, far, n]] = True
    stack = [(0, far), (far, n)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = qq[b] - qq[a]
        ln = math.hypot(seg[0], seg[1])
        mid = qq[a + 1:b]
        if ln < 1e-15:
            d = np.hypot(mid[:, 0] - qq[a, 0], mid[:, 1] - qq[a, 1])
        else:
            d = np.abs(seg[0] * (mid[:, 1] - qq[a, 1]) - seg[1] * (mid[:, 0] - qq[a, 0])) / ln
        i = int(np.argmax(d))
        if d[i] > tol_deg:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    out = np.vstack([pts, pts[:1]])[keep]
    if len(out) < 4:
        return np.vstack([pts, pts[:1]])
    return out


def simplify_for_display(rings: list[Ring], decimals: int = 5, min_share: float = 0.02) -> list[list[list[float]]]:
    """地図表示用に、外周だけを残して間引き、座標を丸める。小さな飛び地（面積2%未満）は落とす。"""
    if not rings:
        return []
    areas = [abs(ring_signed_area(r)) for r in rings]
    big = max(areas)
    out = []
    for r, a in zip(rings, areas):
        if a < big * min_share:
            continue
        # 穴（より大きなリングの内側）は描かない
        inner = any(
            (b > a) and points_in_rings(r[:1, 0], r[:1, 1], [o])[0]
            for o, b in zip(rings, areas) if o is not r
        )
        if inner:
            continue
        tol = max(0.00015, math.sqrt(a) * 0.012)
        s = simplify_ring(r, tol)
        out.append([[round(float(x), decimals), round(float(y), decimals)] for x, y in s])
    return out
