"""同一ニッチの公開記事どうしを内部リンクで相互接続する(トピッククラスタ強化)。

本文の真実の保管先はWP(ローカルmdは同期後に削除される)ため、WP REST経由で
各記事末尾に「関連記事」ブロックを冪等に挿入/更新する。新規ドメインでは
クラスタ内の相互リンクがクロール深度とトピック網羅性を底上げし、pillarの評価を押し上げる。

- 対象: articles.json の status=publish かつ wp_id を持つ記事(同一ニッチで2本以上)。
- 各記事に、同一ニッチの他の公開記事へのリンクを最大 LINK_MAX 本貼る。
- ブロックはマーカーコメントで挟み、毎回strip→再生成するので、記事が増えても
  全記事のブロックが最新化される(重複追記しない)。
- pillarガイドへのリンクは generate 時に本文へ入っているので、本文に既に
  pillar slug があるニッチはここでは重複させない。

冪等: 何度走らせてもブロックは1つだけ。本文の他の箇所は一切触らない。

usage:
  python internal_links.py --dry-run   # 変更内容を表示(WP更新しない)
  python internal_links.py             # WP本文を更新
  python internal_links.py --max 4     # 1記事あたりのリンク本数上限(default 6)
"""
import os
import re
import json
import argparse

import requests
from requests.auth import HTTPBasicAuth
from site_config import DOMAIN, NICHES

HERE = os.path.dirname(os.path.abspath(__file__))
REG_PATH = os.path.join(HERE, "articles.json")
BASE = "https://it-career-navi.net/wp-json/wp/v2"
START = "<!-- auto-related-start -->"
END = "<!-- auto-related-end -->"
LINK_MAX = 6


def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def article_url(slug):
    """フラットパーマリンク(/%postname%/)。site_config.pillar_url と同じ規則。"""
    return f"{DOMAIN}/{slug}/"


def fetch_post(auth, wp_id):
    """raw本文とタイトルを取る。context=edit で content.raw / title.raw を得る。"""
    r = requests.get(BASE + f"/posts/{wp_id}",
                     params={"context": "edit", "_fields": "id,title,content"},
                     auth=auth, timeout=30)
    if r.status_code != 200:
        return None
    j = r.json()
    return {"id": j["id"],
            "title": j["title"]["raw"],
            "content": j["content"]["raw"]}


def strip_block(content):
    """既存の関連記事ブロックを除去(冪等再生成のため)。前後の余白も整える。"""
    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    out = pat.sub("", content)
    return out.rstrip() + "\n"


def build_block(siblings):
    """siblings = [(title, url), ...] から関連記事ブロックHTMLを組む。空なら空文字。"""
    if not siblings:
        return ""
    items = "\n".join(f'<li><a href="{url}">{title}</a></li>' for title, url in siblings)
    return (f"{START}\n"
            f"<h2>関連記事</h2>\n"
            f"<ul>\n{items}\n</ul>\n"
            f"{END}")


def main():
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="WP更新せず変更内容を表示")
    ap.add_argument("--max", type=int, default=LINK_MAX, help=f"1記事のリンク上限(default {LINK_MAX})")
    args = ap.parse_args()

    user = os.environ.get("WP_USER", "")
    app = os.environ.get("WP_APP_PASS", "")
    if not user or not app:
        raise SystemExit("WP_USER / WP_APP_PASS env 未設定")
    auth = HTTPBasicAuth(user, app)

    reg = json.load(open(REG_PATH, encoding="utf-8"))
    # 公開済み & wp_id 付きのみ。(slug, niche, wp_id) を集める。
    pub = [a for a in reg.get("articles", [])
           if a.get("status") == "publish" and a.get("wp_id")]

    # ニッチ別にグルーピング。2本以上ないと相互リンクできない。
    by_niche = {}
    for a in pub:
        by_niche.setdefault(a["niche"], []).append(a)

    # 各記事のタイトルをWPから引いてキャッシュ(wp_id → post dict)。
    posts = {}
    for a in pub:
        p = fetch_post(auth, a["wp_id"])
        if p:
            posts[a["wp_id"]] = p
        else:
            print(f"⚠ 本文取得失敗 slug={a['slug']} id={a['wp_id']}")

    updated = skipped = 0
    for niche, arts in by_niche.items():
        arts = [a for a in arts if a["wp_id"] in posts]
        if len(arts) < 2:
            continue  # 相互リンクには2本以上必要
        pillar_slug = NICHES[niche].get("pillar_slug")
        for a in arts:
            post = posts[a["wp_id"]]
            is_pillar = a["slug"] == pillar_slug
            # 同一ニッチの他記事 → 関連記事リンク(自分を除く、上限まで)。
            # クラスタ記事は本文で既にpillarへリンク済みなので、関連リストでは
            # pillarを除外し重複リンクを避ける。pillar記事自身は全クラスタを列挙。
            siblings = []
            for other in arts:
                if other["slug"] == a["slug"]:
                    continue
                if not is_pillar and other["slug"] == pillar_slug:
                    continue
                title = posts[other["wp_id"]]["title"]
                siblings.append((title, article_url(other["slug"])))
                if len(siblings) >= args.max:
                    break

            base = strip_block(post["content"])
            block = build_block(siblings)
            new_content = (base.rstrip() + "\n\n" + block + "\n") if block else base

            if new_content.strip() == post["content"].strip():
                skipped += 1
                continue

            if args.dry_run:
                print(f"[DRY] id={a['wp_id']} slug={a['slug']} [{niche}] "
                      f"関連{len(siblings)}本 → {[s[0] for s in siblings]}")
                updated += 1
                continue

            r = requests.post(BASE + f"/posts/{a['wp_id']}", auth=auth,
                              json={"content": new_content}, timeout=30)
            if r.status_code in (200, 201):
                print(f"✓ 内部リンク更新 id={a['wp_id']} slug={a['slug']} [{niche}] 関連{len(siblings)}本")
                updated += 1
            else:
                print(f"✗ 更新失敗 slug={a['slug']}: {r.status_code} {r.text[:160]}")

    print(f"\n完了: 更新{updated}件 / 変更なし{skipped}件 / 公開{len(pub)}本")


if __name__ == "__main__":
    main()
