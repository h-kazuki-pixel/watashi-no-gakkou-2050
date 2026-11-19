#!/usr/bin/env python3
"""閉校の印（make-closures）を確かめるための一覧を opendata/closures_review/ に出す。app/data と pipeline/terms は変えない。

    python3 tools/review_closures.py --ids WORK --mext data_raw/mext_school_code/r8_0501_provisional \
        --town ~/work/abr/mt_town_all.csv.zip [--out opendata/closures_review] [--tests tests.txt]

できるもの
  summary.txt          件数（gone・now・joined・newSchools）、印を付けなかった学校の外れた決まりごとの件数、gone の 2025年の推計の合計、
                       市区町村名の比べた結果、（--tests があれば）テストの結果
  not_marked.csv       閉校に分類された（一覧の行が本分校 9 か廃止年月日あり）のに印を付けなかった学校と、外れた決まり（全部）
  unknown54.csv        学校コードが決まらない学校（区域の面積・学区データの元の行の値つき）
  muni_names.csv       アプリの市区町村名が、町字データ（全国 町字マスター）の今の名前と違うもの
  app_id_to_code.csv   アプリの id → もとの学校コード
  school_closures.csv・new_schools.csv（pipeline/terms の写し）と文科省の CSV 3つの写し
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import shutil
import sys
import zipfile
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from school2050 import closures as cl  # noqa: E402
from school2050 import combined, wards  # noqa: E402


def town_city_names(path) -> dict:
    """町字データ → {市区町村コード（5桁）: 市区町村名（政令市の区は「市名＋区名」）}"""
    out = defaultdict(Counter)
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if not n.lower().endswith(".csv"):
                continue
            with z.open(n) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
                    out[r["lg_code"][:5]][r["city"] + r["ward"]] += 1
    return out


def write(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "app" / "data"))
    ap.add_argument("--opendata", default=str(ROOT / "opendata"), help="school_district_children_XX.csv（区域の面積）")
    ap.add_argument("--ids", required=True, help="ids_XX.csv のフォルダ（tools/capture_school_codes.py）")
    ap.add_argument("--mext", required=True, help="文科省の CSV のフォルダ")
    ap.add_argument("--town", required=True, help="全国 町字マスター（zip）")
    ap.add_argument("--out", default=str(ROOT / "opendata" / "closures_review"))
    ap.add_argument("--tests", help="テストの結果（そのまま summary.txt の最後に入れる）")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    mext_paths = sorted(pathlib.Path(a.mext).glob("*.csv"))
    prefs = cl.read_app(a.data)
    mext, notes = cl.load_mext(mext_paths)
    id_codes = cl.read_id_codes(a.ids)
    res = cl.decide(prefs, mext, id_codes)
    L = []
    P = L.append

    # ---- 件数
    P("閉校の印（make-closures）の確かめ  tools/review_closures.py")
    P(f"材料：文部科学省「学校コード」令和8年5月1日時点（暫定版）{len(mext_paths)}ファイル・{len(mext)}行、app/data {len(res.schools)}校")
    P("")
    P("■ 件数（判定の結果。app/data に入っている数は add-closures の出力を見る）")
    P(f"- gone：{len(res.gone)}校")
    now = [g for g in res.gone if g[2]]
    P(f"- now：{len(now)}校（移行先がアプリの学校で id あり {sum(1 for g in now if 'id' in g[2])}、名前だけ {sum(1 for g in now if 'id' not in g[2])}）")
    nf = Counter(f for g in res.gone for f in g[3])
    P("  now を付けなかった gone の学校（外れた決まりごと。重なりあり）：" + ("、".join(f"{k}（{cl.NOW_RULES[k]}）{v}" for k, v in sorted(nf.items())) or "なし"))
    P(f"  移行後の学校コードが空の gone の学校：{sum(1 for g in res.gone if not g[1].next_raw)}校")
    P(f"- joined：{len(res.joined)}校（受け入れた gone の学校 {sum(len(v) for v in res.joined.values())}校）")
    P(f"- newSchools：{len(res.new_schools)}校（from あり {sum(1 for x in res.new_schools if x[2])}）")
    P("  新しい学校の候補（公立の小・義務、本分校 1・廃止なし・設定年月日が後）で外れた決まり：" +
      ("、".join(f"{k}（{cl.NEW_RULES[k]}）{v}" for k, v in sorted(res.new_rejected.items())) or "なし"))
    by_kind = Counter(r.kind for r, _c, _f in res.new_schools)
    P("  学校種：" + "、".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
    g25 = sum(g[0].est2025 for g in res.gone)
    P(f"- gone の学校の 2025年の推計（6〜11歳）の合計：{g25:,.1f}人"
      f"（うち approx {sum(g[0].est2025 for g in res.gone if g[0].approx):,.1f}人・{sum(1 for g in res.gone if g[0].approx)}校）")
    P("")
    P(f"■ 閉校に分類された {len(res.closed_classified)}校のうち、印を付けなかった {len(res.closed_not_marked)}校")
    fc = Counter(f for _s, _r, fs in res.closed_not_marked for f in fs)
    for k in sorted(cl.GONE_RULES):
        P(f"- 決まり{k}（{cl.GONE_RULES[k]}）：{fc.get(k, 0)}校")
    combo = Counter(";".join(map(str, fs)) for _s, _r, fs in res.closed_not_marked)
    P("  外れた決まりの組み合わせ：" + "、".join(f"[{k}] {v}" for k, v in combo.most_common()))
    unr = Counter(w.split("（")[0] for v in res.unreliable.values() for w in v)
    P("- 当てにならない学校（決まり7）の内訳（全校。重なりあり）：" + "、".join(f"{k} {v}" for k, v in unr.most_common()))
    P("")

    rows = []
    for s, r, fs in sorted(res.closed_not_marked, key=lambda x: (x[0].pref, x[0].city, x[0].id)):
        rows.append([s.pref_name, s.city, s.city_name, s.id, s.name, "1" if s.approx else "", s.code,
                     r.name if r else "", r.honbun if r else "", r.abol if r else "", r.next_raw if r else "", s.est2025,
                     ";".join(map(str, fs)), "／".join(cl.GONE_RULES[f] for f in fs),
                     "／".join(res.unreliable.get((s.pref, s.id), []))])
    write(out / "not_marked.csv", ["都道府県", "市区町村コード", "市区町村名", "id", "アプリの学校名", "approx", "学校コード",
                                   "文科省の学校名", "本分校", "属性情報廃止年月日", "移行後の学校コード", "2025年の推計",
                                   "外れた決まり", "外れた決まりの中身", "当てにならない理由"], rows)

    # ---- コード不明
    area = {}
    for p in pathlib.Path(a.opendata).glob("school_district_children_*.csv"):
        with open(p, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                area[(r["pref_code"], r["school_id"])] = r["area_km2"]
    unk = [s for s in res.schools if s.code_how == "unknown"]
    keys = []
    for s in unk:
        r = id_codes.get((s.pref, s.id))
        for k in (json.loads(r["props"]) if r and r.get("props") else {}):
            if k not in keys:
                keys.append(k)
    rows = []
    for s in unk:
        r = id_codes.get((s.pref, s.id))
        pr = json.loads(r["props"]) if r and r.get("props") else {}
        rows.append([s.pref_name, s.city, s.city_name, s.id, s.name, "1" if s.approx else "", s.est2025,
                     area.get((s.pref, s.id), ""), s.unknown_why] + [pr.get(k, "") for k in keys])
    write(out / "unknown54.csv", ["都道府県", "市区町村コード", "市区町村名", "id", "学校名", "approx", "2025年の推計", "区域の面積_km2",
                                  "コードが決まらない理由"] + [f"学区データ {k}" for k in keys], rows)
    P(f"■ コード不明：{len(unk)}校（unknown54.csv。区域の面積が無いもの {sum(1 for x in rows if x[7] == '')}）")
    P("")

    # ---- id → 学校コード
    write(out / "app_id_to_code.csv", ["id", "学校コード", "都道府県", "市区町村コード", "市区町村名", "アプリの学校名"],
          [[s.id, s.code, s.pref, s.city, s.city_name, s.name] for s in res.schools])

    # ---- 市区町村名
    towns = town_city_names(a.town)
    wt = wards.load()
    city_of_ward = defaultdict(set)
    for w in wt.values():
        city_of_ward[w.city].add(w.city_name)
    comb = combined.load()
    rows, n = [], 0
    for o in prefs:
        for c in o["cities"]:
            n += 1
            code, nm = c["code"], c["name"]
            if code in towns:
                cand = towns[code].most_common()
                want = cand[0][0]
                note = "" if len(cand) == 1 else "町字データに名前が2つ以上: " + ",".join(x for x, _ in cand)
            elif code in city_of_ward:
                want = sorted(city_of_ward[code])[0]
                note = "政令市を市でまとめた市区町村（designated_city_wards.csv の市の名前）"
            elif code in comb:
                want, note = "", "まとめた区域"
            else:
                want, note = "", "町字データに無いコード"
            if want != nm:
                rows.append([o["code"], code, nm, want, note])
    write(out / "muni_names.csv", ["都道府県", "市区町村コード", "アプリの名前", "町字データの名前", "備考"], rows)
    P(f"■ 市区町村名：アプリの {n}市区町村を、町字データ（{pathlib.Path(a.town).name}）の今の名前と比べた。違うもの {len(rows)}（muni_names.csv）")
    for r in rows:
        P(f"  {r[1]}：アプリ「{r[2]}」、町字データ「{r[3]}」 {r[4]}")
    P("")

    # ---- 同じ市区町村に同じ名前の学校が2つ以上
    dups = defaultdict(list)
    for o in prefs:
        for c in o["cities"]:
            for s in c["schools"]:
                dups[(o["code"], c["code"], c["name"], s["name"])].append(s)
    dup_rows = []
    for (pc, cc, cn, nm), ss in sorted(dups.items()):
        if len(ss) > 1:
            for s in ss:
                code = next((x.code for x in res.schools if x.pref == pc and x.id == s["id"]), "")
                mrow = [r for r in mext if r.code == code]
                dup_rows.append([pc, cc, cn, nm, len(ss), s["id"], code, mrow[0].name if len(mrow) == 1 else "",
                                 mrow[0].honbun if len(mrow) == 1 else "", "1" if s.get("approx") else "",
                                 "1" if s.get("gone") else "", s["est"][0]])
    write(out / "same_name_schools.csv", ["都道府県", "市区町村コード", "市区町村名", "学校名", "同じ名前の数", "id", "学校コード",
                                          "文科省のそのコードの名前", "本分校", "approx", "gone", "2025年の推計"], dup_rows)
    groups = sorted({(r[0], r[2], r[3], r[4]) for r in dup_rows})
    P(f"■ 同じ市区町村に同じ名前の学校が2つ以上ある組：{len(groups)}組（same_name_schools.csv）")
    for g in groups:
        ids = [r for r in dup_rows if (r[0], r[2], r[3]) == g[:3]]
        P(f"  {g[1]} {g[2]}（{g[3]}校）：" + "、".join(f"{r[5]}（{r[7] or 'コード不明'}{'・gone' if r[10] else ''}）" for r in ids))
    P("")

    P("■ 文科省の一覧の注意（止めずに扱ったもの）")
    for x in notes:
        P(f"- {x}（移行後の学校コードが2つ以上なので now を付けない）")
    P("")
    if a.tests:
        P("■ テストの結果")
        P(pathlib.Path(a.tests).read_text(encoding="utf-8").rstrip())
    (out / "summary.txt").write_text("\n".join(L) + "\n", encoding="utf-8")

    for p in (cl.CLOSURES_CSV, cl.NEW_CSV, *mext_paths):
        if not p.exists():
            raise SystemExit(f"写す表がありません（先に make-closures）: {p}")
        shutil.copy2(p, out / p.name)
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
