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
from school2050 import estimate, export, geo, inputs, readers, shapes, terms, wards  # noqa: E402


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
        # 国土数値情報「学校」(P29) の zip はポイントだけ。学区の zip（ポイントの層が同梱）が渡されることもある
        try:
            args.schools = str(inputs.find_schools(args.schools).points)
        except ValueError:
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


def _repair_shapes(feats, fields) -> dict:
    """学区の図形の乱れ（同じ輪の重複・外に出た穴）を直し、一覧を返す（docs/DATA_METHOD.md「学区の図形」）。"""
    def city(f):
        return str(f.props.get(fields.city_code, "")).strip().zfill(5) if fields.city_code else ""

    def key(f):
        code = f.props.get(fields.school_code, "") if fields.school_code else ""
        return code or (city(f), f.props.get(fields.name, ""))

    def label(f):
        return {"city": city(f), "name": f.props.get(fields.name, "")}
    issues = shapes.repair(feats, key, label)
    return issues


def _shape_label(fields):
    def label(f):
        return {"city": f.props.get("_city", ""), "name": f.props.get(fields.name, "")}
    return label


def _school_points(path, pref_code, to_city=None) -> dict:
    """学校の位置を、学校コードと（行政区域コード, 学校名）の両方で引けるようにする（export.locate で引く）。
    学校コードの鍵には市区町村も持たせる（学区データの学校コードが別の市区町村のものなことがある。古河市）。
    to_city：区のコードを市のコードに読み替える関数（学区データが市のコードで入っている政令市）。
    属性を判定できなければ止める（黙って学区の重心で代えない）。"""
    feats = readers.read_features(path)
    try:
        f = readers.detect_fields(feats)
    except ValueError as e:
        raise SystemExit(f"学校の位置データの属性を判定できません（{e}）: {path}")
    out = {}
    for ft in feats:
        xy = (float(ft.rings[0][0][0]), float(ft.rings[0][0][1]))
        city = ft.props.get(f.city_code, "").zfill(5) if f.city_code else pref_code + "000"
        if to_city:
            city = to_city(city)
        if f.school_code and ft.props.get(f.school_code):
            out[("code", ft.props[f.school_code])] = (city, xy)
        out[("name", city, export.strip_owner(ft.props.get(f.name, "")))] = xy
    return out


def _school_city_codes(path) -> set | None:
    """学校の位置データ（P29）にある行政区域コード。読めなければ None。"""
    if not path:
        return None
    try:
        feats = readers.read_features(inputs.find_schools(path).points)
        f = readers.detect_fields(feats)
    except (ValueError, KeyError, OSError):
        return None
    if not f.city_code:
        return None
    return {ft.props.get(f.city_code, "").zfill(5) for ft in feats if ft.props.get(f.city_code)}


def _city_coded(feats, mt, schools_path, table=None):
    """学区データが市のコードで入っている政令市を見つける。返り値: ({市のコード: CityCoded}, 読み替える関数)"""
    table = wards.load() if table is None else table
    if not mt.city or not table:
        return {}, None
    found = wards.find_city_coded({f.props["_city"] for f in feats}, mt.city, _school_city_codes(schools_path), table)
    return found, (wards.mapper(found, table) if found else None)


# 国土数値情報「学校」の休校区分（コード表「休校コード」：0 調査なし、1 開校中、2 休校中）
CLOSED_CODES = {"0", "1", "2"}


def closed_field(feats) -> str | None:
    """休校区分の属性：名前が P29_007 か「休校」を含み、中身が1桁の数字（空欄を除く）だけのもの。無ければ None。"""
    if not feats:
        return None
    keys = list(feats[0].props)
    for k in [k for k in keys if k == "P29_007"] + [k for k in keys if "休校" in k]:
        vals = {ft.props.get(k, "") for ft in feats} - {""}
        if vals and all(len(v) == 1 and v.isdigit() for v in vals):
            return k
    return None


def is_closed(value: str) -> bool:
    """休校中（2）か、コード表に無い値（9 など）なら True。空欄・0・1 は False。"""
    return bool(value) and (value == "2" or value not in CLOSED_CODES)


def _public_elementary(code: str, name: str) -> bool:
    """公立小学校か。学校コードがあれば先頭2文字が B1（小学校）で5文字目が 2（公立）。無ければ名前で決める。"""
    if code:
        return code.startswith("B1") and code[4:5] == "2"
    return name.endswith("小学校") and not re.search(r"附属|私立", name)


def _closed_schools(path, to_city=None) -> tuple[list, str | None]:
    """学校の位置データのうち、休校の公立小学校。返り値: ([{city, name, code, value}], 休校区分の属性名)"""
    feats = readers.read_features(inputs.find_schools(path).points)
    f = readers.detect_fields(feats)
    cf = closed_field(feats)
    if not cf:
        return [], None
    out = []
    for ft in feats:
        code = ft.props.get(f.school_code, "") if f.school_code else ""
        name = export.strip_owner(ft.props.get(f.name, ""))
        if not _public_elementary(code, name) or not is_closed(ft.props.get(cf, "")):
            continue
        city = ft.props.get(f.city_code, "").zfill(5) if f.city_code else ""
        out.append({"city": to_city(city) if to_city and city else city, "name": name, "code": code, "value": ft.props.get(cf, "")})
    return out, cf


def _gap_schools(path, gap_cities: set, dfields, to_city=None, city_names=None) -> list:
    """学校の位置データから、学区の無い市区町村の公立小学校を取り出す。
    返り値: [(行政区域コード, 経度, 緯度, 学区データと同じ属性名に直した props)]"""
    src = inputs.find_schools(path)
    feats = readers.read_features(src.points)
    f = readers.detect_fields(feats)
    cf = closed_field(feats)  # 休校区分。休校中・コード表に無い値の学校は使わない（docs/DATA_METHOD.md）
    out, names = [], {}
    for ft in feats:
        city = ft.props.get(f.city_code, "").zfill(5) if f.city_code else ""
        if to_city and city:
            city = to_city(city)
        addr = ft.props.get(f.address, "") if f.address else ""
        if city and city_names and city in city_names:
            names[city] = city_names[city]
        elif city and addr and city not in names:
            names[city] = export.city_from_address(addr)
        if city not in gap_cities:
            continue
        code = ft.props.get(f.school_code, "") if f.school_code else ""
        name = export.strip_owner(ft.props.get(f.name, ""))
        # 文部科学省の学校コード：先頭2文字が学校種（B1＝小学校）、5文字目が設置者（2＝公立）
        if not _public_elementary(code, name):
            continue
        if cf and is_closed(ft.props.get(cf, "")):
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


COVERAGE_FILL = 0.9  # 学区データのある市区町村で、配分率がこれ未満のときだけ、学区データに無い学校を補う


def _fill_missing(args, mt, values, alloc, feats, fields, sums, gaps, taken=None):
    """学区データのある市区町村で、国土数値情報「学校」に公立小学校としてあるのに学区データに無い学校を補う。

    対象：配分率（学区に配分できた子どもの割合）が 0.9 未満で、学区データに無い公立小学校がある市区町村。
    突き合わせ：学校コード、無ければ（市区町村, 設置者を外した学校名）。名前が「分校」で終わる学校は補わない。
    割り当て：どの学区にも入らなかった点（学区データなしの市区町村の補いで使った点も除く）を、
    「補う学校の中で」いちばん近い学校に当てる。学区のある学校は候補にしない。
    前提：学区のある学校の線引きは正しい。その外の子どもは、学区データに無い学校のどれかに通うとみなす。
    学区のある学校の値は変えない。
    返り値: (sums, feats, {市区町村: 補った学校の数}, 補った合計)"""
    zero = np.zeros(values.shape[1])
    by_city: dict = {}
    for code, v, a in zip(mt.city, mt.kids[:, 0], alloc.mesh_assigned):
        c = by_city.setdefault(code, [0.0, 0.0])
        c[0] += v
        c[1] += v * a
    dcities = {f.props["_city"] for f in feats if not f.props.get("_approx")} - set(gaps)
    low = {c for c in dcities if c in by_city and by_city[c][0] > 0 and by_city[c][1] / by_city[c][0] < COVERAGE_FILL}
    args._fill_low = low
    if not low:
        return sums, feats, {}, zero
    sch = _gap_schools(args.fill_schools, low, fields, getattr(args, "_to_city", None), getattr(args, "_to_city_names", None))
    have_code = {f.props.get(fields.school_code) for f in feats if fields.school_code and f.props.get(fields.school_code)}
    have_name = {(f.props["_city"], export.strip_owner(f.props.get(fields.name, ""))) for f in feats}
    miss = [s2 for s2 in sch
            if not (fields.school_code and s2[3].get(fields.school_code) in have_code)
            and (s2[0], s2[3].get(fields.name, "")) not in have_name
            and not s2[3].get(fields.name, "").endswith("分校")]
    if not miss:
        return sums, feats, {}, zero
    targets = {c for c, *_r in miss}
    count = alloc.count.copy()
    if taken is not None and taken.taken is not None:
        count[taken.taken] += 1  # 学区データなしの市区町村の補いで使った点は、もう使わない
    near = estimate.allocate_nearest(mt.codes, mt.city, values, [(c, x, y) for c, x, y, _p in miss], targets, k=args.k,
                                     count=count)
    extra, rows, info = [], [], {}
    for (city, x, y, props), hull, row in zip(miss, near.hulls, near.sums):
        if hull is None:
            continue
        pr = dict(props)
        pr.update({"_city": city, "_approx": "1", "_fill": "1", "_lng": x, "_lat": y})
        extra.append(readers.Feature(pr, [hull]))
        rows.append(row)
        info[city] = info.get(city, 0) + 1
    if not extra:
        return sums, feats, {}, zero
    add = np.vstack(rows)
    log("学区データに無い学校を補いました: " + ", ".join(f"{c}（{n}校）" for c, n in sorted(info.items())))
    return np.vstack([sums, add]), feats + extra, info, add.sum(axis=0)


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
    # 乱れた図形（同じ輪の重複・外に出た穴）。利用条件で除く前の全部の学区を「ほかの学校の学区」として使う
    geometry_issues = _repair_shapes(feats, fields)
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
    geometry_issues["overlapping_parts"] = shapes.overlapping_parts(feats, _shape_label(fields))
    for k, v in geometry_issues.items():
        if v:
            log(f"注意: 学区の図形の乱れ（{k}）: " + ", ".join(f"{e['city']} {e['name']}" for e in v))

    df = readers.read_table(args.mesh)
    mc = _mesh_columns(df, args)
    log(f"メッシュ {len(df)} 行。\n{mc.describe()}")
    mt = readers.build_mesh_table(df, mc)
    log(f"子ども（0〜14歳）のいるメッシュ {len(mt.codes)} 件")

    # ---- 学区データが市のコードで入っている政令市（静岡市 22100 など）。メッシュと学校の位置の区のコードを市にまとめる
    wt = wards.load()
    city_coded, args._to_city = _city_coded(feats, mt, args.fill_schools, wt)
    args._to_city_names = {c: cc.name for c, cc in city_coded.items()}
    if city_coded:
        mt.city = [args._to_city(c) for c in mt.city]
        log("注意: 学区データが市のコードで入っている政令市があります。メッシュと学校の位置の区を市にまとめて扱います: "
            + ", ".join(f"{c} {cc.name}（区 {', '.join(cc.mesh_wards)}"
                        + (f"。うち欠番 {', '.join(cc.obsolete_wards)}" if cc.obsolete_wards else "") + "）"
                        for c, cc in city_coded.items()))

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
    gap_near = None
    if gaps and args.fill_schools:
        sch = _gap_schools(args.fill_schools, set(gaps), fields, args._to_city, args._to_city_names)
        args._gap_names = getattr(_gap_schools, "names", {})
        if sch:
            near = estimate.allocate_nearest(mt.codes, mt.city, values, [(c, x, y) for c, x, y, _p in sch], set(gaps), k=args.k,
                                           count=alloc.count)
            gap_near = near
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

    # ---- 学区データのある市区町村で、学区データに入っていない公立小学校を補う
    filled_info: dict = {}
    if args.fill_schools and mt.city:
        n_dist = alloc.sums.shape[0]
        sums, feats, filled_info, filled_sum = _fill_missing(args, mt, values, alloc, feats, fields, sums, gaps,
                                                             taken=gap_near)
        alloc.unassigned = alloc.unassigned - filled_sum
        # 学区のある学校の値は、補う前と同じでなければならない
        if not np.array_equal(sums[:n_dist], alloc.sums):
            raise SystemExit("学区データに無い学校を補ったら、学区のある学校の値が変わりました")

    points = _school_points(args.schools, pref, args._to_city) if args.schools else None
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
    obj, rows = export.build_pref(pref, feats, fields, sums, mt.years, ny, points, overrides, source, args.min_children,
                                  generated=getattr(args, "generated", None))
    have = {c["code"] for c in obj["cities"]}
    names = getattr(args, "_gap_names", {})
    obj["missing"] = [{"code": c, "name": names.get(c, "")} for c in sorted(gaps) if c not in have]
    # 条件公開・特記条件のある市区町村は、アプリで「学区は めやす」と表示する
    noted = terms.needs_note(tm)
    for c in obj["cities"]:
        if c["code"] in noted:
            c["note"] = True

    # 休校の公立小学校（学校の位置データから選ぶ候補に使わなかった学校）
    closed_out = []
    if args.fill_schools:
        closed, cf = _closed_schools(args.fill_schools, args._to_city)
        if cf is None:
            log("注意: 学校の位置データに休校区分の属性が見つかりません。休校の学校も候補に使います")
        have_code = {f.props.get(fields.school_code) for f in feats
                     if fields.school_code and f.props.get(fields.school_code) and not f.props.get("_approx")}
        have_name = {(f.props["_city"], export.strip_owner(f.props.get(fields.name, ""))) for f in feats if not f.props.get("_approx")}
        low = getattr(args, "_fill_low", set())
        for s in closed:
            if s["code"] in have_code or (s["city"], s["name"]) in have_name:
                how = "学区データにあるので学区の学校として使う"
            elif s["city"] in gaps:
                how = "おおよその区域の候補から外した"
            elif s["city"] in low:
                how = "補う学校の候補から外した"
            else:
                how = "候補になる市区町村ではない"
            closed_out.append({"city": s["city"], "name": s["name"], "value": s["value"], "how": how})
        if closed_out:
            log("休校の公立小学校（学校の位置データの候補に使わない）: "
                + ", ".join(f"{s['city']} {s['name']}（{s['value']}、{s['how']}）" for s in closed_out))

    filled_out: dict = {}
    for c in obj["cities"]:
        if not c.get("approx"):
            n = sum(1 for s2 in c["schools"] if s2.get("approx"))
            if n:
                filled_out[c["code"]] = n

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
        # 学区データに無いので補った学校（出力した学校だけ）。2025年の推計が min_children 未満で出力しなかった学校は別に数える
        "filled_missing_schools": filled_out,
        "filled_missing_dropped_small": {c: n - filled_out.get(c, 0) for c, n in filled_info.items() if n > filled_out.get(c, 0)},
        "excluded_by_terms": excluded_by_terms,
        "note_cities": sorted(c["code"] for c in obj["cities"] if c.get("note")),
        "missing_cities": obj["missing"],
        # 学区データが市のコードで入っていたので、区を市にまとめた政令市
        "city_coded_districts": {c: cc.to_report() for c, cc in city_coded.items()},
        # 区で分けて出した市区町村のうち、欠番（再編前など）の区のコード。今の区と名前が合わない
        "obsolete_ward_cities": wards.obsolete_split([c["code"] for c in obj["cities"]], wt),
        # 休校区分が休校中（2）かコード表に無い値の公立小学校。学校の位置データから選ぶ候補には使わない
        "closed_schools_excluded": closed_out,
        # 学区の図形の乱れ（同じ輪の重複・外に出た穴・部分の重なり）と、その扱い
        "geometry_issues": geometry_issues,
        # 学区データのある学校のうち、学校の位置データに見つからず学区の重心にした学校と、位置が学区の外にある学校
        "location_fallback": obj["_no_location"],
        "location_outside_district": obj["_location_outside_district"],
        "seconds": round(time.time() - t0, 1),
    }
    if report["obsolete_ward_cities"]:
        log("注意: 再編前の区のコードで区を分けて出しています（今の区と合いません）: "
            + ", ".join(f"{c} {v}" for c, v in report["obsolete_ward_cities"].items()))
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
    if report["conservation_error"] > 1e-6 * max(1.0, float(total.max())):
        raise SystemExit(f"配分した合計＋未配分がメッシュの合計と合いません（誤差 {report['conservation_error']}）")
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
        # 学校の位置（学区データのある学校のピン）にも国土数値情報「学校」を使う
        sub.districts, sub.mesh, sub.pref = str(got["districts"]), str(got["mesh"]), pref
        sub.schools = str(got["schools"]) if "schools" in got else None
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
    _repair_shapes(feats, fields)  # build と同じ図形で比べる
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
    # build と同じく、学区データが市のコードで入っている政令市は、区を市にまとめる
    city_coded, to_city = _city_coded(feats, mt, got["schools"])
    if to_city:
        mt.city = [to_city(c) for c in mt.city]

    # 学校の位置：おおよその区域と同じく国土数値情報「学校」を使う。学校コード → (市区町村, 学校名) の順に探し、
    # 見つからない学校だけ学区の重心で代える（件数を出す）
    pts = _school_points(str(inputs.find_schools(got["schools"]).points), pref, to_city)
    xy, fallback = [], 0
    for f in feats:
        code = f.props.get(fields.school_code, "") if fields.school_code else ""
        loc = export.locate(pts, code, f.props["_city"], f.props.get(fields.name, ""))
        if not loc:
            loc, fallback = geo.centroid(f.rings), fallback + 1
        xy.append(loc)
    city = [f.props["_city"] for f in feats]
    year_i = 0  # 2025年
    d, n = estimate.compare_nearest(mt.codes, mt.kids[:, year_i:year_i + 1], feats, xy, city, k=args.k)
    d, n = d[:, 0], n[:, 0]
    # 同じ子ども（学区に入った点）を割り当て直しているので、県全体と市区町村ごとの合計は一致するはず。合わなければ止める
    if not np.isclose(d.sum(), n.sum(), rtol=0, atol=1e-6 * max(1.0, d.sum())):
        raise SystemExit(f"validate-approx: 県全体の合計が2通りで一致しません（学区 {d.sum():.3f}／近い学校 {n.sum():.3f}）")
    for c in sorted(set(city)):
        m = np.array([x == c for x in city])
        if not np.isclose(d[m].sum(), n[m].sum(), rtol=0, atol=1e-6 * max(1.0, d[m].sum())):
            raise SystemExit(f"validate-approx: {c} の合計が2通りで一致しません（学区 {d[m].sum():.3f}／近い学校 {n[m].sum():.3f}）")

    per_city: dict = {}
    for i, c in enumerate(city):
        if d[i] >= args.min_children:  # build と同じく、推計1人未満の学区は比べない
            per_city.setdefault(c, []).append((n[i] - d[i]) / d[i])
    names = export._city_names(feats, fields, None)
    cities = {c: {"name": names.get(c, ""), **estimate.summarize_rel(r)} for c, r in sorted(per_city.items()) if len(r) >= 2}
    all_rel = [v for c in cities for v in per_city[c]]
    return {
        "year": mt.years[year_i],
        "method": "学区データのある市区町村で、学区に入った点（学区での推計に数えた子ども）だけを、同じ市区町村の"
                  "いちばん近い学校に割り当て直した推計と、学区を使った推計を学校ごとに比べた。市区町村ごとの合計は2通りで一致する。"
                  "ずれ＝(近い学校での推計 − 学区での推計) ÷ 学区での推計。学校が1校だけの市区町村は除く。",
        "excluded_by_terms": excluded,
        "location_fallback_schools": fallback,
        "total_by_district": round(float(d.sum()), 1), "total_by_nearest": round(float(n.sum()), 1),
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


def _date(s: str) -> str:
    """--generated の値（YYYY-MM-DD）を確かめる。"""
    import datetime
    try:
        return datetime.date.fromisoformat(s).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"日付は YYYY-MM-DD で書いてください: {s}")


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
    pb.add_argument("--generated", type=_date, help="生成日（YYYY-MM-DD）。省略すると今日。作り直して前と比べるときに指定する")
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
    pa.add_argument("--generated", type=_date, help="生成日（YYYY-MM-DD）。省略すると今日。作り直して前と比べるときに指定する")
    for opt in ("name_field", "city_field", "code_field", "owner_field", "address_field", "age_columns"):
        pa.set_defaults(**{opt: None})
    pa.set_defaults(fn=cmd_build_all)

    args = ap.parse_args(argv)
    if args.cmd == "build" and not (args.districts and args.mesh):
        ap.error("build には --districts と --mesh が必要です")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
