"""Search Console の検索パフォーマンスを取得して順位/流入を可視化する(効果測定)。

gsc_submit.py の認証(SAサービスアカウント)とDOMAINをそのまま再利用する。
新規サイトはデータが溜まるまで空。日が経つほど中身が出る。

何が見えるか:
  - サマリ: 期間合計のクリック/表示/CTR/平均掲載順位
  - ページ別: 記事URLごとのクリック/表示/CTR/順位(表示数の多い順)
  - クエリ別(--queries): 流入キーワードと順位
  - 機会(--opportunities): 表示は多いがCTR低い or 順位11-20位(あと一押しで1ページ目)

trends: --save で gsc_report_history.json に日次スナップショットを追記
        → 順位が上がってるか下がってるかを後から追える。

usage:
  python gsc_report.py                 # 直近28日 ページ別
  python gsc_report.py --days 7        # 期間変更
  python gsc_report.py --queries       # 流入キーワード
  python gsc_report.py --opportunities # 伸ばしどころを抽出
  python gsc_report.py --save          # 履歴に保存(cron向け)
"""
import os
import json
import argparse
import datetime
from urllib.parse import quote

import gsc_submit as g

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(HERE, "gsc_report_history.json")
READONLY = ["https://www.googleapis.com/auth/webmasters.readonly"]
WRITE = ["https://www.googleapis.com/auth/webmasters"]


def query(session, start, end, dimensions, row_limit=1000, filters=None):
    """searchAnalytics.query を叩いて rows を返す。"""
    site = g.DOMAIN + "/"
    url = (f"https://www.googleapis.com/webmasters/v3/sites/"
           f"{quote(site, safe='')}/searchAnalytics/query")
    body = {"startDate": str(start), "endDate": str(end),
            "dimensions": dimensions, "rowLimit": row_limit}
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    r = session.post(url, json=body, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"searchAnalytics 失敗: {r.status_code} {r.text[:200]}")
    return r.json().get("rows", [])


def _fmt_rows(rows, key_label, limit):
    """rows を整形表示。各 row は keys[0] が次元値。"""
    if not rows:
        print("  (データなし — 新規サイトは数日〜数週間で出始めます)")
        return
    print(f"  {'クリック':>7} {'表示':>7} {'CTR':>6} {'順位':>5}  {key_label}")
    for row in rows[:limit]:
        k = row["keys"][0]
        clicks = row.get("clicks", 0)
        impr = row.get("impressions", 0)
        ctr = row.get("ctr", 0) * 100
        pos = row.get("position", 0)
        print(f"  {clicks:7.0f} {impr:7.0f} {ctr:5.1f}% {pos:5.1f}  {k}")


def summary(session, start, end):
    rows = query(session, start, end, dimensions=[], row_limit=1)
    print(f"■ サマリ ({start} 〜 {end})")
    if not rows:
        print("  クリック0 / 表示0 (まだ検索に出ていません)")
        return {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}
    r = rows[0]
    s = {"clicks": r.get("clicks", 0), "impressions": r.get("impressions", 0),
         "ctr": r.get("ctr", 0), "position": r.get("position", 0)}
    print(f"  クリック {s['clicks']:.0f} / 表示 {s['impressions']:.0f} / "
          f"CTR {s['ctr']*100:.1f}% / 平均順位 {s['position']:.1f}")
    return s


def opportunities(session, start, end):
    """伸ばしどころ: 表示はあるのに(1)順位11-20=2ページ目 or (2)CTRが順位平均より低い。"""
    rows = query(session, start, end, dimensions=["page"])
    page2 = [r for r in rows if 10.5 <= r.get("position", 99) <= 20.5 and r.get("impressions", 0) >= 5]
    page2.sort(key=lambda r: r.get("impressions", 0), reverse=True)
    print("■ あと一押し: 2ページ目(11-20位)で表示されてる記事 → 内部リンク/追記で1ページ目を狙う")
    _fmt_rows(page2, "page", 20)
    lowctr = [r for r in rows if r.get("position", 99) <= 10.5
              and r.get("impressions", 0) >= 20 and r.get("ctr", 1) < 0.02]
    lowctr.sort(key=lambda r: r.get("impressions", 0), reverse=True)
    print("\n■ タイトル改善候補: 1ページ目なのにCTR<2% → タイトル/メタを書き直すとクリック増")
    _fmt_rows(lowctr, "page", 20)


def save_snapshot(s):
    hist = []
    if os.path.exists(HISTORY):
        hist = json.load(open(HISTORY, encoding="utf-8"))
    hist.append({"date": str(datetime.date.today()), **{k: round(v, 4) for k, v in s.items()}})
    json.dump(hist, open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n履歴に保存: {os.path.basename(HISTORY)} ({len(hist)}件)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28, help="集計期間(日, default 28)")
    ap.add_argument("--queries", action="store_true", help="ページ別でなくクエリ(流入KW)別")
    ap.add_argument("--opportunities", action="store_true", help="伸ばしどころを抽出")
    ap.add_argument("--limit", type=int, default=30, help="表示行数(default 30)")
    ap.add_argument("--save", action="store_true", help="サマリを履歴JSONに追記(cron向け)")
    args = ap.parse_args()

    g._load_env()
    session = g.get_session(WRITE if args.save else READONLY)
    # サイト未追加なら追加(過去の403の自己修復)。READONLYでは追加できないのでWRITE時のみ。
    if args.save:
        g.ensure_site(session)

    # GSCのデータは2-3日遅延するので終端を3日前にする(0件を避ける)
    end = datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=args.days)

    s = summary(session, start, end)

    if args.opportunities:
        print()
        opportunities(session, start, end)
    elif args.queries:
        print("\n■ 流入キーワード(表示数の多い順)")
        rows = query(session, start, end, dimensions=["query"])
        rows.sort(key=lambda r: r.get("impressions", 0), reverse=True)
        _fmt_rows(rows, "query", args.limit)
    else:
        print("\n■ ページ別(表示数の多い順)")
        rows = query(session, start, end, dimensions=["page"])
        rows.sort(key=lambda r: r.get("impressions", 0), reverse=True)
        _fmt_rows(rows, "page", args.limit)

    if args.save:
        save_snapshot(s)


if __name__ == "__main__":
    main()
