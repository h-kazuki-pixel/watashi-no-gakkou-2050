"""標準地域メッシュコード → 緯度経度（南西端とセルの大きさ）。

対応: 3次メッシュ（約1km・8桁）、2分の1地域メッシュ（約500m・9桁）、4分の1地域メッシュ（約250m・10桁）。
座標は秒単位の有理数で計算し、最後に度へ直す（丸め誤差を避けるため）。

  1次（4桁 pquv）: 緯度 = pq × 40分, 経度 = uv + 100度
  2次（2桁 rs）  : 緯度 + r × 5分,   経度 + s × 7分30秒
  3次（2桁 tx）  : 緯度 + t × 30秒,  経度 + x × 45秒
  2分の1（1桁 m）: 1=南西 2=南東 3=北西 4=北東（15秒 × 22.5秒）
  4分の1（1桁 n）: 同じ並びでさらに半分（7.5秒 × 11.25秒）
"""
from __future__ import annotations

import numpy as np

_CELL_SEC = {8: (30.0, 45.0), 9: (15.0, 22.5), 10: (7.5, 11.25)}


def decode(code: str) -> tuple[float, float, float, float]:
    """1件のメッシュコードを (南端の緯度, 西端の経度, 緯度幅, 経度幅) に。単位は度。"""
    lat0, lng0, dlat, dlng = decode_many([code])
    return float(lat0[0]), float(lng0[0]), float(dlat[0]), float(dlng[0])


def decode_many(codes) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """メッシュコードの列をまとめて変換する。桁数が混在していてもよい。"""
    codes = [str(c).strip() for c in codes]
    n = len(codes)
    lat = np.zeros(n)
    lng = np.zeros(n)
    dlat = np.zeros(n)
    dlng = np.zeros(n)
    for i, c in enumerate(codes):
        if not c.isdigit() or len(c) not in _CELL_SEC:
            raise ValueError(f"メッシュコードとして読めません: {c!r}（8〜10桁の数字が必要）")
        p, u = int(c[0:2]), int(c[2:4])
        r, s = int(c[4]), int(c[5])
        t, x = int(c[6]), int(c[7])
        if r > 7 or s > 7:
            raise ValueError(f"2次メッシュの桁が範囲外です: {c!r}")
        la = p * 2400.0 + r * 300.0 + t * 30.0
        lo = (u + 100) * 3600.0 + s * 450.0 + x * 45.0
        h_lat, h_lng = 30.0, 45.0
        for d in c[8:]:
            m = int(d)
            if m < 1 or m > 4:
                raise ValueError(f"分割地域メッシュの桁は1〜4です: {c!r}")
            h_lat /= 2
            h_lng /= 2
            la += ((m - 1) // 2) * h_lat
            lo += ((m - 1) % 2) * h_lng
        lat[i], lng[i] = la / 3600.0, lo / 3600.0
        dlat[i], dlng[i] = h_lat / 3600.0, h_lng / 3600.0
    return lat, lng, dlat, dlng


def encode(lat: float, lng: float, digits: int = 9) -> str:
    """緯度経度を含むメッシュコードを返す（テストと検算用）。"""
    if digits not in _CELL_SEC:
        raise ValueError("digits は 8, 9, 10 のいずれか")
    la, lo = lat * 3600.0, (lng - 100.0) * 3600.0
    p, la = divmod(la, 2400.0)
    u, lo = divmod(lo, 3600.0)
    r, la = divmod(la, 300.0)
    s, lo = divmod(lo, 450.0)
    t, la = divmod(la, 30.0)
    x, lo = divmod(lo, 45.0)
    code = f"{int(p):02d}{int(u):02d}{int(r)}{int(s)}{int(t)}{int(x)}"
    h_lat, h_lng = 30.0, 45.0
    for _ in range(digits - 8):
        h_lat /= 2
        h_lng /= 2
        a, la = divmod(la, h_lat)
        b, lo = divmod(lo, h_lng)
        code += str(int(a) * 2 + int(b) + 1)
    return code
