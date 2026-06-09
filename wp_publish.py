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
import requests
from requests.auth import HTTPBasicAuth

BASE = "https://it-career-navi.net/wp-json/wp/v2"
USER = os.environ.get("WP_USER", "")
APP = os.environ.get("WP_APP_PASS", "")
AUTH = HTTPBasicAuth(USER, APP)

# 記事 → (file, category_slug, category_name, post_slug)
ARTICLES = [
    ("drafts/article-A-construction-it-career.md", "construction", "施工管理からのIT転職", "inexperienced-truth"),
    ("drafts/article-B-sier-inhouse-se.md", "inhouse-se", "社内SE転職", "sier-salary-reality"),
    ("drafts/article-C-inhouse-se-childcare.md", "inhouse-se", "社内SE転職", "childcare-work-balance"),
    ("drafts/article-D-adhd-it-career.md", "vocational-support", "IT就労移行・社会復帰", "adhd-remote-it"),
    ("drafts/article-E-tax-accountant-it-career.md", "tax-accountant", "税理士からのIT転職", "age-34-too-late"),
]


def _inline(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", t)
    return t


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


def find_post_by_slug(slug):
    r = requests.get(BASE + f"/posts?slug={slug}&status=draft,publish,pending,future&per_page=1",
                     auth=AUTH, timeout=20)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return None


def main():
    if not USER or not APP:
        print("WP_USER / WP_APP_PASS env 未設定"); sys.exit(1)
    cat_cache = {}
    for path, cslug, cname, pslug in ARTICLES:
        md = open(path, encoding="utf-8").read()
        title, content = md_to_html(md)
        if cslug not in cat_cache:
            cat_cache[cslug] = ensure_category(cslug, cname)
        cid = cat_cache[cslug]
        payload = {"title": title, "content": content, "slug": pslug,
                   "status": "draft", "categories": [cid]}
        existing = find_post_by_slug(pslug)
        if existing:
            r = requests.post(BASE + f"/posts/{existing}", auth=AUTH, json=payload, timeout=30)
            action = "更新"
        else:
            r = requests.post(BASE + "/posts", auth=AUTH, json=payload, timeout=30)
            action = "新規"
        if r.status_code in (200, 201):
            j = r.json()
            print(f"✓ {action} draft id={j['id']} [{cslug}] slug={pslug} title={title[:30]}")
            print(f"    編集: https://it-career-navi.net/wp-admin/post.php?post={j['id']}&action=edit")
        else:
            print(f"✗ FAIL {path}: {r.status_code} {r.text[:160]}")


if __name__ == "__main__":
    main()
