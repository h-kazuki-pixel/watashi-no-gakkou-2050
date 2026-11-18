/* 計算モデルの検算。  実行:  node --test app/tests/ */
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../js/model.js");

const school = { est: [306, 262, 228, 203, 184, 168, 152, 138, 125, 113], hist: { 2000: 781, 2020: 352 } };

test("推計の補間と変化率", () => {
  const p = M.estPoints(school, null);
  assert.equal(M.interp(p, 2050), 168);
  assert.equal(M.interp(p, 2027.5), 284); // (306+262)/2
  assert.equal(M.interp(p, 1990), 306);   // 範囲外は端の値
  assert.equal(Math.round(M.pctChange(306, 168)), -45);
  assert.equal(M.pctChange(0, 10), null);
});

test("実際の児童数で補正すると全体が同じ比で動く", () => {
  const p = M.estPoints(school, 612); // 2025年推計 306 のちょうど2倍
  assert.equal(p[0].v, 612);
  assert.equal(M.interp(p, 2050), 336);
  assert.equal(M.calibFactor(school, 0), 1);
  assert.equal(M.calibFactor(school, null), 1);
});

test("過去の人数：子どもが足したデータは同じ年のデータを上書きし、2025年以降は入れない", () => {
  const h = M.histPoints(school, [{ y: 1990, v: 960 }, { y: 2000, v: 800 }, { y: 2030, v: 1 }]);
  assert.deepEqual(h.map((x) => [x.y, x.v, x.src]), [[1990, 960, "kid"], [2000, 800, "kid"], [2020, 352, "data"]]);
});

test("学級のめやす：35人学級", () => {
  const p = M.classPlan(548); // 91,91,91,91,92,92 → 各3学級
  assert.deepEqual(p.grades, [91, 91, 91, 91, 92, 92]);
  assert.equal(p.classCount, 18);
  assert.equal(p.shuffle, "all");
  assert.deepEqual(p.rows[0].classes, [31, 30, 30]);
  // 35人ちょうどは1学級、36人で2学級
  assert.equal(M.classPlan(35 * 6).classCount, 6);
  assert.equal(M.classPlan(36 * 6).classCount, 12);
  assert.equal(M.classPlan(35 * 6).shuffle, "none");
});

test("学級のめやす：複式学級（2学年で16人以下、1年生を含むと8人以下）", () => {
  // 全校48人 → 各学年8人。1・2年は16人で8人を超えるので単式、3・4年と5・6年は16人以下で複式
  const p = M.classPlan(48);
  assert.deepEqual(p.rows.map((r) => [r.grades.join("-"), r.multi]), [["1", false], ["2", false], ["3-4", true], ["5-6", true]]);
  assert.equal(p.classCount, 4);
  // 全校24人 → 各学年4人。1・2年も8人以下で複式
  const q = M.classPlan(24);
  assert.equal(q.rows.length, 3);
  assert.ok(q.rows.every((r) => r.multi));
  // 全校54人 → 各学年9人。3・4年は18人で複式にならない
  assert.ok(M.classPlan(54).rows.every((r) => !r.multi));
  assert.equal(M.classPlan(0).classCount, 0);
});

test("もしもシミュレーター", () => {
  const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} ≠ ${b}`);
  // 転入：毎年5人、6年在籍 → 2032年以降は +30人で頭打ち
  near(M.simValue(2025, 100, 5, 0), 100);
  near(M.simValue(2029, 100, 5, 0), 115);
  near(M.simValue(2050, 100, 5, 0), 130);
  // 出生：+20% は2033年入学から効きはじめ、2039年に全学年へ
  near(M.simValue(2033, 100, 0, 20), 100);
  near(M.simValue(2036, 100, 0, 20), 110);
  near(M.simValue(2050, 100, 0, 20), 120);
  near(M.simValue(2050, 10, 0, -30), 7);
});

test("年齢の階段：6〜11歳の合計が2025年推計に、1〜6歳の合計が2030年推計に一致する（サンプルの近似）", () => {
  const a = M.agesFor(school, null);
  const sum = (i, j) => a.slice(i, j + 1).reduce((s, v) => s + v, 0);
  assert.ok(Math.abs(sum(6, 11) - 306) < 1e-6);
  assert.ok(Math.abs(sum(1, 6) - 262) < 1e-6);
  const k5 = M.elementaryAfter(a, 5);
  assert.ok(k5.known && Math.abs(k5.sum - 262) < 1e-6);
  assert.equal(M.elementaryAfter(a, 6).known, true);
  assert.equal(M.elementaryAfter(a, 7).known, false); // まだ生まれていない世代がまざる
  assert.equal(M.ageStep(a, 3)[2], null);
  assert.equal(M.ageStep(a, 3)[3], a[0]);
});

test("pipeline 出力の ages があればそれを使う", () => {
  const s2 = { est: [60, 50, 0, 0, 0, 0, 0, 0, 0, 0], ages: [8, 8, 8, 8, 8, 10, 10, 10, 10, 10, 10, 10] };
  assert.deepEqual(M.agesFor(s2, 120), s2.ages.map((v) => v * 2));
});

test("2050年の年齢・予想の判定・目もり", () => {
  assert.equal(M.ageIn("e4", 2050), 34);
  assert.equal(M.ageIn("j3", 2050), 39);
  assert.equal(M.ageIn("adult", 2050), null);
  assert.equal(M.judgeGuess(170, 168).level, "close");
  assert.equal(M.judgeGuess(200, 168).level, "near");
  assert.equal(M.judgeGuess(559, 168).level, "far");
  assert.equal(M.judgeGuess(9, 8).level, "close"); // 小さな学校は人数の幅で判定
  assert.equal(M.niceMax(1054), 1200);
  assert.deepEqual(M.niceTicks(1500, 4), [0, 500, 1000, 1500]);
});

test("学年別漢字配当表：学年ごとの字数と、語の学年", () => {
  const K = require("../js/kanji-grade.js");
  const counts = [1, 2, 3, 4, 5, 6].map((g) => [...K.TABLE[g]].length);
  assert.deepEqual(counts, [80, 160, 200, 202, 193, 191]);
  const all = [1, 2, 3, 4, 5, 6].map((g) => K.TABLE[g]).join("");
  assert.equal(new Set(all).size, 1026); // 重複なし
  assert.equal(K.gradeOf("学校"), 1);
  assert.equal(K.gradeOf("教育委員会"), 3); // 教2・育3・委3・員3・会2
  assert.equal(K.gradeOf("岡"), 4);         // 2020年度から4年（都道府県名の漢字）
  assert.equal(K.gradeOf("修了"), 7);       // 修は5年、了は配当表に無い（中学）→ 7
  assert.equal(K.gradeOf("鬱"), 7);         // 配当表に無い漢字
  assert.equal(K.gradeOf("ふりがな"), 0);   // 漢字なし
});

test("学校をさがす：先頭の設置者を外して比べる", () => {
  assert.equal(M.schoolQuery("福岡市立西新小学校"), "西新小学校");
  assert.equal(M.schoolQuery("福岡市立"), "");
  assert.equal(M.schoolQuery(" 岡垣町立 吉木 "), "吉木");
  assert.equal(M.schoolQuery("東村立"), "");
  assert.equal(M.schoolQuery("千代田区立麹町小"), "麹町小");
  assert.equal(M.schoolQuery("〇〇学校組合立△△小学校"), "△△小学校");
  assert.equal(M.schoolQuery("西新"), "西新");           // 設置者が無ければそのまま
  assert.equal(M.schoolQuery("立花小学校"), "立花小学校"); // 「立」だけでは外さない
  assert.equal(M.matchSchool("西新小学校", "福岡市立西新小学校"), true);
  assert.equal(M.matchSchool("西新小学校", "福岡市立"), true); // 空になったら全部
  assert.equal(M.matchSchool("西新小学校", ""), true);
  assert.equal(M.matchSchool("西新小学校", "福岡市立百道小学校"), false);
});

test("学校をさがす：ひらがな・カタカナ・異体字・「ヶ」でも見つかる", () => {
  const ryuo = { name: "龍王小学校", kana: ["りゅうおうしょうがっこう"] };
  const kita = { name: "竜王北小学校", kana: ["りゅうおうきたしょうがっこう"] };
  const mii = { name: "三入小学校", kana: ["みいりしょうがっこう", "さんにゅうしょうがっこう"] };
  const nokana = { name: "龍王小学校" };
  // 平仮名：読みのどれかに含まれれば合う（途中から打っても出る）
  assert.equal(M.matchSchool(ryuo, "りゅうおう"), true);
  assert.equal(M.matchSchool(ryuo, "おう"), true);
  assert.equal(M.matchSchool(ryuo, "りゅうおうきた"), false);
  assert.equal(M.matchSchool(kita, "りゅうおうきた"), true);
  assert.equal(M.matchSchool(mii, "みいり"), true);
  assert.equal(M.matchSchool(mii, "さんにゅう"), true);   // 読みは2つまで
  // 片仮名・半角片仮名は平仮名にそろえる
  assert.equal(M.matchSchool(ryuo, "リュウオウ"), true);
  assert.equal(M.matchSchool(ryuo, "ﾘｭｳｵｳ"), true);
  assert.equal(M.schoolQuery("ﾘｭｳｵｳｷﾀ"), "りゆうおうきた"); // 小さい字も大きくそろえる
  assert.equal(M.matchSchool({ name: "あずま小中学校" }, "アズマ"), true); // 名前の かな は読みが無くても合う
  // 「ー」を含む平仮名
  assert.equal(M.matchSchool({ name: "ルーテル学院小学校", kana: ["るーてるがくいんしょうがっこう"] }, "るーてる"), true);
  // 異体字：学校名と入力の両方を寄せる
  assert.equal(M.matchSchool(ryuo, "竜王"), true);
  assert.equal(M.matchSchool(kita, "龍王北"), true);
  assert.equal(M.matchSchool({ name: "髙島小学校" }, "高島"), true);
  assert.equal(M.matchSchool({ name: "山﨑小学校" }, "山崎"), true);
  assert.equal(M.matchSchool({ name: "長嶋小学校" }, "長島小"), true);
  // 「ヶ・ケ・が」
  assert.equal(M.matchSchool({ name: "霞ヶ丘小学校" }, "霞ケ丘"), true);
  assert.equal(M.matchSchool({ name: "霞ケ丘小学校" }, "霞が丘"), true);
  assert.equal(M.matchSchool({ name: "霞が丘小学校" }, "霞ヶ丘"), true);
  assert.equal(M.foldText("ケヤキ"), "けやき"); // 漢字の後でない「ケ」は寄せない
  // 全角英数・空白
  assert.equal(M.matchSchool({ name: "第1小学校" }, "第１"), true);
  assert.equal(M.matchSchool({ name: "第1小学校" }, " 第 1 "), true);
  // 設置者つきの入力
  assert.equal(M.matchSchool(ryuo, "東広島市立龍王"), true);
  assert.equal(M.matchSchool(kita, "甲斐市立 竜王北小学校"), true);
  // 漢字とかなが混ざった入力は、学校名とだけ比べる（読みとは比べない）
  assert.equal(M.matchSchool(ryuo, "龍おう"), false);
  assert.equal(M.matchSchool({ name: "さくら台小学校", kana: ["さくらだいしょうがっこう"] }, "さくら台"), true);
  assert.equal(M.matchSchool({ name: "さくら台小学校", kana: ["さくらだいしょうがっこう"] }, "さくらだい"), true);
  // 空の入力は全部
  assert.equal(M.matchSchool(ryuo, ""), true);
  assert.equal(M.matchSchool(ryuo, "　"), true);
  assert.equal(M.matchSchool(nokana, ""), true);
  // 読み（kana）が無い学校は、平仮名の入力では出ない（漢字の入力では出る）
  assert.equal(M.matchSchool(nokana, "りゅうおう"), false);
  assert.equal(M.matchSchool(nokana, "龍王"), true);
  assert.equal(M.matchSchool({ name: "龍王小学校", kana: [] }, "りゅうおう"), false);
  // 学校名の文字列だけを渡したとき（前の呼び方）も動く
  assert.equal(M.matchSchool("龍王小学校", "竜王"), true);
  assert.equal(M.matchSchool("龍王小学校", "りゅうおう"), false);
  // 小さい字は大きい字にそろえる（町字データの読みは「じゆうもんじ」のように大きく書いてある）
  assert.equal(M.matchSchool({ name: "十文字小学校", kana: ["じゆうもんじしょうがつこう"] }, "じゅうもんじ"), true);
  assert.equal(M.matchSchool({ name: "中央小学校", kana: ["ちゆうおうしようがつこう"] }, "ちゅうおう"), true);
  assert.equal(M.matchSchool({ name: "中央小学校", kana: ["ちゆうおうしようがつこう"] }, "チュウオウ"), true);
  assert.equal(M.matchSchool({ name: "中央小学校", kana: ["ちゅうおうしょうがっこう"] }, "ちゆうおう"), true); // 逆も
  assert.equal(M.foldText("ぁぃぅぇぉっゃゅょゎゕゖ"), "あいうえおつやゆよわかけ");
  assert.equal(M.schoolQuery("ジュウモンジ"), "じゆうもんじ");
  assert.equal(M.isKanaQuery("りゅうおー"), true);
  assert.equal(M.isKanaQuery("りゅう王"), false);
});

test("年齢の階段：整数の小学生の合計が、ステップ1の人数とそろう（いわき市 三阪小）", () => {
  const s = { est: [12.5, 15.1, 17.6, 18.5, 18.3, 14.2, 10.4, 8.2, 7.4, 7.8],
              ages: [2.9, 2.9, 2.9, 2.9, 2.9, 1.8, 1.8, 1.8, 1.8, 1.8, 2.6, 2.6] };
  const now = M.estPoints(s, null)[0].v;
  const I = M.cohortInts(M.agesFor(s, null), now);
  assert.equal(I.length, 12);
  assert.ok(I.every((v) => Number.isInteger(v) && v >= 0));
  assert.equal(M.elementaryAfter(I, 0).sum, Math.round(now)); // 13（各歳を丸めると14、小数の合計は12.4）
  // 各歳の整数は、小数の値と1人未満しかずれない
  const ag = M.agesFor(s, null), k = now / ag.slice(6).reduce((a, b) => a + b, 0);
  I.forEach((v, j) => assert.ok(Math.abs(v - ag[j] * k) < 1));
  // 年を進めても、どの6本の合計も小数の合計と1人未満
  for (let step = 1; step <= 6; step++) {
    const r = M.elementaryAfter(I, step), t = M.elementaryAfter(ag.map((v) => v * k), step);
    assert.ok(Math.abs(r.sum - t.sum) < 1, step);
  }
});

test("年齢の階段：補正（いまの実際の人数）を入れても合計がそろう。0.5ちょうども同じ丸め", () => {
  const s = { est: [12.5, 15.1, 17.6, 18.5, 18.3, 14.2, 10.4, 8.2, 7.4, 7.8],
              ages: [2.9, 2.9, 2.9, 2.9, 2.9, 1.8, 1.8, 1.8, 1.8, 1.8, 2.6, 2.6] };
  [20, 7, 306, 1234].forEach((calib) => {
    const now = M.estPoints(s, calib)[0].v;
    assert.equal(M.elementaryAfter(M.cohortInts(M.agesFor(s, calib), now), 0).sum, Math.round(now));
  });
  assert.equal(M.elementaryAfter(M.cohortInts([0, 0, 0, 0, 0, 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.0], 1.5), 0).sum, 2);
});

test("変化率は画面に出す丸めた人数から出す", () => {
  assert.equal(Math.round(M.shownPct(9.3, 5.7)), -33);  // 9人 → 6人。小数のままだと −39%
  assert.equal(Math.round(M.shownPct(306, 168)), -45);
  assert.equal(M.shownPct(0.4, 3), null);                // 0人からの変化率は出さない
});

/* ---------------- クラスモード：よそうのコード ---------------- */
const DRAW = { 2030: 300.4, 2035: 280, 2040: 250.6, 2045: 230, 2050: 210 };
const G1 = { pref: "34", school: "B134210003686", guess: "down", draw: DRAW, reason: "近くに 新しい 家が ふえているから" };

test("コード：作る → 読む で元にもどる（日本語の理由・空の理由）", () => {
  const c = M.encodeGuess(G1);
  assert.match(c, /^WG50-[A-Za-z0-9_-]+$/);
  const d = M.decodeGuess(c);
  assert.equal(d.ok, true);
  assert.deepEqual([d.pref, d.school, d.guess, d.reason], ["34", "B134210003686", "down", "近くに 新しい 家が ふえているから"]);
  assert.deepEqual(d.draw, { 2030: 300, 2035: 280, 2040: 251, 2045: 230, 2050: 210 }); // 整数に丸める
  const e = M.decodeGuess(M.encodeGuess({ ...G1, reason: "" }));
  assert.equal(e.ok, true);
  assert.equal(e.reason, "");
  assert.equal(M.decodeGuess(M.encodeGuess({ ...G1, reason: "   " })).reason, "");
  // 絵文字（UTF-16 のペア）や記号も もどる
  assert.equal(M.decodeGuess(M.encodeGuess({ ...G1, reason: "😀 \"かぎ\" と \\ と 、。" })).reason, "😀 \"かぎ\" と \\ と 、。");
  for (const g of ["up", "same", "down"]) assert.equal(M.decodeGuess(M.encodeGuess({ ...G1, guess: g })).guess, g);
  // 名前（nick）は入らない
  const withNick = M.encodeGuess({ ...G1, nick: "たろう" });
  assert.equal(withNick, c);
  assert.equal(JSON.stringify(M.decodeGuess(withNick)).indexOf("たろう"), -1);
  // 線がそろっていない・guess が無いときは作らない
  assert.equal(M.encodeGuess({ ...G1, draw: { 2030: 1, 2035: 2 } }), null);
  assert.equal(M.encodeGuess({ ...G1, guess: null }), null);
});

test("コード：こわれたもの・別のものは読まない", () => {
  const c = M.encodeGuess(G1);
  assert.equal(M.decodeGuess(c.slice(0, -1)).ok, false);         // 最後が切れた
  assert.equal(M.decodeGuess(c.slice(0, 30)).ok, false);         // 途中で切れた
  const mid = Math.floor(c.length / 2);
  const flip = c.slice(0, mid) + (c[mid] === "A" ? "B" : "A") + c.slice(mid + 1);
  assert.equal(M.decodeGuess(flip).ok, false);                    // 1文字ちがう
  assert.equal(M.decodeGuess(flip).error, "check");
  assert.equal(M.decodeGuess("WG50-").ok, false);
  assert.equal(M.decodeGuess("WG50-abc").ok, false);
  assert.equal(M.decodeGuess("こんにちは").ok, false);
  assert.equal(M.decodeGuess("https://example.com/WG50").ok, false);
  assert.equal(M.decodeGuess(null).ok, false);
});

test("コード：まわりに文がある貼り付けから全部取り出す。同じコードは1回", () => {
  const a = M.encodeGuess(G1);
  const b = M.encodeGuess({ ...G1, guess: "up", draw: { 2030: 320, 2035: 340, 2040: 360, 2045: 380, 2050: 400 }, reason: "" });
  const other = M.encodeGuess({ ...G1, school: "B134210003613" });
  const text = `山田 花子　2026/11/20 10:31\n${a}\n\n鈴木 一郎 11月20日\nよそうです→${b}。おねがいします\n` +
    `${a}\n（もう一度 送りました）\n${b}${other}\nWG50-abcdef こわれた\n佐藤：${a.slice(0, 40)}…`;
  const r = M.extractGuesses(text);
  assert.equal(r.items.length, 3);
  assert.equal(r.dup, 2);           // a と b の2回目
  assert.equal(r.bad.length, 2);    // WG50-abcdef と 途中で切れたもの
  assert.deepEqual(r.items.map((d) => d.guess), ["down", "up", "down"]);
  assert.deepEqual(M.extractGuesses("").items, []);
  assert.deepEqual(M.extractGuesses("コードは ありません").bad, []);
  // 全角で貼られても読む
  const wide = a.replace(/[A-Za-z0-9]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) + 0xfee0));
  assert.equal(M.extractGuesses(wide).items.length, 1);
});

test("コード：学校がまじったら学校ごとに分ける（人数の多い順）", () => {
  const items = M.extractGuesses([
    M.encodeGuess(G1), M.encodeGuess({ ...G1, school: "X2" }), M.encodeGuess({ ...G1, reason: "べつ" }),
    M.encodeGuess({ ...G1, pref: "40", school: "X2" })].join(" ")).items;
  const g = M.groupGuesses(items);
  assert.deepEqual(g.map((x) => [x.pref, x.school, x.items.length]), [["34", "B134210003686", 2], ["34", "X2", 1], ["40", "X2", 1]]);
});

test("集計：最小・最大・真ん中、guess ごと、推計より多い・少ない・ほぼ同じ", () => {
  const mk = (v50, guess) => ({ guess, draw: { 2030: 1, 2035: 1, 2040: 1, 2045: 1, 2050: v50 } });
  const items = [mk(100, "down"), mk(150.4, "down"), mk(200, "same"), mk(149.6, "up"), mk(300, "up")];
  const s = M.summarizeGuesses(items, 150.2);
  assert.equal(s.n, 5);
  assert.equal(s.min, 100);
  assert.equal(s.max, 300);
  assert.equal(s.median, 150.4);
  assert.deepEqual(s.guess, { up: 2, same: 1, down: 2 });
  assert.deepEqual(s.vsEst, { more: 2, less: 1, same: 2 }); // 150.4 と 149.6 は画面の丸めで 150 → 同じ
  assert.equal(M.summarizeGuesses(items.slice(0, 4)).median, (149.6 + 150.4) / 2); // 偶数は真ん中2つの平均
  assert.equal(M.summarizeGuesses(items).vsEst, null);                        // 推計を渡さなければ出さない
  const e = M.summarizeGuesses([], 10);
  assert.deepEqual([e.n, e.min, e.max, e.median], [0, null, null, null]);
});

test("見本のクラス：架空の30人分のコード。毎回同じ", () => {
  const a = M.sampleClass("00", "S2", 306, 168, 30, 7), b = M.sampleClass("00", "S2", 306, 168, 30, 7);
  assert.equal(a.length, 30);
  assert.deepEqual(a, b);
  const r = M.extractGuesses(a.join("\n"));
  assert.equal(r.items.length + r.dup, 30);
  assert.ok(r.items.every((d) => d.pref === "00" && d.school === "S2"));
  const s = M.summarizeGuesses(r.items);
  assert.ok(s.guess.up > 0 && s.guess.same > 0 && s.guess.down > 0);
  assert.equal(r.replaced, 0); // 子どもごとに ちがう 端末の印
  // 画面の 見本（seed 2050）：データより少なく予想する子が 30人中 8〜12人
  for (const [now, e50] of [[306, 168], [548, 447], [23, 8], [451, 327]]) {
    const t = M.summarizeGuesses(M.extractGuesses(M.sampleClass("00", "S2", now, e50, 30, 2050).join("\n")).items, e50);
    assert.ok(t.vsEst.less >= 8 && t.vsEst.less <= 12, JSON.stringify([now, e50, t.vsEst]));
  }
});

test("コード：実際の人数（calib）・端末の印・番号が もどる。版1も読む", () => {
  const c = M.encodeGuess({ ...G1, calib: 412, mark: "aB3_-z", seq: 7 });
  const d = M.decodeGuess(c);
  assert.deepEqual([d.ok, d.calib, d.mark, d.seq, d.reason], [true, 412, "aB3_-z", 7, G1.reason]);
  const e = M.decodeGuess(M.encodeGuess({ ...G1, reason: "", calib: 98.6, mark: "zzzzzz", seq: 2 }));
  assert.deepEqual([e.ok, e.calib, e.reason], [true, 99, ""]);     // calib だけ
  const f = M.decodeGuess(M.encodeGuess({ ...G1, calib: null }));
  assert.deepEqual([f.ok, f.calib, f.mark, f.seq], [true, null, "", 0]); // calib・印なし
  assert.equal(M.encodeGuess({ ...G1, mark: "名前" }), M.encodeGuess({ ...G1 })); // 印の形でなければ入れない
  // 版1（印・番号・calib なし）
  const v1 = M.decodeGuess("WG50-WzEsIjAwIiwiUzEiLCJ1IiwzMDAsMjgwLDI1MCwyMzAsMjEwXQA1vyjY");
  assert.deepEqual([v1.ok, v1.pref, v1.school, v1.guess, v1.draw[2050], v1.calib, v1.mark], [true, "00", "S1", "up", 210, null, ""]);
  // 端末の印は でたらめな6文字
  const mk = M.makeMark(Math.random);
  assert.match(mk, /^[A-Za-z0-9_-]{6}$/);
  assert.equal(M.makeMark(() => 0), "AAAAAA");
});

test("コード：calib のある・無いが まじっても読む。いちばん多い calib", () => {
  const codes = [M.encodeGuess({ ...G1, calib: 412 }), M.encodeGuess({ ...G1, calib: 412, reason: "" }),
    M.encodeGuess({ ...G1, calib: 400 }), M.encodeGuess({ ...G1 }), M.encodeGuess({ ...G1, guess: "up" })];
  const r = M.extractGuesses(codes.join("\n"));
  assert.equal(r.items.length, 5);
  assert.equal(M.commonCalib(r.items), 412);
  assert.equal(M.commonCalib([{ calib: 400 }, { calib: 380 }]), 380);   // 同じ数なら小さい値
  assert.equal(M.commonCalib([{ calib: null }, {}]), null);
});

test("コード：同じ端末から2回 → 番号のいちばん大きいものだけ", () => {
  const old = M.encodeGuess({ ...G1, mark: "dev001", seq: 3, guess: "up" });
  const mid = M.encodeGuess({ ...G1, mark: "dev001", seq: 5, guess: "same" });
  const now = M.encodeGuess({ ...G1, mark: "dev001", seq: 9 });
  const other = M.encodeGuess({ ...G1, mark: "dev002", seq: 1 });
  const nomark = M.encodeGuess({ ...G1, reason: "印なし" });
  const r = M.extractGuesses([now, old, other, mid, nomark, now].join("\n"));
  assert.equal(r.items.length, 3);
  assert.equal(r.replaced, 2);
  assert.equal(r.dup, 1);
  assert.equal(r.items.find((d) => d.mark === "dev001").guess, "down");
});

test("コード：途中で改行された貼り付け（Classroom 風）を つないで読む", () => {
  const a = M.encodeGuess({ ...G1, mark: "dev0a1", seq: 1 });
  const b = M.encodeGuess({ ...G1, mark: "dev0b2", seq: 1, guess: "up", reason: "" });
  const c = M.encodeGuess({ ...G1, mark: "dev0c3", seq: 1, guess: "same", calib: 300 });
  const text = [
    "山田 花子", "11月20日 10:31", a.slice(0, 40), a.slice(40, 80), "  " + a.slice(80) + "  ", "",
    "鈴木 一郎", "11月20日 10:32", "提出しました " + b.slice(0, 33), b.slice(33),
    "佐藤", "WG50-", c.slice(5, 50), c.slice(50, 90), c.slice(90),
  ].join("\n");
  const r = M.extractGuesses(text);
  assert.deepEqual(r.items.map((d) => d.mark), ["dev0a1", "dev0b2", "dev0c3"]);
  assert.equal(r.bad.length, 0);
  // 後ろの行の頭だけを つなぐ（後ろに 名前などが 続いても読む）
  const r2 = M.extractGuesses(b.slice(0, 50) + "\n" + b.slice(50) + " 鈴木");
  assert.equal(r2.items.length, 1);
  // 5行に分かれても読む（20行まで）
  const split5 = [a.slice(0, 20), a.slice(20, 40), a.slice(40, 60), a.slice(60, 80), a.slice(80)].join("\n");
  const r3 = M.extractGuesses(split5);
  assert.deepEqual([r3.items.length, r3.bad.length], [1, 0]);
  // 改行の後ろが 別のコードなら つながない
  const r4 = M.extractGuesses(a.slice(0, 40) + "\n" + b);
  assert.deepEqual([r4.items.length, r4.bad.length], [1, 1]);
});

/* ---------------- クラスモード 第2段階：提案 ---------------- */
const IDEA_IDS = ["room_study", "room_town", "room_kids", "online", "events", "bus", "family", "pr", "play"];
const TO_IDS = ["mayor", "board", "principal", "town", "family"];
const PROP = {
  sort: { c1: "good", c2: "bad", c3: "mid", c5: "good", c8: "bad" },
  ideas: ["room_study", "online", "family"], ownIdea: "校庭で 月に 1回、朝市を ひらく", to: "mayor",
  proposal: "空いた 教室を 地域の 人も 使える 場所に して ほしいです。\n2行目も あります。"
};
const FULL = { ...G1, calib: 412, mark: "dev123", seq: 9, nick: "はなこ", grade: "e5", prop: { ...PROP, nick: "はなこ" } };

test("提案：全部入りのコードを作る → 読むで元にもどる。名前・学年は入らない", () => {
  const c = M.encodeGuess(FULL);
  const d = M.decodeGuess(c);
  assert.equal(d.ok, true);
  assert.deepEqual([d.pref, d.school, d.guess, d.reason, d.calib, d.mark, d.seq], ["34", "B134210003686", "down", G1.reason, 412, "dev123", 9]);
  assert.deepEqual(d.prop, {
    sort: { c1: "good", c2: "bad", c3: "mid", c5: "good", c8: "bad" }, ideas: ["room_study", "online", "family"],
    ownIdea: "校庭で 月に 1回、朝市を ひらく", to: "mayor", proposal: "空いた 教室を 地域の 人も 使える 場所に して ほしいです。 2行目も あります。"
  });
  const json = JSON.stringify(d);
  assert.equal(json.indexOf("はなこ"), -1);
  assert.equal(json.indexOf("e5"), -1);
  // 空の提案（カードだけ・何も えらばない）も 読む
  const e = M.decodeGuess(M.encodeGuess({ ...G1, prop: {} }));
  assert.deepEqual(e.prop, { sort: {}, ideas: [], ownIdea: "", to: "", proposal: "" });
  assert.equal(e.calib, null);
  // 第1段階（提案なし）は prop が null
  assert.equal(M.decodeGuess(M.encodeGuess(G1)).prop, null);
  // 長さ（提案110字・自分のアイデア40字・理由60字）
  const long = M.encodeGuess({ ...FULL, reason: "あ".repeat(60), prop: { ...PROP, ownIdea: "い".repeat(40), proposal: "う".repeat(110) } });
  assert.ok(long.length > 900 && long.length < 1200, long.length);
  assert.equal(M.decodeGuess(long).prop.proposal, "う".repeat(110));
  // 形のおかしい 提案は 読まない
  const bad = M.encodeGuess({ ...G1, prop: { ideas: ["<script>"] } });
  assert.equal(M.decodeGuess(bad).prop.ideas.length, 0); // 作るときに 外す
});

test("提案：第1段階のコードとまぜて読む。同じ端末なら ステップ5のコードに入れかわる", () => {
  const step2 = M.encodeGuess({ ...G1, mark: "devAAA", seq: 3 });
  const step5 = M.encodeGuess({ ...G1, mark: "devAAA", seq: 4, prop: PROP });
  const other = M.encodeGuess({ ...G1, mark: "devBBB", seq: 1 });
  const v1 = "WG50-WzEsIjAwIiwiUzEiLCJ1IiwzMDAsMjgwLDI1MCwyMzAsMjEwXQA1vyjY";
  const r = M.extractGuesses([step2, other, step5, v1].join("\n"));
  assert.equal(r.items.length, 3);
  assert.equal(r.replaced, 1);
  const a = r.items.find((d) => d.mark === "devAAA");
  assert.ok(a.prop && a.seq === 4);
  assert.equal(r.items.find((d) => d.mark === "devBBB").prop, null);
  // 古いほうが後に貼られても、番号の大きいほう
  const r2 = M.extractGuesses([step5, step2].join("\n"));
  assert.deepEqual([r2.items.length, r2.items[0].seq], [1, 4]);
});

test("提案：20行に折れた貼り付けを読む。21行以上・ほかのコードで始まる行は つながない", () => {
  const c = M.encodeGuess(FULL);
  const chunk = Math.ceil((c.length - 5) / 20);
  const lines = [];
  for (let i = 0; i < c.length; i += chunk) lines.push(c.slice(i, i + chunk));
  assert.ok(lines.length >= 20 && lines.length <= 21, lines.length);
  const ok = lines.length === 21 ? [lines[0] + lines[1]].concat(lines.slice(2)) : lines; // 1行目＋20行
  const r = M.extractGuesses("山田 花子 11月20日\n" + ok.join("\n") + "\n鈴木 一郎");
  assert.deepEqual([r.items.length, r.bad.length], [1, 0]);
  assert.equal(r.items[0].prop.ownIdea, PROP.ownIdea);
  // 22行に分かれたもの（1行目＋21行）は読まない
  const many = [];
  const ch2 = Math.ceil(c.length / 22);
  for (let i = 0; i < c.length; i += ch2) many.push(c.slice(i, i + ch2));
  assert.ok(many.length >= 22);
  assert.deepEqual(M.extractGuesses(many.join("\n")).items.length, 0);
  // 途中の行の後ろに 別のコードが 来たら そこで止める（別のコードは そのまま読む）
  const g = M.encodeGuess({ ...G1, mark: "devZZZ", seq: 1 });
  const cl = M.encodeGuess({ ...FULL, prop: { ...PROP, proposal: "う".repeat(110) } });
  assert.ok(cl.length > 700);
  const r3 = M.extractGuesses([cl.slice(0, 300), cl.slice(300, 600), g, cl.slice(600)].join("\n"));
  assert.deepEqual([r3.items.length, r3.items[0].mark, r3.bad.length], [1, "devZZZ", 1]);
  // 空白だけの行を はさんでも つなぐ（行の頭の空白は 除く）
  const r4 = M.extractGuesses(c.slice(0, 500) + "\n   " + c.slice(500));
  assert.equal(r4.items.length, 1);
});

test("提案：集計（カードごと・アイデアの順位・自分のアイデア・宛先ごと）", () => {
  const mk = (p, extra) => M.decodeGuess(M.encodeGuess({ ...G1, ...extra, prop: p }));
  const items = [
    mk({ sort: { c1: "good", c2: "bad" }, ideas: ["online", "room_study"], to: "mayor", proposal: "A" }, { mark: "m00001" }),
    mk({ sort: { c1: "good", c2: "mid" }, ideas: ["room_study"], to: "board", proposal: "B", ownIdea: "朝市" }, { mark: "m00002" }),
    mk({ sort: { c1: "bad" }, ideas: ["online", "family"], to: "mayor", proposal: "C" }, { mark: "m00003" }),
    mk({ sort: {}, ideas: ["bus"], to: "town", proposal: "" }, { mark: "m00004" }),          // 文なし → 宛先の一覧に入らない
    M.decodeGuess(M.encodeGuess({ ...G1, mark: "m00005" }))                                   // 提案なし → 数えない
  ];
  const st = M.sortTally(items);
  assert.deepEqual(st.c1, { good: 2, bad: 1, mid: 0 });
  assert.deepEqual(st.c2, { good: 0, bad: 1, mid: 1 });
  assert.deepEqual(st.c8, { good: 0, bad: 0, mid: 0 });
  assert.deepEqual(Object.keys(st), M.SORT_IDS);
  assert.deepEqual(M.ideaTally(items, IDEA_IDS), [
    { id: "room_study", n: 2 }, { id: "online", n: 2 }, { id: "bus", n: 1 }, { id: "family", n: 1 }]); // 同じ数は order の順
  assert.deepEqual(M.ownIdeas(items), ["朝市"]);
  const by = M.proposalsByTo(items, TO_IDS);
  assert.deepEqual(by.map((g) => [g.to, g.items.map((d) => d.prop.proposal)]), [["mayor", ["A", "C"]], ["board", ["B"]]]);
  assert.deepEqual(M.proposalsByTo([], TO_IDS), []);
});

test("見本のクラス：架空の提案も入る。よそうの値は第1段階と同じ", () => {
  const a = M.sampleClass("00", "S2", 306, 168, 30, 2050, IDEA_IDS);
  assert.deepEqual(a, M.sampleClass("00", "S2", 306, 168, 30, 2050, IDEA_IDS)); // 毎回同じ
  const plain = M.extractGuesses(M.sampleClass("00", "S2", 306, 168, 30, 2050).join("\n")).items;
  const r = M.extractGuesses(a.join("\n")).items;
  assert.deepEqual(r.map((d) => d.draw), plain.map((d) => d.draw));
  const withP = r.filter((d) => d.prop);
  assert.ok(withP.length >= 18 && withP.length < 30, withP.length);
  const by = M.proposalsByTo(r, TO_IDS);
  assert.ok(by.length >= 4, by.map((g) => g.to)); // 宛先が ばらける
  assert.ok(M.ideaTally(r, IDEA_IDS).length >= 5);
  assert.ok(M.ownIdeas(r).length >= 2);
});
