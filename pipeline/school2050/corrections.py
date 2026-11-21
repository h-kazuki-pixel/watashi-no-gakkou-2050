"""元データの誤記の訂正（docs/DATA_METHOD.md「元データの行政区域コードや学校コードの誤り」の4）。

表：pipeline/terms/source_corrections.csv
  データ名,学校コード,項目,元の値,直した値,根拠,見分ける学校名
読み込んだ直後に、地物の項目の値が「元の値」なら「直した値」に置きかえる。
すでに「直した値」なら何もしない。どちらでもなければ止める（表が古い）。表が無ければ止める。

どの地物にどの行を当てるかは、すべての地物について、どの行も当てる前の値で先に決める（入れかえの2行が、
1行目で直した地物を2行目でもう一度見つけないように）。1つの地物に、同じ項目を直す行が2つ当たったら止める。
  - 学校名などを直す行（項目が学校コード以外）：学校コードが「学校コード」の地物に当てる。
  - 学校コードそのものを直す行：学校名が「見分ける学校名」で、学校コードが「元の値」か「直した値」の地物に当てる
    （学校コードだけでは、入れかえの組で元データが直ったあとの地物と見分けられないため）。
    学校名が同じでも学校コードがどちらでもない地物は別の学校とみて当てない。
"""
from __future__ import annotations

import csv
import pathlib

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "terms" / "source_corrections.csv"
CODE_FIELD = {"P29": "P29_002", "A27": "A27_003"}  # データ名 → 学校コードの属性
NAME_FIELD = {"P29": "P29_004", "A27": "A27_004"}  # データ名 → 学校名の属性（学校コードを直す行で地物を見分ける）
NAME_COL = "見分ける学校名"

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
            is_code = r["項目"] == CODE_FIELD[r["データ名"]]
            if is_code and r["元の値"] != r["学校コード"]:
                raise ValueError(f"{p}: 学校コードを直す行は、元の値が学校コードと同じ: {r}")
            if is_code and not r.get(NAME_COL):
                raise ValueError(f"{p}: 学校コードを直す行には「{NAME_COL}」が要ります: {r}")
            if not is_code and r.get(NAME_COL):
                raise ValueError(f"{p}: 「{NAME_COL}」は学校コードを直す行だけに書きます: {r}")
            rows.append(r)
    return rows


def reset() -> None:
    _applied.clear()


def applied() -> list[dict]:
    return [dict(v) for _k, v in sorted(_applied.items())]


def _matches(props: dict, r: dict, dataset: str) -> bool:
    key = CODE_FIELD[dataset]
    if r["項目"] == key:
        return (props.get(NAME_FIELD[dataset], "") == r[NAME_COL]
                and props.get(key, "") in (r["元の値"], r["直した値"]))
    return props.get(key, "") == r["学校コード"]


def apply(features, dataset: str, rows: list[dict] | None = None) -> int:
    """features（readers.Feature の並び）の props を表で直す。返り値：置きかえた数"""
    rows = load() if rows is None else rows
    rows = [r for r in rows if r["データ名"] == dataset]
    if not rows:
        return 0
    # どの行も当てる前の値で、地物ごとに当てる行を決める
    plan = []
    for f in features:
        hit = [r for r in rows if _matches(f.props, r, dataset)]
        seen = {}
        for r in hit:
            if r["項目"] in seen:
                raise SystemExit(f"誤記の訂正の表で、1つの地物（{dataset} {f.props.get(CODE_FIELD[dataset], '')} "
                                 f"{f.props.get(NAME_FIELD[dataset], '')}）に {r['項目']} を直す行が2つ当たります"
                                 f"（{seen[r['項目']]['学校コード']} と {r['学校コード']}）")
            seen[r["項目"]] = r
        if hit:
            plan.append((f, hit, dict(f.props)))
    n = 0
    for f, hit, orig in plan:
        for r in hit:
            v = orig.get(r["項目"])
            if v == r["元の値"]:
                f.props[r["項目"]] = r["直した値"]
                n += 1
                _applied[(dataset, r["学校コード"], r["項目"])] = {
                    "data": dataset, "code": r["学校コード"], "field": r["項目"], "from": r["元の値"], "to": r["直した値"]}
            elif v != r["直した値"]:
                raise SystemExit(f"誤記の訂正の表が元データと合いません（{dataset} {r['学校コード']} {r['項目']}）："
                                 f"元データは「{v}」、表の元の値は「{r['元の値']}」")
    return n
