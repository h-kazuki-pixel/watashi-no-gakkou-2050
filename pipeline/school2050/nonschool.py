"""学校ではない区域（docs/DATA_METHOD.md「学校ではない区域」）。

表：pipeline/terms/non_school_areas.csv（市区町村コード,学校名,理由,学区データの元の値）
学区データの区域のうち、表にある（市区町村, 学校名）の区域は学校にしない。名前の形から自動では決めない。
配分は学区として行い（その区域の中の点は、ほかの学校にも、学区データに無い学校の補いにも使わない）、
学校としては出さず、その子どもは「どの学校にも入らなかった子ども」（未配分）に数える。
「学区データの元の値」は「A27_002=…／A27_003=…／A27_005=…」の形で、合わなければ止める（表が古い）。
"""
from __future__ import annotations

import csv
import pathlib

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "terms" / "non_school_areas.csv"
HEADER = ["市区町村コード", "学校名", "理由", "学区データの元の値"]


def load(path=None) -> list[dict]:
    p = pathlib.Path(path) if path else DEFAULT
    if not p.exists():
        raise SystemExit(f"学校ではない区域の表がありません: {p}")
    rows = []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        if [h.strip() for h in (rd.fieldnames or [])] != HEADER:
            raise SystemExit(f"{p} の見出しは {','.join(HEADER)} にしてください")
        for r in rd:
            r = {k: (v or "").strip() for k, v in r.items()}
            if not r["市区町村コード"]:
                continue
            if not (len(r["市区町村コード"]) == 5 and r["市区町村コード"].isdigit() and r["学校名"] and r["理由"] and r["学区データの元の値"]):
                raise SystemExit(f"{p}: 空の列があります: {r}")
            orig = {}
            for part in r["学区データの元の値"].split("／"):
                k, sep, v = part.partition("=")
                if not sep:
                    raise SystemExit(f"{p}: 学区データの元の値は「項目=値」を「／」でつなぐ: {r}")
                orig[k.strip()] = v.strip()
            r["_orig"] = orig
            rows.append(r)
    return rows


def mark(features, fields, pref: str, rows=None) -> list[dict]:
    """学校ごとにまとめた学区（_city あり）のうち、表の区域に _non_school を付ける。付けた区域の一覧を返す。
    その県の行で当たる区域が無い・元の値が合わないときは止める。"""
    rows = load() if rows is None else rows
    out = []
    for r in rows:
        if r["市区町村コード"][:2] != pref:
            continue
        hit = [f for f in features if f.props.get("_city") == r["市区町村コード"] and f.props.get(fields.name, "") == r["学校名"]]
        if not hit:
            raise SystemExit(f"学校ではない区域の表の行が学区データに見つかりません: {r['市区町村コード']} {r['学校名']}")
        for f in hit:
            bad = {k: (f.props.get(k, ""), v) for k, v in r["_orig"].items() if str(f.props.get(k, "") or "") != v}
            if bad:
                raise SystemExit(f"学校ではない区域の表が学区データと合いません（{r['市区町村コード']} {r['学校名']}）: "
                                 + ", ".join(f"{k} は「{a}」、表は「{b}」" for k, (a, b) in bad.items()))
            f.props["_non_school"] = r["理由"]
        out.append({"city": r["市区町村コード"], "name": r["学校名"], "reason": r["理由"]})
    return out
