#!/usr/bin/env python3
"""学区別の将来児童数（6〜11歳、2025〜2070年）を計算し、アプリ用データを作る。

入力（国土数値情報。ダウンロードした zip のままでよい）
  小学校区データ                         … 学区のポリゴン。学校の位置の層が同じ zip にあれば自動で使う
  500mメッシュ別将来推計人口（R6国政局推計）… CSV を優先して使う

いちばん簡単な使い方（ダウンロードした zip を1つのフォルダに入れて）
  python3 pipeline/build_school_data.py build-all --input data_raw --out app/data --opendata opendata
  → 中身から「学区かメッシュか」「どの都道府県か」を判定し、そろった県をすべて生成する

1県ずつ
  python3 pipeline/build_school_data.py inspect --districts <学区.zip> --mesh <メッシュ.zip>
  python3 pipeline/build_school_data.py build --districts <学区.zip> --mesh <メッシュ.zip> --out app/data

自動判定が合わないとき
  --name-field / --city-field / --code-field / --owner-field / --address-field で学区の属性を、
  --age-columns 'PT01_{Y},PT02_{Y},PT03_{Y}'（0〜4歳,5〜9歳,10〜14歳）でメッシュの列を明示できる。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from school2050 import estimate, export, geo, inputs, readers, terms  # noqa: E402


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _fields(features, args) -> readers.DistrictFields:
    f = readers.detect_fields(features)
    for attr, opt in (("name", "name_field"), ("city_code", "city_field"), ("school_code", "code_field"),
                      ("owner", "owner_field"), ("address", "address_field")):
        v = getattr(args, opt, None)
        if v:
            if v not in features[0].props:
                raise SystemExit(f"--{opt.replace('_', '-')} {v} は属性にありません: {', '.join(features[0].props)}")
            setattr(f, attr, v)
    return f


def _mesh_columns(df, args) -> readers.MeshColumns:
    if getattr(args, "age_columns", None):
        ages = readers.parse_age_columns(args.age_columns)
        miss = [c for cols in ages.values() for c in cols[:3] if c not in df.columns]
        if miss:
            raise SystemExit("--age-columns で指定した列がありません: " + ", ".join(miss[:6]))
        mesh, city = readers.detect_code_columns(df)
        return readers.MeshColumns(mesh, city, ages)
    return readers.detect_mesh_columns(df)


def _resolve(args) -> None:
    """--districts / --mesh に zip やフォルダが渡されたら、中の使うファイルに置き換える。"""
    args.pref_guess = None
    if getattr(args, "districts", None):
        ds = inputs.find_districts(args.districts)
        args.districts = str(ds.polygons)
        if ds.points and not args.schools:
            args.schools = str(ds.points)
        args.pref_guess = ds.pref
    if getattr(args, "mesh", None):
        ms = inputs.find_mesh(args.mesh)
        args.mesh = str(ms.table)
        args.pref_guess = args.pref_guess or ms.pref
    if getattr(args, "schools", None) and pathlib.Path(args.schools).suffix.lower() == ".zip":
        ds = inputs.find_districts(args.schools)
        args.schools = str(ds.points or ds.polygons)


def cmd_inspect(args) -> int:
    _resolve(args)
    if args.pref_guess:
        print(f"都道府県コード（中身から判定）: {args.pref_guess}")
    if args.districts:
        feats = readers.read_features(args.districts)
        print(f"[学区] {args.districts}: {len(feats)} 件")
        print("  属性:", ", ".join(feats[0].props.keys()))
        for f in feats[:3]:
            print("  例:", json.dumps(f.props, ensure_ascii=False))
        try:
            print("  判定:", _fields(feats, args).describe())
        except ValueError as e:
            print("  判定できません:", e)
    if args.mesh:
        df = readers.read_table(args.mesh)
        print(f"[メッシュ] {args.mesh}: {len(df)} 行 × {len(df.columns)} 列")
        print("  先頭の列:", ", ".join(list(df.columns)[:40]), "…" if len(df.columns) > 40 else "")
        try:
            print("  判定:", _mesh_columns(df, args).describe())
        except (ValueError, SystemExit) as e:
            print("  判定できません:", e)
    if args.schools:
        feats = readers.read_features(args.schools)
        print(f"[学校] {args.schools}: {len(feats)} 件")
        print("  属性:", ", ".join(feats[0].props.keys()))
        for f in feats[:3]:
            print("  例:", json.dumps(f.props, ensure_ascii=False))
    return 0


def _school_points(path, pref_code) -> dict:
    """学校の位置を、学校コードと（行政区域コード, 学校名）の両方で引けるようにする。"""
    feats = readers.read_features(path)
    try:
        f = readers.detect_fields(feats)
    except ValueError as e:
        log(f"学校の位置データを使えません（{e}）。学区の重心を使います")
        return {}
    out = {}
    for ft in feats:
        xy = (float(ft.rings[0][0][0]), float(ft.rings[0][0][1]))
        if f.school_code and ft.props.get(f.school_code):
            out[ft.props[f.school_code]] = xy
        city = ft.props.get(f.city_code, "").zfill(5) if f.city_code else pref_code + "000"
        out[(city, export.strip_owner(ft.props.get(f.name, "")))] = xy
    return out


def _gap_schools(path, gap_cities: set, dfields) -> list:
    """学校の位置データから、学区の無い市区町村の公立小学校を取り出す。
    返り値: [(行政区域コード, 経度, 緯度, 学区データと同じ属性名に直した props)]"""
    src = inputs.find_schools(path)
    feats = readers.read_features(src.points)
    f = readers.detect_fields(feats)
    out, names = [], {}
    for ft in feats:
        city = ft.props.get(f.city_code, "").zfill(5) if f.city_code else ""
        addr = ft.props.get(f.address, "") if f.address else ""
        if city and addr and city not in names:
            names[city] = export.city_from_address(addr)
        if city not in gap_cities:
            continue
        code = ft.props.get(f.school_code, "") if f.school_code else ""
        name = export.strip_owner(ft.props.get(f.name, ""))
        if code:
            # 文部科学省の学校コード：先頭2文字が学校種（B1＝小学校）、5文字目が設置者（2＝公立）
            if not (code.startswith("B1") and code[4:5] == "2"):
                continue
        elif not name.endswith("小学校") or re.search(r"附属|私立", name):
            continue
        x, y = float(ft.rings[0][0][0]), float(ft.rings[0][0][1])
        props = {dfields.name: name, "_city_name": names.get(city, "")}
        if dfields.city_code:
            props[dfields.city_code] = city
        if dfields.school_code and code:
            props[dfields.school_code] = code
        out.append((city, x, y, props))
    for c, _x, _y, pr in out:
        pr["_city_name"] = names.get(c, "")
    _gap_schools.names = names
    return out


def cmd_build(args) -> int:
    t0 = time.time()
    _resolve(args)
    if not args.pref and not args.pref_guess:
        raise SystemExit("都道府県コードを中身から判定できませんでした。--pref で指定してください")
    pref = str(args.pref or args.pref_guess).zfill(2)
    if args.pref and args.pref_guess and str(args.pref).zfill(2) != args.pref_guess:
        log(f"注意: --pref {args.pref} と、ファイルの中身（{args.pref_guess}）が一致しません")
    log(f"== {export.PREF_NAMES.get(pref, pref)}（{pref}）")

    feats = readers.read_features(args.districts)
    fields = _fields(feats, args)
    log(f"学区 {len(feats)} 件。{fields.describe()}")
    # 利用条件で再配布できない市区町村の学区は、配分の前に除く（学区データなしとして扱う）
    tm = terms.load()
    if not tm:
        log(f"注意: 利用条件の一覧（{terms.DEFAULT}）がありません。学区を除かずに進めます")
    ex = terms.excluded(tm)
    excluded_by_terms = []
    if ex and fields.city_code:
        def city_of(f):
            return str(f.props.get(fields.city_code, "")).strip().zfill(5)
        excluded_by_terms = sorted({city_of(f) for f in feats if city_of(f) in ex})
        if excluded_by_terms:
            feats = [f for f in feats if city_of(f) not in ex]
            log(f"利用条件（再配布不可）で除いた市区町村: {', '.join(excluded_by_terms)}。残り {len(feats)} 件")
    elif ex:
        log("注意: 学区データに行政区域コードが無いため、利用条件で除く市区町村を判定できません")
    feats = export.merge_same_school(feats, fields, pref)
    log(f"同じ学校の地物をまとめて {len(feats)} 校")

    df = readers.read_table(args.mesh)
    mc = _mesh_columns(df, args)
    log(f"メッシュ {len(df)} 行。\n{mc.describe()}")
    mt = readers.build_mesh_table(df, mc)
    log(f"子ども（0〜14歳）のいるメッシュ {len(mt.codes)} 件")

    values = np.hstack([mt.kids, mt.ages])
    alloc = estimate.allocate(mt.codes, values, feats, k=args.k, log=log)
    ny = len(mt.years)

    # ---- 学区データの無い市区町村
    gaps, approx_info = {}, {}
    if mt.city:
        by_city: dict = {}
        for code, v, a in zip(mt.city, mt.kids[:, 0], alloc.mesh_assigned):
            c = by_city.setdefault(code, [0.0, 0.0])
            c[0] += v
            c[1] += v * a
        # 判定は1つの市区町村だけのメッシュで行う。"40133_40134" のような境界のメッシュは市区町村ではないので含めない
        gaps = {k: v[0] for k, v in by_city.items() if "_" not in k and v[0] >= 1 and v[1] / v[0] < 0.05}
    sums = alloc.sums
    if gaps and args.fill_schools:
        sch = _gap_schools(args.fill_schools, set(gaps), fields)
        args._gap_names = getattr(_gap_schools, "names", {})
        if sch:
            near = estimate.allocate_nearest(mt.codes, mt.city, values, [(c, x, y) for c, x, y, _p in sch], set(gaps), k=args.k,
                                           count=alloc.count)
            extra = []
            for (city, x, y, props), hull in zip(sch, near.hulls):
                if hull is None:
                    continue
                pr = dict(props)
                pr.update({"_city": city, "_approx": "1", "_lng": x, "_lat": y})
                extra.append(readers.Feature(pr, [hull]))
            keep = [i for i, h in enumerate(near.hulls) if h is not None]
            feats = feats + extra
            sums = np.vstack([sums, near.sums[keep]])
            alloc.unassigned = alloc.unassigned - near.sums.sum(axis=0)
            filled = sorted({c for c, *_r in sch if c in gaps})
            approx_info = {c: sum(1 for s2 in sch if s2[0] == c) for c in filled}
            log(f"学区データの無い {len(filled)} 市区町村を、学校の位置からおおよその区域で補いました: {', '.join(filled)}")
    elif gaps:
        log(f"学区データの無い市区町村があります（{len(gaps)}）: {', '.join(sorted(gaps))}。"
            "国土数値情報「学校」の zip を --fill-schools に渡すと、おおよその区域で補えます")

    points = _school_points(args.schools, pref) if args.schools else None
    overrides = None
    if args.city_names:
        with open(args.city_names, encoding="utf-8-sig", newline="") as fh:
            overrides = {r[0].strip().zfill(5): r[1].strip() for r in csv.reader(fh) if len(r) >= 2 and r[0].strip().isdigit()}
    source = {
        "districts": pathlib.Path(args.districts).name,
        "mesh": pathlib.Path(args.mesh).name,
        "method": f"面積按分（{args.k}×{args.k}点サンプリング）。6〜11歳＝(5〜9歳)×4/5＋(10〜14歳)×2/5",
        "credit": "国土数値情報（国土交通省）を加工して作成",
    }
    obj, rows = export.build_pref(pref, feats, fields, sums, mt.years, ny, points, overrides, source, args.min_children)
    have = {c["code"] for c in obj["cities"]}
    names = getattr(args, "_gap_names", {})
    obj["missing"] = [{"code": c, "name": names.get(c, "")} for c in sorted(gaps) if c not in have]
    # 条件公開・特記条件のある市区町村は、アプリで「学区は めやす」と表示する
    noted = terms.needs_note(tm)
    for c in obj["cities"]:
        if c["code"] in noted:
            c["note"] = True

    # ---- 検査（数字が保存されているか、どこが漏れたか）
    total = mt.kids.sum(axis=0)
    got = sums[:, :ny].sum(axis=0)
    un = alloc.unassigned[:ny]
    report = {
        "pref": pref, "schools": sum(len(c["schools"]) for c in obj["cities"]), "cities": len(obj["cities"]),
        "mesh_children_2025": round(float(total[0]), 1),
        "allocated_2025": round(float(got[0]), 1),
        "unassigned_2025": round(float(un[0]), 1),
        "unassigned_share_2025": round(float(un[0] / total[0]), 4) if total[0] else None,
        "conservation_error": round(float(abs(total - got - un).max()), 6),
        "overlap_point_share": round(alloc.overlap_points / max(1, alloc.total_points), 4),
        "dropped_small": obj["_dropped"],
        "approx_cities": approx_info,
        "excluded_by_terms": excluded_by_terms,
        "note_cities": sorted(c["code"] for c in obj["cities"] if c.get("note")),
        "missing_cities": obj["missing"],
        "seconds": round(time.time() - t0, 1),
    }
    if mt.city:
        by_city = {}
        for code, v, a in zip(mt.city, mt.kids[:, 0], alloc.mesh_assigned):
            c = by_city.setdefault(code, [0.0, 0.0])
            c[0] += v
            c[1] += v * a
        report["city_coverage_2025"] = {k: round(v[1] / v[0], 3) for k, v in sorted(by_city.items()) if v[0] >= 20}
        low = {k: v for k, v in report["city_coverage_2025"].items() if v < 0.9}
        if low:
            log(f"注意: 学区でカバーできていない市区町村があります（配分率 < 0.9）: {low}")

    js = export.write_pref_js(obj, args.out)
    idx = export.update_index(args.out, obj)
    log(f"書き出し: {js}（{js.stat().st_size / 1024:.0f} KB）, {idx}")
    if args.opendata:
        od = export.write_opendata_csv(rows, pathlib.Path(args.opendata) / f"school_district_children_{pref}.csv")
        rp = pathlib.Path(args.opendata) / f"report_{pref}.json"
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"書き出し: {od}, {rp}")
    print(json.dumps({k: v for k, v in report.items() if k != "city_coverage_2025"}, ensure_ascii=False, indent=1))
    return 0


def _scan_inputs(root) -> dict:
    """フォルダの中の zip / ファイルを中身で仕分ける。{都道府県コード: {"districts"|"mesh"|"schools": パス}}"""
    root = pathlib.Path(root)
    items = sorted(p for p in root.iterdir() if not p.name.startswith(".") and not p.is_dir())
    found: dict = {}
    for it in items:
        try:
            kind = inputs.classify(it)
        except Exception as e:  # 壊れた zip など。1つの失敗で全体を止めない
            log(f"読めません: {it.name}（{e}）")
            continue
        if kind == "districts":
            pref = inputs.find_districts(it).pref
        elif kind == "mesh":
            pref = inputs.find_mesh(it).pref
        elif kind == "schools":
            pref = inputs.find_schools(it).pref
        else:
            log(f"使わないファイル: {it.name}")
            continue
        if not pref:
            log(f"都道府県が分かりません: {it.name}")
            continue
        found.setdefault(pref, {})[kind] = it
        log(f"{it.name} → {export.PREF_NAMES.get(pref, pref)} の{ {'districts': '学区', 'mesh': 'メッシュ', 'schools': '学校の位置'}[kind] }")
    return found


def cmd_build_all(args) -> int:
    """フォルダの中の zip / ファイルを中身で仕分けし、学区とメッシュがそろった県をすべて生成する。"""
    found = _scan_inputs(args.input)
    results, missing = {}, {}
    for pref in sorted(found):
        got = found[pref]
        if "districts" not in got or "mesh" not in got:
            missing[pref] = "学区がありません" if "districts" not in got else "メッシュがありません"
            continue
        sub = argparse.Namespace(**vars(args))
        sub.districts, sub.mesh, sub.pref, sub.schools = str(got["districts"]), str(got["mesh"]), pref, None
        sub.fill_schools = None if args.no_fill else (str(got["schools"]) if "schools" in got else None)
        try:
            cmd_build(sub)
            results[pref] = "ok"
        except (ValueError, SystemExit) as e:
            results[pref] = f"失敗: {e}"
            log(f"{pref} 失敗: {e}")
    print(json.dumps({"built": results, "missing": missing}, ensure_ascii=False, indent=1))
    return 0 if results and all(v == "ok" for v in results.values()) else 1


def _validate_pref(pref, got, args) -> dict:
    """学区データのある市区町村で、学区を使わず「おおよその区域」と同じ方法で割り当て直し、学校ごとのずれを要約する。"""
    sub = argparse.Namespace(districts=str(got["districts"]), mesh=str(got["mesh"]), schools=None, pref=pref,
                             name_field=None, city_field=None, code_field=None, owner_field=None, address_field=None,
                             age_columns=None)
    _resolve(sub)
    feats = readers.read_features(sub.districts)
    fields = _fields(feats, sub)
    if not fields.city_code:
        raise ValueError("学区データに行政区域コードが無いので、市区町村ごとに比べられません")
    # build と同じく、利用条件で再配布できない市区町村の学区は使わない
    ex = terms.excluded(terms.load())
    def city_of(f):
        return str(f.props.get(fields.city_code, "")).strip().zfill(5)
    excluded = sorted({city_of(f) for f in feats if city_of(f) in ex})
    feats = [f for f in feats if city_of(f) not in ex]
    feats = export.merge_same_school(feats, fields, pref)
    df = readers.read_table(sub.mesh)
    mt = readers.build_mesh_table(df, _mesh_columns(df, sub))
    if not mt.city:
        raise ValueError("メッシュに行政区域コードが無いので、おおよその区域を作れません")

    # 学校の位置：おおよその区域と同じく国土数値情報「学校」を使う。学校コード → (市区町村, 学校名) の順に探し、
    # 見つからない学校だけ学区の重心で代える（件数を出す）
    pts = _school_points(str(inputs.find_schools(got["schools"]).points), pref)
    xy, fallback = [], 0
    for f in feats:
        code = f.props.get(fields.school_code, "") if fields.school_code else ""
        loc = pts.get(code) or pts.get((f.props["_city"], f.props.get(fields.name, "")))
        if not loc:
            loc, fallback = geo.centroid(f.rings), fallback + 1
        xy.append(loc)
    city = [f.props["_city"] for f in feats]
    year_i = 0  # 2025年
    d, n = estimate.compare_nearest(mt.codes, mt.city, mt.kids[:, year_i:year_i + 1], feats, xy, city, k=args.k)
    d, n = d[:, 0], n[:, 0]

    per_city: dict = {}
    for i, c in enumerate(city):
        if d[i] >= args.min_children:  # build と同じく、推計1人未満の学区は比べない
            per_city.setdefault(c, []).append((n[i] - d[i]) / d[i])
    names = export._city_names(feats, fields, None)
    cities = {c: {"name": names.get(c, ""), **estimate.summarize_rel(r)} for c, r in sorted(per_city.items()) if len(r) >= 2}
    all_rel = [v for c in cities for v in per_city[c]]
    return {
        "year": mt.years[year_i],
        "method": "学区データのある市区町村で、学区を使わずに、メッシュの点を同じ市区町村（境界のメッシュは並んだ市区町村）の"
                  "いちばん近い学校に割り当て直した推計と、学区を使った推計を学校ごとに比べた。"
                  "ずれ＝(近い学校での推計 − 学区での推計) ÷ 学区での推計。学校が1校だけの市区町村は除く。",
        "excluded_by_terms": excluded,
        "location_fallback_schools": fallback,
        "pref": estimate.summarize_rel(all_rel),
        "cities": cities,
    }


def cmd_validate_approx(args) -> int:
    """おおよその区域の当たり具合を、学区データのある市区町村で測り、report_XX.json に書き足す。"""
    found = _scan_inputs(args.input)
    out = {}
    for pref in sorted(found):
        got = found[pref]
        lack = [k for k in ("districts", "mesh", "schools") if k not in got]
        if lack:
            out[pref] = "足りないファイル: " + ", ".join(lack)
            continue
        log(f"== {export.PREF_NAMES.get(pref, pref)}（{pref}）おおよその区域の当たり具合")
        res = _validate_pref(pref, got, args)
        rp = pathlib.Path(args.opendata) / f"report_{pref}.json"
        report = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {"pref": pref}
        report["validate_approx"] = res
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"書き出し: {rp}")
        out[pref] = res["pref"]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--districts", help="小学校区データ（.geojson / .shp）")
        p.add_argument("--mesh", help="500mメッシュ別将来推計人口（.csv / .shp / .dbf）")
        p.add_argument("--schools", help="（任意）学校の位置データ")
        p.add_argument("--name-field"); p.add_argument("--city-field"); p.add_argument("--code-field")
        p.add_argument("--owner-field"); p.add_argument("--address-field")
        p.add_argument("--age-columns", help="0〜4歳,5〜9歳,10〜14歳 の列名。年は {Y} と書く")

    pi = sub.add_parser("inspect", help="入力ファイルの属性と、自動判定の結果を表示する")
    common(pi)
    pi.set_defaults(fn=cmd_inspect)

    pb = sub.add_parser("build", help="都道府県1つ分のデータを生成する")
    common(pb)
    pb.add_argument("--pref", help="都道府県コード（01〜47）。省略すると中身から判定する")
    pb.add_argument("--out", default="app/data", help="アプリ用データの出力先")
    pb.add_argument("--opendata", help="オープンデータ用 CSV と検査レポートの出力先")
    pb.add_argument("--city-names", help="（任意）行政区域コード,名称 の CSV。市区町村名を上書きする")
    pb.add_argument("--k", type=int, default=4, help="メッシュ1辺あたりのサンプル点数（既定 4）")
    pb.add_argument("--min-children", type=float, default=1.0, help="2025年の推計がこれ未満の学区は出力しない")
    pb.add_argument("--fill-schools", help="（任意）国土数値情報「学校」。学区データの無い市区町村を、学校の位置からおおよその区域で補う")
    pb.set_defaults(fn=cmd_build)

    pv = sub.add_parser("validate-approx", help="おおよその区域の当たり具合を、学区データのある市区町村で測る")
    pv.add_argument("--input", required=True, help="国土数値情報の zip を入れたフォルダ（学区・メッシュ・学校の3つ）")
    pv.add_argument("--opendata", required=True, help="report_XX.json のあるフォルダ（validate_approx を書き足す）")
    pv.add_argument("--k", type=int, default=4)
    pv.add_argument("--min-children", type=float, default=1.0)
    pv.set_defaults(fn=cmd_validate_approx)

    pa = sub.add_parser("build-all", help="フォルダの中のダウンロードファイルをまとめて処理する")
    pa.add_argument("--input", required=True, help="国土数値情報の zip を入れたフォルダ")
    pa.add_argument("--out", default="app/data")
    pa.add_argument("--opendata")
    pa.add_argument("--city-names")
    pa.add_argument("--k", type=int, default=4)
    pa.add_argument("--min-children", type=float, default=1.0)
    pa.add_argument("--no-fill", action="store_true", help="学区データの無い市区町村を補わない")
    for opt in ("name_field", "city_field", "code_field", "owner_field", "address_field", "age_columns"):
        pa.set_defaults(**{opt: None})
    pa.set_defaults(fn=cmd_build_all)

    args = ap.parse_args(argv)
    if args.cmd == "build" and not (args.districts and args.mesh):
        ap.error("build には --districts と --mesh が必要です")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
