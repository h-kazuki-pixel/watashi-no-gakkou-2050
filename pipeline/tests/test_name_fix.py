"""学校名の誤り（同じ名前の学校がもう1つある学校）の決まり（docs/DATA_METHOD.md「元データの…誤り」の5）。

1〜5 を全部満たすと直し、1つだけ外すと直さないことを確かめる。

    python3 -m pytest pipeline/tests -q
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "pipeline"))

import name_fix_review as nf  # noqa: E402
from school2050.closures import MextRow  # noqa: E402


def mrow(name, honbun="1", abol=""):
    return MextRow(code="B198220100010", kind="B1", pref="98", setchi="2", honbun=honbun, name=name, addr="",
                   set_date="2020-12-22", abol=abol, next_raw="")


BASE = dict(app_name="ためし小学校",
            partner_mext=mrow("みほん市立ためし小学校"),           # 相手のコードの行：存続で、名前がアプリの名前
            self_mext=mrow("みほん市立なかよし小学校"),             # この学校のコードの行：存続
            p29_a_name="なかよし小学校",                            # P29 でこのコードの学校の名前
            a_inside=True,                                          # その点がこの区域の中
            a27_addr="みほん市本町1-2",                             # 学区データの所在地
            partner_addr="ためし県みほん市西町5-6")                 # 相手の所在地（P29）


def test_all_rules_met():
    assert nf.partner_rule(**BASE) == []


@pytest.mark.parametrize("kw,rule", [
    ({"partner_mext": mrow("みほん市立ためし小学校", honbun="9", abol="2025-05-01")}, 1),  # 相手が廃校の行
    ({"partner_mext": mrow("みほん市立ためし小学校", honbun="2")}, 1),                     # 相手が分校の行
    ({"partner_mext": mrow("みほん市立べつ小学校")}, 1),                                    # 相手の行の名前がアプリの名前と違う
    ({"partner_mext": None}, 1),                                                            # 相手のコードが一覧に無い
    ({"self_mext": mrow("みほん市立なかよし小学校", honbun="9", abol="2024-05-01")}, 2),  # この学校のコードが廃校
    ({"self_mext": None}, 2),
    ({"p29_a_name": "ちがう小学校"}, 2),                                                    # P29 の名前と文科省の名前が違う
    ({"p29_a_name": ""}, 2),
    ({"a_inside": False}, 4),                                                               # コードの学校の点が区域の外
    ({"partner_addr": "ためし県みほん市本町1-2"}, 5),                                       # 学区データの所在地が相手の所在地と一致
    ({"partner_addr": ""}, 5),                                                              # 相手の所在地が無い（一致しないと言えない）
])
def test_one_rule_off_is_not_fixed(kw, rule):
    assert nf.partner_rule(**{**BASE, **kw}) == [rule]


def test_rule5_town_only_match_still_fixes():
    # 「町名まで一致」は一致ではない（決まり5は、完全に一致したときだけ直さない）
    assert nf.addr_match("みほん市本町1-2", "ためし県みほん市本町9-9") == "町名まで一致"
    assert nf.partner_rule(**{**BASE, "partner_addr": "ためし県みほん市本町9-9"}) == []


def test_rule3_name_taken():
    names = {"A": ("98201", "なかよし小学校"), "B": ("98201", "ためし小学校"), "C": ("98202", "なかよし小学校")}
    assert nf.name_taken(names, "B", "98201", "なかよし小学校") is True    # 同じ市区町村にもうある → 外れ
    assert nf.name_taken(names, "B", "98201", "ほか小学校") is False
    assert nf.name_taken({"B": ("98201", "なかよし小学校"), "C": ("98202", "なかよし小学校")}, "B", "98201", "なかよし小学校") is False  # 別の市区町村はよい
