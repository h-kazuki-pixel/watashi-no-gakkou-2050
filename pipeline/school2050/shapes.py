"""学区の図形の検査と、乱れた図形の扱い（docs/DATA_METHOD.md「学区の図形」）。

国土数値情報の小学校区データには、次のような乱れた図形がある（2026-11-16 の全国予行で見つけたもの）。
  - 同じ輪の重複：同じ穴の輪が2回入っている（千葉県 鶴巻小など）
  - 外に出た穴：穴の輪が、外側の輪の外にはみ出している（石川県 天神山小など。実際は、となりの飛び地が穴として入っている）
  - 部分の重なり：同じ学校の部分（ポリゴン）どうしが重なっている（鹿児島県 大和小など）

区域は「部分ごとに 外側の輪 − 穴 を作り、部分を合わせたもの」（geo.points_in_polys）。そのうえで
  - 同じ輪の重複は、2つ目からを取り除く
  - 外に出た穴は、はみ出した部分がほかの学校の学区に入っていなければ、飛び地としてその学校の区域に入れる
    （外側の輪の内側の部分は、穴のまま抜く）。ほかの学校の学区に入っていれば、穴のままにする
  - 部分の重なりは、合わせるときに1回だけ数える（geo.points_in_polys がそうなっている）
どれも report_XX.json の geometry_issues に一覧で出す。
"""
from __future__ import annotations

import numpy as np

from . import geo

GRID = 200            # 穴の範囲に置く格子の1辺の点の数（面積の割合を測る）
OUTSIDE_MIN = 0.01    # 穴の面積のうち、外側の輪の外にある割合がこれ以下なら「外に出た穴」としない（輪が接しているだけ）
OTHER_SHARE = 0.5     # はみ出した部分のうち、ほかの学区に入る割合がこれ以上なら「ほかの学校の学区に入っている」


def polys_of(f) -> list:
    """地物の部分の並び。無ければ（凸包など）リングから組み立てる。"""
    return f.polys if getattr(f, "polys", None) else geo.polys_from_rings(f.rings)


def _bbox(polys) -> tuple:
    return geo.bbox([p[0] for p in polys])


def _grid(b, n=GRID):
    x0, y0, x1, y1 = b
    gx, gy = np.meshgrid(np.linspace(x0, x1, n), np.linspace(y0, y1, n))
    return gx.ravel(), gy.ravel()


def repair(features: list, key, label) -> dict:
    """同じ輪の重複を取り除き、外に出た穴を扱う（features の polys と rings を書き換える）。

    key(f)：同じ学校かどうかの鍵（同じ学校の別の地物は「ほかの学校」に数えない）。label(f)：報告用の {city, name}。
    返り値: {"duplicate_rings": [...], "hole_outside_outer": [...]}"""
    dup_out, hole_out = [], []
    # 「ほかの学校の学区」は、直す前の図形で決める（直す順番で結果が変わらないように）
    orig = [polys_of(f) if f.rings else [] for f in features]
    boxes = [_bbox(p) if p else None for p in orig]
    for i, f in enumerate(features):
        if not getattr(f, "polys", None):
            continue
        # ---- 同じ輪の重複（外側の輪どうし、穴の輪どうし）
        seen_outer, seen_hole, polys, removed = set(), set(), [], 0
        for p in f.polys:
            ko = geo.ring_key(p[0])
            if ko in seen_outer:
                removed += len(p)
                continue
            seen_outer.add(ko)
            q = [p[0]]
            for h in p[1:]:
                kh = geo.ring_key(h)
                if kh in seen_hole:
                    removed += 1
                    continue
                seen_hole.add(kh)
                q.append(h)
            polys.append(q)
        if removed:
            dup_out.append({**label(f), "rings_removed": removed})
        # ---- 外に出た穴
        added = []
        for p in polys:
            outer = p[0]
            for h in p[1:]:
                if geo.points_in_rings(h[:, 0], h[:, 1], [outer]).all():
                    continue
                gx, gy = _grid(geo.bbox([h]))
                inh = geo.points_in_rings(gx, gy, [h])
                if not inh.any():
                    continue
                out = inh & ~geo.points_in_rings(gx, gy, [outer])
                share = float(out.sum() / inh.sum())
                if share <= OUTSIDE_MIN:
                    continue  # 穴の輪が外側の輪に接しているだけ
                ox, oy = gx[out], gy[out]
                cover = np.zeros(ox.shape[0], dtype=bool)
                hb = geo.bbox([h])
                for j, g in enumerate(features):
                    if j == i or boxes[j] is None or key(g) == key(f):
                        continue
                    b = boxes[j]
                    if b[0] > hb[2] or b[2] < hb[0] or b[1] > hb[3] or b[3] < hb[1]:
                        continue
                    cover |= geo.points_in_polys(ox, oy, orig[j])
                other = float(cover.mean())
                entry = {**label(f), "outside_share": round(share, 3), "outside_in_other_districts": round(other, 3)}
                if other >= OTHER_SHARE:
                    entry["how"] = "はみ出した部分がほかの学区に入るので、穴のまま"
                else:
                    # はみ出した部分を飛び地として入れる：穴の輪を外側、もとの外側の輪を穴にした部分を足す（＝穴 − 外側）
                    added.append([h, outer])
                    entry["how"] = "はみ出した部分を飛び地として区域に入れた（外側の輪の内側の部分は穴のまま）"
                hole_out.append(entry)
        f.polys = polys + added
        f.rings = [r for p in f.polys for r in p]
    return {"duplicate_rings": dup_out, "hole_outside_outer": hole_out}


def overlapping_parts(features: list, label) -> list:
    """同じ学校の部分どうしが重なっている学校（同じ学校の別の地物をまとめたあとで調べる）。重なりは1回だけ数えている。"""
    out = []
    for f in features:
        polys = polys_of(f)
        if len(polys) < 2:
            continue
        bs = [geo.bbox([p[0]]) for p in polys]
        pairs, area = 0, 0.0
        for a in range(len(polys)):
            for b in range(a + 1, len(polys)):
                x0, y0 = max(bs[a][0], bs[b][0]), max(bs[a][1], bs[b][1])
                x1, y1 = min(bs[a][2], bs[b][2]), min(bs[a][3], bs[b][3])
                if x0 >= x1 or y0 >= y1:
                    continue
                gx, gy = _grid((x0, y0, x1, y1))
                n = int((geo.points_in_polys(gx, gy, [polys[a]]) & geo.points_in_polys(gx, gy, [polys[b]])).sum())
                if n:  # 境界を共有しているだけの部分は、格子の点に当たらない
                    pairs += 1
                    cell = (x1 - x0) / (GRID - 1) * (y1 - y0) / (GRID - 1)
                    area += n * cell * np.cos(np.radians((y0 + y1) / 2)) * 111.32 * 111.32
        if pairs:
            out.append({**label(f), "pairs": pairs, "overlap_km2": round(area, 4)})
    return out
