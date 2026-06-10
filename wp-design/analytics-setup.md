# GSC / GA4 導入手順（it-career-navi.net）

計測の土台。**順位を見て記事をリライトする(PDCA)ための必須インフラ**。
実作業はGoogleアカウント操作なので下記をユーザーが踏む。Cocoon側の貼り付け場所だけ用意済。

---

## A. Google Search Console（GSC）= 検索順位・CTR・流入KWを見る

### A-1. プロパティ登録
1. https://search.google.com/search-console → 「プロパティを追加」
2. 種類は **「ドメイン」** を推奨（`it-career-navi.net`。www有無/http/https を全部まとめて計測できる）
   - ドメイン認証が面倒なら「URLプレフィックス」(`https://it-career-navi.net/`)でも可。
3. **所有権の確認**:
   - ドメイン版 → DNSにTXTレコード追加（Xserver管理画面 > DNSレコード設定）。GSCが出すTXT値を貼る。
   - URLプレフィックス版 → 後述のGA4を先に入れれば「Googleアナリティクス」で自動確認できる（一番ラク）。

### A-2. サイトマップ送信
- GSC > サイトマップ → `https://it-career-navi.net/sitemap.xml` を送信。
- Cocoonは標準でサイトマップを吐かないので **「XML Sitemap & Google News」プラグイン**等を入れて生成→そのURLを送信。
  （または Cocoon設定の連携で対応。プラグイン版が確実）

### A-3. 見るところ（運用フェーズ）
- 「検索パフォーマンス」= クエリ別の **表示回数 / クリック / CTR / 平均掲載順位**。
- リライト対象の発見に直結（[[SEO記事執筆ガイド]]の「10位前後 / CTR低」をここで判定）。

---

## B. Google Analytics 4（GA4）= 流入数・行動・CV(無料相談クリック)を見る

### B-1. プロパティ作成
1. https://analytics.google.com → 管理 > プロパティを作成（`IT転職ナビ`）。
2. データストリーム > ウェブ → `https://it-career-navi.net` を登録。
3. **測定ID `G-XXXXXXXXXX`** が発行される。これを控える。

### B-2. 計測タグの設置（Cocoonに貼るだけ）
Cocoonは測定IDを入れる欄が用意されている。**タグを直書きしないこと**（重複計測の元）。
- **Cocoon設定 > アクセス解析・認証**:
  - 「Google AnalyticsトラッキングID」or「GA4測定ID」欄に **`G-XXXXXXXXXX`** を貼る。
  - 「ヘッド用コード」「Google Search Console ID」欄もここ（GSCのmetaタグ認証を使う場合はSearch Console IDを貼る）。
- これでCocoonが gtag を全ページのheadに自動出力する。プラグイン不要。

### B-3. CV計測（無料相談クリックを「コンバージョン」に）
アフィの肝。**CTAボタンのクリックをイベント化**して、どの記事が相談に繋がるか測る。
1. GA4 > 管理 > イベント or Google Tag Manager でクリックイベントを作成。
   - 簡易版: GA4の「拡張計測機能」で外部リンククリックは自動取得される（A8リンク=外部ドメインなので拾える）。
   - 確実版: CTAボタンに `data-ga="cta_consult"` を付け、GTMで click → GA4イベント `cta_consult` 送信。
2. そのイベントを GA4 > 管理 > **「キーイベント(旧コンバージョン)」** に登録。
3. 記事別CV = 探索レポートで「ページ × cta_consultイベント数」。

---

## C. 導入順序（推奨）
1. **GA4を先に作る**（測定ID発行 → CocoonにID貼る）。
2. **GSCはGA4で所有権確認**（URLプレフィックス版なら自動。一番手間が少ない）。
3. サイトマッププラグイン入れて GSC にサイトマップ送信。
4. CTAクリックのイベント化（CV計測）。

## D. 今ブロックされていること（ユーザー操作待ち）
- Googleアカウントでの GA4 / GSC 作成（測定ID・TXT値の発行）。
- Cocoon設定 > アクセス解析欄への ID貼り付け（WP管理ログイン要）。
- サイトマッププラグインのインストール。
→ 測定ID(`G-...`)とGSCのTXT値さえ出れば、あとは貼る場所は上記で確定。
