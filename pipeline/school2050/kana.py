"""学校名の読み（ひらがなで学校をさがすため）。決まりは docs/DATA_METHOD.md「学校名の読み」。

make-kana：app/data の学校名 ＋ アドレス・ベース・レジストリの町字データ ＋ 辞書（SudachiPy）
           → pipeline/terms/school_kana_auto.csv と docs/KANA.md
add-kana ：school_kana_auto.csv ＋ 手直しの表 school_kana.csv → app/data/pref_XX.js の各校に kana を足す
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict

from . import combined, wards

# ---------------------------------------------------------------------------
# 町字データの列名。ここ1か所にまとめる（実物で確かめたら、ここと docs/DATA_METHOD.md の表を直す）。
# 実物に無い列があれば、足りない列名を出して止まる（別の列で代わりに進めない）。
TOWN_COLUMNS = {
    "lg_code": "lg_code",          # 全国地方公共団体コード（6桁。先頭5桁が市区町村コード。政令市は区のコード）
    "city": "city",                # 市区町村名
    "ward": "ward",                # 政令市の区名
    "oaza": "oaza_cho",            # 大字・町名
    "oaza_kana": "oaza_cho_kana",  # 大字・町名の読み（カナ）
    "koaza": "koaza",              # 小字
    "koaza_kana": "koaza_kana",    # 小字の読み（カナ）
}
# ---------------------------------------------------------------------------

TERMS = pathlib.Path(__file__).resolve().parents[1] / "terms"
AUTO_CSV = TERMS / "school_kana_auto.csv"
MANUAL_CSV = TERMS / "school_kana.csv"
AUTO_HEADER = ["学校コード", "学校名", "読み", "元"]
MANUAL_HEADER = ["学校コード", "読み", "理由"]
SOURCES = ("town", "dict", "name")
MAX_READINGS = 2

# 種別（末尾。長いものから当てる）
TYPES = [
    ("義務教育学校", "ぎむきょういくがっこう"),
    ("小中一貫学校", "しょうちゅういっかんがっこう"),
    ("小中一貫校", "しょうちゅういっかんこう"),
    ("小中学校", "しょうちゅうがっこう"),
    ("小学校", "しょうがっこう"),
    ("学園", "がくえん"),
    ("学校", "がっこう"),
]
LEAD_TYPE = ("義務教育学校", "ぎむきょういくがっこう")
BRANCH_RE = re.compile(r"^(.+?)(小学校|小)(.*)分校$")
OWNER_RE = re.compile(r"^.{1,12}?(?:市|町|村|区|組合)立(?=.)")

# 方角と番号の表（町字の後に残った部分、または町字の前の語）
_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
_NUM_KANA = ["いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう", "じゅう"]
DIRS = {
    "中央": "ちゅうおう", "東部": "とうぶ", "西部": "せいぶ", "南部": "なんぶ", "北部": "ほくぶ", "中部": "ちゅうぶ",
    "東": "ひがし", "西": "にし", "南": "みなみ", "北": "きた", "中": "なか",
}
for _i, (_k, _r) in enumerate(zip(_NUM, _NUM_KANA)):
    DIRS["第" + _k] = "だい" + _r
    DIRS["第" + str(_i + 1)] = "だい" + _r
_DIR_KEYS = sorted(DIRS, key=len, reverse=True)

# 異体字（app/js/model.js の VARIANTS と同じ。町字と学校名を比べるときだけ寄せる。読みには影響しない）
VARIANTS = {
    "龍": "竜", "﨑": "崎", "嵜": "崎", "碕": "崎", "髙": "高", "邊": "辺", "邉": "辺", "齋": "斎", "齊": "斉",
    "澤": "沢", "濱": "浜", "廣": "広", "國": "国", "櫻": "桜", "瀨": "瀬", "曾": "曽", "德": "徳", "槇": "槙",
    "冨": "富", "嶋": "島", "嶌": "島", "舘": "館", "栁": "柳", "淵": "渕", "萬": "万", "會": "会", "惠": "恵",
    "眞": "真", "黑": "黒", "檜": "桧", "藪": "薮", "鷗": "鴎", "條": "条", "壽": "寿", "實": "実", "峯": "峰",
}
_KE_AFTER_KANJI = re.compile(r"([㐀-鿿豈-﫿々〆])[ケヶ]")
KANA_ONLY = re.compile(r"^[ぁ-ゖァ-ヺー]+$")
HIRA_ONLY = re.compile(r"^[ぁ-ゔー]+$")  # 「ゕ」「ゖ」が残る読みは捨てる
AUTO_KANA = re.compile(r"^[ぁ-ゖー]+$")  # add-kana が school_kana_auto.csv で受け付ける字（前の表との互換）
_CHOME = re.compile(r"^(.+?)[0-9一二三四五六七八九十〇]+丁目$")
# 町字データの読みは小さい字を大きく書く（「イツチヨウメ」「チヨウ」）ので、読みの末尾は小さい字を大きくしてから比べる
_SMALL = str.maketrans("ぁぃぅぇぉっゃゅょゎゕゖ", "あいうえおつやゆよわかけ")
_CHOME_KANA = re.compile(r"(?:いつ|いち|に|さん|よん|し|ご|ろく|ろつ|なな|しち|はち|はつ|きゆう|く|じゆう|じゆつ|じつ)+ちようめ$")
_TOWN_TAIL = (("町", ("ちょう", "まち")), ("村", ("むら", "そん")))


def big(s: str) -> str:
    """小さい平仮名を大きい字に（長さは変わらない）"""
    return s.translate(_SMALL)


def hira(s: str) -> str:
    """片仮名を平仮名に（ヴ・ヵ・ヶも）。「ー」はそのまま。"""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def fold(s: str) -> str:
    """町字と学校名を比べるためにそろえる（1文字 → 1文字なので、長さは変わらない）。"""
    s = _KE_AFTER_KANJI.sub(r"\1が", s).replace("ヶ", "が")
    return "".join(VARIANTS.get(c, c) for c in s)


def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


# ---------------------------------------------------------------------------
# 町字データ

def _csv_texts(path: pathlib.Path):
    """町字データのファイル（.csv か .zip。zip の中の zip もたどる）から (名前, テキストの行) を順に返す。"""
    def from_zip(zf: zipfile.ZipFile, label: str):
        names = sorted(zf.namelist())
        for n in names:
            low = n.lower()
            if low.endswith(".csv"):
                yield f"{label}:{n}", io.TextIOWrapper(zf.open(n), encoding="utf-8-sig", newline="")
            elif low.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(zf.read(n))) as inner:
                    yield from from_zip(inner, f"{label}:{n}")

    path = pathlib.Path(path)
    if not path.exists():
        raise SystemExit(f"町字データがありません: {path}")
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            yield from from_zip(zf, path.name)
    else:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            yield path.name, fh


def missing_columns(header: list[str]) -> list[str]:
    have = {h.strip() for h in header}
    return [c for c in TOWN_COLUMNS.values() if c not in have]


def _check_header(label: str, header: list[str] | None) -> None:
    if header is None:
        raise SystemExit(f"町字データ {label} が空です")
    lack = missing_columns(header)
    if lack:
        raise SystemExit(
            f"町字データ {label} に次の列がありません: {', '.join(lack)}\n"
            f"  実物の列: {', '.join(h.strip() for h in header)}\n"
            "  列名は pipeline/school2050/kana.py の TOWN_COLUMNS にまとめてあります。実物に合わせて直してください"
            "（別の列で代わりに進めません）。")


def check_columns(path) -> list[str]:
    """町字データのすべての CSV の見出しを確かめる。足りない列があれば止まる。確かめたファイル名を返す。"""
    seen = []
    for label, fh in _csv_texts(path):
        try:
            header = next(csv.reader(fh), None)
        except UnicodeDecodeError:
            raise SystemExit(f"町字データ {label} を UTF-8 で読めません（ほかの文字コードで代わりに読むことはしません）")
        _check_header(label, header)
        seen.append(label)
    if not seen:
        raise SystemExit(f"町字データ {path} に CSV がありません")
    return seen


def _variants(name: str, kana: str):
    """比べる名前と読み：そのまま、先頭の「大字」「字」を外したもの、末尾の丁目を外したもの、末尾の「町」「村」を外したもの。"""
    out = [(name, kana)]
    for head, khead in (("大字", "おおあざ"), ("字", "あざ")):
        if name.startswith(head) and len(name) > len(head):
            out.append((name[len(head):], kana[len(khead):] if kana.startswith(khead) else kana))
            break
    for n, k in list(out):
        m, mk = _CHOME.match(n), _CHOME_KANA.search(big(k))
        if m and mk:
            out.append((m.group(1), k[:mk.start()]))
    for n, k in list(out):  # 「日比津町」→ 日比津（読みの「チヨウ」「マチ」も外す）。外したあと2文字以上のときだけ
        for tail, ktails in _TOWN_TAIL:
            if n.endswith(tail) and len(n) - len(tail) >= 2:
                kt = next((t for t in ktails if big(k).endswith(big(t)) and len(k) > len(t)), None)
                if kt:
                    out.append((n[:-len(tail)], k[:-len(kt)]))
    return [(n, k) for n, k in out if n and k]


class TownIndex:
    """市区町村コード（5桁）→ {そろえた名前: Counter(読み)}"""

    def __init__(self):
        self.by_city: dict = defaultdict(lambda: defaultdict(Counter))
        self.rows = 0
        self.files: list[str] = []

    def add(self, lg_code: str, name: str, kana: str) -> None:
        code = (lg_code or "").strip()
        name, kana = norm(name), hira(norm(kana))
        if not (code[:5].isdigit() and len(code) >= 5 and name and kana and HIRA_ONLY.match(kana)):
            return
        for n, k in _variants(name, kana):
            self.by_city[code[:5]][fold(n)][k] += 1

    def lookup(self, codes) -> dict:
        """いくつかの市区町村の町字をまとめ、名前 → 読み（行の多いもの。同じなら五十音順で先）にする。"""
        merged: dict = defaultdict(Counter)
        for c in codes:
            for n, cnt in self.by_city.get(c, {}).items():
                merged[n].update(cnt)
        return {n: sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for n, cnt in merged.items()}


def read_towns(path) -> TownIndex:
    col = TOWN_COLUMNS
    idx = TownIndex()
    found = False
    for label, fh in _csv_texts(path):
        found = True
        try:
            rd = csv.DictReader(fh)
            _check_header(label, rd.fieldnames)
            for r in rd:
                idx.rows += 1
                idx.add(r[col["lg_code"]], r[col["oaza"]], r[col["oaza_kana"]])
                idx.add(r[col["lg_code"]], r[col["koaza"]], r[col["koaza_kana"]])
        except UnicodeDecodeError:
            raise SystemExit(f"町字データ {label} を UTF-8 で読めません（ほかの文字コードで代わりに読むことはしません）")
        idx.files.append(label)
    if not found:
        raise SystemExit(f"町字データ {path} に CSV がありません")
    return idx


def town_codes(city_code: str, ward_table: dict, combined_table: dict) -> list[str]:
    """アプリの市区町村コード → 町字を使う市区町村コード。政令市を市でまとめたところは全区、まとめた区域は全市町村。"""
    codes = [city_code]
    codes += sorted(w.code for w in ward_table.values() if w.city == city_code)
    codes += sorted(combined_table.get(city_code, {}))
    return codes


# ---------------------------------------------------------------------------
# 辞書（SudachiPy）

class SudachiReader:
    """語の並びを SudachiPy（SudachiDict full、分割 C）で読む。読みに漢字が残る語があれば None。"""

    def __init__(self):
        try:
            from sudachipy import Dictionary, SplitMode
        except ImportError:
            raise SystemExit("make-kana には SudachiPy と SudachiDict full が要ります: "
                             "python3 -m pip install -r pipeline/requirements-kana.txt")
        dic = Dictionary(dict="full")
        if hasattr(dic, "tokenizer"):
            tok = dic.tokenizer(mode=SplitMode.C)
            self._split = tok.tokenize
        else:  # 古い SudachiPy
            tok = dic.create()
            self._split = lambda t: tok.tokenize(t, SplitMode.C)

    def __call__(self, text: str) -> str | None:
        out = []
        for m in self._split(text):
            surf = m.surface()
            if KANA_ONLY.match(surf):
                out.append(hira(surf))
                continue
            # 辞書に無い語（未知語）は、読みがかなで付いたとき（「一」→ イチ などの数詞）だけ使う。漢字のままなら読めない
            r = hira(m.reading_form() or "")
            if not HIRA_ONLY.match(r):
                return None
            out.append(r)
        r = "".join(out)
        return r if r and HIRA_ONLY.match(r) else None


# ---------------------------------------------------------------------------
# 学校名 → 読み

def parse_name(name: str) -> list[tuple]:
    """学校名を [("read", 語) | ("fixed", 読み)] に分ける。"""
    s = norm(name)
    s = OWNER_RE.sub("", s, count=1)  # 先頭の設置者（「姫路市立」など）
    head = []
    if s.startswith(LEAD_TYPE[0]) and len(s) > len(LEAD_TYPE[0]):
        head, s = [("fixed", LEAD_TYPE[1])], s[len(LEAD_TYPE[0]):]
    m = BRANCH_RE.match(s)
    if m:
        out = head + [("read", m.group(1)), ("fixed", "しょうがっこう")]
        if m.group(3):
            out.append(("read", m.group(3)))
        return out + [("fixed", "ぶんこう")]
    for t, r in TYPES:
        if s.endswith(t) and len(s) > len(t):
            return head + [("read", s[:-len(t)]), ("fixed", r)]
    return head + [("read", s)]


def read_table(s: str) -> str | None:
    """方角と番号の表だけで、全部読めれば読みを返す。"""
    out, i = [], 0
    while i < len(s):
        for k in _DIR_KEYS:
            if s.startswith(k, i):
                out.append(DIRS[k])
                i += len(k)
                break
        else:
            return None
    return "".join(out)


def _longest(s: str, towns: dict):
    f = fold(s)
    for n in range(len(f), 0, -1):
        if f[:n] in towns:
            return n, towns[f[:n]]
    return None


# 辞書で読むときに「が」に置き換える字：「ヶ」は前の字を問わず、「ケ」は前が漢字か平仮名で後ろが漢字のとき（草ヶ江、つつじケ丘、りんどうヶ丘）
_KE_FOR_DICT = re.compile(r"ヶ|(?<=[㐀-鿿豈-﫿々〆ぁ-ゖ])ケ(?=[㐀-鿿豈-﫿々〆])")


def _read_oka(text: str, dict_reader) -> list[str]:
    """辞書で読む。語末の「丘」が「おか」以外に読まれたら、「丘」の前までを読み「がおか」と「おか」の両方に（前が「が」「の」なら「おか」だけ）。"""
    r = dict_reader(text)
    if r and len(text) >= 2 and text.endswith("丘") and not r.endswith("おか"):
        head = dict_reader(text[:-1])
        if not head:
            return []
        return [head + "おか"] if head.endswith(("が", "の")) else [head + "がおか", head + "おか"]
    return [r] if r else []


def dict_reads(text: str, dict_reader) -> list[str]:
    """辞書の読みの候補（同じ読みは1つに）。学校名のままの読みと、「ヶ」「ケ」を「が」に置き換えた読みの両方を候補にする。
    並べ方：そのままの1つ目、置き換えの1つ目、そのままの2つ目、置き換えの2つ目。「ゕ」「ゖ」など平仮名と「ー」以外が残る読みは捨てる。"""
    if not dict_reader or not text:
        return []
    asis = _read_oka(text, dict_reader)
    sub = _KE_FOR_DICT.sub("が", text)
    repl = _read_oka(sub, dict_reader) if sub != text else []
    out = []
    for i in range(2):
        for c in (asis, repl):
            if len(c) > i and HIRA_ONLY.match(c[i]) and c[i] not in out:
                out.append(c[i])
    return out


def dict_read(text: str, dict_reader) -> str | None:
    """辞書の読みの1つ目（町字の後に残った部分を読むとき）。"""
    c = dict_reads(text, dict_reader)
    return c[0] if c else None


def read_town(seg: str, towns: dict, dict_reader) -> str | None:
    """語の頭から町字で読む。残りは方角と番号の表か辞書で。町字が当たらなければ None。"""
    def rest(r):
        if not r:
            return ""
        return read_table(r) or dict_read(r, dict_reader)

    hit = _longest(seg, towns)
    if hit:
        r = rest(seg[hit[0]:])
        return hit[1] + r if r is not None else None
    for k in _DIR_KEYS:  # 頭が方角・番号の語なら、その後ろから町字を探す（「東竜王」）
        if seg.startswith(k) and len(seg) > len(k):
            hit = _longest(seg[len(k):], towns)
            if hit:
                r = rest(seg[len(k) + hit[0]:])
                return DIRS[k] + hit[1] + r if r is not None else None
    return None


def school_readings(name: str, towns: dict, dict_reader) -> list[tuple[str, str]]:
    """学校名 → [(読み, 元)]（0〜2個。町字が先）。元は town / dict / name。"""
    parts = parse_name(name)
    segs = []  # (町字の読み, 辞書の読み, 名前のかなか)
    for p in parts:
        if p[0] != "read":
            continue
        t = p[1]
        if KANA_ONLY.match(t):
            h = hira(t)
            segs.append((h, [h], True))
        else:
            segs.append((read_town(t, towns, dict_reader), dict_reads(t, dict_reader), False))
    if not segs:
        return []

    def join(pick):
        out, j = [], 0
        for p in parts:
            if p[0] == "fixed":
                out.append(p[1])
            else:
                r = pick(segs[j])
                j += 1
                if r is None:
                    return None
                out.append(r)
        r = "".join(out)
        return r if HIRA_ONLY.match(r) else None

    if all(s[2] for s in segs):
        r = join(lambda s: s[0])
        return [(r, "name")] if r else []
    def nth(s, i):  # 辞書の読みの i 番目の候補（候補が1つしかなければその1つ。無ければ None）
        return s[1][min(i, len(s[1]) - 1)] if s[1] else None

    res = []
    if any(s[0] is not None and not s[2] for s in segs):
        t = join(lambda s: s[0] if s[0] is not None else nth(s, 0))
        if t:
            res.append((t, "town"))
    for i in range(MAX_READINGS):
        d = join(lambda s: nth(s, i))
        if d and all(d != r for r, _ in res):
            res.append((d, "dict"))
    return res[:MAX_READINGS]


# ---------------------------------------------------------------------------
# app/data の読み書き

PREF_RE = re.compile(r"^pref_(\d{2})\.js$")


def pref_files(data_dir) -> list[pathlib.Path]:
    return sorted(p for p in pathlib.Path(data_dir).iterdir() if PREF_RE.match(p.name))


def read_pref(path) -> tuple[str, dict]:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.match(r"^(.*?\n)UG\.registerPref\((\{.*\})\);\n?$", text, re.S)
    if not m:
        raise SystemExit(f"{path} の形が想定と違います（UG.registerPref({{…}}); ）")
    return m.group(1), json.loads(m.group(2))


def write_pref(path, header: str, obj: dict) -> None:
    pathlib.Path(path).write_text(
        header + "UG.registerPref(" + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + ");\n", encoding="utf-8")


def iter_schools(data_dir):
    """(県コード, 市区町村, 学校) を順に"""
    for p in pref_files(data_dir):
        _, obj = read_pref(p)
        for c in obj["cities"]:
            for s in c["schools"]:
                yield obj["code"], c, s


# ---------------------------------------------------------------------------
# make-kana

def make_kana(data_dir, town_path, out_csv=AUTO_CSV, doc_path=None, dict_reader=None,
              ward_table=None, combined_table=None, town_label=None, manual_csv=MANUAL_CSV) -> dict:
    """読みを作り、school_kana_auto.csv（と KANA.md）を書く。集計を返す。
    KANA.md には、手直しの表（school_kana.csv）で読みを決めた学校も書く（自動の読みはそのまま。add-kana が表の読みに置き換える）。"""
    ward_table = wards.load() if ward_table is None else ward_table
    combined_table = combined.load() if combined_table is None else combined_table
    idx = read_towns(town_path)
    if dict_reader is None:
        dict_reader = SudachiReader()
    rows, stats = [], Counter()
    differ, none = [], []
    manual: dict = {}  # 学校コード → ([読み], 理由)
    if manual_csv and pathlib.Path(manual_csv).exists():
        for r in _read_table(manual_csv, MANUAL_HEADER):
            if r["学校コード"]:
                ks, why = manual.setdefault(r["学校コード"], ([], r.get("理由", "")))
                if r["読み"] and r["読み"] not in ks:
                    ks.append(r["読み"])
    manual_rows = []
    cache: dict = {}
    for pref, city, s in iter_schools(data_dir):
        code = city["code"]
        if code not in cache:
            cache[code] = idx.lookup(town_codes(code, ward_table, combined_table))
        rs = school_readings(s["name"], cache[code], dict_reader)
        stats["schools"] += 1
        if s["id"] in manual:
            ks, why = manual[s["id"]]
            manual_rows.append((pref, city["name"], s["id"], s["name"], "・".join(r for r, _ in rs), "・".join(ks), why))
        if not rs:
            stats["none"] += 1
            none.append((pref, city["name"], s["id"], s["name"]))
        else:
            stats[rs[0][1]] += 1
            if len(rs) == 2:
                stats["two"] += 1
                differ.append((pref, city["name"], s["id"], s["name"], rs[0][0], rs[1][0]))
        for r, src in rs:
            rows.append([s["id"], s["name"], r, src])
    out = pathlib.Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(AUTO_HEADER)
        w.writerows(rows)
    res = {"schools": stats["schools"], "town": stats["town"], "dict": stats["dict"], "name": stats["name"],
           "none": stats["none"], "two_readings": stats["two"], "town_rows": idx.rows,
           "town_files": idx.files, "differ": differ, "unreadable": none, "manual": manual_rows}
    if doc_path:
        write_kana_doc(doc_path, res, town_label or pathlib.Path(town_path).name)
    res.pop("manual")
    return res


def write_kana_doc(path, res: dict, town_label: str) -> None:
    from .export import PREF_NAMES
    L = ["# 学校名の読み（make-kana の結果）", "",
         "`python3 pipeline/build_school_data.py make-kana` が書く。手で編集しないこと。決まりは "
         "[DATA_METHOD.md](DATA_METHOD.md)「学校名の読み」。手直しは `pipeline/terms/school_kana.csv`。", "",
         f"- 町字データ：`{town_label}`（{res['town_rows']:,}行）", "",
         "## 読みの元ごとの校数", "",
         "| 元 | 校数 |", "|---|---:|",
         f"| 町字（town。辞書と違えば辞書の読みも残す） | {res['town']:,} |",
         f"| 辞書だけ（dict） | {res['dict']:,} |",
         f"| 名前のかな（name） | {res['name']:,} |",
         f"| 読みが作れなかった | {res['none']:,} |",
         f"| 計 | {res['schools']:,} |", "",
         f"町字と辞書で読みが違い、2つ残した学校：{res['two_readings']:,}校", "",
         "## 町字と辞書で読みが違った学校", "",
         "手で決めた読みは、手直しの表（`pipeline/terms/school_kana.csv`）の読み。`add-kana` は自動の読みの代わりにこれを使う。", "",
         "| 都道府県 | 市区町村 | 学校コード | 学校名 | 町字の読み | 辞書の読み | 手で決めた読み |", "|---|---|---|---|---|---|---|"]
    man = {m[2]: m[5] for m in res.get("manual", [])}
    L += [f"| {PREF_NAMES.get(p, p)} | {c} | {i} | {n} | {a} | {b} | {man.get(i, '')} |" for p, c, i, n, a, b in res["differ"]]
    L += ["", "## 読みが作れなかった学校", "",
          "| 都道府県 | 市区町村 | 学校コード | 学校名 | 手で決めた読み |", "|---|---|---|---|---|"]
    L += [f"| {PREF_NAMES.get(p, p)} | {c} | {i} | {n} | {man.get(i, '')} |" for p, c, i, n in res["unreadable"]]
    L += ["", "## 手で決めた読み（school_kana.csv）", "",
          f"手直しの表で読みを決めた学校：{len(res.get('manual', [])):,}校（アプリにある学校だけ）。自動の読みは make-kana が作ったもの。", "",
          "| 都道府県 | 市区町村 | 学校コード | 学校名 | 自動の読み | 手で決めた読み | 理由 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {PREF_NAMES.get(p, p)} | {c} | {i} | {n} | {a or '（なし）'} | {k} | {w} |"
          for p, c, i, n, a, k, w in sorted(res.get("manual", []))]
    pathlib.Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# add-kana

def _read_table(path, header: list[str]) -> list[dict]:
    p = pathlib.Path(path)
    if not p.exists():
        raise SystemExit(f"読みの表がありません: {p}")
    with p.open(encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        if [h.strip() for h in (rd.fieldnames or [])][:len(header)] != header:
            raise SystemExit(f"{p} の見出しは {','.join(header)} にしてください（いま: {','.join(rd.fieldnames or [])}）")
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in rd]


def load_readings(auto_csv=AUTO_CSV, manual_csv=MANUAL_CSV) -> tuple[dict, dict]:
    """(自動 {学校コード: (学校名, [読み])}, 手直し {学校コード: [読み]})"""
    auto: dict = {}
    for r in _read_table(auto_csv, AUTO_HEADER):
        # 前の make-kana が作った表には「ゕ」「ゖ」の残る読みがある（くさゖこう など）。add-kana ではそのまま受け付けて数だけ出し、
        # make-kana をかけ直したときに消える（いまの make-kana は作らない）
        if r["元"] not in SOURCES or not AUTO_KANA.match(r["読み"]):
            raise SystemExit(f"{auto_csv}: 読みは平仮名と「ー」、元は {'/'.join(SOURCES)}: {r}")
        name, ks = auto.setdefault(r["学校コード"], (r["学校名"], []))
        if name != r["学校名"]:
            raise SystemExit(f"{auto_csv}: 同じ学校コードに違う学校名があります: {r['学校コード']}")
        if r["読み"] not in ks:
            ks.append(r["読み"])
    manual: dict = {}
    for r in _read_table(manual_csv, MANUAL_HEADER):
        if not r["学校コード"]:
            continue
        if r["読み"] and not HIRA_ONLY.match(r["読み"]):
            raise SystemExit(f"{manual_csv}: 読みは平仮名と「ー」で書いてください: {r}")
        ks = manual.setdefault(r["学校コード"], [])
        if r["読み"] and r["読み"] not in ks:
            ks.append(r["読み"])
    for sid, ks in list(auto.items()) + [(k, (None, v)) for k, v in manual.items()]:
        if len(ks[1]) > MAX_READINGS:
            raise SystemExit(f"読みは1校に{MAX_READINGS}つまで: {sid}")
    return auto, manual


def _with_kana(s: dict, kana: list[str] | None) -> dict:
    """kana を name の後に置く（無ければ消す）。ほかの項目と並びは変えない。"""
    out = {}
    for k, v in s.items():
        if k == "kana":
            continue
        out[k] = v
        if k == "name" and kana:
            out["kana"] = list(kana)
    return out


def add_kana(data_dir, auto_csv=AUTO_CSV, manual_csv=MANUAL_CSV) -> dict:
    """app/data の各校に kana を足す。変わった県のファイルだけ書き直す。集計を返す。"""
    auto, manual = load_readings(auto_csv, manual_csv)
    st = Counter()
    seen = set()
    with_kana_prefs = set()
    for p in pref_files(data_dir):
        header, obj = read_pref(p)
        changed = False
        for c in obj["cities"]:
            for i, s in enumerate(c["schools"]):
                seen.add(s["id"])
                kana = None
                if s["id"] in manual:
                    kana, how = manual[s["id"]], "manual"
                elif s["id"] in auto:
                    name, ks = auto[s["id"]]
                    if name == s["name"]:
                        kana, how = ks, "auto"
                    else:
                        st["name_mismatch"] += 1
                if kana:
                    st[how] += 1
                    with_kana_prefs.add(obj["code"])
                new = _with_kana(s, kana)
                if new != s or list(new) != list(s):
                    c["schools"][i] = new
                    changed = True
        if changed:
            write_pref(p, header, obj)
            st["files_written"] += 1
    st["auto_not_found"] = sum(1 for k in auto if k not in seen)
    st["manual_not_found"] = sum(1 for k in manual if k not in seen)
    if _update_index_flags(data_dir, with_kana_prefs):
        st["index_written"] = 1
    st["schools_with_kana"] = st["auto"] + st["manual"]
    st["auto_small_ka_ke"] = sum(1 for k, (_, ks) in auto.items() if k not in manual and any(not HIRA_ONLY.match(x) for x in ks))
    return dict(st)


def _update_index_flags(data_dir, prefs: set) -> bool:
    """data/index.js の各県に kana: true（読みのある県だけ）。変わったときだけ書く。"""
    p = pathlib.Path(data_dir) / "index.js"
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8")
    m = re.match(r"^(.*?\n)UG\.registerIndex\((\[.*\])\);\n?$", text, re.S)
    if not m:
        raise SystemExit(f"{p} の形が想定と違います")
    entries = json.loads(m.group(2))
    changed = False
    for e in entries:
        want = e.get("code") in prefs
        if want and e.get("kana") is not True:
            e["kana"] = True
            changed = True
        elif not want and "kana" in e:
            del e["kana"]
            changed = True
    if changed:
        p.write_text(m.group(1) + "UG.registerIndex(" + json.dumps(entries, ensure_ascii=False, indent=1) + ");\n",
                     encoding="utf-8")
    return changed
