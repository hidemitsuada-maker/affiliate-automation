"""drafts/*.md を WordPress(it-career-navi.net) に下書き投稿する。

- 認証は環境変数 WP_USER / WP_APP_PASS から読む(スクリプトに秘密を持たせない)。
- Markdown→HTML は依存なしの自前変換(見出し/太字/斜体/箇条書き/番号/表/引用/区切り)。
- カテゴリは slug で冪等作成。記事も slug 重複なら更新、無ければ新規(status=draft)。
- 先頭の `# 見出し` を記事タイトルに使い、本文からは除外。

usage:
  WP_USER=ken_takahashi WP_APP_PASS="xxxx ..." python wp_publish.py
"""
import os
import re
import sys
import json
import requests
from requests.auth import HTTPBasicAuth
from site_config import NICHES
import thumbnail as thumb

HERE = os.path.dirname(os.path.abspath(__file__))

BASE = "https://it-career-navi.net/wp-json/wp/v2"
USER = os.environ.get("WP_USER", "")
APP = os.environ.get("WP_APP_PASS", "")
AUTH = HTTPBasicAuth(USER, APP)
# WP_FORCE_STATUS=draft を指定すると、articles.jsonの個別statusを無視して全件下書きにする。
# 公開前の目視確認用(本番公開はこの環境変数を付けずに実行)。
FORCE_STATUS = os.environ.get("WP_FORCE_STATUS", "")

# 記事/ページのレジストリは articles.json(単一ソース)から読む。
# 新規記事は new_article.py が articles.json に追記する(手編集不要)。
_REG = json.load(open(os.path.join(os.path.dirname(__file__), "articles.json"), encoding="utf-8"))
# 記事 → (file, category_slug, category_name, post_slug, status)。category_name は site_config から解決。
ARTICLES = [
    (a["file"], a["niche"], NICHES[a["niche"]]["category_name"], a["slug"], a["status"])
    for a in _REG["articles"]
]
# 固定ページ → (file, page_slug)。E-E-A-T/アフィ規約上の必須ページ。カテゴリなし。
PAGES = [(p["file"], p["slug"]) for p in _REG["pages"]]


def extract_meta(md):
    """先頭付近の `<!-- meta: ... -->` を抜き出してメタディスクリプション(excerpt)に使う。"""
    m = re.search(r"<!--\s*meta:\s*(.*?)\s*-->", md)
    return m.group(1).strip() if m else ""


def _inline(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 画像 ![alt](src) → <img>。alt必須(SEO/アクセシビリティ)。altは escape 済みなので decode して属性化。
    def _img(m):
        alt = m.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        return f'<img src="{m.group(2)}" alt="{alt}" loading="lazy" />'
    t = re.sub(r"!\[(.*?)\]\((.*?)\)", _img, t)
    # リンク [text](url)。内部(自サイト/相対)=follow・同タブ / 外部(アフィ含む)=nofollow・別タブ。
    def _link(m):
        text, url = m.group(1), m.group(2)
        internal = ("it-career-navi.net" in url) or url.startswith("/") or url.startswith("#")
        if internal:
            return f'<a href="{url}">{text}</a>'
        return f'<a href="{url}" rel="nofollow noopener" target="_blank">{text}</a>'
    t = re.sub(r"(?<!!)\[(.+?)\]\((.+?)\)", _link, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", t)
    return t


def lint_alt(md, label):
    """alt空の画像を検出して警告(SEO的にalt必須)。"""
    bad = re.findall(r"!\[\s*\]\((.*?)\)", md)
    for src in bad:
        print(f"  ⚠ alt属性なし画像 [{label}]: {src} ← alt文を入れてください")
    return len(bad)


def md_to_html(md):
    # ★全パターン判定を strip 済み行(ln)で統一する。以前は dispatch=非strip /
    #   段落判定=strip の不整合で、番号リスト直下の「   - インデント箇条書き」が
    #   どの分岐にも進まず i が止まり無限ループしていた(A/Eで発生)。末尾に安全弁も追加。
    lines = md.split("\n")
    html = []
    i = 0
    title = None
    while i < len(lines):
        ln = lines[i].strip()
        # title (first H1)
        if ln.startswith("# ") and title is None:
            title = ln[2:].strip()
            i += 1
            continue
        # skip HTML comments / hr / blank
        if ln.startswith("<!--") or ln in ("---", ""):
            i += 1
            continue
        # 生HTMLブロック(埋め込んだA8の<a>/<img>等)はエスケープせずそのまま通す。
        # 空行 or コメントが来るまでを1ブロックとして連結。
        if ln.startswith("<"):
            raw = []
            while i < len(lines):
                s = lines[i].strip()
                if not s or s.startswith("<!--"):
                    break
                raw.append(s)
                i += 1
            html.append("\n".join(raw))
            continue
        # headings
        m = re.match(r"^(#{2,4})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            html.append(f"<h{lvl}>{_inline(m.group(2).strip())}</h{lvl}>")
            i += 1
            continue
        # blockquote
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(_inline(lines[i].strip()[1:].strip()))
                i += 1
            html.append("<blockquote><p>" + "<br>".join(buf) + "</p></blockquote>")
            continue
        # table
        if ln.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            if len(tbl) >= 2:
                def cells(row):
                    return [c.strip() for c in row.strip("|").split("|")]
                head = cells(tbl[0])
                rows = [cells(r) for r in tbl[2:]]  # tbl[1]=---区切り
                t = ["<figure class=\"wp-block-table\"><table><thead><tr>"]
                t += [f"<th>{_inline(h)}</th>" for h in head]
                t.append("</tr></thead><tbody>")
                for r in rows:
                    t.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
                t.append("</tbody></table></figure>")
                html.append("".join(t))
            continue
        # unordered list (インデント付きも strip 済みで拾う)
        if re.match(r"^[-*]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append("<li>" + _inline(re.sub(r"^[-*]\s+", "", lines[i].strip())) + "</li>")
                i += 1
            html.append("<ul>" + "".join(items) + "</ul>")
            continue
        # ordered list
        if re.match(r"^\d+\.\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                items.append("<li>" + _inline(re.sub(r"^\d+\.\s+", "", lines[i].strip())) + "</li>")
                i += 1
            html.append("<ol>" + "".join(items) + "</ol>")
            continue
        # paragraph (gather until blank/別ブロック)
        buf = []
        while i < len(lines):
            s = lines[i].strip()
            if not s or re.match(r"^(#{1,4}\s|[-*]\s|\d+\.\s|\||>|<!--|---)", s):
                break
            buf.append(_inline(s))
            i += 1
        if buf:
            html.append("<p>" + "<br>".join(buf) + "</p>")
        else:
            i += 1  # ★安全弁: どの分岐でも進めなかった場合に強制前進(無限ループ防止)
    return title, "\n".join(html)


def ensure_category(slug, name):
    r = requests.get(BASE + f"/categories?slug={slug}", auth=AUTH, timeout=20)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    r = requests.post(BASE + "/categories", auth=AUTH, json={"name": name, "slug": slug}, timeout=20)
    if r.status_code in (200, 201):
        return r.json()["id"]
    # 既存(term_exists)なら拾い直す
    r2 = requests.get(BASE + f"/categories?slug={slug}", auth=AUTH, timeout=20)
    if r2.status_code == 200 and r2.json():
        return r2.json()[0]["id"]
    raise RuntimeError(f"category {slug} failed: {r.status_code} {r.text[:120]}")


def upload_thumbnail(slug, title, niche, cname):
    """アイキャッチを生成→WPメディアへアップし media id を返す(冪等)。
    既に article-<slug> のメディアがあれば作り直さず再利用する。失敗時は None。"""
    media_slug = f"article-{slug}"
    r = requests.get(BASE + f"/media?slug={media_slug}&per_page=1", auth=AUTH, timeout=20)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    png = thumb.make_thumbnail(title, niche, cname,
                               os.path.join(HERE, "thumbs", f"{media_slug}.png"))
    headers = {"Content-Disposition": f'attachment; filename="{media_slug}.png"',
               "Content-Type": "image/png"}
    r = requests.post(BASE + "/media", auth=AUTH, headers=headers,
                      data=open(png, "rb").read(), timeout=60)
    if r.status_code in (200, 201):
        mid = r.json()["id"]
        requests.post(BASE + f"/media/{mid}", auth=AUTH, json={"alt_text": title}, timeout=20)
        return mid
    print(f"  ⚠ サムネupload失敗 {slug}: {r.status_code} {r.text[:120]}")
    return None


def find_post_by_slug(slug):
    r = requests.get(BASE + f"/posts?slug={slug}&status=draft,publish,pending,future&per_page=1",
                     auth=AUTH, timeout=20)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return None


def find_page_by_slug(slug):
    r = requests.get(BASE + f"/pages?slug={slug}&status=draft,publish,pending,future&per_page=1",
                     auth=AUTH, timeout=20)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return None


def thumb_only():
    """既存投稿の featured_media(サムネ)だけを更新する。本文/status/カテゴリは触らない。
    WP上に未投稿の記事はスキップ(新規作成しない)。WP_THUMB_ONLY=1 で起動。"""
    for path, cslug, cname, pslug, status in ARTICLES:
        title, _ = md_to_html(open(path, encoding="utf-8").read())
        existing = find_post_by_slug(pslug)
        if not existing:
            print(f"– 未投稿スキップ slug={pslug}")
            continue
        mid = upload_thumbnail(pslug, title, cslug, cname)
        if not mid:
            print(f"✗ サムネ生成失敗 slug={pslug}"); continue
        r = requests.post(BASE + f"/posts/{existing}", auth=AUTH,
                          json={"featured_media": mid}, timeout=30)
        if r.status_code in (200, 201):
            print(f"✓ サムネ更新 id={existing} slug={pslug} media={mid} title={title}")
        else:
            print(f"✗ FAIL slug={pslug}: {r.status_code} {r.text[:160]}")


def main():
    if not USER or not APP:
        print("WP_USER / WP_APP_PASS env 未設定"); sys.exit(1)
    if os.environ.get("WP_THUMB_ONLY"):
        return thumb_only()
    cat_cache = {}
    for path, cslug, cname, pslug, status in ARTICLES:
        md = open(path, encoding="utf-8").read()
        lint_alt(md, pslug)
        title, content = md_to_html(md)
        meta = extract_meta(md)
        if cslug not in cat_cache:
            cat_cache[cslug] = ensure_category(cslug, cname)
        cid = cat_cache[cslug]
        payload = {"title": title, "content": content, "slug": pslug,
                   "status": FORCE_STATUS or status, "categories": [cid]}
        # メタディスクリプション: Cocoonは抜粋(excerpt)を自動でmeta descriptionに使う設定が可能。
        if meta:
            payload["excerpt"] = meta
        # アイキャッチ(サムネ)を生成・アップしてfeatured_mediaに設定(冪等)
        mid = upload_thumbnail(pslug, title, cslug, cname)
        if mid:
            payload["featured_media"] = mid
        existing = find_post_by_slug(pslug)
        if existing:
            r = requests.post(BASE + f"/posts/{existing}", auth=AUTH, json=payload, timeout=30)
            action = "更新"
        else:
            r = requests.post(BASE + "/posts", auth=AUTH, json=payload, timeout=30)
            action = "新規"
        if r.status_code in (200, 201):
            j = r.json()
            print(f"✓ {action} {FORCE_STATUS or status} id={j['id']} [{cslug}] slug={pslug} title={title}({len(title)}字)")
            if meta:
                print(f"    meta({len(meta)}字): {meta}")
            print(f"    編集: https://it-career-navi.net/wp-admin/post.php?post={j['id']}&action=edit")
        else:
            print(f"✗ FAIL {path}: {r.status_code} {r.text[:160]}")

    # 固定ページ(運営者情報/プライバシーポリシー/免責/お問い合わせ)
    for path, pslug in PAGES:
        md = open(path, encoding="utf-8").read()
        lint_alt(md, pslug)
        title, content = md_to_html(md)
        meta = extract_meta(md)
        payload = {"title": title, "content": content, "slug": pslug, "status": FORCE_STATUS or "publish"}
        if meta:
            payload["excerpt"] = meta
        existing = find_page_by_slug(pslug)
        if existing:
            r = requests.post(BASE + f"/pages/{existing}", auth=AUTH, json=payload, timeout=30)
            action = "更新"
        else:
            r = requests.post(BASE + "/pages", auth=AUTH, json=payload, timeout=30)
            action = "新規"
        if r.status_code in (200, 201):
            j = r.json()
            print(f"✓ {action} page id={j['id']} slug={pslug} title={title}({len(title)}字)")
            print(f"    編集: https://it-career-navi.net/wp-admin/post.php?post={j['id']}&action=edit")
        else:
            print(f"✗ FAIL {path}: {r.status_code} {r.text[:160]}")


if __name__ == "__main__":
    main()
