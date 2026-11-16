"""元データの誤記の訂正（docs/DATA_METHOD.md「元データの行政区域コードや学校コードの誤り」の4）。

表：pipeline/terms/source_corrections.csv
  データ名,学校コード,項目,元の値,直した値,根拠
読み込んだ直後に、学校コードが合う地物の項目の値が「元の値」なら「直した値」に置きかえる。
すでに「直した値」なら何もしない。どちらでもなければ止める（表が古い）。表が無ければ止める。
"""
from __future__ import annotations

import csv
import pathlib

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "terms" / "source_corrections.csv"
CODE_FIELD = {"P29": "P29_002"}

_applied: dict = {}  # (データ名, 学校コード, 項目) → 使った訂正。同じ build で何度読んでも1件


def load(path=None) -> list[dict]:
    p = pathlib.Path(path) if path else DEFAULT
    if not p.exists():
        raise SystemExit(f"誤記の訂正の表がありません: {p}")
    rows = []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            r = {k: (v or "").strip() for k, v in r.items()}
            if not r.get("データ名"):
                continue
            if r["データ名"] not in CODE_FIELD:
                raise ValueError(f"{p}: データ名は {sorted(CODE_FIELD)} のどれか: {r['データ名']}")
            if not (r["学校コード"] and r["項目"] and r["元の値"] and r["直した値"] and r["根拠"]):
                raise ValueError(f"{p}: 空の列があります: {r}")
            rows.append(r)
    return rows


def reset() -> None:
    _applied.clear()


def applied() -> list[dict]:
    return [dict(v) for _k, v in sorted(_applied.items())]


def apply(features, dataset: str, rows: list[dict] | None = None) -> int:
    """features（readers.Feature の並び）の props を表で直す。返り値：置きかえた数"""
    rows = load() if rows is None else rows
    key = CODE_FIELD[dataset]
    want = {}
    for r in rows:
        if r["データ名"] == dataset:
            want.setdefault(r["学校コード"], []).append(r)
    n = 0
    if not want:
        return 0
    for f in features:
        for r in want.get(f.props.get(key, ""), []):
            v = f.props.get(r["項目"])
            if v == r["元の値"]:
                f.props[r["項目"]] = r["直した値"]
                n += 1
                _applied[(dataset, r["学校コード"], r["項目"])] = {
                    "data": dataset, "code": r["学校コード"], "field": r["項目"], "from": r["元の値"], "to": r["直した値"]}
            elif v != r["直した値"]:
                raise SystemExit(f"誤記の訂正の表が元データと合いません（{dataset} {r['学校コード']} {r['項目']}）："
                                 f"元データは「{v}」、表の元の値は「{r['元の値']}」")
    return n
