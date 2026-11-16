"""集計結果を、アプリ用（data/pref_XX.js）とオープンデータ用（CSV）に書き出す。"""
from __future__ import annotations

import csv
import datetime
import json
import pathlib
import re
from collections import Counter, defaultdict

import numpy as np

from . import geo
from .readers import DistrictFields, Feature

PREF_NAMES = {
    "01": "北海道", "02": "青森県", "03": "岩手県", "04": "宮城県", "05": "秋田県", "06": "山形県", "07": "福島県",
    "08": "茨城県", "09": "栃木県", "10": "群馬県", "11": "埼玉県", "12": "千葉県", "13": "東京都", "14": "神奈川県",
    "15": "新潟県", "16": "富山県", "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県", "21": "岐阜県",
    "22": "静岡県", "23": "愛知県", "24": "三重県", "25": "滋賀県", "26": "京都府", "27": "大阪府", "28": "兵庫県",
    "29": "奈良県", "30": "和歌山県", "31": "鳥取県", "32": "島根県", "33": "岡山県", "34": "広島県", "35": "山口県",
    "36": "徳島県", "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県", "41": "佐賀県", "42": "長崎県",
    "43": "熊本県", "44": "大分県", "45": "宮崎県", "46": "鹿児島県", "47": "沖縄県",
}


def merge_same_school(features: list[Feature], fields: DistrictFields, pref_code: str) -> list[Feature]:
    """同じ学校の学区が複数の地物（飛び地など）に分かれている場合、1つにまとめる。"""
    groups: dict = {}
    order = []
    for f in features:
        city = f.props.get(fields.city_code, "").zfill(5) if fields.city_code else pref_code + "000"
        code = f.props.get(fields.school_code, "") if fields.school_code else ""
        name = f.props.get(fields.name, "")
        key = code if code else (city, name)
        if key not in groups:
            groups[key] = Feature(dict(f.props), list(f.rings), list(f.polys) if f.polys else None)
            groups[key].props["_city"] = city
            order.append(key)
        else:
            g = groups[key]
            if g.polys is not None or f.polys is not None:
                g.polys = (g.polys or geo.polys_from_rings(g.rings)) + (f.polys or geo.polys_from_rings(f.rings))
            g.rings += f.rings
    return [groups[k] for k in order]


def locate(points: dict | None, code: str, city: str, name: str):
    """学校の位置。学校コードで引くのは市区町村も合うときだけ。合わなければ（市区町村, 設置者を外した学校名）で引く。無ければ None。"""
    if not points:
        return None
    hit = points.get(("code", code)) if code else None
    if hit and hit[0] == city:
        return hit[1]  # ("code", 学校コード) → (市区町村, 位置, 設置者)
    return points.get(("name", city, strip_owner(name)))


def strip_owner(name: str) -> str:
    """学校名の先頭の設置者（「北九州市立」「〇〇町立」「〇〇組合立」など）を取り、学区データの形（「大積小学校」）にそろえる。
    国土数値情報「学校」は設置者つき、「小学校区」は設置者なしで収録されているため。「立花小学校」のように
    「立」で始まる名前はそのまま。"""
    # 義務教育学校には「学び舎ゆめの森」（大熊町立）のように「学校」「学園」で終わらない名前もある
    m = re.match(r"^.{1,12}?(?:市|町|村|区|組合)立(.+(?:学校|学園|分校|森))$", name or "")
    return m.group(1) if m else (name or "")


def city_from_address(addr: str) -> str:
    """所在地から市区町村名を取り出す（例：福岡県福岡市中央区天神… → 福岡市中央区、糟屋郡宇美町… → 宇美町）。"""
    a = re.sub(r"^(北海道|東京都|大阪府|京都府|.{2,3}県)", "", (addr or "").strip())
    m = re.match(r"^(?:.+?郡)?(.+?[市町村])(.+?区)?", a)
    if not m:
        w = re.match(r"^(.{1,4}?区)", a)  # 東京23区
        return w.group(1) if w else ""
    city, ward = m.group(1), m.group(2) or ""
    if not city.endswith("市"):
        ward = ""
    elif ward and len(ward) > 5:  # 「〇〇市大字〇〇区」のような誤読を避ける
        ward = ""
    return city + ward


def _city_names(features, fields: DistrictFields, overrides: dict | None) -> dict:
    """行政区域コード → 表示名。設置主体（「〜市立」など）と所在地から決める。"""
    by_code = defaultdict(list)
    for f in features:
        by_code[f.props["_city"]].append(f)
    base = {}
    for code, fs in by_code.items():
        if overrides and code in overrides:
            base[code] = overrides[code]
            continue
        given = [f.props.get("_city_name", "") for f in fs if f.props.get("_city_name")]
        if given:
            base[code] = Counter(given).most_common(1)[0][0]
            continue
        owners = [re.sub(r"立$", "", f.props.get(fields.owner, "")) for f in fs] if fields.owner else []
        owners = [o for o in owners if o]
        base[code] = Counter(owners).most_common(1)[0][0] if owners else ""
    # 政令指定都市の区など、同じ名前が複数のコードにまたがるときは、所在地から区名を補う
    dup = {n for n, c in Counter(v for v in base.values() if v).items() if c > 1}
    names = {}
    for code, fs in by_code.items():
        nm = base[code]
        if not nm:
            names[code] = code
            continue
        if nm in dup and not (overrides and code in overrides):
            ward = None
            if fields.address:
                wards = []
                for f in fs:
                    m = re.search(re.escape(nm) + r"(.{1,6}?区)", f.props.get(fields.address, ""))
                    if m:
                        wards.append(m.group(1))
                if wards:
                    ward = Counter(wards).most_common(1)[0][0]
            nm = nm + (ward if ward else f"（{code}）")
        names[code] = nm
    return names


def build_pref(pref_code: str, features: list[Feature], fields: DistrictFields, sums: np.ndarray, years: list,
               n_years: int, school_points: dict | None = None, city_overrides: dict | None = None,
               source: dict | None = None, min_children: float = 1.0,
               generated: str | None = None) -> tuple[dict, list[dict]]:
    """アプリ用のオブジェクトと、オープンデータ用の行を作る。sums の列は [年ごとの6〜11歳…, 0〜11歳の各歳…]。
    generated：生成日（YYYY-MM-DD）。省略すると今日の日付。同じ入力から同じファイルを作り直すときに指定する。"""
    names = _city_names(features, fields, city_overrides)
    cities: dict = {}
    rows, dropped, used_ids = [], [], set()
    no_loc, outside = [], []  # 学校の位置が見つからず学区の重心にした学校、学校の位置が学区の外にある学校
    for i, f in enumerate(features):
        est = sums[i, :n_years]
        ages = sums[i, n_years:n_years + 12]
        name = f.props.get(fields.name, "")
        city = f.props["_city"]
        if est[0] < min_children:
            dropped.append(name)
            continue
        sid = f.props.get(fields.school_code, "") if fields.school_code else ""
        if not sid or sid in used_ids or f.props.get("_code_other_city"):
            sid = f"{city}-{i:04d}"
        used_ids.add(sid)
        loc, loc_src = None, "学区の重心"
        if f.props.get("_lng"):
            loc, loc_src = (float(f.props["_lng"]), float(f.props["_lat"])), "学校の位置データ"
        if not loc and school_points:
            code = f.props.get(fields.school_code, "") if fields.school_code else ""
            loc = locate(school_points, code, city, name)
            if loc:
                loc_src = "学校の位置データ"
                if not geo.points_in_polys([loc[0]], [loc[1]], f.polys or geo.polys_from_rings(f.rings))[0]:
                    outside.append({"city": city, "name": name})
        if not loc:
            loc = geo.centroid(f.rings)
            no_loc.append({"city": city, "name": name})
        school = {
            "id": sid, "name": name,
            "lng": round(float(loc[0]), 5), "lat": round(float(loc[1]), 5),
            "est": [round(float(v), 1) for v in est],
            "ages": [round(float(v), 1) for v in ages],
            "geom": geo.simplify_for_display(f.rings),
        }
        approx = bool(f.props.get("_approx"))
        if approx:
            school["approx"] = True
        cobj = cities.setdefault(city, {"code": city, "name": names.get(city, city), "schools": []})
        if approx and not f.props.get("_fill"):
            # 学区データのある市区町村で補った学校（_fill）は、市区町村ではなく学校だけを approx にする
            cobj["approx"] = True
        cobj["schools"].append(school)
        row = {"pref_code": pref_code, "city_code": city, "city_name": names.get(city, city), "school_id": sid,
               "school_name": name, "lat": school["lat"], "lng": school["lng"], "loc_source": loc_src,
               "area_km2": round(geo.area_km2_polys(f.polys) if f.polys else geo.area_km2(f.rings), 3),
               "district_source": "学校から最も近い区域（おおよそ）" if approx else "国土数値情報 小学校区"}
        for y, v in zip(years, school["est"]):
            row[f"age6_11_{y}"] = v
        rows.append(row)
    for c in cities.values():
        c["schools"].sort(key=lambda s: s["name"])
    obj = {
        "code": pref_code,
        "name": PREF_NAMES.get(pref_code, pref_code),
        "generated": generated or datetime.date.today().isoformat(),
        "source": source or {},
        "cities": [cities[k] for k in sorted(cities)],
        "missing": [],
        "_dropped": dropped,
        "_no_location": no_loc,
        "_location_outside_district": outside,
    }
    return obj, rows


def write_pref_js(obj: dict, out_dir) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pub = {k: v for k, v in obj.items() if not k.startswith("_")}
    p = out / f"pref_{obj['code']}.js"
    p.write_text(
        "/* わたしの学校2050 — pipeline/build_school_data.py が生成。手で編集しないこと。 */\n"
        "UG.registerPref(" + json.dumps(pub, ensure_ascii=False, separators=(",", ":")) + ");\n",
        encoding="utf-8")
    return p


def update_index(out_dir, obj: dict) -> pathlib.Path:
    """data/index.js（アプリが最初に読む都道府県の一覧）に、この県を足す・更新する。"""
    p = pathlib.Path(out_dir) / "index.js"
    entries = []
    if p.exists():
        m = re.search(r"UG\.registerIndex\((\[.*\])\);", p.read_text(encoding="utf-8"), re.S)
        if m:
            try:
                entries = json.loads(m.group(1))
            except json.JSONDecodeError:
                entries = []
    entries = [e for e in entries if e.get("code") != obj["code"]]
    entries.append({
        "code": obj["code"], "name": obj["name"], "cities": len(obj["cities"]),
        "schools": sum(len(c["schools"]) for c in obj["cities"]), "generated": obj["generated"],
    })
    entries.sort(key=lambda e: e["code"])
    p.write_text(
        "/* 実データの都道府県一覧。pipeline/build_school_data.py が生成。 */\n"
        "UG.registerIndex(" + json.dumps(entries, ensure_ascii=False, indent=1) + ");\n",
        encoding="utf-8")
    return p


def write_opendata_csv(rows: list[dict], path) -> pathlib.Path:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.write_text("", encoding="utf-8")
        return p
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p
