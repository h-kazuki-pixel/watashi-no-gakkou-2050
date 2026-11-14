"""シェープファイル（.shp / .dbf）の最小限の読み書き。外部ライブラリなし。

国土数値情報は GeoJSON も同梱されていることが多いが、シェープファイルしか無い年度・データにも
対応できるようにするためのもの。読むのはポリゴン（type 5/15/25）とポイント（1/11/21）だけ。
書き込みはテスト用（自作のフィクスチャを作って読み戻す）。
"""
from __future__ import annotations

import pathlib
import struct

import numpy as np


def read_shp(path) -> list[list[np.ndarray] | None]:
    """各レコードを「リングの配列のリスト」で返す（ポイントは1点だけのリング）。Null shape は None。"""
    data = pathlib.Path(path).read_bytes()
    if len(data) < 100 or struct.unpack(">i", data[0:4])[0] != 9994:
        raise ValueError(f"シェープファイルではありません: {path}")
    out: list[list[np.ndarray] | None] = []
    pos = 100
    while pos + 8 <= len(data):
        _num, length_words = struct.unpack(">2i", data[pos:pos + 8])
        pos += 8
        end = pos + length_words * 2
        rec = data[pos:end]
        pos = end
        if len(rec) < 4:
            out.append(None)
            continue
        stype = struct.unpack("<i", rec[0:4])[0]
        if stype in (5, 15, 25):
            n_parts, n_points = struct.unpack("<2i", rec[36:44])
            parts = list(struct.unpack(f"<{n_parts}i", rec[44:44 + 4 * n_parts])) + [n_points]
            p0 = 44 + 4 * n_parts
            pts = np.frombuffer(rec, dtype="<f8", count=n_points * 2, offset=p0).reshape(-1, 2)
            out.append([np.array(pts[parts[i]:parts[i + 1]]) for i in range(n_parts)])
        elif stype in (1, 11, 21):
            x, y = struct.unpack("<2d", rec[4:20])
            out.append([np.array([[x, y]])])
        else:
            out.append(None)
    return out


def read_dbf(path, encoding: str | None = None) -> tuple[list[str], list[dict]]:
    """DBF を (列名のリスト, レコードの辞書のリスト) で返す。値は文字列のまま（前後の空白を除く）。"""
    p = pathlib.Path(path)
    if encoding is None:
        cpg = p.with_suffix(".cpg")
        enc = cpg.read_text(errors="ignore").strip().lower() if cpg.exists() else ""
        encoding = "utf-8" if "utf" in enc else "cp932"
    data = p.read_bytes()
    n_rec, header_len, rec_len = struct.unpack("<IHH", data[4:12])
    fields = []
    pos = 32
    while pos < header_len - 1 and data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\x00")[0].decode(encoding, errors="replace")
        flen = data[pos + 16]
        fields.append((name, flen))
        pos += 32
    recs = []
    pos = header_len
    for _ in range(n_rec):
        row = data[pos:pos + rec_len]
        pos += rec_len
        if not row or row[0:1] == b"*":
            recs.append(None)
            continue
        d, o = {}, 1
        for name, flen in fields:
            d[name] = row[o:o + flen].decode(encoding, errors="replace").strip()
            o += flen
        recs.append(d)
    return [f[0] for f in fields], recs


# ---------------------------------------------------------------- テスト用の書き込み

def write_shp_polygons(path, polygons: list[list[np.ndarray]]) -> None:
    body = b""
    for i, rings in enumerate(polygons, 1):
        pts = np.vstack(rings)
        parts, o = [], 0
        for r in rings:
            parts.append(o)
            o += len(r)
        content = struct.pack("<i", 5)
        content += struct.pack("<4d", pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
        content += struct.pack("<2i", len(rings), len(pts))
        content += struct.pack(f"<{len(parts)}i", *parts)
        content += pts.astype("<f8").tobytes()
        body += struct.pack(">2i", i, len(content) // 2) + content
    allpts = np.vstack([np.vstack(r) for r in polygons])
    header = struct.pack(">i", 9994) + b"\x00" * 20 + struct.pack(">i", (100 + len(body)) // 2)
    header += struct.pack("<2i", 1000, 5)
    header += struct.pack("<4d", allpts[:, 0].min(), allpts[:, 1].min(), allpts[:, 0].max(), allpts[:, 1].max())
    header += struct.pack("<4d", 0, 0, 0, 0)
    pathlib.Path(path).write_bytes(header + body)


def write_dbf(path, columns: list[str], rows: list[dict], encoding: str = "cp932") -> None:
    enc_rows = [[str(r.get(c, "")).encode(encoding) for c in columns] for r in rows]
    widths = [max([1] + [len(er[i]) for er in enc_rows]) for i in range(len(columns))]
    header_len = 32 + 32 * len(columns) + 1
    rec_len = 1 + sum(widths)
    out = struct.pack("<B3BIHH20x", 3, 126, 1, 1, len(rows), header_len, rec_len)
    for c, w in zip(columns, widths):
        out += c.encode(encoding)[:10].ljust(11, b"\x00") + b"C" + b"\x00" * 4 + bytes([w, 0]) + b"\x00" * 14
    out += b"\x0d"
    for er in enc_rows:
        out += b" " + b"".join(v.ljust(w) for v, w in zip(er, widths))
    out += b"\x1a"
    pathlib.Path(path).write_bytes(out)
