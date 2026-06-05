# content-bank/

## 構造
- `*.json` — 過去のX投稿データ（エンゲージメント率付き）
- `scheduled/` — daily-sns-posterが生成した当日分の投稿

## 投稿ファイル形式
```json
{
  "date": "2026-06-01",
  "posts": [
    {
      "text": "投稿本文（140字以内）",
      "engagement_rate": 3.5,
      "impressions": 1200,
      "likes": 42,
      "pattern": "shocking_stat"
    }
  ]
}
```

## engagement_rateの計算
(likes + retweets + replies) / impressions × 100
