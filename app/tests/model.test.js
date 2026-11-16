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
