# affiliate-automation

Claude Code Routines（/schedule）で動くアフィリエイト自動化システム。

## 稼働中のルーチン

| ルーチン | スケジュール | 概要 |
|---|---|---|
| daily-article-drafter | 毎日 6:00 JST | keyword-queueからキーワードを取得してSERP分析→4000字ドラフト生成 |
| daily-sns-poster | 毎日 7:00 JST | 当日ドラフトのテーマでX投稿3本生成 |
| weekly-serp-watcher | 毎週月曜 9:00 JST | keywords.csvの全KWの順位変動を監視 |
| monthly-pl-reporter | 毎月1日 9:00 JST | Notion案件管理DBから月次P&Lレポート生成 |
| weekly-article-health-monitor | 毎週金曜 10:00 JST | PV30%以上低下した記事を検出して改修案を出す |

## セットアップ手順

1. **MCP接続**: https://claude.ai/customize/connectors でSlack・Notionを接続
2. **ルーチンにリポジトリを追加**: https://claude.ai/code/routines から各ルーチンを編集
3. **keywords.csvを更新**: [yoursite]を実際のドメインに変更
4. **keyword-queueにキーワードを投入**: YYYY-MM-DD-001.txt形式で1件ずつ

## フォルダ構成

```
keyword-queue/   ← 未処理キーワード（処理後に.doneに変名）
drafts/          ← 生成された記事ドラフト（YYYY-MM-DD.md）
content-bank/    ← X投稿履歴・scheduled/に当日分が生成される
data/            ← analytics.csv, affiliate-YYYY-MM.csv
reports/         ← SERP監視・月次P&L・記事健康レポート
keywords.csv     ← 全監視キーワード一覧
```
