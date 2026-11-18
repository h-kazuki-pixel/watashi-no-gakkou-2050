# わたしの学校2050

**2050年、わたしの学校は何人？** 国の将来推計人口を小学校区ごとに集計し、子どもが「予想する → データで確かめる → 理由を探る → まちに提案する」までを一巡する学習アプリです。アーバンデータチャレンジ2026（テーマ：教育・政治、データキッズ賞）への応募作品として開発しています。

- 対象：小学5年生〜中学3年生（ふりがな付き。4年生から使えます）
- 動作：ブラウザだけ。ログイン・インストール・サーバー不要。`app/index.html` を開けばオフラインでも動きます
- 端末：タブレットかパソコンでの利用をおすすめします（線をかく画面やグラフが見やすいため）。スマートフォンでも使えます（下の「利用する端末」）
- 個人情報：氏名を求めません。入力はブラウザ内にだけ保存し、外部へ送信しません

## いまの状態（2026-11-17）

| 部分 | 状態 |
|---|---|
| アプリ（5ステップ＋先生向けページ） | 動作。架空のまち「みらい市」と、47都道府県の実データで全ステップを通せる |
| クラスモード（第1段階：予想を集める／第2段階：提案を集める） | ステップ2・5の「先生に ○○を わたす」でコード（名前なし）を出し、先生が「クラスで 見る」（`#class`）にまとめて貼ると、全員の線・2050年の散らばり・理由の一覧と、カードごとの いいね／しんぱい・アイデアの順位・宛先ごとの提案を映せる。宛先ごとに A4縦1枚に印刷できる。読んだコードは保存しない |
| 全国データ | **実データで動作**（国土数値情報の実ファイルから生成、2026-11-17）。47都道府県・1,808市区町村・18,681校。うち3,601校は、学校の位置から作った「おおよその区域」で計算：学区データが無い（または利用条件などで使わない）214市区町村の3,537校と、学区データのある市区町村で学区データに入っていなかった64校。福島県の浜通りの7町村は扱わない。市区町村ごとの扱いは [`docs/COVERAGE.md`](docs/COVERAGE.md) |
| 計算モデル | テスト 11件 合格（`node --test`） |
| データ生成パイプライン | テスト 66件 合格（`pytest`）。テスト用データは公式コード表と同じ列の並び（秘匿メッシュ・合算先メッシュを含む） |
| ブラウザ通しテスト | 2本（サンプル経路・パイプライン出力経路）とも合格（Chromium。パイプライン出力経路は、合成データと、実データの北海道・東京都・神奈川県・京都府・福島県・沖縄県。下の「利用する端末」） |
| 推計の確かめ | 別の実装での計算し直し（`tools/independent_check.py`。47都道府県とも一致）、学区の代わりにいちばん近い学校を使ったときのずれ（47都道府県）、福岡市・北九州市・久留米市の実際の児童数との照合（市ごとの集計。照合は福岡県の3市だけ。`docs/ACCURACY.md`） |
| 公開 | `main` に push すると、テストを通したうえで GitHub Pages に自動公開（`.github/workflows/pages.yml`） |

作り直すときは、`inspect` の表示を必ず見てください（`docs/DATA_METHOD.md`）。全国をまとめて作り直すときは `tools/national_dryrun.py`（県ごとにダウンロード・inspect・build・validate-approx・independent_check）。

## 利用する端末

タブレットかパソコンでの利用をおすすめします（線をかく画面やグラフが見やすいため）。スマートフォンでも使えます。子ども向けの画面には端末の案内を出しません（スマートフォンで開いた子も、そのまま進めます）。

確かめてある範囲：

| 確かめ方 | 画面の幅 | ブラウザ |
|---|---|---|
| 自動テスト（`tools/e2e_check.py`） | PC の幅（1180px）で全ステップ。スマートフォンの幅（390px・320px）では、ステップ2・3の配置（「かきなおす」の位置、教室の箱の数字が折れないこと など）とタッチ端末での表示 | Chromium |
| 自動テスト（`tools/e2e_realdata.py`。`--prefs` で実データの県を選ぶ） | PC の幅（1180px） | Chromium |
| 開発中の画面の確認（スクリーンショットを撮って目で見る。自動テストには入っていない） | スマートフォンの幅（390px・320px）、タブレットの幅（820px）、PC の幅（1180px） | Chromium と WebKit（iPhone・iPad の Safari と同じ描画エンジン） |

タブレットと Chromebook の実機では、まだ確かめていません（最終調整のときに確かめる予定）。

## 動かす

```bash
# アプリ：ファイルを開くだけ
open app/index.html            # macOS。Windows はダブルクリック

# テスト
node --test app/tests/model.test.js        # 計算モデル
python3 -m pytest pipeline/tests -q        # パイプライン（numpy, pandas, pytest）
python3 tools/e2e_check.py                 # ブラウザで全ステップ（playwright。Chrome が無ければ付属の Chromium）
python3 tools/e2e_realdata.py              # パイプライン出力をアプリが読めるか（合成データ）
python3 tools/e2e_realdata.py --prefs 01,13,14:横浜市,26:京都市東山区,07:いわき市,47   # app/data の実データ
python3 tools/compare_actual.py            # 実際の児童数との照合（pdfplumber。PDF は data_raw/actual/ に置く。docs/ACCURACY.md）
```

## 実データを入れる

国土数値情報ダウンロードサイトから、入れたい都道府県の次の3つをダウンロードし、**zip のまま** `data_raw/` に入れます（`app/data/` は出力先なので、ここには入れない）。

1. 小学校区データ
2. 500mメッシュ別将来推計人口（R6国政局推計）。CSV・シェープファイル・GML のどれでもよい（CSV が最も速い）
3. 学校（学校の位置）。小学校区データが無い市区町村（福岡市・北九州市・東京都品川区など）を「おおよその区域」で補うのに使う

```bash
# どれが学区でどれがメッシュか、どの県かは中身から判定する
python3 pipeline/build_school_data.py build-all --input data_raw --out app/data --opendata opendata
```

1県だけ確かめたいときは、先に `inspect` で判定結果を見ます。

```bash
python3 pipeline/build_school_data.py inspect --districts data_raw/<学区>.zip --mesh data_raw/<メッシュ>.zip
python3 pipeline/build_school_data.py build   --districts data_raw/<学区>.zip --mesh data_raw/<メッシュ>.zip --out app/data --opendata opendata
```

`opendata/report_XX.json` の `approx_cities`（おおよその区域で補った市区町村）、`missing_cities`（補えなかった市区町村）、`unassigned_share_2025`（学区に入らなかった子どもの割合）と `city_coverage_2025`（市区町村ごとの配分率）を確かめてから公開してください。生成後にアプリを開くと、はじめの画面に都道府県と市区町村の選択が現れます。

### 学校名の読み（ひらがなで さがす）

学校名の読み（`kana`）は、アドレス・ベース・レジストリ（デジタル庁）の町字データと辞書（SudachiPy）から作ります。町字データはリポジトリに入れず、`~/work/abr` などに置きます。

```bash
python3 -m pip install -r pipeline/requirements-kana.txt
python3 pipeline/build_school_data.py make-kana --town ~/work/abr/mt_town_all.csv.zip --check-columns
python3 pipeline/build_school_data.py make-kana --town ~/work/abr/mt_town_all.csv.zip
python3 pipeline/build_school_data.py add-kana
```

取りに行く URL、列名の確かめ方、決まりは `docs/DATA_METHOD.md`「学校名の読み」、結果は `docs/KANA.md`。`build-all` は最後に `add-kana` を呼ぶので、作り直しても読みは付き直ります（学校コードの無い学校は、作り直したら `make-kana` もかけ直す）。

作り直して前と比べるときは、生成日を決めて（`--generated 2026-11-16`）作り、`tools/compare_builds.py` で前の出力と比べます（生成日・実行時間・`validate_approx` 以外の違いを学校単位で出します）。

## 構成

```
app/                 アプリ本体（ビルド不要の HTML/CSS/JS）
  js/model.js          計算（学級数、もしも、年齢の階段）。画面に依存しない
  js/chart.js          グラフと地図（ライブラリなしの SVG）
  js/views1.js, views2.js  画面
  js/classmode.js      クラスで 見る（よそうのコードを まとめて 読む。計算は model.js）
  js/ruby-dict.js      ふりがな辞書
  data/sample.js       架空のまち「みらい市」
  data/index.js, pref_XX.js  実データ（パイプラインが生成）
  fonts/               同梱の書体（使う文字だけの woff2。tools/build_fonts.py が作る。SIL OFL 1.1）
pipeline/            学区 × メッシュ → 学区別の将来児童数
  build_school_data.py   コマンド（inspect / build / build-all / make-kana / add-kana）
  school2050/            zip の中身判定、メッシュコード、幾何、読み込み、配分、書き出し、学校名の読み（kana.py）
  tests/                 手計算できる合成データでの検算
tools/               ブラウザ通しテスト（e2e_check, e2e_realdata）、書体の作成（build_fonts）、別の実装での検算（independent_check）、
                     実際の児童数との照合（compare_actual。pdfplumber が必要。入力は data_raw/actual/ に置き、リポジトリには入れない）
docs/                応募文、授業案、データと方法、推計の当たり具合（ACCURACY）、ロードマップ
```

## データの出典

`app/data/` のデータは、次のデータを「わたしの学校2050」（h-kazuki-pixel）が加工して作成したものです。国が作成したものではありません。

| 範囲 | 出典 |
|---|---|
| 47都道府県 | 出典：「国土数値情報（小学校区データ）」（国土交通省）（<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A27-2023.html>）、「国土数値情報（500mメッシュ別将来推計人口データ）」（国土交通省）（<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-mesh500r6.html>）、「国土数値情報（学校データ）」（国土交通省）（<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P29-2023.html>）（いずれも2026年11月16日取得。福岡県だけ2026年11月14日取得）を加工して作成。加工：わたしの学校2050（h-kazuki-pixel） |

- 県ごとの出典は `pref_XX.js` の `source`（`datasets`：データの名前・ページ・取得日、`processor`：加工者、`credit`：表示の文）にあり、アプリの先生向けページに県ごとに出ます。
- 取得日は、ダウンロードしたときに記録して `build --retrieved YYYY-MM-DD`（`build-all` は `--retrieved` か、`data_raw/retrieved.csv`「都道府県コード,取得日」）で渡します。生成のたびには変わりません。
- 文部科学省「令和6年度 廃校施設等活用状況実態調査」（5 ていあん のヒント）
- 学校名の読み（ひらがなで学校をさがす機能。画面には出さない）：「アドレス・ベース・レジストリ（町字データ）」（デジタル庁）を加工して作成（町字の読みが無い部分は SudachiDict で補う）。読みを付けた県があるときだけ、先生向けページに出します（まだ読みは付けていません。`docs/KANA.md`）。

## データの利用条件

- **小学校区データは、自治体ごとに利用条件が異なります。** 国土数値情報が公開している一覧（`R5_Terms_of_use_municipality_data.xlsx`）の小学校区の列を、`pipeline/terms/school_district_terms_R5.csv` に置いています。
- **再配布不可の自治体は除外しています。** 利用条件に「再配布不可」を含む市区町村の学区は、`build` / `build-all` が配分の前に取り除きます。その市区町村は学区データなしとして扱い、学校の位置（国土数値情報「学校」）があれば、そこから作った「おおよその区域」で計算します。除いた市区町村は `report_XX.json` の `excluded_by_terms` に出ます（全国で10市町。うち神奈川県小田原市は、再配布不可ではなく利用条件の確認待ちで使っていない。一覧は `docs/COVERAGE.md`）。
- **商用利用不可の自治体があるため、このデータ（`app/data/` と `opendata/` に生成したもの）は非営利の利用に限ります。**
- 利用条件が「条件公開」または特記条件のある市区町村は、アプリで「この まちの 学区は めやすです」と表示します（全国で25市町村。一覧は `docs/COVERAGE.md`）。
- 詳しくは `docs/DATA_METHOD.md` の「利用条件」を見てください。

## ライセンス

- **コード**：MIT ライセンス（[`LICENSE`](LICENSE)）。対象はプログラムだけです。
- **書体**：`app/fonts/` の BIZ UDPGothic（Copyright 2022 The BIZ UDGothic Project Authors）と Yusei Magic（Copyright 2020 The Yusei Magic Project Authors）は SIL Open Font License 1.1 です（`app/fonts/OFL-BIZUDPGothic.txt`、`app/fonts/OFL-YuseiMagic.txt`）。アプリで使う文字だけを収録した woff2 を同梱し、外部（Google Fonts）からは読みこみません。作り直すときは `pip install -r tools/requirements-fonts.txt` のあと `python3 tools/build_fonts.py <TTF のフォルダ>`（TTF は google/fonts の `ofl/bizudpgothic` と `ofl/yuseimagic`。リポジトリには入れない）。画面の文字や学校名を足したら作り直す。
- **データ**：`app/data/` と `pipeline` が生成するデータは国土数値情報を加工したもので、MIT ライセンスの対象外です。上の「データの利用条件」に従い、非営利の利用に限ります。
