"""国土数値情報「小学校区データ」の、自治体ごとの利用条件。

元データ：R5_Terms_of_use_municipality_data.xlsx（国土数値情報のダウンロードページ）の小学校区の列を、
pipeline/terms/school_district_terms_R5.csv（行政コード,自治体名,公開条件,利用条件,特記条件詳細）にしたもの。

- 利用条件に「再配布不可」を含む市区町村 → 学区の地物を配分の前に除く（学区データなしとして扱う）
- 利用条件が「条件公開」か、特記条件がある市区町村 → アプリで「学区は めやす」と表示する（note）

別の表 pipeline/terms/pending_confirmation.csv（行政区域コード,自治体名,理由,出典）：
利用の前に自治体の確認が要る市区町村（小田原市）。確認が取れるまで学区データを使わない（再配布不可と同じく除く）。
"""
from __future__ import annotations

import csv
import pathlib

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "terms" / "school_district_terms_R5.csv"
PENDING = pathlib.Path(__file__).resolve().parents[1] / "terms" / "pending_confirmation.csv"


def load(path=None) -> dict:
    """行政コード（5桁）→ {"name", "publish", "use", "detail"}。ファイルが無ければ空。"""
    p = pathlib.Path(path) if path else DEFAULT
    if not p.exists():
        return {}
    out = {}
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            code = (r.get("行政コード") or "").strip()
            if code.isdigit():
                out[code.zfill(5)] = {"name": r.get("自治体名", ""), "publish": r.get("公開条件", ""),
                                      "use": r.get("利用条件", ""), "detail": (r.get("特記条件詳細") or "").strip()}
    return out


def pending(path=None) -> dict:
    """確認が取れるまで学区データを使わない市区町村。行政コード → {"name", "reason", "source"}。ファイルが無ければ空。"""
    p = pathlib.Path(path) if path else PENDING
    if not p.exists():
        raise SystemExit(f"確認待ちの市区町村の表がありません: {p}")
    out = {}
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            code = (r.get("行政区域コード") or "").strip()
            if code.isdigit():
                out[code.zfill(5)] = {"name": r.get("自治体名", ""), "reason": r.get("理由", ""), "source": r.get("出典", "")}
    return out


def excluded(t: dict, pend: dict | None = None) -> dict:
    """学区データを使わない市区町村と、その理由。再配布できない市区町村と、確認待ちの市区町村（pend）。"""
    out = {c: {"name": r["name"], "reason": f"利用条件「{r['use']}」"} for c, r in t.items() if "再配布不可" in r["use"]}
    for c, r in (pend or {}).items():
        out[c] = {"name": r["name"], "reason": "確認待ち：" + r["reason"]}
    return out


def needs_note(t: dict, ex: dict | None = None) -> set:
    """条件公開、または特記条件がある市区町村（学区データを使わない市区町村 ex は除く）。"""
    return {c for c, r in t.items() if (r["use"] == "条件公開" or r["detail"] not in ("", "-")) and c not in (ex or {})}
