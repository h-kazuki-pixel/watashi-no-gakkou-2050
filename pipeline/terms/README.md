# pipeline/terms — パイプラインが使う対応表

| ファイル | 中身 | 出典 | 作り方 |
|---|---|---|---|
| `school_district_terms_R5.csv` | 小学校区データの、自治体ごとの利用条件（行政コード,自治体名,公開条件,利用条件,特記条件詳細） | 国土数値情報「小学校区データ」のダウンロードページにある `R5_Terms_of_use_municipality_data.xlsx` の小学校区の列 | 手で CSV にした。使い方は `school2050/terms.py` |
| `designated_city_wards.csv` | 政令指定都市の区と市の対応（区のコード,区の名称,市のコード,市の名称,状態,改正年月日,改正後のコード,改正後の名称,改正事由）。20市・178区（うち欠番7＝浜松市の再編前の区） | 国土数値情報「行政区域コード」（令和6年1月1日現在）<https://nlftp.mlit.go.jp/ksj/gml/codelist/AdminiBoundary_CD.xlsx>。総務省「全国地方公共団体コード」に改正情報を加えたもの | `python3 tools/make_ward_table.py AdminiBoundary_CD.xlsx > pipeline/terms/designated_city_wards.csv`。使い方は `school2050/wards.py` |

`designated_city_wards.csv` の「状態」が「欠番」の区は、再編などで今は使われていないコードです。
国土数値情報のメッシュや「学校」は、作られた時点のコードで入っているので、再編前の区のコードが出てくることがあります。
