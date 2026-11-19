# わたしの学校2050 — 開発メモ（Claude Code 用）

アーバンデータチャレンジ2026 応募作品。子どもが自分の学校の将来の児童数を予想し、データで確かめ、まちに提案する学習アプリ。全体像は `README.md`、予定は `docs/ROADMAP.md`。

## コマンド

```bash
node --test app/tests/model.test.js     # 計算モデル
python3 -m pytest pipeline/tests -q     # パイプライン
python3 tools/e2e_check.py              # ブラウザ通し（サンプル）。ふりがな漏れも検出する
python3 tools/e2e_realdata.py           # パイプライン出力 → アプリ（--prefs 01,13,... で app/data の実データ）
```

変更したら4つとも通すこと。画面を変えたら `tools/_shots/` のスクリーンショットを目で見る。

## クラウド（claude.ai/code）で作業するとき

- `data_raw/` と `opendata/` はありません（リポジトリに入れていないため）。元データが要る作業（`build-all`、`tools/independent_check.py`、元データとの照合）はクラウドでせず、Mac で行う。
- ネットワークで断られたら（プロキシの 403・502、名前が引けない など）、別のホストやミラー、別の手段で回り込まない。断られたホスト名を報告して、そこで止める。
- 終わるのを待つときに `pgrep` を使わない（自分のコマンド行にも当たって、終わらない待ちになる）。前で動かすか、バックグラウンドの完了通知を待つ。

## 守ること

- **ビルドなし・サーバーなし。** `app/index.html` を file:// で開いて動くこと。ES モジュールと fetch は使わない（データは `<script>` で読む）。
- **外部に何も送らない。** 解析タグ、外部 API、氏名の入力欄を足さない。保存は localStorage だけ。
- **計算は `app/js/model.js` に置く。** 画面のコードに数式を書かない。足したらテストも足す。
- **子ども向けの文章**は分かち書き。漢字を足したら `app/js/ruby-dict.js` に読みを足し、`e2e_check.py` で漏れを確かめる。数字の後の「年」「人」は辞書に入れない。
- **学校名や子どもの入力**を HTML に入れるときは `UG.nr()`（エスケープし、ふりがな処理から外す）。
- **グラフの色**は役割で固定：青＝きみのよそう（点線）、赤＝データ（実線）、青緑＝もしも（破線）。文字はインク色のままにし、色は丸や線で示す。
- **画面ごとにイベントを付け直す。** `UG.render` が `#view` を作り直すので、ハンドラは `root` かその中の要素に付ける。`document` に付けるのは `main.js` だけ。
- **統合・廃校を予測したり勧めたりする表示は足さない。** 推計は「前提つきの計算」として扱う。
- 練習用の「みらい市」は架空。実在の地名や実データに見える値を足さない。
- **画面の文字や学校名に新しい字を足したら**、`python3 tools/build_fonts.py <TTF のフォルダ>` で `app/fonts` の書体を作り直す（手順は `README.md`）。

## データ形式（`UG.registerPref`）

```js
{ code: "13", name: "東京都", generated: "2026-11-20", source: {...},
  cities: [{ code: "13101", name: "千代田区",
    approx: true | 無し,   // 学区データが無く（または利用条件で除き）、学校の位置から「おおよその区域」を作った市区町村
    note:   true | 無し,   // 学区データの利用条件が「条件公開」か特記条件つき。画面に「学区は めやす」と出す
    combined: true | 無し, // 国の推計が複数の市町村をまとめた区域（福島県浜通り 07999）。画面に「まとめて 計算」の注意書きを出す
    schools: [{ id, name, lng, lat,
      kana: ["りゅうおうしょうがっこう"] | 無し, // 学校名全体の読み（平仮名、1〜2個）。ひらがなで さがすときだけ使い、画面には出さない（add-kana が足す）
      approx: true | 無し, // おおよその区域の学校（geom は割り当てた点の凸包）
      est:  [2025, 2030, …, 2070 の 6〜11歳推計],   // 10個
      ages: [0〜11歳の各歳（2025年）],              // 12個。無ければアプリが est から近似
      hist: { 年: 人数 } | 無し,
      geom: [[[lng, lat], …]],                       // 表示用に間引いた外周
      gone: true | 無し,      // 学区データより後に閉校した学校（文科省「学校コード」。決まりは docs/DATA_METHOD.md。人数・区域はそのまま）
      now: { name, id | 無し } | 無し,  // gone の学校の移行先。id はアプリにあるときだけ（無ければ newSchools に入るはず）
      joined: [{ id, name }] | 無し }] }], // この学校を移行先とする gone の学校（人数は足さない）
  missing: [{ code: "13102", name: "中央区" | "",     // 学区データも学校の位置も無く、計算できなかった市区町村（空のこともある）
              nothandled: true | 無し }],             // このアプリでは扱わない市区町村（福島県浜通りの7町村）
  newSchools: [{ muni: "13101", name, kana: [...] | 無し, from: [id, …] }] | 無し }  // 統合などでできた新しい学校（人数・区域なし）。add-closures が足す
```

## 実データ

ダウンロードした zip を `data_raw/` に入れて `python3 pipeline/build_school_data.py build-all --input data_raw --out app/data --opendata opendata`。列の並びは公式コード表どおりで、テストの合成データもその並び。全国47都道府県が実データで動作（1,808市区町村・18,681校、うち3,601校は学校の位置から補ったおおよその区域。福島県の7町村は扱わない）。全国をまとめて作り直すのは `tools/national_dryrun.py`、扱いの一覧は `tools/coverage_doc.py` → `docs/COVERAGE.md`。元データの誤記は `pipeline/terms/source_corrections.csv` で直す（市区町村名は `pipeline/terms/city_names.csv`）。閉校の印（`gone`・`now`・`joined`・`newSchools`）は `make-closures`（Mac。文科省「学校コード」と `tools/capture_school_codes.py` の id → 学校コードの表）→ `add-closures`（`build-all` の最後でも呼ぶ）で足す。決まりは `docs/DATA_METHOD.md`「学区データより後に閉校した学校」。今も続いている学校に印を付けないことを最優先にし、決まりを緩めない。学校名の読み（`kana`）は `make-kana`（町字データと辞書。Mac で）→ `add-kana`（`build-all` の最後でも呼ぶ）で足す。決まりと手順は `docs/DATA_METHOD.md`「学校名の読み」、読みのある県は `data/index.js` に `kana: true`。作り直すときは `docs/DATA_METHOD.md` の「まだ確かめていないこと」を上から潰す。判定が外れたら、決め打ちに書き換えるのではなく、判定ロジックとテストのフィクスチャを実物の形に合わせて直す。
