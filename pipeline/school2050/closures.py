"""学区データより後に閉校した学校（docs/DATA_METHOD.md「学区データより後に閉校した学校」）。

材料：文部科学省「学校コード」（data_raw/mext_school_code/…/ の CSV）、app/data、アプリの id → もとの学校コードの表
（tools/capture_school_codes.py が作る ids_XX.csv）。

  make-closures（Mac。文科省の CSV・ids_XX.csv・町字データが要る）
      → pipeline/terms/school_closures.csv（gone の学校）と pipeline/terms/new_schools.csv（新しい学校）
  add-closures（表だけで回る。build-all の最後でも呼ぶ）
      → app/data の学校に gone・now・joined、都道府県に newSchools を足す

いちばん大事な方針：今も続いている学校に「閉校」の印を付けるのは、印が無いことよりずっと悪い。
印は決まり（GONE_RULES）をすべて満たすときだけ付け、1つでも外れたら付けずに、外れた決まりを残す。
人数（est・ages・hist）、区域、ピン、学校の数は変えない。
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import kana as kana_mod

TERMS = pathlib.Path(__file__).resolve().parents[1] / "terms"
CLOSURES_CSV = TERMS / "school_closures.csv"
NEW_CSV = TERMS / "new_schools.csv"
MANUAL_CSV = TERMS / "school_closures_manual.csv"  # 手で確かめた閉校（文科省の一覧からは決められない学校）
MANUAL_HEADER = ["市区町村コード", "id", "学校名", "移行先の名前", "移行先の id", "出典", "確かめた日"]
CLOSURES_HEADER = ["都道府県", "市区町村コード", "id", "アプリの学校名", "学校コード", "文科省の学校名", "本分校",
                   "属性情報廃止年月日", "移行後の学校コード", "now の名前", "now の id"]
NEW_HEADER = ["都道府県", "市区町村コード", "学校コード", "学校名", "学校種", "属性情報設定年月日", "from の id", "読み"]

MEXT_HEADER = ["学校コード", "学校種", "都道府県番号", "設置区分", "本分校", "学校名", "学校所在地", "郵便番号",
               "属性情報設定年月日", "属性情報廃止年月日", "旧学校調査番号", "移行後の学校コード"]
CODE_RE = re.compile(r"^[A-H]\d{12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CUTOFF = "2023-04-01"  # 学区データ（A27 令和5年度）・学校の位置（P29 2023年）の時点
SCHOOL_KINDS = ("B1", "C2")  # 小学校・義務教育学校
NEXT_SPLIT = re.compile(r"[、､,，;；/／\s]+")

# 浜通りの扱わない7町村（pipeline/terms/fukushima_hamadori.csv の「出さない」と同じ。表とずれたら止める）
HAMADORI_NOT_HANDLED = {"07542", "07543", "07545", "07546", "07547", "07548", "07564"}

GONE_RULES = {
    1: "もとの学校コードが文科省の一覧のちょうど1行と一致",
    2: "その行が 公立・学校種 B1 か C2・本分校 9・廃止年月日あり",
    3: f"廃止年月日が {CUTOFF} 以降",
    4: "都道府県番号が同じで、所在地から決めた市区町村がアプリの市区町村と同じ",
    5: "そろえた学校名が同じ",
    6: "同じ市区町村に、そろえた名前が同じで存続している行が無い",
    7: "当てにならない学校（作り直しで取ったコード・コードの取り違えの候補・学校種のずれ・コード不明）でない",
    8: "福島県浜通りの扱わない7町村でない",
}
NOW_RULES = {
    1: "移行後の学校コードがちょうど1つ",
    2: "移行先の行が存続（公立・B1 か C2・本分校 1・廃止年月日なし）",
    3: "移行先の所在地から決めた市区町村が gone の学校と同じ",
}
NEW_RULES = {
    1: "公立・B1 か C2・本分校 1・廃止年月日なし",
    2: f"設定年月日が {CUTOFF} 以降",
    3: "所在地から市区町村がちょうど1つに決まり、アプリの市区町村（浜通り7町村を除く）",
    4: "学校コードがアプリのどの学校のもとのコードでもない",
    5: "同じ市区町村のアプリの学校に、そろえた名前が同じ学校が無い",
}


# ---------------------------------------------------------------------------
# 名前のそろえ方

# 先頭の設置者名：「○○市立」「○○町立」「○○村立」「○○区立」。前に都道府県名・郡名が付くもの（「耶麻郡北塩原村立」）も外す。
# 「組合立」と「立」の無い設置者名（「福井市下宇坂小学校」）は外さない（同じにならず、印は付かない）
OWNER_RE = re.compile(r"^(?:北海道|東京都|大阪府|京都府|[^\s]{2,3}県)?(?:[^市区町村郡\s]{1,6}郡)?[^\s]{1,10}?[市区町村]立(?=.)")
# 言い方・書き方の違いで、同じとみなすもの（これ以外は同じとみなさない。docs/DATA_METHOD.md の表と同じ）
NAME_TABLE = [("ヶ", "ケ"), ("ヵ", "カ")]


def norm_name(name: str) -> str:
    """NFKC、空白を除く、先頭の設置者名を外す、NAME_TABLE の置きかえ。"""
    s = unicodedata.normalize("NFKC", name or "")
    s = re.sub(r"\s+", "", s)
    s = OWNER_RE.sub("", s, count=1)
    for a, b in NAME_TABLE:
        s = s.replace(a, b)
    return s


def display_name(name: str) -> str:
    """文科省の学校名 → 画面に出す名前（NFKC・空白を除き、先頭の設置者名を外す。ヶ などはそのまま）。"""
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or ""))
    return OWNER_RE.sub("", s, count=1)


# ---------------------------------------------------------------------------
# 文部科学省「学校コード」

@dataclass
class MextRow:
    code: str
    kind: str      # B1 など
    pref: str      # 01 など
    setchi: str    # 1 国立・2 公立・3 私立
    honbun: str    # 1 本校・2 分校・9 廃校
    name: str
    addr: str
    set_date: str
    abol: str
    next_raw: str
    nexts: list = field(default_factory=list)
    where: str = ""

    @property
    def living(self) -> bool:
        """存続している公立の小学校・義務教育学校（本分校 1 か 2、廃止年月日なし）"""
        return self.setchi == "2" and self.kind in SCHOOL_KINDS and self.honbun in ("1", "2") and not self.abol


def _head(v: str) -> str:
    """「B1(小学校)」→「B1」。括弧が無ければそのまま。"""
    return (v or "").split("(")[0].strip()


def load_mext(paths) -> tuple[list[MextRow], list[str]]:
    """文科省の CSV（UTF-8、BOM つき可）を読む。1行目は題、2行目が見出し。読めない値があれば止める。
    返り値：(行, 注意（止めるほどではない形の外れ。移行後の学校コードが2つ以上 など）)"""
    rows, notes, problems = [], [], []
    for p in paths:
        p = pathlib.Path(p)
        try:
            text = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise SystemExit(f"{p} を UTF-8 で読めません（ほかの文字コードで代わりに読むことはしません）")
        rs = list(csv.reader(text.splitlines(keepends=True)))
        if len(rs) < 3:
            raise SystemExit(f"{p}: 行がありません")
        head = [re.sub(r"\s+", "", h) for h in rs[1]]
        if head != MEXT_HEADER:
            raise SystemExit(f"{p}: 見出しが想定と違います: {rs[1]}")
        for n, r in enumerate(rs[2:], start=3):
            where = f"{p.name}:{n}"
            if not any(x.strip() for x in r):
                continue
            if len(r) != len(MEXT_HEADER):
                problems.append(f"{where} 列の数 {len(r)}")
                continue
            v = [x.strip() for x in r]
            row = MextRow(code=v[0], kind=_head(v[1]), pref=_head(v[2]), setchi=_head(v[3]), honbun=_head(v[4]),
                          name=v[5], addr=v[6], set_date=v[8], abol=v[9], next_raw=v[11], where=where)
            row.nexts = [x for x in NEXT_SPLIT.split(row.next_raw) if x]
            if not CODE_RE.match(row.code):
                problems.append(f"{where} 学校コード「{row.code}」")
            if not re.fullmatch(r"[A-H]\d", row.kind) or row.code[:2] != row.kind:
                problems.append(f"{where} 学校種「{v[1]}」")
            if not re.fullmatch(r"\d{2}", row.pref) or row.code[2:4] != row.pref:
                problems.append(f"{where} 都道府県番号「{v[2]}」")
            if row.setchi not in ("1", "2", "3") or row.code[4:5] != row.setchi:
                problems.append(f"{where} 設置区分「{v[3]}」")
            if row.honbun not in ("1", "2", "9"):
                problems.append(f"{where} 本分校「{v[4]}」")
            for lab, d in (("設定", row.set_date), ("廃止", row.abol)):
                if d and not DATE_RE.match(d):
                    problems.append(f"{where} {lab}年月日「{d}」")
            for x in row.nexts:
                if not CODE_RE.match(x):
                    problems.append(f"{where} 移行後の学校コード「{row.next_raw}」")
            if len(row.nexts) > 1:
                notes.append(f"{where} {row.code} 移行後の学校コードが{len(row.nexts)}つ「{row.next_raw}」")
            rows.append(row)
    if problems:
        raise SystemExit("文科省の一覧に読めない値があります（" + str(len(problems)) + "件）: " + "；".join(problems[:10]))
    return rows, notes


# ---------------------------------------------------------------------------
# 所在地 → 市区町村

def cities_from_address(addr: str, pref_name: str, cities: dict) -> set:
    """所在地 → 当たる市区町村コードの集合。都道府県名（pref_name）を外した文字列の先頭が、市区町村名（cities: {コード: 名前}）と
    一致するもの。郡名（「夕張郡」）は外した形でも比べる。政令市は、区の市区町村があれば区名まで一致したものだけ。
    ちょうど1つでなければ、呼ぶ側で「決まらない」とする。"""
    a = re.sub(r"\s+", "", unicodedata.normalize("NFKC", addr or ""))
    pn = unicodedata.normalize("NFKC", pref_name)
    if not a.startswith(pn):
        return set()
    a = a[len(pn):]
    cands = [a]
    # 郡名は「余市郡」「西村山郡」のように市・町・村の字を含むことがあるので、先頭7字までの「郡」のどれで切った形も比べる
    for i, ch in enumerate(a[1:8], start=1):
        if ch == "郡" and a[i + 1:]:
            cands.append(a[i + 1:])
    hits = set()
    for code, nm in cities.items():
        n = unicodedata.normalize("NFKC", nm)
        if n and any(c.startswith(n) for c in cands):
            hits.add(code)
    # 「○○市」と「○○市△△区」の両方に当たったら、長いほう（区）だけを残す
    if len(hits) > 1:
        names = {c: unicodedata.normalize("NFKC", cities[c]) for c in hits}
        hits = {c for c in hits if not any(o != c and names[o].startswith(names[c]) and len(names[o]) > len(names[c])
                                           for o in hits)}
    return hits


# ---------------------------------------------------------------------------
# アプリの学校

@dataclass
class AppSchool:
    pref: str
    pref_name: str
    city: str
    city_name: str
    id: str
    name: str
    approx: bool
    est2025: float
    code: str = ""          # もとの学校コード（決まらなければ空）
    code_how: str = ""      # id / rebuild / unknown
    unknown_why: str = ""


def read_app(data_dir) -> list[dict]:
    return [kana_mod.read_pref(p)[1] for p in kana_mod.pref_files(data_dir)]


def read_id_codes(dirpath) -> dict:
    """ids_XX.csv（tools/capture_school_codes.py）→ {(県, id): 行}"""
    out = {}
    files = sorted(pathlib.Path(dirpath).glob("ids_*.csv"))
    if not files:
        raise SystemExit(f"{dirpath} に ids_XX.csv がありません（tools/capture_school_codes.py で作る）")
    for p in files:
        with p.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                out[(r["pref"], r["id"])] = r
    return out


def app_schools(prefs: list[dict], id_codes: dict) -> list[AppSchool]:
    out = []
    for obj in prefs:
        for c in obj["cities"]:
            for s in c["schools"]:
                a = AppSchool(obj["code"], obj["name"], c["code"], c["name"], s["id"], s["name"], bool(s.get("approx")),
                              float(s["est"][0]))
                if CODE_RE.match(s["id"]):
                    a.code, a.code_how = s["id"], "id"
                else:
                    r = id_codes.get((obj["code"], s["id"]))
                    if r and r["name"] == s["name"] and r["city"] == c["code"] and CODE_RE.match(r["raw_code"]):
                        a.code, a.code_how = r["raw_code"], "rebuild"
                    else:
                        a.code_how = "unknown"
                        a.unknown_why = ("作り直しの表に無い" if not r else
                                         "作り直しの表と名前か市区町村が違う" if (r["name"] != s["name"] or r["city"] != c["code"])
                                         else f"もとの学校コードが学校コードの形でない（{r['raw_code'] or '空'}。{r['why']}）")
                out.append(a)
    return out


# ---------------------------------------------------------------------------
# 判定

@dataclass
class Result:
    gone: list = field(default_factory=list)          # [(AppSchool, MextRow, now dict|None, 外れた now の決まり)]
    closed_not_marked: list = field(default_factory=list)  # [(AppSchool, MextRow|None, [外れた決まり])]
    unreliable: dict = field(default_factory=dict)    # (県, id) → [理由]
    new_schools: list = field(default_factory=list)   # [(MextRow, 市区町村コード, [from の id])]
    new_rejected: Counter = field(default_factory=Counter)  # 新しい学校の決まりごとの外れ（公立の小・義務で設定日が後のもの）
    joined: dict = field(default_factory=dict)        # (県, id) → [{"id", "name"}]
    schools: list = field(default_factory=list)
    closed_classified: list = field(default_factory=list)  # 閉校に分類された（一覧の行が本分校 9 か廃止年月日あり）学校


def decide(prefs: list[dict], mext: list[MextRow], id_codes: dict, hamadori=HAMADORI_NOT_HANDLED) -> Result:
    res = Result()
    schools = app_schools(prefs, id_codes)
    res.schools = schools
    by_code = defaultdict(list)
    for r in mext:
        by_code[r.code].append(r)
    pref_names = {o["code"]: o["name"] for o in prefs}
    pref_cities = {o["code"]: {c["code"]: c["name"] for c in o["cities"]} for o in prefs}
    for o in prefs:  # 浜通りの7町村など、学校の無い市区町村も所在地の判定には入れる（その市区町村に決まるように）
        for m in o.get("missing", []):
            if m.get("name"):
                pref_cities[o["code"]].setdefault(m["code"], m["name"])

    city_cache: dict = {}

    def city_of(r: MextRow):
        """所在地から決めた市区町村コード（ちょうど1つのときだけ。決まらなければ None）"""
        if r.code not in city_cache:
            if r.pref not in pref_names:
                city_cache[r.code] = None
            else:
                hits = cities_from_address(r.addr, pref_names[r.pref], pref_cities[r.pref])
                city_cache[r.code] = next(iter(hits)) if len(hits) == 1 else None
        return city_cache[r.code]

    living_by_city_name = defaultdict(list)
    any_by_city_name = defaultdict(list)
    for r in mext:
        c = city_of(r)
        if c:
            any_by_city_name[(r.pref, c, norm_name(r.name))].append(r)
            if r.living:
                living_by_city_name[(r.pref, c, norm_name(r.name))].append(r)
    app_cities = {o["code"]: {c["code"] for c in o["cities"]} for o in prefs}

    # ---- 当てにならない学校（決まり7）
    for s in schools:
        why = []
        if s.code_how == "unknown":
            why.append("コード不明")
        if s.code_how == "rebuild":
            why.append("id が学校コードでなく、作り直しで取ったコード")
        rows = by_code.get(s.code, []) if s.code else []
        if len(rows) == 1:
            r = rows[0]
            if r.kind not in SCHOOL_KINDS:
                why.append(f"学校種のずれ（{r.kind}）")
            if norm_name(r.name) != norm_name(s.name):
                other = [x for x in any_by_city_name.get((s.pref, s.city, norm_name(s.name)), []) if x.code != r.code]
                if other:
                    why.append("コードの取り違えの候補（同じ市区町村にアプリの名前の行がある）")
        if why:
            res.unreliable[(s.pref, s.id)] = why

    # ---- gone
    app_by_code = defaultdict(list)
    for s in schools:
        if s.code:
            app_by_code[s.code].append(s)
    for s in schools:
        rows = by_code.get(s.code, []) if s.code else []
        classified = any(r.honbun == "9" or r.abol for r in rows)
        if classified:
            res.closed_classified.append(s)
        failed = []
        r = rows[0] if len(rows) == 1 else None
        if r is None:
            failed.append(1)
        else:
            if not (r.setchi == "2" and r.kind in SCHOOL_KINDS and r.honbun == "9" and r.abol):
                failed.append(2)
            if not (r.abol and r.abol >= CUTOFF):
                failed.append(3)
            if not (r.pref == s.pref and city_of(r) == s.city):
                failed.append(4)
            if norm_name(r.name) != norm_name(s.name):
                failed.append(5)
            if living_by_city_name.get((s.pref, s.city, norm_name(s.name))):
                failed.append(6)
        if (s.pref, s.id) in res.unreliable:
            failed.append(7)
        if s.city in hamadori:
            failed.append(8)
        if not failed:
            res.gone.append([s, r, None, []])
        elif classified:
            res.closed_not_marked.append((s, r, failed))

    # ---- now / joined
    for g in res.gone:
        s, r = g[0], g[1]
        nf = []
        if len(r.nexts) != 1:
            nf.append(1)
        t = None
        if not nf:
            ts = by_code.get(r.nexts[0], [])
            t = ts[0] if len(ts) == 1 else None
            if not (t and t.setchi == "2" and t.kind in SCHOOL_KINDS and t.honbun == "1" and not t.abol):
                nf.append(2)
            if not (t and t.pref == s.pref and city_of(t) == s.city):
                nf.append(3)
        g[3] = nf
        if nf:
            continue
        now = {"name": display_name(t.name), "code": t.code}
        cand = [a for a in app_by_code.get(t.code, []) if a.pref == s.pref and a.city == s.city
                and (a.pref, a.id) not in res.unreliable]
        if len(cand) == 1 and len(app_by_code.get(t.code, [])) == 1:
            now["id"] = cand[0].id
            res.joined.setdefault((s.pref, cand[0].id), []).append({"id": s.id, "name": s.name})
        g[2] = now

    # ---- newSchools
    from_by_code = defaultdict(list)
    for g in res.gone:
        if g[2]:
            from_by_code[g[2]["code"]].append(g[0].id)
    names_by_city = defaultdict(set)
    for s in schools:
        names_by_city[(s.pref, s.city)].add(norm_name(s.name))
    for r in mext:
        if not (r.setchi == "2" and r.kind in SCHOOL_KINDS):
            continue  # 公立の小学校・義務教育学校だけを見る（ほかは数えない）
        failed = []
        if not (r.honbun == "1" and not r.abol):
            failed.append(1)
        if not (r.set_date and r.set_date >= CUTOFF):
            failed.append(2)
        c = city_of(r)
        if not (c and c in app_cities.get(r.pref, set()) and c not in hamadori):
            failed.append(3)
        if app_by_code.get(r.code):
            failed.append(4)
        if c and norm_name(r.name) in names_by_city.get((r.pref, c), set()):
            failed.append(5)
        if failed:
            if 1 not in failed and 2 not in failed:
                for f in failed:
                    res.new_rejected[f] += 1
            continue
        res.new_schools.append((r, c, sorted(from_by_code.get(r.code, []))))
    return res


# ---------------------------------------------------------------------------
# make-closures

def make_closures(data_dir, mext_paths, id_codes_dir, town_path=None, closures_csv=CLOSURES_CSV, new_csv=NEW_CSV,
                  dict_reader=None, ward_table=None, combined_table=None, hamadori=None) -> tuple[Result, list[str]]:
    """決まりで表を作り、pipeline/terms の2つの CSV を書く。(判定の結果, 文科省の一覧の注意) を返す。"""
    from . import combined, wards
    combined_table = combined.load() if combined_table is None else combined_table
    if hamadori is None:
        hamadori = {c for m in combined_table.values() for c, r in m.items() if not r["show"]}
        if hamadori != HAMADORI_NOT_HANDLED:
            raise SystemExit(f"浜通りの扱わない町村が、表（fukushima_hamadori.csv）と closures.py で違います: {sorted(hamadori)}")
    prefs = read_app(data_dir)
    mext, notes = load_mext(mext_paths)
    res = decide(prefs, mext, read_id_codes(id_codes_dir), hamadori)

    rows = []
    for s, r, now, _nf in sorted(res.gone, key=lambda g: (g[0].pref, g[0].city, g[0].id)):
        rows.append([s.pref, s.city, s.id, s.name, s.code, r.name, r.honbun, r.abol, r.next_raw,
                     now["name"] if now else "", (now or {}).get("id", "")])
    _write_csv(closures_csv, CLOSURES_HEADER, rows)

    # 新しい学校の読み（学校名の読みの決まり。make-kana と同じ）
    readings = {}
    if res.new_schools:
        if town_path is None:
            raise SystemExit("新しい学校の読みを作るには町字データ（--town）が要ります")
        ward_table = wards.load() if ward_table is None else ward_table
        idx = kana_mod.read_towns(town_path)
        dict_reader = kana_mod.SudachiReader() if dict_reader is None else dict_reader
        cache = {}
        for r, c, _f in res.new_schools:
            if c not in cache:
                cache[c] = idx.lookup(kana_mod.town_codes(c, ward_table, combined_table))
            readings[r.code] = [k for k, _src in kana_mod.school_readings(display_name(r.name), cache[c], dict_reader)]
    rows = []
    for r, c, frm in sorted(res.new_schools, key=lambda x: (x[0].pref, x[1], x[0].code)):
        rows.append([r.pref, c, r.code, display_name(r.name), r.kind, r.set_date, ";".join(frm), ";".join(readings.get(r.code, []))])
    _write_csv(new_csv, NEW_HEADER, rows)
    return res, notes


def _write_csv(path, header, rows) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


# ---------------------------------------------------------------------------
# add-closures

def _read_table(path, header) -> list[dict]:
    p = pathlib.Path(path)
    if not p.exists():
        raise SystemExit(f"閉校の表がありません: {p}")
    with p.open(encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        if [h.strip() for h in (rd.fieldnames or [])] != header:
            raise SystemExit(f"{p} の見出しは {','.join(header)} にしてください（いま: {','.join(rd.fieldnames or [])}）")
        return [{k: (v or "").strip() for k, v in r.items()} for r in rd]


SCHOOL_KEYS = ("gone", "now", "joined")


def _read_manual(path) -> list[dict]:
    """手で確かめた閉校の表。出典か確かめた日が空、日付の形が違う行があれば止める。"""
    rows = _read_table(path, MANUAL_HEADER)
    for r in rows:
        if not re.fullmatch(r"\d{5}", r["市区町村コード"]) or not r["id"] or not r["学校名"]:
            raise SystemExit(f"{path}: 市区町村コード（5桁）・id・学校名は空にしない: {r}")
        if not r["出典"]:
            raise SystemExit(f"{path}: 出典が空の行があります: {r['市区町村コード']} {r['学校名']}")
        if not DATE_RE.match(r["確かめた日"]):
            raise SystemExit(f"{path}: 確かめた日は YYYY-MM-DD: {r['市区町村コード']} {r['学校名']}")
        if r["移行先の id"] and not r["移行先の名前"]:
            raise SystemExit(f"{path}: 移行先の id があるのに移行先の名前が空: {r['市区町村コード']} {r['学校名']}")
    return rows


def add_closures(data_dir, closures_csv=CLOSURES_CSV, new_csv=NEW_CSV, manual_csv=MANUAL_CSV) -> dict:
    """表から app/data に gone・now・joined・newSchools を足す（前に付けたものは一度外してから付け直す）。
    表の行の学校が見つからない・名前が違うときは付けず、数を返す。変わった県のファイルだけ書き直す。2回かけても同じ。
    手で確かめた閉校の表（manual_csv）の学校にも gone を付ける。その県のファイルがあるのに学校が無い・名前が違うときは止める。"""
    gone_rows = _read_table(closures_csv, CLOSURES_HEADER)
    new_rows = _read_table(new_csv, NEW_HEADER)
    st = Counter()
    gone_by = {(r["都道府県"], r["id"]): r for r in gone_rows}
    if len(gone_by) != len(gone_rows):
        raise SystemExit(f"{closures_csv}: 同じ学校が2行あります")
    for r in _read_manual(manual_csv):
        key = (r["市区町村コード"][:2], r["id"])
        if key in gone_by:
            raise SystemExit(f"{manual_csv}: 文科省の一覧で決めた閉校の表（{closures_csv}）と同じ学校です: {r['学校名']}")
        gone_by[key] = {"都道府県": key[0], "市区町村コード": r["市区町村コード"], "id": r["id"], "アプリの学校名": r["学校名"],
                        "now の名前": r["移行先の名前"], "now の id": r["移行先の id"], "_manual": True}
    new_by_pref = defaultdict(list)
    for r in new_rows:
        new_by_pref[r["都道府県"]].append(r)
    seen = set()
    for p in kana_mod.pref_files(data_dir):
        header, obj = kana_mod.read_pref(p)
        before = json.dumps(obj, ensure_ascii=False)
        pref = obj["code"]
        index = {}
        for c in obj["cities"]:
            for s in c["schools"]:
                for k in SCHOOL_KEYS:
                    s.pop(k, None)
                index[s["id"]] = (c, s)
        obj.pop("newSchools", None)
        joined = defaultdict(list)
        for (pc, sid), r in gone_by.items():
            if pc != pref:
                continue
            seen.add((pc, sid))
            hit = index.get(sid)
            if not hit or hit[0]["code"] != r["市区町村コード"] or hit[1]["name"] != r["アプリの学校名"]:
                if r.get("_manual"):
                    raise SystemExit(f"手で確かめた閉校の表の学校が app/data にありません（市区町村・id・学校名が合わない）: "
                                     f"{r['市区町村コード']} {sid} {r['アプリの学校名']}")
                st["gone_not_found"] += 1
                continue
            if r.get("_manual"):
                st["gone_manual"] += 1
            s = hit[1]
            s["gone"] = True
            st["gone"] += 1
            if r["now の名前"]:
                now = {"name": r["now の名前"]}
                tid = r["now の id"]
                if tid:
                    if tid in index and index[tid][0]["code"] == r["市区町村コード"] and not gone_by.get((pref, tid)):
                        now["id"] = tid
                        joined[tid].append({"id": sid, "name": s["name"]})
                    else:
                        st["now_id_not_found"] += 1
                s["now"] = now
                st["now"] += 1
                st["now_with_id"] += 1 if "id" in now else 0
        for tid, lst in joined.items():
            index[tid][1]["joined"] = sorted(lst, key=lambda x: x["id"])
            st["joined"] += 1
        city_codes = {c["code"] for c in obj["cities"]}
        ns = []
        for r in sorted(new_by_pref.get(pref, []), key=lambda r: (r["市区町村コード"], r["学校コード"])):
            if r["市区町村コード"] not in city_codes:
                st["new_city_not_found"] += 1
                continue
            frm = [x for x in r["from の id"].split(";") if x]
            bad = [x for x in frm if x not in index or not index[x][1].get("gone")]
            if bad:
                st["new_from_not_found"] += 1
                frm = [x for x in frm if x not in bad]
            item = {"muni": r["市区町村コード"], "name": r["学校名"]}
            ks = [x for x in r["読み"].split(";") if x]
            if ks:
                item["kana"] = ks
            item["from"] = frm
            ns.append(item)
        if ns:
            obj["newSchools"] = ns
            st["newSchools"] += len(ns)
        if json.dumps(obj, ensure_ascii=False) != before:
            kana_mod.write_pref(p, header, obj)
            st["files_written"] += 1
    st["gone_pref_not_found"] = sum(1 for k in gone_by if k not in seen)
    return dict(st)
