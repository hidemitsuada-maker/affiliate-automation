"""公開記事のURLを Google Indexing API に送信する(クロール促進)。

★規約注意: GoogleのIndexing APIは公式には JobPosting / BroadcastEvent 向け。
  一般記事への利用は規約グレー(効く保証なし・濫用はマイナス評価リスク)。
  自サイト・自Googleアカウントの範囲で使うこと。正攻法はサイトマップ登録。

前提(初回のみ手動):
  1. GCPでプロジェクト作成 → "Indexing API" を有効化
  2. サービスアカウント作成 → JSONキーをDL
  3. Search Console の対象プロパティに、そのSAのメールを「オーナー」権限で追加
  4. JSONキーのパスを GSC_SA_JSON で渡す(.env 可)

送信対象: articles.json の status=publish な記事URL(DOMAIN/slug/)。
  pages(about等)も --pages で対象に含められる。
  送信済みは gsc_submitted.json に記録し、--force でない限り再送しない。

usage:
  python gsc_submit.py --dry-run     # 認証不要。送信予定URLを一覧表示
  python gsc_submit.py               # 未送信のpublish記事を送信
  python gsc_submit.py --all         # 送信済みも含め全publishを再送(--forceと同義)
  python gsc_submit.py --pages       # 固定ページも対象に含める
  GSC_SA_JSON=/path/sa.json python gsc_submit.py
"""
import os
import sys
import json
import argparse
import datetime

import requests
from site_config import DOMAIN

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "articles.json")
STATE = os.path.join(HERE, "gsc_submitted.json")
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPES = ["https://www.googleapis.com/auth/indexing"]
WEBMASTERS_SCOPES = ["https://www.googleapis.com/auth/webmasters"]
SITEMAP_URL = f"{DOMAIN}/wp-sitemap.xml"  # WP標準サイトマップ

# .env 簡易ローダ(generate_article.py と同方式)
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


def target_urls(include_pages=False):
    """送信対象URL一覧を (url, slug, kind) で返す。記事は status=publish のみ。"""
    reg = json.load(open(REGISTRY, encoding="utf-8"))
    out = []
    for a in reg.get("articles", []):
        if a.get("status") == "publish" and a.get("slug"):
            out.append((article_url(a["slug"]), a["slug"], "article"))
    if include_pages:
        for p in reg.get("pages", []):
            if p.get("slug"):
                out.append((article_url(p["slug"]), p["slug"], "page"))
    # slug重複排除(順序維持)
    seen, uniq = set(), []
    for url, slug, kind in out:
        if url not in seen:
            seen.add(url)
            uniq.append((url, slug, kind))
    return uniq


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {}


def save_state(state):
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def get_session(scopes=SCOPES):
    """SA JSONから認証済みrequestsセッションを作る。失敗は分かりやすく落とす。"""
    sa_path = os.environ.get("GSC_SA_JSON", "")
    if not sa_path:
        raise SystemExit("GSC_SA_JSON 未設定(サービスアカウントJSONのパスを .env か環境変数で渡す)")
    if not os.path.exists(sa_path):
        raise SystemExit(f"SA JSON が見つからない: {sa_path}")
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
    except ImportError:
        raise SystemExit("google-auth 未インストール: venvで pip install google-auth")
    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
    return AuthorizedSession(creds)


def submit(session, url):
    """1URLを URL_UPDATED で通知。(ok, detail) を返す。"""
    r = session.post(ENDPOINT, json={"url": url, "type": "URL_UPDATED"}, timeout=30)
    if r.status_code == 200:
        return True, "ok"
    return False, f"{r.status_code} {r.text[:160]}"


def ensure_site(session):
    """SAのSearch Consoleアカウントに対象サイトを追加(冪等, PUT /sites)。
    Site Verification で所有者になっていても sites.add しないと
    searchAnalytics/sitemaps が 403 になる(=過去の403の真因)。検証済みなら204。"""
    from urllib.parse import quote
    site = DOMAIN + "/"
    r = session.put(f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}",
                    timeout=30)
    return r.status_code in (200, 204)


def submit_sitemap():
    """WP標準サイトマップを Search Console に登録(冪等)。所有権の伝播前は403/権限不足。"""
    from urllib.parse import quote
    session = get_session(WEBMASTERS_SCOPES)
    ensure_site(session)  # サイト未追加なら追加(403の自己修復)
    site = DOMAIN + "/"
    base = (f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}"
            f"/sitemaps/{quote(SITEMAP_URL, safe='')}")
    r = session.put(base, timeout=30)
    if r.status_code == 204:
        print(f"✓ サイトマップ登録: {SITEMAP_URL}")
        # 登録内容を確認表示
        lst = session.get(f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/sitemaps",
                          timeout=30)
        if lst.status_code == 200:
            for sm in lst.json().get("sitemap", []):
                print(f"  登録済: {sm.get('path')} | pending={sm.get('isPending')} | DL数={sm.get('contents', [{}])[0].get('submitted','?') if sm.get('contents') else '?'}")
        return True
    if r.status_code == 403 and "permission" in r.text.lower():
        print(f"✗ 権限不足(所有権の伝播待ちの可能性)。数分〜数十分おいて再実行: {r.status_code}")
    else:
        print(f"✗ サイトマップ登録失敗: {r.status_code} {r.text[:200]}")
    return False


def main():
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="認証せず送信予定URLを表示")
    ap.add_argument("--all", "--force", dest="force", action="store_true", help="送信済みも再送")
    ap.add_argument("--pages", action="store_true", help="固定ページも対象に含める")
    ap.add_argument("--if-configured", action="store_true",
                    help="GSC_SA_JSON未設定なら送信せず正常終了(日次ジョブで落とさない用)")
    ap.add_argument("--sitemap", action="store_true",
                    help="URL送信の代わりにサイトマップをGSCに登録(一度きりでOK)")
    args = ap.parse_args()

    if args.if_configured and not args.dry_run and not os.environ.get("GSC_SA_JSON"):
        print("GSC_SA_JSON 未設定 → 送信スキップ(--if-configured)")
        return

    if args.sitemap:
        return submit_sitemap()

    urls = target_urls(include_pages=args.pages)
    state = load_state()
    pending = [(u, s, k) for (u, s, k) in urls if args.force or u not in state]

    if args.dry_run:
        print(f"DRY-RUN  対象 {len(urls)}件 / 未送信 {len(pending)}件 (pages={'含む' if args.pages else '除外'})")
        for u, s, k in urls:
            mark = "再送" if u in state else "新規"
            if args.force or u not in state:
                print(f"  [{mark}] {u}")
            else:
                print(f"  [送信済] {u}  ({state[u].get('at','?')})")
        return

    if not pending:
        print("送信対象なし(全て送信済み)。--all で再送できます。")
        return

    session = get_session()
    ok = 0
    for u, s, k in pending:
        success, detail = submit(session, u)
        if success:
            state[u] = {"slug": s, "kind": k, "at": datetime.datetime.now().isoformat(timespec="seconds")}
            ok += 1
            print(f"✓ {u}")
        else:
            print(f"✗ {u}  {detail}")
    save_state(state)
    print(f"完了: {ok}/{len(pending)} 送信。記録 → {os.path.basename(STATE)}")


if __name__ == "__main__":
    main()
