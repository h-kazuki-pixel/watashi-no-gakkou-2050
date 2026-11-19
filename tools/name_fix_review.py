#!/usr/bin/env python3
"""学校名か学校コードが誤っている学校を、学区データ（A27）・学校の位置（P29）・文科省「学校コード」で調べ、直すかどうかを決める。

    python3 tools/name_fix_review.py --targets targets.csv [--out opendata/closures_review/name_fix.csv] [--corrections OUT.csv]

targets.csv：分類,市区町村,id,アプリの学校名,文科省の学校名（分類 A は、同じ市区町村の同じ名前のアプリの学校も一緒に調べる）。
決め方（docs/DATA_METHOD.md「元データの行政区域コードや学校コードの誤り」の5。1つでも外れたら直さず「決められない」）：
  (a) P29 で、その学校のコードの学校。(b) P29 で、同じ市区町村の、アプリの学校名と同じ名前（設置者を外す）の学校（(a) 以外）。
  名前が誤り：(a) がちょうど1つで点がこの学区の中、(b) が無いか点が外、P29 の (a) の名前と文科省のそのコードの名前が同じ（closures.norm_name）、
             学区データの所在地が (b) により合っていない → 学校名を (a) の名前（設置者を外す）に直す
  コードが誤り：(b) がちょうど1つで点がこの学区の中、(a) がちょうど1つで点が外、学区データの所在地が (a) により合っていない、
             (b) のコードが文科省で存続（本分校 1 か 2・廃止年月日なし）、そのコードが県の学区データでまだ使われていない → コードを (b) のコードに直す
  直したあと同じ市区町村に同じ名前の学校が2つ残る組は、組ごと直さない。
--corrections には、直すものを pipeline/terms/source_corrections.csv の形（データ名,学校コード,項目,元の値,直した値,根拠）で書く。
zip は TMPDIR に展開される（呼ぶ側で1つのフォルダに決め、終わったら消す）。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import re
import sys
import unicodedata
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import build_school_data as bsd  # noqa: E402
from school2050 import closures as cl  # noqa: E402
from school2050 import export, geo, inputs, kana, readers, wards  # noqa: E402

RANK = {"一致": 2, "町名まで一致": 1, "不一致": 0, "": -1}


def norm_addr(a: str) -> str:
    s = unicodedata.normalize("NFKC", a or "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"^(北海道|東京都|大阪府|京都府|.{2,3}県)", "", s)
    s = re.sub(r"^.{1,6}?郡", "", s)
    s = re.sub(r"(丁目|番地の|番地|番|号|の|−|ー|―|‐)", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    s = s.replace("大字", "").replace("字", "")
    return s


def town(a: str) -> str:
    return re.split(r"\d", a, maxsplit=1)[0]


def addr_match(a27: str, p29: str) -> str:
    if not a27 or not p29:
        return ""
    x, y = norm_addr(a27), norm_addr(p29)
    if x == y or x.endswith(y) or y.endswith(x):
        return "一致"
    tx, ty = town(x), town(y)
    if tx and ty and (tx.endswith(ty) or ty.endswith(tx)):
        return "町名まで一致"
    return "不一致"


def dist_m(x, y, polys) -> float:
    """点から区域の境界までのいちばん近い距離（m。経度は点の緯度で縮める）"""
    kx, ky = 111320.0 * math.cos(math.radians(y)), 110540.0
    best = float("inf")
    for poly in polys:
        for ring in poly:
            r = ring
            ax, ay = (r[:-1, 0] - x) * kx, (r[:-1, 1] - y) * ky
            bx, by = (r[1:, 0] - x) * kx, (r[1:, 1] - y) * ky
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            ll[ll == 0] = 1e-12
            t = ((-ax) * dx + (-ay) * dy) / ll
            t = t.clip(0, 1)
            d = ((ax + t * dx) ** 2 + (ay + t * dy) ** 2) ** 0.5
            best = min(best, float(d.min()))
    return best


PARTNER_RULES = {
    1: "相手の学校のコードが文科省の存続の行（本分校 1・廃止年月日なし）で、名前がアプリの名前と同じ",
    2: "この学校のコードが文科省の存続の行（本分校 1・廃止年月日なし）で、名前が P29 の (a) の名前と同じ",
    3: "直す名前の学校が、同じ市区町村のアプリの学校にほかに無い",
    4: "この学校のコードの学校の点（P29 の (a)）がこの区域の中",
    5: "学区データの所在地が、相手の学校の所在地（P29）と一致しない",
}


def partner_rule(app_name, partner_mext, self_mext, p29_a_name, a_inside, a27_addr, partner_addr) -> list[int]:
    """同じ名前の学校がもう1つある学校の「名前が誤り」の決まり（DATA_METHOD.md）の 1・2・4・5 を見て、外れた番号を返す。
    partner_mext / self_mext は文科省の行（closures.MextRow）か None。決まり3（ほかに同じ名前が無いか）は呼ぶ側で見る。"""
    failed = []
    if not (partner_mext and partner_mext.honbun == "1" and not partner_mext.abol
            and cl.norm_name(partner_mext.name) == cl.norm_name(app_name)):
        failed.append(1)
    if not (self_mext and self_mext.honbun == "1" and not self_mext.abol and p29_a_name
            and cl.norm_name(p29_a_name) == cl.norm_name(self_mext.name)):
        failed.append(2)
    if not a_inside:
        failed.append(4)
    if not partner_addr or addr_match(a27_addr, partner_addr) in ("一致", ""):
        failed.append(5)  # 相手の所在地が無いときは「一致しない」と言えないので外れ
    return failed


def name_taken(names: dict, sid: str, city: str, new_name: str) -> bool:
    """決まり3：直す名前（new_name）の学校が、同じ市区町村に sid のほかにあるか。names は {id: (市区町村, 名前)}（直す学校の新しい名前を入れたもの）"""
    return any(k == (city, new_name) and x != sid for x, k in names.items())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets", required=True)
    ap.add_argument("--data", default=str(ROOT / "app" / "data"))
    ap.add_argument("--raw", default=str(ROOT / "data_raw"))
    ap.add_argument("--mext", default=str(ROOT / "data_raw" / "mext_school_code" / "r8_0501_provisional"))
    ap.add_argument("--ids", default=str(ROOT / "opendata" / "closures_survey" / "capture"))
    ap.add_argument("--out", default=str(ROOT / "opendata" / "closures_review" / "name_fix.csv"))
    ap.add_argument("--corrections")
    a = ap.parse_args(argv)

    prefs = cl.read_app(a.data)
    app = {}
    by_city_name = defaultdict(list)
    for o in prefs:
        for c in o["cities"]:
            for s in c["schools"]:
                app[s["id"]] = (o["code"], c["code"], c["name"], s)
                by_city_name[(c["code"], s["name"])].append(s["id"])
    mext, _ = cl.load_mext(sorted(pathlib.Path(a.mext).glob("*.csv")))
    mx = defaultdict(list)
    for r in mext:
        mx[r.code].append(r)
    id_codes = cl.read_id_codes(a.ids)
    wt = wards.load()

    app_cities = {c["code"] for o in prefs for c in o["cities"]}
    city_of_app = {c: c for c in app_cities}
    rows_in = list(csv.DictReader(open(a.targets, encoding="utf-8-sig")))
    todo = []  # (分類, 組, id)
    for r in rows_in:
        o, city, cname, s = app[r["id"]]
        group = r["id"]
        todo.append((r["分類"], group, r["id"], "対象"))
        if r["分類"] == "A":
            partners = [x for x in by_city_name[(city, s["name"])] if x != r["id"]]
            for p in partners:
                todo.append(("A", group, p, "A の相手"))
        if r["分類"] == "B":
            pass
    # B は入れ替わった2校で1組（同じ市区町村で、互いの文科省の名前がアプリの名前）
    bgroup = {}
    for r in rows_in:
        if r["分類"] == "B":
            o, city, cname, s = app[r["id"]]
            mine = cl.norm_name(r["文科省の学校名"])
            for r2 in rows_in:
                if r2["分類"] == "B" and r2["id"] != r["id"] and app[r2["id"]][1] == city and cl.norm_name(app[r2["id"]][3]["name"]) == mine:
                    bgroup[r["id"]] = "-".join(sorted([r["id"], r2["id"]]))
    todo = [(k, bgroup.get(g, g), i, role) for k, g, i, role in todo]

    by_pref = defaultdict(list)
    for t in todo:
        by_pref[app[t[2]][0]].append(t)
    out = []
    for pref in sorted(by_pref):
        dz = pathlib.Path(a.raw) / f"A27-23_{pref}_GML.zip"
        pz = pathlib.Path(a.raw) / f"P29-23_{pref}_GML.zip"
        dfeats = readers.read_features(inputs.find_districts(dz).polygons)
        fields = readers.detect_fields(dfeats)
        pfeats = bsd._read_p29(inputs.find_schools(pz).points)
        pf = readers.detect_fields(pfeats)
        used_codes = defaultdict(set)
        for f in dfeats:
            used_codes[f.props.get(fields.school_code, "")].add(f.props.get(fields.city_code, "").zfill(5))

        def a27_city(f):
            c = f.props.get(fields.city_code, "").zfill(5)
            w = wt.get(c)
            return w.city if (w and c != city_of_app.get(c)) else c

        def p29_city(ft):
            c = ft.props.get(pf.city_code, "").zfill(5)
            w = wt.get(c)
            return w.city if (w and c not in app_cities) else c

        for kind, group, sid, role in by_pref[pref]:
            _o, city, cname, s = app[sid]
            code = sid if cl.CODE_RE.match(sid) else (id_codes.get((pref, sid)) or {}).get("raw_code", "")
            if s.get("approx"):
                feats = []
            elif code:
                feats = [f for f in dfeats if f.props.get(fields.school_code) == code and a27_city(f) == city]
            else:
                feats = [f for f in dfeats if not f.props.get(fields.school_code) and f.props.get(fields.name) == s["name"]
                         and a27_city(f) == city]
            polys = []
            for f in feats:
                polys += f.polys or geo.polys_from_rings(f.rings)
            a27_name = ";".join(sorted({f.props.get(fields.name, "") for f in feats}))
            a27_addr = ";".join(sorted({f.props.get(fields.address, "") for f in feats})) if fields.address else ""
            pa = [ft for ft in pfeats if code and ft.props.get(pf.school_code) == code]
            pb = [ft for ft in pfeats if p29_city(ft) == city and export.strip_owner(ft.props.get(pf.name, "")) == s["name"]
                  and ft.props.get(pf.school_code) != code]

            def pt(ft):
                return float(ft.rings[0][0][0]), float(ft.rings[0][0][1])

            def where(fts):
                if len(fts) != 1 or not polys:
                    return "", ""
                x, y = pt(fts[0])
                ins = bool(geo.points_in_polys([x], [y], polys)[0])
                return ("中" if ins else "外"), ("" if ins else f"{dist_m(x, y, polys):.0f}")

            ia, da = where(pa)
            ib, db = where(pb)
            ma = addr_match(a27_addr, pa[0].props.get(pf.address, "")) if len(pa) == 1 and pf.address else ""
            mb = addr_match(a27_addr, pb[0].props.get(pf.address, "")) if len(pb) == 1 and pf.address else ""
            mrow = mx.get(code, [])
            mname = mrow[0].name if len(mrow) == 1 else ""
            b_code = pb[0].props.get(pf.school_code, "") if len(pb) == 1 else ""
            b_m = mx.get(b_code, [])
            judge, why, new = "決められない", [], ""
            if not polys:
                why.append("学区データの区域が無い")
            if len(pa) > 1:
                why.append(f"(a) が{len(pa)}つ")
            if len(pb) > 1:
                why.append(f"(b) が{len(pb)}つ")
            if not why:
                if ia == "中" and (not pb or ib == "外"):
                    pa_name = export.strip_owner(pa[0].props.get(pf.name, ""))
                    if not mname or cl.norm_name(pa_name) != cl.norm_name(mname):
                        why.append("P29 の (a) の名前と文科省の名前が違う")
                    elif pb and RANK[mb] > RANK[ma]:
                        why.append("学区データの所在地が (b) により合う")
                    elif pa_name == s["name"]:
                        why.append("名前はすでに (a) の名前")
                    else:
                        judge, new = "名前が誤り", pa_name
                elif ib == "中" and ia == "外":
                    if RANK[ma] > RANK[mb]:
                        why.append("学区データの所在地が (a) により合う")
                    elif not (len(b_m) == 1 and b_m[0].living):
                        why.append("(b) のコードが文科省で存続していない")
                    elif cl.norm_name(b_m[0].name) != cl.norm_name(s["name"]):
                        why.append("(b) のコードの文科省の名前がアプリの名前と違う")
                    elif used_codes.get(b_code):
                        why.append(f"(b) のコードが県の学区データでもう使われている（{','.join(sorted(used_codes[b_code]))}）")
                    else:
                        judge, new = "コードが誤り", b_code
                elif ia == "中" and ib == "中":
                    why.append("(a) も (b) も点がこの学区の中")
                elif not pa:
                    why.append("(a) が P29 に無い")
                else:
                    why.append("(a) も (b) も点がこの学区の外" if ia == "外" and ib in ("外", "") else "材料がそろわない")
            # 同じ名前の学校がもう1つある学校の「名前が誤り」（決まり3は全部見たあとで）
            prow = {"相手の id": "", "相手のコード": "", "相手の文科省の名前": "", "相手の文科省の本分校": "", "相手の所在地（P29）": "",
                    "A27 の所在地と相手": "", "相手ありの決まりで外れた番号": "", "_cand": ""}
            if role == "対象" and judge == "決められない":
                partners = [x for x in by_city_name[(city, s["name"])] if x != sid]
                if len(partners) == 1:
                    psid = partners[0]
                    pcode = psid if cl.CODE_RE.match(psid) else (id_codes.get((pref, psid)) or {}).get("raw_code", "")
                    pm = mx.get(pcode, []) if pcode else []
                    pp = [ft for ft in pfeats if pcode and ft.props.get(pf.school_code) == pcode]
                    paddr = pp[0].props.get(pf.address, "") if len(pp) == 1 and pf.address else ""
                    pa_name = export.strip_owner(pa[0].props.get(pf.name, "")) if len(pa) == 1 else ""
                    failed = partner_rule(s["name"], pm[0] if len(pm) == 1 else None, mrow[0] if len(mrow) == 1 else None,
                                          pa_name, ia == "中", a27_addr, paddr)
                    prow.update({"相手の id": psid, "相手のコード": pcode, "相手の文科省の名前": pm[0].name if len(pm) == 1 else "",
                                 "相手の文科省の本分校": pm[0].honbun if len(pm) == 1 else "", "相手の所在地（P29）": paddr,
                                 "A27 の所在地と相手": addr_match(a27_addr, paddr) if paddr else "",
                                 "相手ありの決まりで外れた番号": ";".join(map(str, failed)), "_cand": pa_name})
            out.append({"分類": kind, "組": group, "役割": role, "都道府県": pref, "市区町村コード": city, "市区町村名": cname,
                        "id": sid, "アプリの学校名": s["name"], "approx": "1" if s.get("approx") else "",
                        "学校コード": code, "文科省のそのコードの名前": mname,
                        "文科省のそのコードの本分校": mrow[0].honbun if len(mrow) == 1 else "",
                        "A27 の学校名": a27_name, "A27 の学校コード": code if feats else "", "A27 の所在地": a27_addr,
                        "(a) P29 の名前": ";".join(ft.props.get(pf.name, "") for ft in pa),
                        "(a) 点": ";".join(f"{pt(ft)[0]:.5f},{pt(ft)[1]:.5f}" for ft in pa),
                        "(a) 所在地": ";".join(ft.props.get(pf.address, "") for ft in pa) if pf.address else "",
                        "(a) 区域の中か": ia, "(a) 境界までの距離_m": da, "A27 の所在地と (a)": ma,
                        "(b) P29 の名前": ";".join(ft.props.get(pf.name, "") for ft in pb),
                        "(b) 学校コード": ";".join(ft.props.get(pf.school_code, "") for ft in pb),
                        "(b) 点": ";".join(f"{pt(ft)[0]:.5f},{pt(ft)[1]:.5f}" for ft in pb),
                        "(b) 所在地": ";".join(ft.props.get(pf.address, "") for ft in pb) if pf.address else "",
                        "(b) 区域の中か": ib, "(b) 境界までの距離_m": db, "A27 の所在地と (b)": mb,
                        "(b) のコードの文科省の名前": b_m[0].name if len(b_m) == 1 else "",
                        "判定": judge, "直した値": new, "決められない理由": "／".join(why), **prow, "直したか": ""})

    # 相手ありの決まり3：直す名前の学校が、同じ市区町村のアプリの学校にほかに無い（ほかに直す学校の新しい名前も数える）
    names = {sid: (v[1], v[3]["name"]) for sid, v in app.items()}
    for r in out:
        if r["判定"] == "名前が誤り":
            names[r["id"]] = (r["市区町村コード"], r["直した値"])
    cands = [r for r in out if r["相手の id"] and r["_cand"] and r["相手ありの決まりで外れた番号"] in ("",)]
    for r in out:
        if r["相手の id"] and r["_cand"]:
            names_try = dict(names)
            for c in cands:
                names_try[c["id"]] = (c["市区町村コード"], c["_cand"])
            if name_taken(names_try, r["id"], r["市区町村コード"], r["_cand"]):
                f = sorted(set(map(int, filter(None, r["相手ありの決まりで外れた番号"].split(";")))) | {3})
                r["相手ありの決まりで外れた番号"] = ";".join(map(str, f))
    for r in out:
        if r["相手の id"] and r["_cand"] and not r["相手ありの決まりで外れた番号"]:
            r["判定"], r["直した値"], r["決められない理由"] = "名前が誤り（相手あり）", r["_cand"], ""
        elif r["相手の id"]:
            r["決められない理由"] += "／相手ありの決まりで外れた：" + "、".join(
                f"{n}（{PARTNER_RULES[int(n)]}）" for n in r["相手ありの決まりで外れた番号"].split(";") if n)
    for r in out:
        r.pop("_cand", None)

    # 直したあと同じ市区町村に同じ名前の学校が2つ残る組は、組ごと直さない
    names = {sid: (v[1], v[3]["name"]) for sid, v in app.items()}
    for r in out:
        if r["判定"] in ("名前が誤り", "名前が誤り（相手あり）"):
            names[r["id"]] = (r["市区町村コード"], r["直した値"])
    count = defaultdict(list)
    for sid, k in names.items():
        count[k].append(sid)
    bad_groups = set()
    for r in out:
        if r["判定"] in ("名前が誤り", "名前が誤り（相手あり）", "コードが誤り"):
            k = names[r["id"]]
            if len(count[k]) > 1:
                bad_groups.add(r["組"])
    for r in out:
        if r["判定"] in ("名前が誤り", "名前が誤り（相手あり）", "コードが誤り"):
            if r["組"] in bad_groups:
                r["直したか"] = "直さない（直すと同じ市区町村に同じ名前の学校が2つ残る）"
            else:
                r["直したか"] = "直した"
        else:
            r["直したか"] = "直さない"
    p = pathlib.Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    if a.corrections:
        with open(a.corrections, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            for r in out:
                if r["直したか"] != "直した":
                    continue
                basis = (f"name_fix_review：A27 の区域の中に P29 の (a)「{r['(a) P29 の名前']}」{r['(a) 区域の中か']}"
                         f"、(b)「{r['(b) P29 の名前'] or '無し'}」{r['(b) 区域の中か'] or ''}"
                         f"{'（境界まで ' + r['(b) 境界までの距離_m'] + 'm）' if r['(b) 境界までの距離_m'] else ''}"
                         f"{'（(a) は境界まで ' + r['(a) 境界までの距離_m'] + 'm）' if r['(a) 境界までの距離_m'] else ''}"
                         f"。A27 の所在地「{r['A27 の所在地']}」と (a) {r['A27 の所在地と (a)'] or '-'}・(b) {r['A27 の所在地と (b)'] or '-'}。"
                         f"文科省「学校コード」（令和8年5月1日時点）で {r['学校コード']} は「{r['文科省のそのコードの名前']}」"
                         + (f"、{r['直した値']} は「{r['(b) のコードの文科省の名前']}」" if r["判定"] == "コードが誤り" else "")
                         + (f"。同じ市区町村に同じ名前の学校 {r['相手の id']}（文科省「{r['相手の文科省の名前']}」本分校 {r['相手の文科省の本分校']}）があり、"
                            f"A27 の所在地は相手の所在地「{r['相手の所在地（P29）']}」と{r['A27 の所在地と相手']}（相手ありの決まり1〜5を満たす）"
                            if r["判定"] == "名前が誤り（相手あり）" else "")
                         + "（2026-11-20 確認）")
                if r["判定"] in ("名前が誤り", "名前が誤り（相手あり）"):
                    w.writerow(["A27", r["学校コード"], "A27_004", r["アプリの学校名"], r["直した値"], basis])
                else:
                    w.writerow(["A27", r["学校コード"], "A27_003", r["学校コード"], r["直した値"], basis])
    from collections import Counter
    print(Counter((r["役割"], r["判定"], r["直したか"]) for r in out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
