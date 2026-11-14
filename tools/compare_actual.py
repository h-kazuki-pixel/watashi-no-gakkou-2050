"""推計（app/data/pref_40.js の est[0]＝2025年）と、実際の在籍児童数（令和7年5月1日）を市ごとに照合する。

    python3 tools/compare_actual.py            # pdfplumber が必要（pip install pdfplumber）

入力（手で保存。リポジトリには入れない。data_raw/ は .gitignore 済み）
  data_raw/actual/fukuoka_R7.pdf            福岡市「児童生徒数等一覧表」令和7年5月1日現在・速報値
  data_raw/actual/kitakyushu_No73_2025.pdf  北九州市「教育調査統計資料 No.73 2025」
  data_raw/actual/kurume_R7_opendata.csv    久留米市「市立学校児童生徒数一覧（久留米市）」令和7年度（BODIK、CC BY、特別支援学級を含む）
  data_raw/actual/kurume_R7.pdf             久留米市「市立小学校の児童数・学級数の将来推計及び学校施設の状況について（令和7年度）」
                                            （通常学級のみ。照合には使わず、CSV の検算にだけ使う）

出力
  opendata/accuracy_actual_40.json   市ごとの集計値と学校数だけ（学校名・学校別の値は入れない）
  data_raw/actual/matched_40.csv     学校ごとの対応表（確認用。data_raw/ の外には出さない）

公表値（市・区の合計、久留米市の学校数と合計）と一致しなければ、何も書き出さずに止める。
久留米市は CSV の「小学校」で終わる行の1〜6学年の合計を使う（市立特別支援学校の「特別小」などと中学校は使わない）。
CSV の各校の人数が、PDF の通常学級の人数以上であることも確かめる。
ずれ ＝（推計 − 実際）÷ 実際。絶対ずれはその絶対値。
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACT = ROOT / "data_raw" / "actual"

# ---------------------------------------------------------------- 公表値（一致しなければ止める）
FUKUOKA_TOTAL, FUKUOKA_SCHOOLS = 82207, 147
FUKUOKA_WARDS = {"40131": 18336, "40132": 8814, "40133": 7889, "40134": 15289, "40135": 11876, "40136": 6691, "40137": 13312}
KITA_TOTAL = 42377
KITA_WARDS = {"40101": 3781, "40106": 6985, "40107": 10316, "40103": 4253, "40108": 2845, "40109": 11883, "40105": 2314}
KURUME_SCHOOLS, KURUME_TOTAL = 43, 16317
# 学校別の検算値（学校名と実数の組）は、リポジトリに入れないため data_raw/actual/checks.json に置く：
#   {"fukuoka_small": {学校名: 人数, …}, "kurume": {学校名: 人数, …}}

# 照合から外す学校・アプリに無い学校（区の小計の検算では足す）
EXCLUDE = {"fukuoka": {"曲渕"}, "kitakyushu": {"藍島"}}
NOT_IN_APP = {"fukuoka": {"照葉はばたき": "40131"}, "kitakyushu": {"河内": "40108"}}
MERGED = {"kurume": {"青峰": "高良内"}}  # 令和7年4月1日に統合。推計を統合先に足す

CITIES = {
    "fukuoka": ("福岡市", ["40131", "40132", "40133", "40134", "40135", "40136", "40137"]),
    "kitakyushu": ("北九州市", ["40101", "40103", "40105", "40106", "40107", "40108", "40109"]),
    "kurume": ("久留米市", ["40203"]),
}


def stop(msg: str) -> None:
    print("止めます: " + msg, file=sys.stderr)
    sys.exit(1)


def key(name: str) -> str:
    """学校名の照合用の形：空白を除き、「ヶ」を「ケ」に、末尾の「小学校」「小」を取る。"""
    n = re.sub(r"\s+", "", name or "").replace("ヶ", "ケ")
    return re.sub(r"(小学校|小)$", "", n)


# ---------------------------------------------------------------- PDF の読み取り
def _children_total(nums: list) -> int | None:
    """数の並びから児童数の合計を探す：合計＝男＋女 で、そのあとに学年ごとの（計＝男＋女）が続き、計の和が合計になる位置。"""
    for j in range(len(nums) - 2):
        t, m, f = nums[j:j + 3]
        if t <= 0 or t != m + f:
            continue
        s, k, g = 0, j + 3, 0
        while k + 2 < len(nums) and s < t:
            c, cm, cf = nums[k:k + 3]
            if c != cm + cf:
                break
            s, k, g = s + c, k + 3, g + 1
        # 学年は6つ。1学年分の短い並び（例：田野浦の「8 5 3」）を合計と取り違えないよう、5学年以上続くことを条件にする
        if s == t and g >= 5:
            return t
    return None


def _children_total_loose(nums: list) -> int | None:
    """小さい学校は学年の欄が空欄で並びが崩れる。合計＝男＋女 になる位置のうち最大のものを合計とみなす
    （福岡市の玄界・小呂・勝馬・志賀島。値は公表値で検算する）。"""
    cands = [nums[j] for j in range(len(nums) - 2) if nums[j] > 0 and nums[j] == nums[j + 1] + nums[j + 2]]
    return max(cands) if cands else None


def _rows(pdf, pages, numbered: bool):
    """(学校名, 数の並び) を順に返す。() 内（特別支援学級の再掲）は除く。"""
    pending = ""
    for i in pages:
        for line in (pdf.pages[i].extract_text() or "").splitlines():
            pre = re.match(r"^([^\d\s(（][^\d(（]*?)\s+[(（]", line)  # 「照葉 (20) …」：次の行の学校名の前半
            body = re.sub(r"[(（][\d,]*[)）]", " ", line).strip()
            toks = body.split()
            if numbered:
                if not toks or not toks[0].isdigit():
                    pending = pre.group(1) if pre else ""
                    continue
                toks = toks[1:]
            name, nums = [], []
            for t in toks:
                if re.fullmatch(r"[\d,]+", t):
                    nums.append(int(t.replace(",", "")))
                elif not nums:
                    name.append(t)
            if name:  # 児童がいない（休校）学校は数が並ばない
                yield (pending + "".join(name)), nums
            pending = ""


def read_fukuoka(pdfplumber) -> dict:
    with pdfplumber.open(ACT / "fukuoka_R7.pdf") as pdf:
        pages = [i for i, p in enumerate(pdf.pages) if "学校別・学年別児童数＜小学校＞" in (p.extract_text() or "")]
        out = {}
        for name, nums in _rows(pdf, pages, numbered=True):
            if not nums:
                out[key(name)] = 0
                continue
            t = _children_total(nums)
            if t is None:
                t = _children_total_loose(nums)
            if t is None:
                stop(f"福岡市 {name} の児童数を読み取れません: {nums}")
            out[key(name)] = t
    return out


# 北九州市の表は、左端に縦書きの区名（門司・小倉北…）があり、その字が学校名の前に付いて読まれることがある
KITA_WARD_CHARS = set("門司小倉北南若松八幡東西戸畑区")


def _strip_ward_chars(k: str, known: set) -> str:
    """アプリの学校名に無いときだけ、先頭の区名の字を1字ずつ外して、アプリの学校名に合う形を探す。"""
    cur = k
    while cur not in known and cur and cur[0] in KITA_WARD_CHARS:
        cur = cur[1:]
    return cur if cur in known else k


def read_kitakyushu(pdfplumber, known: set) -> dict:
    """1校につき「児童数の行」と「学級数の行」がこの順に並ぶ。合計は 計＝男＋女 の並びで探し、
    見つからない小さい学校（空欄で並びが崩れる）だけ、その学校の最初の行（児童数の行）から最大の 計＝男＋女 を取る。"""
    with pdfplumber.open(ACT / "kitakyushu_No73_2025.pdf") as pdf:
        pages = [i for i, p in enumerate(pdf.pages)
                 if re.search(r"小学校学級数（.+区）", (p.extract_text() or "").splitlines()[0] if p.extract_text() else "")]
        lines: dict = {}
        for name, nums in _rows(pdf, pages, numbered=False):
            if not nums or re.search(r"計|総数|学級|学年", name):
                continue
            lines.setdefault(_strip_ward_chars(key(name), known | set(EXCLUDE["kitakyushu"]) | set(NOT_IN_APP["kitakyushu"])), []).append(nums)
        out = {}
        for k, ls in lines.items():
            t = next((x for x in (_children_total(n) for n in ls) if x is not None), None)
            if t is None:
                t = _children_total_loose(ls[0])
            if t is not None:
                out[k] = t
    return out


def read_kurume(pdfplumber) -> dict:
    with pdfplumber.open(ACT / "kurume_R7.pdf") as pdf:
        p = next(p for p in pdf.pages if "学校規模・校舎最長築年数 一覧表" in (p.extract_text() or ""))
        out = {}
        for line in p.extract_text().splitlines():
            m = re.match(r"^\d{2}\s+(.+?)\s+\d+\s*クラス\s+([\d,]+)\s*人", line)
            if m:
                out[key(m.group(1))] = int(m.group(2).replace(",", ""))
    return out


def read_kurume_csv() -> dict:
    """BODIK の CSV（UTF-8、BOM つき）。「小学校」で終わる行の1〜6学年の合計。"""
    raw = (ACT / "kurume_R7_opendata.csv").read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp932")
    rows = list(csv.reader(text.splitlines()))
    head = rows[0]
    try:
        ci = head.index("学校名")
        gi = [head.index(f"{g}学年児童・生徒数（人）") for g in range(1, 7)]
    except ValueError:
        stop(f"久留米市の CSV の列が想定と違います: {head}")
    out = {}
    for r in rows[1:]:
        if len(r) <= max(gi) or not r[ci].strip().endswith("小学校"):
            continue
        k = key(r[ci])
        if k in out:
            stop(f"久留米市の CSV に {r[ci]} が2行あります")
        out[k] = sum(int(r[i]) for i in gi)
    return out


# ---------------------------------------------------------------- 照合
def load_pref() -> dict:
    s = (ROOT / "app" / "data" / "pref_40.js").read_text(encoding="utf-8")
    return json.loads(s[s.index("(") + 1: s.rindex(")")])


def summarize(pairs: list) -> dict:
    """pairs: [(推計, 実際)]。市ごとの集計（学校別の値は返さない）。"""
    rel = [(e - a) / a for e, a in pairs]
    ab = sorted(abs(r) for r in rel)
    q = statistics.quantiles(ab, n=4, method="inclusive")
    n = len(ab)
    es, as_ = sum(e for e, _ in pairs), sum(a for _, a in pairs)
    share = lambda c: round(sum(1 for x in ab if c(x)) / n, 4)
    count = lambda c: sum(1 for x in ab if c(x))
    return {
        "schools": n, "est_total": round(es, 1), "actual_total": as_,
        "total_diff": round((es - as_) / as_, 4),
        "abs_median": round(statistics.median(ab), 4), "abs_q1": round(q[0], 4), "abs_q3": round(q[2], 4),
        "within_10": share(lambda x: x <= 0.10), "within_20": share(lambda x: x <= 0.20),
        "over_30": share(lambda x: x > 0.30), "over_30_schools": count(lambda x: x > 0.30),
        "over_50": share(lambda x: x > 0.50), "over_50_schools": count(lambda x: x > 0.50),
    }


def main() -> int:
    try:
        import pdfplumber
    except ImportError:
        stop("pdfplumber がありません（pip install pdfplumber）")
    pref = load_pref()
    kita_known = {key(s["name"]) for c in pref["cities"] if c["code"] in CITIES["kitakyushu"][1] for s in c["schools"]}
    actual = {"fukuoka": read_fukuoka(pdfplumber), "kitakyushu": read_kitakyushu(pdfplumber, kita_known),
              "kurume": read_kurume_csv()}
    kurume_pdf = read_kurume(pdfplumber)

    # ---- 公表値との検算
    fk = actual["fukuoka"]
    if len(fk) != FUKUOKA_SCHOOLS or sum(fk.values()) != FUKUOKA_TOTAL:
        stop(f"福岡市の学校数・合計が合いません: {len(fk)}校 {sum(fk.values())}人（公表 {FUKUOKA_SCHOOLS}校 {FUKUOKA_TOTAL}人）")
    checks_path = ACT / "checks.json"
    if not checks_path.exists():
        stop(f"学校別の検算値 {checks_path} がありません")
    checks = json.loads(checks_path.read_text(encoding="utf-8"))
    for n, v in checks["fukuoka_small"].items():
        if fk.get(n) != v:
            stop(f"福岡市 {n} の児童数が {fk.get(n)}（{v} のはず）")
    kk = actual["kitakyushu"]
    if sum(kk.values()) != KITA_TOTAL:
        stop(f"北九州市の合計が合いません: {len(kk)}校 {sum(kk.values())}人（公表 {KITA_TOTAL}人）")
    # 久留米市：PDF（通常学級のみ）は読み取りを確かめたうえで、CSV の検算にだけ使う
    if len(kurume_pdf) != KURUME_SCHOOLS:
        stop(f"久留米市の PDF の学校数が {len(kurume_pdf)}（{KURUME_SCHOOLS}校のはず）")
    for n, v in checks["kurume"].items():
        if kurume_pdf.get(n) != v:
            stop(f"久留米市の PDF の {n} の児童数が {kurume_pdf.get(n)}（{v} のはず）")
    ku = actual["kurume"]
    if len(ku) != KURUME_SCHOOLS or sum(ku.values()) != KURUME_TOTAL:
        stop(f"久留米市の CSV の学校数・合計が合いません: {len(ku)}校 {sum(ku.values())}人（{KURUME_SCHOOLS}校 {KURUME_TOTAL}人のはず）")
    if "青峰" in ku or "大橋" not in ku:
        stop("久留米市の CSV：青峰小の行が無く、大橋小の行があるはず")
    if set(ku) != set(kurume_pdf):
        stop(f"久留米市の CSV と PDF の学校が違います: CSVだけ {sorted(set(ku) - set(kurume_pdf))} / PDFだけ {sorted(set(kurume_pdf) - set(ku))}")
    less = sorted(n for n in ku if ku[n] < kurume_pdf[n])
    if less:
        stop(f"久留米市の CSV の人数が PDF の通常学級の人数より少ない学校があります: {', '.join(less)}")

    # ---- 学校名の対応づけ
    out, rows = {"source_date": "2025-05-01", "estimate": "pref_40.js est[0]（2025年）", "cities": {}}, []
    for cid, (cname, codes) in CITIES.items():
        app = {}
        for c in pref["cities"]:
            if c["code"] in codes:
                for s in c["schools"]:
                    app[key(s["name"])] = (c["code"], s["est"][0])
        for src, dst in MERGED.get(cid, {}).items():
            if src in app and dst in app:
                app[dst] = (app[dst][0], app[dst][1] + app.pop(src)[1])
        act = actual[cid]
        pairs, ward_sum = [], {}
        unmatched_pdf = []
        for n, a in act.items():
            if n in EXCLUDE.get(cid, set()):
                continue
            if n in NOT_IN_APP.get(cid, {}):
                ward_sum[NOT_IN_APP[cid][n]] = ward_sum.get(NOT_IN_APP[cid][n], 0) + a
                continue
            if n not in app:
                unmatched_pdf.append(n)
                continue
            code, e = app[n]
            ward_sum[code] = ward_sum.get(code, 0) + a
            pairs.append((e, a))
            rows.append([cname, code, n, round(e, 1), a, round((e - a) / a, 4)])
        if unmatched_pdf:
            stop(f"{cname}：アプリの学校と対応しない学校があります: {', '.join(unmatched_pdf)}")
        unmatched_app = sorted(set(app) - set(act) - set().union(*MERGED.get(cid, {}).keys() and [set(MERGED[cid])] or [set()]))
        # 区の小計の検算（除いた学校の児童は0か記載なし）
        wards = FUKUOKA_WARDS if cid == "fukuoka" else KITA_WARDS if cid == "kitakyushu" else {}
        for w, v in wards.items():
            if ward_sum.get(w, 0) != v:
                stop(f"{cname} {w} の小計が {ward_sum.get(w, 0)}（公表 {v}）")
        res = summarize(pairs)
        res["app_schools_not_in_pdf"] = len(unmatched_app)
        if cid == "fukuoka":  # 参考：全市（アプリの全校の推計 と 公表の全市）
            res["reference_city"] = {"est_total": round(sum(e for _, e in app.values()), 1), "est_schools": len(app),
                                     "actual_total": FUKUOKA_TOTAL, "actual_schools": FUKUOKA_SCHOOLS,
                                     "total_diff": round((sum(e for _, e in app.values()) - FUKUOKA_TOTAL) / FUKUOKA_TOTAL, 4)}
        out["cities"][cname] = res

    (ROOT / "opendata").mkdir(exist_ok=True)
    (ROOT / "opendata" / "accuracy_actual_40.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with (ACT / "matched_40.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["市", "行政区域コード", "学校名", "推計2025", "実際R7", "ずれ"])
        w.writerows(rows)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
