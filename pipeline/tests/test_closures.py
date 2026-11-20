"""学区データより後に閉校した学校（make-closures / add-closures）の検算。架空の県（98 ためし県）と、合成の文科省の一覧で確かめる。

決まり（docs/DATA_METHOD.md「学区データより後に閉校した学校」）は、すべて満たすときだけ印を付ける。
ここでは、全部を満たす基本の形から、決まりを1つだけ外すと印が付かないことを、決まりごとに確かめる。

    python3 -m pytest pipeline/tests -q
"""
import csv
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from school2050 import closures as cl  # noqa: E402
from school2050 import kana  # noqa: E402

TITLE = ["文部科学省　学校コード一覧", "", "", "", "", "", "", "", "", "", "更新日：", "2026/5/20"]
HEAD = ["学校コード", "学校種", "都道府県番号", "設置\r\n区分", "本分校", "学校名", "学校所在地", "郵便番号",
        "属性情報\r\n設定年月日", "属性情報\r\n廃止年月日", "旧学校\r\n調査番号", "移行後の学校コード"]
KIND = {"B1": "B1(小学校)", "C2": "C2(義務)", "C1": "C1(中学校)"}
HONBUN = {"1": "1(本)", "2": "2(分)", "9": "9(廃)"}

GONE = "B198220100010"     # 閉校した学校（アプリにある）
TARGET = "B198220100029"   # 移行先（アプリにある）
NEWC = "C298220100015"     # 新しい義務教育学校（アプリに無い）
GONE2 = "B198220100038"    # 新しい学校へ移った閉校の学校（アプリにある）


def row(code, name, addr="ためし県みほん市本町1", honbun="1", set_date="2020-12-22", abol="", nxt=""):
    kind = code[:2]
    return [code, KIND[kind], "98(ためし)", {"1": "1(国)", "2": "2(公)", "3": "3(私)"}[code[4]], HONBUN[honbun], name, addr,
            "9990000", set_date, abol, "989999", nxt]


def base_rows():
    return [
        row(GONE, "みほん市立ためし小学校", honbun="9", abol="2024-05-01", nxt=TARGET),
        row(TARGET, "みほん市立なかよし小学校"),
        row(GONE2, "みほん市立きた小学校", honbun="9", abol="2025-05-01", nxt=NEWC),
        row(NEWC, "みほん市立みほん学園", set_date="2025-05-01"),
    ]


def school(sid, name, est=30.0):
    return {"id": sid, "name": name, "lng": 130.0, "lat": 33.0, "est": [est] * 10, "ages": [est / 6] * 12,
            "geom": [[[130.0, 33.0], [130.1, 33.0], [130.1, 33.1], [130.0, 33.0]]]}


def base_pref():
    return {"code": "98", "name": "ためし県", "generated": "2026-11-17", "source": {},
            "cities": [{"code": "98201", "name": "みほん市", "schools": [
                school(GONE, "ためし小学校"), school(TARGET, "なかよし小学校", 200.0), school(GONE2, "きた小学校")]},
                {"code": "98202", "name": "べつ市", "schools": [school("B198220200019", "べつ小学校")]}],
            "missing": [{"code": "98301", "name": "よそ町"}]}


def write_mext(tmp_path, rows):
    p = tmp_path / "mext.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(TITLE)
        w.writerow(HEAD)
        w.writerows(rows)
    return p


def run(tmp_path, rows=None, prefs=None, id_codes=None, hamadori=frozenset()):
    rows = base_rows() if rows is None else rows
    mext, _notes = cl.load_mext([write_mext(tmp_path, rows)])
    return cl.decide(prefs or [base_pref()], mext, id_codes or {}, set(hamadori))


def gone_ids(res):
    return {g[0].id for g in res.gone}


def failed_of(res, sid):
    return next(f for s, _r, f in res.closed_not_marked if s.id == sid)


def set_row(rows, code, **kw):
    for i, r in enumerate(rows):
        if r[0] == code:
            new = row(code, r[5], addr=r[6], honbun=r[4][0], set_date=r[8], abol=r[9], nxt=r[11])
            for k, v in kw.items():
                new[{"name": 5, "addr": 6, "honbun": 4, "set_date": 8, "abol": 9, "nxt": 11}[k]] = v
            rows[i] = new
    return rows


# ---------------------------------------------------------------------------
# 基本の形：全部の決まりを満たす

def test_base_all_marked(tmp_path):
    res = run(tmp_path)
    assert gone_ids(res) == {GONE, GONE2}
    g = {x[0].id: x for x in res.gone}
    assert g[GONE][2] == {"name": "なかよし小学校", "code": TARGET, "id": TARGET}
    assert res.joined == {("98", TARGET): [{"id": GONE, "name": "ためし小学校"}]}
    assert g[GONE2][2] == {"name": "みほん学園", "code": NEWC}  # アプリに無いので id なし
    assert [(r.code, c, f) for r, c, f in res.new_schools] == [(NEWC, "98201", [GONE2])]


# ---------------------------------------------------------------------------
# gone の決まり 1〜8：1つだけ外すと付かない

def test_gone_rule1_no_row(tmp_path):
    rows = [r for r in base_rows() if r[0] != GONE]
    res = run(tmp_path, rows)
    assert GONE not in gone_ids(res)


def test_gone_rule1_two_rows(tmp_path):
    rows = base_rows() + [row(GONE, "みほん市立ためし小学校", honbun="9", abol="2024-05-01", nxt=TARGET)]
    res = run(tmp_path, rows)
    assert GONE not in gone_ids(res)
    assert failed_of(res, GONE) == [1]


@pytest.mark.parametrize("kw", [{"abol": ""}, {"honbun": "1(本)"}])
def test_gone_rule2_needs_both_honbun9_and_date(tmp_path, kw):
    res = run(tmp_path, set_row(base_rows(), GONE, **kw))
    assert GONE not in gone_ids(res)
    f = failed_of(res, GONE)
    assert 2 in f and set(f) <= {2, 3}  # 廃止年月日が空なら 3 も外れる


def test_gone_rule2_private(tmp_path):
    code = "B198320100013"  # 私立
    pref = base_pref()
    pref["cities"][0]["schools"].append(school(code, "わたくし小学校"))
    rows = base_rows() + [row(code, "わたくし小学校", honbun="9", abol="2024-05-01")]
    res = run(tmp_path, rows, [pref])
    assert code not in gone_ids(res) and failed_of(res, code) == [2]


def test_gone_rule3_before_cutoff(tmp_path):
    res = run(tmp_path, set_row(base_rows(), GONE, abol="2023-03-31"))
    assert failed_of(res, GONE) == [3]
    res = run(tmp_path, set_row(base_rows(), GONE, abol="2023-04-01"))
    assert GONE in gone_ids(res)


@pytest.mark.parametrize("addr", ["ためし県べつ市本町1", "ほか県みほん市本町1", "みほん市本町1", "ためし県みほん町1"])
def test_gone_rule4_city(tmp_path, addr):
    res = run(tmp_path, set_row(base_rows(), GONE, addr=addr))
    assert failed_of(res, GONE) == [4]


def test_gone_rule4_gun_is_skipped(tmp_path):
    pref = base_pref()
    pref["cities"].append({"code": "98303", "name": "おか町", "schools": [school("B198230300011", "おか小学校")]})
    rows = base_rows() + [row("B198230300011", "ためし郡おか町立おか小学校", addr="ためし県ためし郡おか町1", honbun="9",
                              abol="2024-05-01")]
    res = run(tmp_path, rows, [pref])
    assert "B198230300011" in gone_ids(res)


@pytest.mark.parametrize("name", ["みほん市立ためし東小学校", "みほん市立ためし小", "福井市ためし小学校", "みほん学校組合立ためし小学校"])
def test_gone_rule5_name(tmp_path, name):
    res = run(tmp_path, set_row(base_rows(), GONE, name=name))
    assert failed_of(res, GONE) == [5]


def test_gone_rule5_table(tmp_path):
    # そろえ方の表（ヶ＝ケ）と NFKC・空白は同じとみなす
    pref = base_pref()
    pref["cities"][0]["schools"][0]["name"] = "ため ヶ小学校"
    res = run(tmp_path, set_row(base_rows(), GONE, name="みほん市立ためケ小学校"), [pref])
    assert GONE in gone_ids(res)


def test_gone_rule6_living_same_name(tmp_path):
    rows = base_rows() + [row("B198220100047", "みほん市立ためし小学校")]  # コードだけ変わって続いている
    res = run(tmp_path, rows)
    assert failed_of(res, GONE) == [6]


def test_gone_rule7_rebuilt_code(tmp_path):
    pref = base_pref()
    pref["cities"][0]["schools"][0]["id"] = "98201-0001"
    ids = {("98", "98201-0001"): {"pref": "98", "id": "98201-0001", "city": "98201", "name": "ためし小学校",
                                  "raw_code": GONE, "why": "県内で学校コードが重なる"}}
    res = run(tmp_path, prefs=[pref], id_codes=ids)
    assert failed_of(res, "98201-0001") == [7]


def test_gone_rule7_unknown_code(tmp_path):
    pref = base_pref()
    pref["cities"][0]["schools"][0]["id"] = "98201-0001"
    res = run(tmp_path, prefs=[pref])
    assert "98201-0001" not in gone_ids(res)
    assert res.unreliable[("98", "98201-0001")] == ["コード不明"]


def test_gone_rule7_swap_candidate(tmp_path):
    # アプリの「ためし小学校」に「みなみ小学校」のコード。同じ市にアプリの名前の行がある（コードの取り違えの候補）
    pref = base_pref()
    pref["cities"][0]["schools"][1]["name"] = "みなみ小学校"   # TARGET のコードの学校の名前を変える
    res = run(tmp_path, base_rows() + [row("B198220100056", "みほん市立みなみ小学校")], [pref])
    assert ("98", TARGET) in res.unreliable


def test_gone_rule8_hamadori(tmp_path):
    res = run(tmp_path, hamadori={"98201"})
    assert failed_of(res, GONE) == [8]


# ---------------------------------------------------------------------------
# now の決まり 1〜3

def test_now_rule1_two_codes(tmp_path):
    res = run(tmp_path, set_row(base_rows(), GONE, nxt=TARGET + "、" + NEWC))
    g = {x[0].id: x for x in res.gone}
    assert GONE in g and g[GONE][2] is None and g[GONE][3] == [1]
    assert res.joined == {}


@pytest.mark.parametrize("kw", [{"honbun": "2(分)"}, {"honbun": "9(廃)", "abol": "2026-05-01"}])
def test_now_rule2_target_living(tmp_path, kw):
    res = run(tmp_path, set_row(base_rows(), TARGET, **kw))
    g = {x[0].id: x for x in res.gone}
    assert g[GONE][2] is None and 2 in g[GONE][3]


def test_now_rule3_target_city(tmp_path):
    res = run(tmp_path, set_row(base_rows(), TARGET, addr="ためし県べつ市本町2"))
    g = {x[0].id: x for x in res.gone}
    assert g[GONE][2] is None and g[GONE][3] == [3]


# ---------------------------------------------------------------------------
# 新しい学校の決まり 1〜5

def new_codes(res):
    return {r.code for r, _c, _f in res.new_schools}


@pytest.mark.parametrize("kw", [{"honbun": "2(分)"}, {"abol": "2026-05-01"}])
def test_new_rule1(tmp_path, kw):
    assert NEWC not in new_codes(run(tmp_path, set_row(base_rows(), NEWC, **kw)))


def test_new_rule2_set_date(tmp_path):
    assert NEWC not in new_codes(run(tmp_path, set_row(base_rows(), NEWC, set_date="2023-03-31")))
    assert NEWC in new_codes(run(tmp_path, set_row(base_rows(), NEWC, set_date="2023-04-01")))


@pytest.mark.parametrize("addr", ["ためし県よそ町1", "ためし県どこか村1", "ためし県1"])
def test_new_rule3_city(tmp_path, addr):
    res = run(tmp_path, set_row(base_rows(), NEWC, addr=addr))
    assert NEWC not in new_codes(res)
    assert res.new_rejected[3] == 1


def test_new_rule3_hamadori(tmp_path):
    assert NEWC not in new_codes(run(tmp_path, hamadori={"98201"}))


def test_new_rule4_code_in_app(tmp_path):
    pref = base_pref()
    pref["cities"][1]["schools"].append(school(NEWC, "べつ学園"))
    assert NEWC not in new_codes(run(tmp_path, prefs=[pref]))


def test_new_rule5_same_name_in_app(tmp_path):
    pref = base_pref()
    pref["cities"][0]["schools"].append(school("98201-0009", "みほん学園"))
    assert NEWC not in new_codes(run(tmp_path, prefs=[pref]))


# ---------------------------------------------------------------------------
# 読み取りと所在地

def test_load_mext_rejects_bad_value(tmp_path):
    rows = base_rows()
    rows[0][4] = "x(廃)"
    with pytest.raises(SystemExit):
        cl.load_mext([write_mext(tmp_path, rows)])


def test_load_mext_two_next_codes_noted(tmp_path):
    rows = set_row(base_rows(), GONE, nxt=TARGET + "､" + NEWC)
    mext, notes = cl.load_mext([write_mext(tmp_path, rows)])
    assert next(r for r in mext if r.code == GONE).nexts == [TARGET, NEWC]
    assert len(notes) == 1


def test_cities_from_address_gun_with_city_char():
    cities = {"98401": "あかい村", "98402": "いち町"}
    assert cl.cities_from_address("ためし県よい市郡あかい村1", "ためし県", cities) == {"98401"}
    assert cl.cities_from_address("ためし県西むら山郡いち町1", "ためし県", cities) == {"98402"}


def test_cities_from_address_ward():
    cities = {"98100": "みほん市", "98101": "みほん市東区"}
    assert cl.cities_from_address("ためし県みほん市東区1", "ためし県", cities) == {"98101"}
    assert cl.cities_from_address("ためし県みほん市西区1", "ためし県", cities) == {"98100"}


# ---------------------------------------------------------------------------
# add-closures

def write_tables(tmp_path, res):
    cpath, npath = tmp_path / "school_closures.csv", tmp_path / "new_schools.csv"
    rows = [[g[0].pref, g[0].city, g[0].id, g[0].name, g[0].code, g[1].name, g[1].honbun, g[1].abol, g[1].next_raw,
             (g[2] or {}).get("name", ""), (g[2] or {}).get("id", "")] for g in res.gone]
    cl._write_csv(cpath, cl.CLOSURES_HEADER, rows)
    cl._write_csv(npath, cl.NEW_HEADER, [[r.pref, c, r.code, cl.display_name(r.name), r.kind, r.set_date, ";".join(f),
                                          "みほんがくえん"] for r, c, f in res.new_schools])
    return cpath, npath


def test_add_closures(tmp_path):
    res = run(tmp_path)
    cpath, npath = write_tables(tmp_path, res)
    data = tmp_path / "data"
    data.mkdir()
    pref = base_pref()
    kana.write_pref(data / "pref_98.js", "/* test */\n", pref)
    st = cl.add_closures(data, cpath, npath)
    assert st["gone"] == 2 and st["now"] == 2 and st["now_with_id"] == 1 and st["joined"] == 1 and st["newSchools"] == 1
    _h, obj = kana.read_pref(data / "pref_98.js")
    s = {x["id"]: x for c in obj["cities"] for x in c["schools"]}
    assert s[GONE]["gone"] is True and s[GONE]["now"] == {"name": "なかよし小学校", "id": TARGET}
    assert s[GONE2]["now"] == {"name": "みほん学園"}
    assert s[TARGET]["joined"] == [{"id": GONE, "name": "ためし小学校"}] and "gone" not in s[TARGET]
    assert "gone" not in s["B198220200019"] and "joined" not in s["B198220200019"]
    assert obj["newSchools"] == [{"muni": "98201", "name": "みほん学園", "kana": ["みほんがくえん"], "from": [GONE2]}]
    # 人数・区域・ピンは変えない
    for c0, c1 in zip(pref["cities"], obj["cities"]):
        for a, b in zip(c0["schools"], c1["schools"]):
            assert {k: v for k, v in b.items() if k not in cl.SCHOOL_KEYS} == a
    # 2回かけても同じ
    before = (data / "pref_98.js").read_text(encoding="utf-8")
    st2 = cl.add_closures(data, cpath, npath)
    assert (data / "pref_98.js").read_text(encoding="utf-8") == before and st2.get("files_written", 0) == 0


def test_add_closures_skips_renamed_school(tmp_path):
    res = run(tmp_path)
    cpath, npath = write_tables(tmp_path, res)
    data = tmp_path / "data"
    data.mkdir()
    pref = base_pref()
    pref["cities"][0]["schools"][0]["name"] = "ちがう小学校"  # 作り直しで同じ id が別の学校になった
    kana.write_pref(data / "pref_98.js", "/* test */\n", pref)
    st = cl.add_closures(data, cpath, npath)
    assert st["gone_not_found"] == 1
    _h, obj = kana.read_pref(data / "pref_98.js")
    s = {x["id"]: x for c in obj["cities"] for x in c["schools"]}
    assert "gone" not in s[GONE] and "joined" not in s[TARGET]


def test_add_closures_empty_tables_change_nothing(tmp_path):
    cpath, npath = tmp_path / "c.csv", tmp_path / "n.csv"
    cl._write_csv(cpath, cl.CLOSURES_HEADER, [])
    cl._write_csv(npath, cl.NEW_HEADER, [])
    data = tmp_path / "data"
    data.mkdir()
    kana.write_pref(data / "pref_98.js", "/* test */\n", base_pref())
    before = (data / "pref_98.js").read_text(encoding="utf-8")
    cl.add_closures(data, cpath, npath)
    assert (data / "pref_98.js").read_text(encoding="utf-8") == before


def test_add_closures_cli(tmp_path):
    import build_school_data as cli  # noqa: E402
    res = run(tmp_path)
    cpath, npath = write_tables(tmp_path, res)
    data = tmp_path / "data"
    data.mkdir()
    kana.write_pref(data / "pref_98.js", "/* test */\n", base_pref())
    assert cli.main(["add-closures", "--data", str(data), "--closures", str(cpath), "--new-schools", str(npath)]) == 0
    _h, obj = kana.read_pref(data / "pref_98.js")
    assert {s["id"] for c in obj["cities"] for s in c["schools"] if s.get("gone")} == {GONE, GONE2}


# ---- 手で確かめた閉校の表（school_closures_manual.csv）

MANUAL_HEAD = "市区町村コード,id,学校名,移行先の名前,移行先の id,出典,確かめた日\n"


def _manual_setup(tmp_path, line):
    cpath, npath = tmp_path / "c.csv", tmp_path / "n.csv"
    cl._write_csv(cpath, cl.CLOSURES_HEADER, [])
    cl._write_csv(npath, cl.NEW_HEADER, [])
    mpath = tmp_path / "m.csv"
    mpath.write_text(MANUAL_HEAD + line + "\n", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    kana.write_pref(data / "pref_98.js", "/* test */\n", base_pref())
    return data, cpath, npath, mpath


def test_manual_closure_marks_gone(tmp_path):
    data, c, n, m = _manual_setup(tmp_path, f"98201,{GONE},ためし小学校,なかよし小学校,{TARGET},テストの出典,2026-11-20")
    st = cl.add_closures(data, c, n, m)
    assert st["gone"] == 1 and st["gone_manual"] == 1
    _h, obj = kana.read_pref(data / "pref_98.js")
    s = {x["id"]: x for cc in obj["cities"] for x in cc["schools"]}
    assert s[GONE]["gone"] is True and s[GONE]["now"] == {"name": "なかよし小学校", "id": TARGET}
    assert s[TARGET]["joined"] == [{"id": GONE, "name": "ためし小学校"}]


@pytest.mark.parametrize("line", [f"98201,{GONE},ちがう小学校,,,テストの出典,2026-11-20",   # 名前が app/data と違う
                                  "98201,98201-0099,ためし小学校,,,テストの出典,2026-11-20",  # id が無い
                                  f"98201,{GONE},ためし小学校,,,,2026-11-20",                 # 出典が空
                                  f"98201,{GONE},ためし小学校,,,テストの出典,2026/11/20"])     # 日付の形
def test_manual_closure_errors_stop(tmp_path, line):
    data, c, n, m = _manual_setup(tmp_path, line)
    with pytest.raises(SystemExit):
        cl.add_closures(data, c, n, m)


def test_manual_closure_other_pref_is_skipped(tmp_path):
    data, c, n, m = _manual_setup(tmp_path, "97201,B197220100010,どこか小学校,,,テストの出典,2026-11-20")
    st = cl.add_closures(data, c, n, m)
    assert st.get("gone", 0) == 0


# ---- 手で確かめた閉校の表の「② 文科省の一覧に同じ名前の学校が無い」行を、一覧で確かめ直す（check_manual）

SRC2 = "文部科学省「学校コード」（令和8年5月1日時点・暫定版）に、同じ県内に同じ名前の公立の小学校・義務教育学校が無い"


def _mrow(city, sid, name, src=SRC2):
    return {"市区町村コード": city, "id": sid, "学校名": name, "移行先の名前": "", "移行先の id": "", "出典": src, "確かめた日": "2026-11-20"}


def _check(tmp_path, rows, mrows):
    mext, _ = cl.load_mext([write_mext(tmp_path, rows)])
    pref = base_pref()
    pref["cities"][0]["schools"].append(school("98201-0001", "まぼろし小学校"))
    pref["cities"][1]["schools"].append(school("98202-0001", "まぼろし小学校"))
    return cl.check_manual(mrows, [pref], mext)


def test_check_manual_no_same_name_is_ok(tmp_path):
    x = _check(tmp_path, base_rows(), [_mrow("98201", "98201-0001", "まぼろし小学校")])
    assert cl.manual_problems(x) == [] and x[0]["other_city"] == [] and x[0]["app"]


@pytest.mark.parametrize("honbun,abol", [("1", ""), ("2", ""), ("9", "2024-05-01")])  # 本分校を問わない（廃校の行も）
def test_check_manual_same_city_row_stops(tmp_path, honbun, abol):
    rows = base_rows() + [row("B198220100047", "みほん市立まぼろし小学校", honbun=honbun, abol=abol)]
    x = _check(tmp_path, rows, [_mrow("98201", "98201-0001", "まぼろし小学校")])
    assert len(x[0]["same_city"]) == 1 and len(cl.manual_problems(x)) == 1


def test_check_manual_same_city_c2_and_table_name(tmp_path):
    # 義務教育学校（C2）の行も、名前のそろえ方（ヶ＝ケ・設置者名を外す）も印の決まり5と同じ
    rows = base_rows() + [row("C298220100024", "みほん市立まぼろしケ丘小学校")]
    x = _check(tmp_path, rows, [_mrow("98201", "98201-0001", "まぼろしヶ丘小学校")])
    assert len(x[0]["same_city"]) == 1


def test_check_manual_private_or_other_kind_is_ignored(tmp_path):
    rows = base_rows() + [row("B198320100013", "私立まぼろし小学校"), row("C198220100011", "みほん市立まぼろし小学校")]
    x = _check(tmp_path, rows, [_mrow("98201", "98201-0001", "まぼろし小学校")])
    assert cl.manual_problems(x) == [] and x[0]["other_city"] == []


def test_check_manual_other_city_is_reported_not_stopped(tmp_path):
    rows = base_rows() + [row("B198220200028", "べつ市立まぼろし小学校", addr="ためし県べつ市本町1")]
    x = _check(tmp_path, rows, [_mrow("98201", "98201-0001", "まぼろし小学校")])
    assert cl.manual_problems(x) == [] and [c for _m, c in x[0]["other_city"]] == ["98202"]
    # 逆に、べつ市の まぼろし小 から見れば同じ市区町村なので止まる
    y = _check(tmp_path, rows, [_mrow("98202", "98202-0001", "まぼろし小学校")])
    assert len(cl.manual_problems(y)) == 1


def test_check_manual_undecided_city_stops(tmp_path):
    rows = base_rows() + [row("B198220100056", "みほん市立まぼろし小学校", addr="ためし県どこか村1")]
    x = _check(tmp_path, rows, [_mrow("98201", "98201-0001", "まぼろし小学校")])
    assert len(x[0]["undecided"]) == 1 and len(cl.manual_problems(x)) == 1


def test_check_manual_app_mismatch_stops(tmp_path):
    x = _check(tmp_path, base_rows(), [_mrow("98201", "98201-0001", "ちがう小学校")])
    assert not x[0]["app"] and len(cl.manual_problems(x)) == 1


def test_make_closures_stops_on_bad_manual_row(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pref = base_pref()
    pref["cities"][0]["schools"].append(school("98201-0001", "まぼろし小学校"))
    kana.write_pref(data / "pref_98.js", "/* test */\n", pref)
    m = tmp_path / "m.csv"
    m.write_text(MANUAL_HEAD + f"98201,98201-0001,まぼろし小学校,,,{SRC2},2026-11-20\n", encoding="utf-8")
    kw = dict(closures_csv=tmp_path / "c.csv", new_csv=tmp_path / "n.csv", manual_csv=m, hamadori=set())
    bad = write_mext(tmp_path, base_rows() + [row("B198220100047", "みほん市立まぼろし小学校")])
    with pytest.raises(SystemExit, match="手で確かめた閉校の表"):
        cl.make_closures(data, [bad], tmp_path, **kw)


def test_is_mext_absence_row():
    assert cl.is_mext_absence_row(_mrow("98201", "x", "y"))
    assert not cl.is_mext_absence_row(_mrow("98201", "x", "y", src="国土数値情報 小学校区データ 令和5年度（A27-23_08）の学校コードの欄（A27_003）が「閉校」"))


# ---- 学校コードが引き継がれて名前だけが変わった学校（存続しているコードの学校）は、③（公式の資料）の行だけ

SRC3 = "広報みほん「ためし小学校で閉校式」 https://example.invalid/kouhou.pdf"
SRC1 = "国土数値情報 小学校区データ 令和5年度（A27-23_98）の学校コードの欄（A27_003）が「閉校」"


def test_manual_kind():
    assert cl.manual_kind(_mrow("98201", "x", "y")) == "②"
    assert cl.manual_kind(_mrow("98201", "x", "y", src=SRC1)) == "①"
    assert cl.manual_kind(_mrow("98201", "x", "y", src=SRC3)) == "③"


@pytest.mark.parametrize("src,stops", [(SRC3, False), (SRC1, True), (SRC2, True)])
def test_living_code_row_needs_official_source(tmp_path, src, stops):
    mext, _ = cl.load_mext([write_mext(tmp_path, base_rows())])
    rows = [_mrow("98201", TARGET, "なかよし小学校", src=src)]  # TARGET は存続している行のコード
    assert bool(cl.living_code_problems(rows, mext)) is stops


def test_closed_code_row_is_not_living_code(tmp_path):
    mext, _ = cl.load_mext([write_mext(tmp_path, base_rows())])
    assert cl.living_code_problems([_mrow("98201", GONE, "ためし小学校", src=SRC1)], mext) == []  # GONE は廃校の行


def test_make_closures_stops_on_living_code_row_without_official_source(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    kana.write_pref(data / "pref_98.js", "/* test */\n", base_pref())
    m = tmp_path / "m.csv"
    m.write_text(MANUAL_HEAD + f"98201,{TARGET},なかよし小学校,,,{SRC1},2026-11-20\n", encoding="utf-8")
    kw = dict(closures_csv=tmp_path / "c.csv", new_csv=tmp_path / "n.csv", manual_csv=m, hamadori=set())
    with pytest.raises(SystemExit, match="存続している学校"):
        cl.make_closures(data, [write_mext(tmp_path, base_rows())], tmp_path, **kw)


# ---- ④ 学校コードは続いているが、国の一覧で学校名が変わっている学校（renamed_problems）

SRC4 = "文部科学省「学校コード」の学校名（令和8年5月1日時点・暫定版）：この学校コードの学校は「みほん市立なかよし小学校」。"


def _renamed(tmp_path, extra_rows=(), extra_schools=(), row_kw=None, undecided=(), name_fixed=()):
    """アプリの TARGET の学校名を「ふるい小学校」にした形（国の一覧ではそのコードは「なかよし小学校」）"""
    mext, _ = cl.load_mext([write_mext(tmp_path, base_rows() + list(extra_rows))])
    pref = base_pref()
    for s in pref["cities"][0]["schools"]:
        if s["id"] == TARGET:
            s["name"] = "ふるい小学校"
    pref["cities"][0]["schools"] += [school(i, n) for i, n in extra_schools]
    r = _mrow("98201", TARGET, "ふるい小学校", src=SRC4)
    r["移行先の名前"] = "なかよし小学校"
    r.update(row_kw or {})
    return cl.renamed_problems([r], [pref], mext, set(undecided), set(name_fixed))


def test_renamed_kind_and_living_code_allowed(tmp_path):
    r = _mrow("98201", TARGET, "ふるい小学校", src=SRC4)
    assert cl.manual_kind(r) == "④" and not cl.is_mext_absence_row(r)
    mext, _ = cl.load_mext([write_mext(tmp_path, base_rows())])
    assert cl.living_code_problems([r], mext) == []


def test_renamed_ok(tmp_path):
    assert _renamed(tmp_path) == []


def test_renamed_rule1_same_name_living_in_city(tmp_path):
    bad = _renamed(tmp_path, extra_rows=[row("B198220100047", "みほん市立ふるい小学校")])
    assert len(bad) == 1 and "決まり1" in bad[0]


def test_renamed_rule1_closed_row_is_not_living(tmp_path):
    # 同じ名前でも 廃校の行は 決まり1に 当たらない
    assert _renamed(tmp_path, extra_rows=[row("B198220100047", "みほん市立ふるい小学校", honbun="9", abol="2024-05-01")]) == []


def test_renamed_rule1_other_city_is_ok(tmp_path):
    assert _renamed(tmp_path, extra_rows=[row("B198220200028", "べつ市立ふるい小学校", addr="ためし県べつ市本町1")]) == []


def test_renamed_rule2_same_name_as_now_in_app(tmp_path):
    bad = _renamed(tmp_path, extra_schools=[("98201-0009", "なかよし小学校")])
    assert len(bad) == 1 and "決まり2" in bad[0]


def test_renamed_rule3_undecided(tmp_path):
    bad = _renamed(tmp_path, undecided=[("98", TARGET)])
    assert len(bad) == 1 and "決まり3" in bad[0] and "決められない" in bad[0]


def test_renamed_rule3_name_fixed(tmp_path):
    bad = _renamed(tmp_path, name_fixed=[TARGET])
    assert len(bad) == 1 and "誤記の表" in bad[0]


@pytest.mark.parametrize("kw,word", [({"移行先の名前": "ちがう小学校"}, "移行先の名前"),
                                     ({"移行先の id": TARGET}, "移行先の id"),
                                     ({"学校名": "ちがう小学校"}, "app/data")])
def test_renamed_row_values(tmp_path, kw, word):
    bad = _renamed(tmp_path, row_kw=kw)
    assert any(word in b for b in bad), bad


def test_renamed_code_must_be_living(tmp_path):
    mext, _ = cl.load_mext([write_mext(tmp_path, base_rows())])
    r = _mrow("98201", GONE, "ためし小学校", src=SRC4)
    r["移行先の名前"] = "ためし小学校"
    bad = cl.renamed_problems([r], [base_pref()], mext, set(), set())
    assert any("存続している行" in b for b in bad), bad


def test_renamed_same_name_after_folding_is_not_renamed(tmp_path):
    # 書き方の違いだけ（設置者名・ヶ）は 名前が変わっていない
    mext, _ = cl.load_mext([write_mext(tmp_path, base_rows())])
    r = _mrow("98201", TARGET, "なかよし小学校", src=SRC4)
    r["移行先の名前"] = "なかよし小学校"
    bad = cl.renamed_problems([r], [base_pref()], mext, set(), set())
    assert any("名前は変わっていない" in b for b in bad), bad


def test_make_closures_checks_renamed_rows(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pref = base_pref()
    pref["cities"][0]["schools"][1]["name"] = "ふるい小学校"
    kana.write_pref(data / "pref_98.js", "/* test */\n", pref)
    m = tmp_path / "m.csv"
    m.write_text(MANUAL_HEAD + f"98201,{TARGET},ふるい小学校,ちがう小学校,,{SRC4},2026-11-20\n", encoding="utf-8")
    nf = tmp_path / "name_fix.csv"
    nf.write_text("都道府県,id,役割,判定\n", encoding="utf-8")
    kw = dict(closures_csv=tmp_path / "c.csv", new_csv=tmp_path / "n.csv", manual_csv=m, hamadori=set())
    with pytest.raises(SystemExit, match="移行先の名前"):
        cl.make_closures(data, [write_mext(tmp_path, base_rows())], tmp_path, name_fix_csv=nf, **kw)
    with pytest.raises(SystemExit, match="name_fix.csv"):  # 決められない学校の表が無ければ止める
        cl.make_closures(data, [write_mext(tmp_path, base_rows())], tmp_path, name_fix_csv=tmp_path / "none.csv", **kw)
