#!/usr/bin/env python3
"""都道府県ごとに、ダウンロード → inspect → build → validate-approx → independent_check を回し、結果を県ごとのフォルダに残す。

全国生成の前の「予行」と、全国生成そのものの両方で使う。リポジトリの app/data/・opendata/・data_raw/ には書かない。

    python3 tools/national_dryrun.py --work /path/to/work [--prefs 01,02,…] [--generated 2026-11-16] [--min-free-gb 10]

県ごとのフォルダ（--work/XX/）
  in/        ダウンロードした zip（小学校区 A27-23_XX、メッシュ 500m_mesh_2024_XX、学校 P29-23_XX）
  app/ od/   build の出力（pref_XX.js、report_XX.json、school_district_children_XX.csv）
  logs/      各段の標準出力・標準エラー（全文）
  status.json  ダウンロードと各段の終了コード・所要時間・エラーの最後の行
  extra.json   集計用の追加の数え上げ（tools/dryrun_summary.py が読む）
status.json があり、done が true の県は飛ばす（途中から再開できる）。
zip と出力（report・pref_XX.js・ログ）は残し、展開したファイル（tmp/）は県ごとに消す。status.json の disk に、
その県の zip と出力の大きさを残す。次の県に入る前に、空き − その県の見込み（メッシュ zip の大きさ × 15）が
--min-free-gb を切るなら止める（展開したメッシュの XML は zip の 10〜14 倍）。
1つの段が失敗しても止めず、記録して次の段・次の県へ進む。パイプラインは直さない。
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIPE = ROOT / "pipeline" / "build_school_data.py"
INDEP = ROOT / "tools" / "independent_check.py"
BASE = "https://nlftp.mlit.go.jp/ksj/gml/data/"
SOURCES = {
    "districts": "A27/A27-23/A27-23_{p}_GML.zip",
    "mesh": "m500r6/m500r6-24/500m_mesh_2024_{p}_GML.zip",
    "schools": "P29/P29-23/P29-23_{p}_GML.zip",
}
UA = "school2050-dryrun/1.0"


def download(url: str, dest: pathlib.Path, tries: int = 3) -> dict:
    t0 = time.time()
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as out:
                shutil.copyfileobj(r, out)
            return {"ok": True, "status": 200, "bytes": dest.stat().st_size, "seconds": round(time.time() - t0, 1)}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"ok": False, "status": 404, "error": str(e), "seconds": round(time.time() - t0, 1)}
            err = str(e)
        except Exception as e:  # ネットワークの一時的な失敗は少し待ってやり直す
            err = f"{type(e).__name__}: {e}"
        time.sleep(5 * (i + 1))
    if dest.exists():
        dest.unlink()
    return {"ok": False, "error": err, "seconds": round(time.time() - t0, 1)}


def run(cmd: list, log: pathlib.Path, timeout: int) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = "timeout", (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), \
            f"{timeout}秒で打ち切り"
    log.write_text(f"$ {' '.join(str(c) for c in cmd)}\n--- stdout\n{out}\n--- stderr\n{err}\n", encoding="utf-8")
    last = [l for l in (err or "").splitlines() if l.strip()]
    res = {"rc": rc, "seconds": round(time.time() - t0, 1)}
    if rc != 0:
        # 例外の行（いちばん最後の行）と、Traceback の後の最初の行
        res["error_last"] = last[-1] if last else ""
        tb = next((i for i, l in enumerate(last) if l.startswith("Traceback")), None)
        if not last:  # 標準エラーが空（independent_check の「不一致」など）は、標準出力の最後の行
            last = [l for l in (out or "").splitlines() if l.strip()] or [""]
            tb = None
        res["error_last"] = last[-1]
        res["error_first"] = last[0] if tb is None else (last[tb + 1] if tb + 1 < len(last) else last[tb])
    return res


def _geojson_from_zip(zpath: pathlib.Path, prefix: str) -> list | None:
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".geojson") and pathlib.PurePath(n).name.startswith(prefix)]
        if not names:
            return None
        return json.loads(z.read(sorted(names, key=lambda n: -z.getinfo(n).file_size)[0]).decode("utf-8-sig"))["features"]


def _mesh_member(zpath: pathlib.Path):
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        csvs = [n for n in names if n.lower().endswith(".csv")]
        xmls = [n for n in names if n.lower().endswith(".xml") and not pathlib.PurePath(n).name.startswith("KS-META")]
        return names, csvs, xmls


def mesh_stats(zpath: pathlib.Path) -> dict:
    """メッシュの形式、市区町村ごとのメッシュ数と人口、秘匿・合算の記号。XML は要素名で1行ずつ読む。"""
    names, csvs, xmls = _mesh_member(zpath)
    out = {"format": "CSV" if csvs else ("GML" if xmls else "?"), "members": names}
    if csvs or not xmls:
        return out
    rx = re.compile(r"<ksj:(\w+)[^>]*>([^<]*)</ksj:")
    want = {"administrativeAreaCode", "totalPopulationOf2020", "populationOfAge0To14In2025", "totalPopulationIn2025",
            "confidentialSymbolOf2025", "destinationMeshOf2025"}
    city_n, city_pop20, city_kids, city_tot25 = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    sym, dest_n, n = collections.Counter(), 0, 0
    cur = None
    with zipfile.ZipFile(zpath) as z, z.open(xmls[0]) as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace")
            if "<ksj:" not in line:
                continue
            m = rx.search(line)
            if not m:
                continue
            tag, v = m.group(1), m.group(2).strip()
            if tag == "meshCode":
                n += 1
                cur = None
            elif tag == "administrativeAreaCode":
                cur = v
                city_n[v] += 1
            elif tag in want and cur is not None:
                if tag == "confidentialSymbolOf2025":
                    sym[v] += 1
                elif tag == "destinationMeshOf2025":
                    dest_n += 1 if v else 0
                else:
                    try:
                        x = float(v) if v else 0.0
                    except ValueError:
                        sym[f"{tag}={v}"] += 1
                        continue
                    {"totalPopulationOf2020": city_pop20, "populationOfAge0To14In2025": city_kids,
                     "totalPopulationIn2025": city_tot25}[tag][cur] += x
    single = [c for c in city_n if "_" not in c]
    out.update({
        "meshes": n, "cities_in_mesh": len(single),
        "symbols_2025": dict(sym), "destination_mesh_rows": dest_n,
        "zero_total_2025_cities": sorted(c for c in single if city_tot25[c] == 0),
        "zero_kids_2025_cities": sorted(c for c in single if city_kids[c] == 0),
        "pop2020_but_zero_2025_cities": sorted(c for c in single if city_pop20[c] > 0 and city_tot25[c] == 0),
    })
    return out


def school_stats(p29: pathlib.Path, report: dict | None) -> dict:
    feats = _geojson_from_zip(p29, "P29")
    if feats is None:
        return {"error": "P29 の GeoJSON が見つかりません"}
    props = [f["properties"] for f in feats]
    code = lambda p: str(p.get("P29_002") or "")
    pub_el = [p for p in props if code(p).startswith("B1") and code(p)[4:5] == "2"]
    c2 = [p for p in props if code(p).startswith("C2") and code(p)[4:5] == "2"]
    approx = set((report or {}).get("approx_cities", {}) or {})
    return {
        "p29_features": len(props),
        "public_elementary": len(pub_el),
        "p29_007_public_elementary": dict(sorted(collections.Counter(str(p.get("P29_007") or "") for p in pub_el).items())),
        "compulsory_c2": len(c2),
        "compulsory_c2_in_approx_cities": sorted(f"{p.get('P29_001')} {p.get('P29_004')}" for p in c2 if str(p.get("P29_001")) in approx),
        "compulsory_c2_names": sorted(f"{p.get('P29_001')} {p.get('P29_004')}" for p in c2),
    }


def district_stats(a27: pathlib.Path) -> dict:
    feats = _geojson_from_zip(a27, "A27")
    if feats is None:
        return {"error": "A27 の GeoJSON が見つかりません"}
    props = [f["properties"] for f in feats]
    codes = collections.Counter(str(p.get("A27_001") or "") for p in props)
    no_code = [f"{p.get('A27_001')} {p.get('A27_004')}" for p in props if not p.get("A27_003")]
    owners = collections.Counter(str(p.get("A27_002") or "") for p in props if not re.search(r"(市|町|村|区)立$", str(p.get("A27_002") or "")))
    return {"features": len(props), "cities": len(codes), "no_school_code": no_code, "unusual_owners": dict(owners)}


def _strip_owner(name: str) -> str:
    m = re.match(r"^.{1,12}?(?:市|町|村|区|組合)立(.+(?:学校|学園|分校))$", name or "")
    return m.group(1) if m else (name or "")


def location_stats(a27: pathlib.Path, p29: pathlib.Path) -> dict:
    """学区データの学校のうち、学校の位置データ（P29）に学校コードでも（市区町村, 名前）でも見つからない学校。
    政令市の区は、pipeline/terms/designated_city_wards.csv で市にも読み替えて探す。"""
    a = _geojson_from_zip(a27, "A27") or []
    pfe = _geojson_from_zip(p29, "P29") or []
    w2c = {}
    tp = ROOT / "pipeline" / "terms" / "designated_city_wards.csv"
    if tp.exists():
        with tp.open(encoding="utf-8-sig", newline="") as fh:
            w2c = {r["区のコード"]: r["市のコード"] for r in csv.DictReader(fh)}
    codes = {str(f["properties"].get("P29_002") or "") for f in pfe}
    names = set()
    for f in pfe:
        c, n = str(f["properties"].get("P29_001") or ""), _strip_owner(str(f["properties"].get("P29_004") or ""))
        names.add((c, n)); names.add((w2c.get(c, c), n))
    miss = []
    seen = set()
    for f in a:
        pr = f["properties"]
        key = pr.get("A27_003") or (pr.get("A27_001"), pr.get("A27_004"))
        if key in seen:
            continue
        seen.add(key)
        if pr.get("A27_003") and pr["A27_003"] in codes:
            continue
        if (str(pr.get("A27_001")), _strip_owner(str(pr.get("A27_004") or ""))) in names:
            continue
        miss.append(f"{pr.get('A27_001')} {pr.get('A27_004')}" + ("" if pr.get("A27_003") else "（学校コードなし）"))
    return {"district_schools": len(seen), "not_in_p29": len(miss), "not_in_p29_schools": miss[:80],
            "no_code_and_not_in_p29": sum(1 for m in miss if m.endswith("（学校コードなし）"))}


def output_stats(pref: str, app: pathlib.Path, od: pathlib.Path) -> dict:
    out = {}
    js = app / f"pref_{pref}.js"
    if js.exists():
        out["pref_js_bytes"] = js.stat().st_size
        t = js.read_text(encoding="utf-8")
        d = json.loads(t[t.index("UG.registerPref(") + 16:t.rindex(")")])
        out["city_schools"] = {c["code"]: [c["name"], len(c["schools"])] for c in d["cities"]}
    csvp = od / f"school_district_children_{pref}.csv"
    if csvp.exists():
        with csvp.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        cen = [r for r in rows if r.get("loc_source") == "学区の重心"]
        out["centroid_pins"] = len(cen)
        out["centroid_pin_schools"] = [f"{r['city_code']} {r['school_name']}" for r in cen][:50]
    return out


def indep_result(log_text: str) -> dict:
    m = re.search(r"結果: (\S+)", log_text)
    if not m:
        return {"result": "?"}
    res = {"result": m.group(1)}
    m2 = re.search(r"アプリ (\d+)校、検算 (\d+)校。アプリだけ (\d+)、検算だけ (\d+)、市区町村や区分の違い (\d+)", log_text)
    if m2:
        res.update(app=int(m2.group(1)), check=int(m2.group(2)), only_app=int(m2.group(3)), only_check=int(m2.group(4)), meta=int(m2.group(5)))
    m3 = re.search(r"0.06人を超えて違う学校：学区のある学校 (\d+)、おおよその区域の学校 (\d+)（最大 ([\d.]+)人）", log_text)
    if m3:
        res.update(bad_district=int(m3.group(1)), bad_approx=int(m3.group(2)), worst=float(m3.group(3)))
    return res


def extract(zpath: pathlib.Path, member_suffix: str, dest: pathlib.Path) -> pathlib.Path | None:
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.lower().endswith(member_suffix) and not pathlib.PurePath(n).name.startswith("KS-META")]
        if not names:
            return None
        n = sorted(names, key=lambda n: -z.getinfo(n).file_size)[0]
        out = dest / pathlib.PurePath(n).name
        with z.open(n) as src, open(out, "wb") as fh:
            shutil.copyfileobj(src, fh)
        return out


def _du(*paths) -> int:
    n = 0
    for p in paths:
        p = pathlib.Path(p)
        if p.is_file():
            n += p.stat().st_size
        elif p.is_dir():
            n += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return n


def mesh_zip_size(pref: str, work: pathlib.Path) -> int:
    """メッシュ zip の大きさ（手元にあればその大きさ、無ければ HEAD で問い合わせる）。分からなければ 0。"""
    pat = SOURCES["mesh"].format(p=pref)
    local = work / pref / "in" / pathlib.PurePath(pat).name
    if local.exists():
        return local.stat().st_size
    try:
        req = urllib.request.Request(BASE + pat, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def do_pref(pref: str, work: pathlib.Path, args) -> dict:
    d = work / pref
    for sub in ("in", "app", "od", "logs", "tmp"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    st = {"pref": pref, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "downloads": {}, "steps": {}}
    zips = {}
    for kind, pat in SOURCES.items():
        dest = d / "in" / pathlib.PurePath(pat.format(p=pref)).name
        if dest.exists() and dest.stat().st_size > 0:
            st["downloads"][kind] = {"ok": True, "bytes": dest.stat().st_size, "cached": True}
        else:
            st["downloads"][kind] = download(BASE + pat.format(p=pref), dest)
        if st["downloads"][kind].get("ok"):
            zips[kind] = dest
            # 取得日＝ダウンロードした日（ファイルの更新日時）。生成のたびに変わらないよう、build に渡す
            st["downloads"][kind]["retrieved"] = time.strftime("%Y-%m-%d", time.localtime(dest.stat().st_mtime))
    py = sys.executable
    L = d / "logs"
    if "districts" in zips and "mesh" in zips:
        cmd = [py, PIPE, "inspect", "--districts", zips["districts"], "--mesh", zips["mesh"]]
        if "schools" in zips:
            cmd += ["--schools", zips["schools"]]
        st["steps"]["inspect"] = run(cmd, L / "1_inspect.log", args.timeout)
        cmd = [py, PIPE, "build", "--pref", pref, "--districts", zips["districts"], "--mesh", zips["mesh"],
               "--out", d / "app", "--opendata", d / "od", "--generated", args.generated,
               "--retrieved", max(v.get("retrieved", "") for v in st["downloads"].values())]
        if "schools" in zips:
            cmd += ["--fill-schools", zips["schools"]]
        st["steps"]["build"] = run(cmd, L / "2_build.log", args.timeout)
        if "schools" in zips:
            st["steps"]["validate_approx"] = run([py, PIPE, "validate-approx", "--input", d / "in", "--opendata", d / "od"],
                                                 L / "3_validate.log", args.timeout)
    else:
        st["steps"]["inspect"] = st["steps"]["build"] = {"rc": "skipped", "error_first": "学区かメッシュが取れない"}
    report_p = d / "od" / f"report_{pref}.json"
    report = json.loads(report_p.read_text(encoding="utf-8")) if report_p.exists() else None

    extra = {}
    if "mesh" in zips:
        try:
            extra["mesh"] = mesh_stats(zips["mesh"])
        except Exception as e:
            extra["mesh"] = {"error": f"{type(e).__name__}: {e}"}
    if "schools" in zips:
        try:
            extra["schools"] = school_stats(zips["schools"], report)
        except Exception as e:
            extra["schools"] = {"error": f"{type(e).__name__}: {e}"}
    if "districts" in zips:
        try:
            extra["districts"] = district_stats(zips["districts"])
        except Exception as e:
            extra["districts"] = {"error": f"{type(e).__name__}: {e}"}
    if "districts" in zips and "schools" in zips:
        try:
            extra["location"] = location_stats(zips["districts"], zips["schools"])
        except Exception as e:
            extra["location"] = {"error": f"{type(e).__name__}: {e}"}
    extra["output"] = output_stats(pref, d / "app", d / "od")

    # independent_check（メッシュが XML のときだけ）
    js = d / "app" / f"pref_{pref}.js"
    if extra.get("mesh", {}).get("format") == "GML" and js.exists() and "schools" in zips:
        tmp = d / "tmp"
        try:
            mx = extract(zips["mesh"], ".xml", tmp)
            dx = extract(zips["districts"], ".geojson", tmp)
            px = extract(zips["schools"], ".geojson", tmp)
            # excluded_by_terms は {code, name, reason} の並び（以前はコードの並び）
            ex = ",".join(e["code"] if isinstance(e, dict) else e for e in ((report or {}).get("excluded_by_terms") or []))
            cmd = [py, INDEP, "--mesh", mx, "--districts", dx, "--schools", px, "--pref-js", js]
            if ex:
                cmd += ["--exclude", ex]
            st["steps"]["independent_check"] = run(cmd, L / "4_independent.log", args.timeout)
            st["steps"]["independent_check"].update(indep_result((L / "4_independent.log").read_text(encoding="utf-8")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(exist_ok=True)
    elif extra.get("mesh", {}).get("format") == "CSV":
        st["steps"]["independent_check"] = {"rc": "未対応", "error_first": "メッシュが CSV（independent_check は XML だけ）"}
    else:
        st["steps"]["independent_check"] = {"rc": "skipped"}

    (d / "extra.json").write_text(json.dumps(extra, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(d / "tmp", ignore_errors=True)  # 展開したファイルは消す（zip と出力は残す）
    st["disk"] = {"zips_bytes": _du(d / "in"), "outputs_bytes": _du(d / "app", d / "od", d / "logs", d / "extra.json")}
    st["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    st["done"] = True
    (d / "status.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True, help="作業用フォルダ（リポジトリの外）")
    ap.add_argument("--prefs", help="県コード（カンマ区切り）。省略すると 01〜47")
    ap.add_argument("--skip", default="", help="飛ばす県コード（カンマ区切り）")
    ap.add_argument("--generated", default="2026-11-16")
    ap.add_argument("--timeout", type=int, default=3600, help="1つの段の打ち切り秒数")
    ap.add_argument("--min-free-gb", type=float, default=10.0, help="次の県の見込みを引いた空きがこれより少なければ止める")
    a = ap.parse_args(argv)
    work = pathlib.Path(a.work).resolve()
    if ROOT in work.parents or work == ROOT:
        raise SystemExit("作業用フォルダはリポジトリの外にしてください")
    work.mkdir(parents=True, exist_ok=True)
    prefs = a.prefs.split(",") if a.prefs else [f"{i:02d}" for i in range(1, 48)]
    skip = set(a.skip.split(",")) - {""}
    for pref in prefs:
        if pref in skip:
            continue
        sp = work / pref / "status.json"
        if sp.exists() and json.loads(sp.read_text(encoding="utf-8")).get("done"):
            print(f"{pref}: 済み（飛ばす）", flush=True)
            continue
        free = shutil.disk_usage(work).free / 1e9
        need = mesh_zip_size(pref, work) * 15 / 1e9 + 0.2  # 展開したメッシュ（一時）＋出力
        if free - need < a.min_free_gb:
            print(f"止めます: {pref} の前で空き {free:.1f}GB、この県の見込み {need:.1f}GB（残すべき空き {a.min_free_gb}GB）", flush=True)
            return 1
        t0 = time.time()
        st = do_pref(pref, work, a)
        steps = ", ".join(f"{k}={v.get('rc')}" for k, v in st["steps"].items())
        dl = ", ".join(f"{k}={'ok' if v.get('ok') else v.get('status') or 'NG'}" for k, v in st["downloads"].items())
        print(f"{pref}: {time.time() - t0:.0f}秒  ダウンロード[{dl}]  {steps}  空き {shutil.disk_usage(work).free / 1e9:.1f}GB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
