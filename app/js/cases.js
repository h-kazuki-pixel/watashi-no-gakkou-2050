/*
 * わたしの学校2050 — 事例帳（使われなくなった校舎や、空いた教室の使い方の例）
 * ステップ5の「ヒント」に出す。出典は先生向けページに出す。確かめた日：2026-11-19
 * ideas は UG.IDEAS の id（えらんだ アイデアに 近い 例を 上に ならべる）。
 * 文の中の {漢字|よみ} は ふりがな。
 */
(function () {
  "use strict";
  var UG = window.UG;
  var BOOK = { name: "文部科学省「廃校活用事例集」（令和5年3月発行、令和6年10月更新）", url: "https://www.mext.go.jp/content/20230331-mxt_sisetujo-000013314_00.pdf" };

  UG.CASES_CHECKED = "2026年11月19日";
  UG.CASES = [
    { id: "kobe", kind: "now", title: "{空|あ}き教室が 地域の {図書室|としょしつ}に",
      place: "{兵庫県|ひょうごけん} {神戸市|こうべし}", from: "{市|し}の 小学校など", who: "学校ごとの {運営|うんえい}の {会|かい}",
      text: "学校の {空|あ}き教室を {図書室|としょしつ}に した。{放課後|ほうかご}や {休|やす}みの {日|ひ}に、地域の 人が {本|ほん}を {読|よ}んだり {借|か}りたり できる。ひらく {日|ひ}や {時間|じかん}は、学校に よって ちがう。",
      ideas: ["room_study", "room_town"], src: [{ name: "神戸市教育委員会事務局「令和8年度 学校施設開放の手引き」", url: "https://www.city.kobe.lg.jp/documents/3487/20260213165058.pdf" }, { name: "神戸市「市民図書室」開室曜日・時間一覧表（2026年7月現在）", url: "https://www.city.kobe.lg.jp/documents/5435/shimintosyoshitu_annai20260713.pdf" }] },
    { id: "muroto", kind: "after", title: "プールが 大きな {水|すい}そうに なった {水族館|すいぞくかん}",
      place: "{高知県|こうちけん} {室戸市|むろとし}", from: "もとは {椎名|しいな}小学校", who: "NPO（{市|し}の 校舎を {運営|うんえい}）",
      text: "25メートルの プールで ウミガメや {魚|さかな}が およぐ。{手洗|てあら}い{場|ば}や とび{箱|ばこ}も {展示|てんじ}に 使って いる。",
      ideas: ["pr"], src: [BOOK, { name: "室戸市「むろと廃校水族館」", url: "https://www.city.muroto.kochi.jp/pages/page0343.php" }, { name: "日本ウミガメ協議会「関連施設」", url: "https://www.umigame.org/toukainitsuite/kanren/top.html" }] },
    { id: "hota", kind: "after", title: "学校が 道の駅に",
      place: "{千葉県|ちばけん} {鋸南町|きょなんまち}", from: "もとは {保田|ほた}小学校", who: "{町|まち}",
      text: "校舎に {食事|しょくじ}の {店|みせ}や とまれる {部屋|へや}が あり、体育館は {地元|じもと}で とれた ものを {売|う}る 場所に なった。地域の 人の はたらく 場所にも なって いる。",
      ideas: ["pr", "room_town"], src: [BOOK, { name: "国土交通省 国土政策局の資料（鋸南町）", url: "https://www.mlit.go.jp/kokudoseisaku/content/001993659.pdf" }] },
    { id: "kyohoku", kind: "after", title: "子どもと 親子が 集まる 場所",
      place: "{三重県|みえけん} {四日市市|よっかいちし}", from: "もとは {東橋北|ひがしきょうほく}小学校", who: "{市|し}",
      text: "こども{園|えん}と、親子で 遊べる {児童館|じどうかん}が 入った。地域の 人が {話|はな}し{合|あ}いの {場|ば}を 作り、{市|し}も そこに {加|くわ}わって 使い方を 考えた。",
      ideas: ["room_kids", "family", "play"], src: [BOOK, { name: "四日市市 こども子育て交流プラザの催しの案内（2026年3月）", url: "https://www.city.yokkaichi.lg.jp/www/contents/1001000001273/files/yokapapa0308.pdf" }] },
    { id: "hayabusa", kind: "after", title: "カフェと はたらく 場所が ある 学校",
      place: "{鳥取県|とっとりけん} {八頭町|やずちょう}", from: "もとは {隼|はやぶさ}小学校", who: "地域の 会社",
      text: "カフェや 会社の {部屋|へや}が できた。入って いる 会社も、地域の {運動会|うんどうかい}に {参加|さんか}して いる。",
      ideas: ["room_town", "family"], src: [BOOK, { name: "国土交通省 官民連携の事例（隼Lab.、令和8年2月）", url: "https://www.mlit.go.jp/smcn/case/content/002010518.pdf" }] },
    { id: "uminokosha", kind: "after", title: "教室が ものづくりの {仕事場|しごとば}に",
      place: "{岡山県|おかやまけん} {笠岡市|かさおかし}", from: "もとは {大島東|おおしまひがし}小学校", who: "{作|つく}り{手|て}たちの NPO",
      text: "教室を {仕事場|しごとば}に して、10より 多くの {作|つく}り{手|て}が 入って いる。年に 1〜2回、校舎と {校庭|こうてい}で {市|いち}を ひらいて いる。",
      ideas: ["events", "pr"], src: [BOOK, { name: "文部科学省 廃校活用の発表資料（海の校舎）", url: "https://www.mext.go.jp/content/000258061.pdf" }, { name: "岡山県観光連盟「第7回 うみの市」（2026年4月）", url: "https://www.okayama-kanko.jp/event/detail_16255.html" }] },
    { id: "atsumare", kind: "after", title: "{町|まち}の {窓口|まどぐち}と プロサッカーの {練習場|れんしゅうじょう}",
      place: "{茨城県|いばらきけん} {城里町|しろさとまち}", from: "もとは {七会|ななかい}中学校", who: "{町|まち}と プロサッカーチーム",
      text: "{町|まち}の {窓口|まどぐち}や 公民館が 入り、{天然芝|てんねんしば}の グラウンドが できた。{水戸|みと}ホーリーホックの {練習場|れんしゅうじょう}にも なって いる。",
      ideas: ["play", "room_town"], src: [{ name: "城里町「広報しろさと」2018年2月号", url: "https://www.town.shirosato.lg.jp/data/doc/1517382109_doc_760_1.pdf" }, { name: "城里町「広報しろさと」2026年1月号", url: "https://www.town.shirosato.lg.jp/data/doc/1766542490_doc_791_0.pdf" }] }
  ];
})();
