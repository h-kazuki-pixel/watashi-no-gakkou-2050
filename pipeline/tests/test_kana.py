"""学校名の読み（make-kana / add-kana）の検算。小さな合成の町字の表と、架空の学校で確かめる。

    python3 -m pytest pipeline/tests -q
"""
import csv
import json
import pathlib
import sys
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import build_school_data as cli  # noqa: E402
from school2050 import kana, wards  # noqa: E402

COLS = kana.TOWN_COLUMNS

# 合成の町字（架空の県 98）。98100 は区を市にまとめた政令市（区 98101・98102）、98201 はふつうの市、98202 は区で分けた市の区
TOWN_ROWS = [
    # lg_code, city, ward, 大字・町名, 読み, 小字, 読み
    ("981010", "みほん市", "東区", "竜", "タツ", "", ""),
    ("981010", "みほん市", "東区", "竜王", "リュウオウ", "", ""),
    ("981028", "みほん市", "西区", "三入", "ミイリ", "", ""),
    ("981028", "みほん市", "西区", "大字西新", "オオアザニシジン", "字上ノ原", "アザウエノハラ"),
    ("981028", "みほん市", "西区", "高取一丁目", "タカトリイッチョウメ", "", ""),
    ("982016", "ためし市", "", "竜王", "リュウオウ", "", ""),
    ("982016", "ためし市", "", "竜王", "リュウオウ", "", ""),
    ("982016", "ためし市", "", "竜王", "タツオウ", "", ""),   # 同じ名前で読みが違う → 行の多い読み
    ("982016", "ためし市", "", "上野", "ウエノ", "", ""),
    ("982024", "べつ市", "", "日向", "ヒュウガ", "", ""),
]

# 区のコード → 市のコード（政令市を市で1つにまとめた 98100）
WARD_TABLE = {c: wards.Ward(c, n, "98100", "みほん市", False) for c, n in (("98101", "みほん市東区"), ("98102", "みほん市西区"))}

# 辞書のかわり（決まった読みを返す。無い語は None）
FAKE_DICT = {
    "竜王": "りゅうおう", "竜王北": "りゅうおうきた", "三入": "さんにゅう", "西新": "にしじん", "日向": "ひなた",
    "上野": "うえの", "北": "きた", "台": "だい", "高取": "たかとり", "上ノ原": "うえのはら", "幌北": "ほろきた",
}


def fake_dict(t):
    return FAKE_DICT.get(t)


def write_town(path, rows=TOWN_ROWS, header=None):
    header = header or [COLS["lg_code"], COLS["city"], COLS["ward"], COLS["oaza"], COLS["oaza_kana"], COLS["koaza"], COLS["koaza_kana"]]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pref"] + header + ["remarks"])
        for r in rows:
            w.writerow(["テスト県"] + list(r) + [""])
    return path


SCHOOLS = {
    "98100": [("A1", "竜王北小学校"), ("A2", "三入小学校"), ("A3", "西新小学校"), ("A4", "竜王小学校上ノ原分校"),
              ("A5", "高取東小学校"), ("A6", "東竜王小学校")],
    "98201": [("B1", "竜王第二小学校"), ("B2", "あずま小中学校"), ("B3", "鬮鬮小学校"), ("B4", "三入小学校"), ("B5", "上野台学園")],
    "98202": [("C1", "日向小学校"), ("C2", "幌北小学校分校")],
}


def write_data(d: pathlib.Path):
    d.mkdir(parents=True, exist_ok=True)
    cities = [{"code": code, "name": code, "schools": [
        {"id": sid, "name": n, "lng": 130.1, "lat": 33.5, "est": [10.0] * 10, "ages": [1.5] * 12, "geom": [[[130.0, 33.0], [130.2, 33.0], [130.1, 33.2]]]}
        for sid, n in ss]} for code, ss in SCHOOLS.items()]
    obj = {"code": "98", "name": "テスト県", "generated": "2026-11-17", "source": {"credit": "x"}, "cities": cities, "missing": []}
    kana.write_pref(d / "pref_98.js", "/* わたしの学校2050 — pipeline/build_school_data.py が生成。手で編集しないこと。 */\n", obj)
    (d / "index.js").write_text("/* 実データの都道府県一覧。pipeline/build_school_data.py が生成。 */\nUG.registerIndex("
                                + json.dumps([{"code": "98", "name": "テスト県", "cities": 3, "schools": 13, "generated": "2026-11-17",
                                              "datasets": []}], ensure_ascii=False, indent=1) + ");\n", encoding="utf-8")
    return d


def run_make(tmp_path, town=None, dict_reader=fake_dict):
    data = write_data(tmp_path / "data")
    town = town or write_town(tmp_path / "town.csv")
    out = tmp_path / "auto.csv"
    res = kana.make_kana(data, town, out, tmp_path / "KANA.md", dict_reader=dict_reader, ward_table=WARD_TABLE, combined_table={})
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    by = {}
    for r in rows:
        by.setdefault(r["学校コード"], []).append((r["読み"], r["元"]))
    return data, res, by, out


def test_longest_match_and_direction_remainder(tmp_path):
    _, _, by, _ = run_make(tmp_path)
    # 「竜」（たつ）より長い「竜王」が当たり、残りの「北」は方角の表で読む
    assert by["A1"] == [("りゅうおうきたしょうがっこう", "town")]
    # 残りの「第二」は番号の表で読む。辞書（竜王第二 は無い）では読めないので、町字の読みだけ
    assert by["B1"] == [("りゅうおうだいにしょうがっこう", "town")]
    # 町字の前の方角（東＋竜王）
    assert by["A6"] == [("ひがしりゅうおうしょうがっこう", "town")]


def test_designated_city_uses_all_wards(tmp_path):
    _, _, by, _ = run_make(tmp_path)
    # 98100（区を市にまとめた政令市）は西区（98102）の町字「三入」も使う。辞書の読みと違うので両方（町字が先）
    assert by["A2"] == [("みいりしょうがっこう", "town"), ("さんにゅうしょうがっこう", "dict")]
    # 98201 には「三入」の町字が無いので、辞書の読みだけ
    assert by["B4"] == [("さんにゅうしょうがっこう", "dict")]


def test_oaza_aza_and_chome_are_stripped(tmp_path):
    _, _, by, _ = run_make(tmp_path)
    assert by["A3"] == [("にしじんしょうがっこう", "town")]        # 「大字西新」→ 西新（オオアザ も外す）。辞書と同じなので1つ
    assert by["A5"] == [("たかとりひがししょうがっこう", "town")]  # 「高取一丁目」→ 高取（イッチョウメ も外す）＋ 東


def test_branch_school(tmp_path):
    _, _, by, _ = run_make(tmp_path)
    # 分校名「上ノ原」は小字「字上ノ原」（アザ を外す）で読む
    assert by["A4"] == [("りゅうおうしょうがっこううえのはらぶんこう", "town")]
    # 分校名の無い分校。町字が無く、辞書で読む
    assert by["C2"] == [("ほろきたしょうがっこうぶんこう", "dict")]


def test_town_and_dict_differ_and_majority_reading(tmp_path):
    _, res, by, _ = run_make(tmp_path)
    assert by["C1"] == [("ひゅうがしょうがっこう", "town"), ("ひなたしょうがっこう", "dict")]
    # 同じ名前で読みが違う町字は、行の多い読み（りゅうおう 2行 > たつおう 1行）
    assert all(r[0].startswith("りゅうおう") for r in by["B1"])
    # 学園。「上野」は町字、「台」は辞書で読む
    assert by["B5"] == [("うえのだいがくえん", "town")]
    doc = (tmp_path / "KANA.md").read_text(encoding="utf-8")
    assert "| 98 | 98202 | C1 | 日向小学校 | ひゅうがしょうがっこう | ひなたしょうがっこう |" in doc
    assert res["two_readings"] == 2


def test_name_kana_and_unreadable(tmp_path):
    _, res, by, _ = run_make(tmp_path)
    assert by["B2"] == [("あずましょうちゅうがっこう", "name")]
    assert "B3" not in by  # 町字にも辞書にも無い → 読みなし
    assert res["none"] == 1 and res["unreadable"][0][2:] == ("B3", "鬮鬮小学校")
    doc = (tmp_path / "KANA.md").read_text(encoding="utf-8")
    assert "| 98 | 98201 | B3 | 鬮鬮小学校 |" in doc
    assert res["schools"] == 13 and res["town"] + res["dict"] + res["name"] + res["none"] == 13


def test_zip_input(tmp_path):
    town = write_town(tmp_path / "mt_town_all.csv")
    z = tmp_path / "mt_town_all.csv.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(town, "mt_town_all.csv")
    _, _, by, _ = run_make(tmp_path, town=z)
    assert by["A1"] == [("りゅうおうきたしょうがっこう", "town")]


def test_missing_column_stops_with_names(tmp_path):
    bad = [c for c in [COLS["lg_code"], COLS["city"], COLS["ward"], COLS["oaza"], COLS["oaza_kana"], COLS["koaza"]]]
    town = write_town(tmp_path / "town.csv", rows=[r[:6] for r in TOWN_ROWS], header=bad)
    with pytest.raises(SystemExit) as e:
        kana.check_columns(town)
    assert COLS["koaza_kana"] in str(e.value) and "TOWN_COLUMNS" in str(e.value)
    with pytest.raises(SystemExit):
        run_make(tmp_path, town=town)
    # CLI の --check-columns も同じ
    with pytest.raises(SystemExit) as e:
        cli.main(["make-kana", "--town", str(town), "--check-columns"])
    assert COLS["koaza_kana"] in str(e.value)
    assert cli.main(["make-kana", "--town", str(write_town(tmp_path / "ok.csv")), "--check-columns"]) == 0


def _read(data):
    return (data / "pref_98.js").read_bytes(), (data / "index.js").read_bytes()


def test_add_kana_manual_override_and_idempotent(tmp_path):
    data, _, _, auto = run_make(tmp_path)
    before = kana.read_pref(data / "pref_98.js")[1]
    manual = tmp_path / "manual.csv"
    manual.write_text("学校コード,読み,理由\nC1,ひなたしょうがっこう,地元の呼び方\nB3,,読まない\nA6,,読みを付けない\n", encoding="utf-8")
    st = kana.add_kana(data, auto, manual)
    once = _read(data)
    obj = kana.read_pref(data / "pref_98.js")[1]
    s = {x["id"]: x for c in obj["cities"] for x in c["schools"]}
    assert s["A2"]["kana"] == ["みいりしょうがっこう", "さんにゅうしょうがっこう"]
    assert s["C1"]["kana"] == ["ひなたしょうがっこう"]   # 手直しの表で置き換え
    assert "kana" not in s["A6"] and "kana" not in s["B3"]  # 空の読み → 付けない
    assert list(s["A1"])[:3] == ["id", "name", "kana"]     # name の後に置く
    # kana のほかは変わらない（generated も）
    strip = lambda o: [[{k: v for k, v in x.items() if k != "kana"} for x in c["schools"]] for c in o["cities"]]
    assert strip(obj) == strip(before) and obj["generated"] == before["generated"] == "2026-11-17"
    assert {k: v for k, v in obj.items() if k != "cities"} == {k: v for k, v in before.items() if k != "cities"}
    assert st["manual"] == 1 and st["auto"] == 10 and st["schools_with_kana"] == 11
    idx = json.loads((data / "index.js").read_text(encoding="utf-8").split("UG.registerIndex(", 1)[1].rsplit(");", 1)[0])
    assert idx[0]["kana"] is True
    # 2回かけても同じ
    st2 = kana.add_kana(data, auto, manual)
    assert _read(data) == once and st2.get("files_written", 0) == 0 and "index_written" not in st2


def test_add_kana_with_empty_tables_changes_nothing(tmp_path):
    data = write_data(tmp_path / "data")
    before = _read(data)
    auto, manual = tmp_path / "a.csv", tmp_path / "m.csv"
    auto.write_text("学校コード,学校名,読み,元\n", encoding="utf-8")
    manual.write_text("学校コード,読み,理由\n", encoding="utf-8")
    st = kana.add_kana(data, auto, manual)
    assert _read(data) == before and st.get("schools_with_kana", 0) == 0
    # リポジトリの表（いまは見出しだけ）でも同じ
    st = kana.add_kana(data)
    assert _read(data) == before


def test_add_kana_skips_rows_whose_school_name_differs(tmp_path):
    data, _, _, auto = run_make(tmp_path)
    obj = kana.read_pref(data / "pref_98.js")[1]
    obj["cities"][0]["schools"][0]["name"] = "べつの小学校"  # 作り直しで学校コードが別の学校になった
    kana.write_pref(data / "pref_98.js", "/* x */\n", obj)
    manual = tmp_path / "m.csv"
    manual.write_text("学校コード,読み,理由\n", encoding="utf-8")
    st = kana.add_kana(data, auto, manual)
    s = kana.read_pref(data / "pref_98.js")[1]["cities"][0]["schools"][0]
    assert "kana" not in s and st["name_mismatch"] == 1


def test_bad_tables_stop(tmp_path):
    data = write_data(tmp_path / "data")
    auto = tmp_path / "a.csv"
    auto.write_text("学校コード,学校名,読み,元\nA1,竜王北小学校,リュウオウ,town\n", encoding="utf-8")
    manual = tmp_path / "m.csv"
    manual.write_text("学校コード,読み,理由\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        kana.add_kana(data, auto, manual)  # 片仮名の読みは受け付けない
    auto.write_text("id,kana\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        kana.add_kana(data, auto, manual)  # 見出しが違う


def test_build_all_adds_kana(tmp_path, capsys):
    import test_pipeline as fx
    fx._make_downloads(tmp_path / "dl")
    out = tmp_path / "d"
    assert cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(out)]) == 0
    pref = kana.read_pref(out / "pref_99.js")[1]
    s = [x for c in pref["cities"] for x in c["schools"] if x["name"] == "にし小学校"][0]
    auto = tmp_path / "auto.csv"
    auto.write_text(f"学校コード,学校名,読み,元\n{s['id']},にし小学校,にししょうがっこう,name\n", encoding="utf-8")
    assert cli.main(["build-all", "--input", str(tmp_path / "dl"), "--out", str(out), "--kana-auto", str(auto)]) == 0
    pref = kana.read_pref(out / "pref_99.js")[1]
    s = [x for c in pref["cities"] for x in c["schools"] if x["name"] == "にし小学校"][0]
    assert s["kana"] == ["にししょうがっこう"]


def test_parse_name_and_tables():
    assert kana.parse_name("姫路市立四郷学院") == [("read", "四郷学院")]
    assert kana.parse_name("義務教育学校香春思永館") == [("fixed", "ぎむきょういくがっこう"), ("read", "香春思永館")]
    assert kana.parse_name("小値賀小大島分校") == [("read", "小値賀"), ("fixed", "しょうがっこう"), ("read", "大島"), ("fixed", "ぶんこう")]
    assert kana.parse_name("戸田小中一貫学校") == [("read", "戸田"), ("fixed", "しょうちゅういっかんがっこう")]
    assert kana.parse_name("立花小学校") == [("read", "立花"), ("fixed", "しょうがっこう")]
    assert kana.read_table("中央") == "ちゅうおう" and kana.read_table("第1") == "だいいち" and kana.read_table("山") is None
    assert kana.hira("リュウオウヴ") == "りゅうおうゔ"
    assert kana.fold("龍ヶ崎") == kana.fold("竜ケ崎") == "竜が崎"


def test_sudachi_reader():
    pytest.importorskip("sudachipy")
    pytest.importorskip("sudachidict_full")
    r = kana.SudachiReader()
    assert r("竜王") == "りゅうおう"
    assert r("第一") == "だいいち"  # 数詞は未知語でも読みが付く


def _towns(rows):
    """(名前, カナ) の並び → 1つの市区町村の 名前 → 読み"""
    idx = kana.TownIndex()
    for n, k in rows:
        idx.add("989010", n, k)
    return idx.lookup(["98901"])


def test_town_tail_machi_mura_is_stripped():
    # 町字データのカナは小さい字を大きく書く（チヨウ）
    towns = _towns([("日比津町", "ヒビツチヨウ"), ("近見町", "チカミマチ"), ("上南摩町", "カミナンマチョウ"), ("大川村", "オオカワムラ"),
                    ("東町", "ヒガシマチ"), ("大村", "オオムラ"), ("田中町", "タナカ")])
    assert kana.school_readings("日比津小学校", towns, None) == [("ひびつしょうがっこう", "town")]
    assert kana.school_readings("近見小学校", towns, None) == [("ちかみしょうがっこう", "town")]
    assert kana.school_readings("上南摩小学校", towns, None) == [("かみなんましょうがっこう", "town")]
    assert kana.school_readings("大川小学校", towns, None) == [("おおかわしょうがっこう", "town")]
    # 外したあと1文字になるもの（東町・大村）は外さない
    assert "東" not in towns and "大" not in towns
    # 読みの末尾が「チョウ」「マチ」でなければ外さない
    assert "田中" not in towns


def test_chome_with_large_kana():
    towns = _towns([("高取二丁目", "タカトリニチヨウメ"), ("西新一丁目", "ニシジンイツチヨウメ")])
    assert towns["高取"] == "たかとり" and towns["西新"] == "にしじん"


def test_dict_ke_after_kanji_and_small_ke_discarded():
    seen = []

    def d(t):
        seen.append(t)
        return {"草が江": "くさがえ", "妙": "みょゖ"}.get(t)
    assert kana.school_readings("草ヶ江小学校", {}, d) == [("くさがえしょうがっこう", "dict")]
    assert "草ヶ江" in seen and "草が江" in seen  # 辞書には、学校名のままと「が」に置き換えたものの両方を渡す
    assert kana.school_readings("妙小学校", {}, d) == []  # 「ゖ」が残る読みは捨てる
    # 町字の読みに「ゖ」があっても使わない
    idx = kana.TownIndex()
    idx.add("989010", "鬼ヶ島", "オニヶシマ")
    assert idx.lookup(["98901"]) == {}


def test_dict_oka_at_end():
    d = {"霧丘": "きりきゅう", "霧": "きり", "香住丘": "かすみたかし", "香住": "かすみ", "旭丘": "あさひがおか",
         "緑の丘": "みどりのきゅう", "緑の": "みどりの", "希望丘": "きぼうきゅう", "希望": "きぼう"}.get
    # 「がおか」と「おか」の両方を候補にする（「がおか」が先）
    assert kana.school_readings("霧丘小学校", {}, d) == [("きりがおかしょうがっこう", "dict"), ("きりおかしょうがっこう", "dict")]
    assert kana.school_readings("香住丘小学校", {}, d) == [("かすみがおかしょうがっこう", "dict"), ("かすみおかしょうがっこう", "dict")]
    assert kana.school_readings("旭丘小学校", {}, d) == [("あさひがおかしょうがっこう", "dict")]   # もとから「おか」
    assert kana.school_readings("緑の丘小学校", {}, d) == [("みどりのおかしょうがっこう", "dict")]  # 「の」の後は「おか」
    # 町字の読みには置き換えをかけない（町字「希望丘」の読みはそのまま。辞書の読みは「がおか」にして、違えば両方残す）
    towns = _towns([("希望丘", "キボウキユウ")])
    assert kana.school_readings("希望丘小学校", towns, d) == [("きぼうきゆうしょうがっこう", "town"),
                                                            ("きぼうがおかしょうがっこう", "dict")]


# SudachiDict full の実際の読み（2026-11-18、make-kana で使ったもの）。辞書は「ゖ」の残る読みを返さない（SudachiReader が None にする）
REAL_DICT = {
    "金ケ崎": "かねがさき", "金が崎": "きんがさき",
    "三ヶ日東": "みっかびひがし", "三が日東": "さんがにちひがし",
    "鈴ケ森": "すずけもり", "鈴が森": "すずがもり",
    "草ヶ江": None, "草が江": "くさがこう",
    "つつじケ丘": "つつじけきゅう", "つつじケ": "つつじけ", "つつじが丘": "つつじがおか",
    "りんどうヶ丘": None, "りんどうが丘": "りんどうがおか",
    "高丘": "こうきゅう", "高": "こう", "鷹丘": "たかきゅう", "鷹": "たか",
}


def test_dict_ke_both_asis_and_replaced():
    d = REAL_DICT.get
    # 学校名のままで読める学校は、その読みが先（ed465d9 で きんがさき だけになっていた）
    assert kana.school_readings("金ケ崎小学校", {}, d) == [("かねがさきしょうがっこう", "dict"), ("きんがさきしょうがっこう", "dict")]
    assert kana.school_readings("三ヶ日東小学校", {}, d)[0] == ("みっかびひがししょうがっこう", "dict")
    # 置き換えないと「け」と読む学校も、置き換えた読みが残る
    assert ("すずがもりしょうがっこう", "dict") in kana.school_readings("鈴ケ森小学校", {}, d)
    # そのままだと「ゖ」が残る学校は、置き換えた読みだけ
    assert kana.school_readings("草ヶ江小学校", {}, d) == [("くさがこうしょうがっこう", "dict")]
    assert kana.school_readings("りんどうヶ丘小学校", {}, d) == [("りんどうがおかしょうがっこう", "dict")]
    # 「ケ」は前が平仮名でも置き換える。そのままの1つ目、置き換えの1つ目の順（2つまで）
    assert kana.school_readings("つつじケ丘小学校", {}, d) == [("つつじけがおかしょうがっこう", "dict"),
                                                            ("つつじがおかしょうがっこう", "dict")]


def test_ke_replacement_targets():
    sub = lambda s: kana._KE_FOR_DICT.sub("が", s)
    assert sub("草ヶ江") == "草が江" and sub("りんどうヶ丘") == "りんどうが丘" and sub("ヶ丘") == "が丘"  # 「ヶ」は前を問わない
    assert sub("つつじケ丘") == "つつじが丘" and sub("金ケ崎") == "金が崎"
    assert sub("ケ丘") == "ケ丘"          # 前に字が無い「ケ」は置き換えない
    assert sub("アケ丘") == "アケ丘"      # 前が片仮名
    assert sub("金ケ") == "金ケ"          # 後ろが無い
    assert sub("金ケの") == "金ケの"      # 後ろが漢字でない


def test_oka_keeps_oka_reading_with_town_first():
    d = REAL_DICT.get
    # 高丘（中野市）：町字「高丘」＝タカオカ。辞書は こうがおか・こうおか。町字が先で2つまで
    towns = _towns([("高丘", "タカオカ")])
    assert kana.school_readings("高丘小学校", towns, d) == [("たかおかしょうがっこう", "town"), ("こうがおかしょうがっこう", "dict")]
    # 鷹丘（豊橋市）：町字が無くても「たかおか」が候補に残る
    assert kana.school_readings("鷹丘小学校", {}, d) == [("たかがおかしょうがっこう", "dict"), ("たかおかしょうがっこう", "dict")]


def test_add_kana_accepts_old_small_ke_rows_and_counts_them(tmp_path):
    data = write_data(tmp_path / "data")
    auto = tmp_path / "a.csv"
    auto.write_text("学校コード,学校名,読み,元\nA1,竜王北小学校,りゅうおうゖたしょうがっこう,dict\n", encoding="utf-8")
    manual = tmp_path / "m.csv"
    manual.write_text("学校コード,読み,理由\n", encoding="utf-8")
    st = kana.add_kana(data, auto, manual)
    assert st["auto"] == 1 and st["auto_small_ka_ke"] == 1  # 前の表との互換。make-kana をかけ直すと消える
    manual.write_text("学校コード,読み,理由\nA1,りゅうおうきたしょうがっこう,手直し\n", encoding="utf-8")
    assert kana.add_kana(data, auto, manual)["auto_small_ka_ke"] == 0
    manual.write_text("学校コード,読み,理由\nA1,りゅうおうゖた,手直し\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        kana.add_kana(data, auto, manual)  # 手直しの表では受け付けない


def test_kana_doc_records_manual_readings(tmp_path):
    """KANA.md に、手直しの表で読みを決めた学校（自動の読み・手で決めた読み・理由）を書く。自動の表は変えない"""
    man = tmp_path / "manual.csv"
    man.write_text("学校コード,読み,理由\nA1,りゅうおうきたしょうがっこう,テスト\nZZ,ないしょうがっこう,アプリに無い\n", encoding="utf-8")
    data = write_data(tmp_path / "data")
    out = tmp_path / "auto.csv"
    kana.make_kana(data, write_town(tmp_path / "town.csv"), out, tmp_path / "KANA.md", dict_reader=fake_dict,
                   ward_table=WARD_TABLE, combined_table={}, manual_csv=man)
    doc = (tmp_path / "KANA.md").read_text(encoding="utf-8")
    sec = doc.split("## 手で決めた読み（school_kana.csv）")[1]
    assert "手直しの表で読みを決めた学校：1校" in sec
    assert "| A1 |" in sec and "| りゅうおうきたしょうがっこう | テスト |" in sec and "ZZ" not in sec
    assert [r["学校コード"] for r in csv.DictReader(out.open(encoding="utf-8"))].count("A1") == 1
