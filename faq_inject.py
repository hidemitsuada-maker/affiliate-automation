"""公開記事にFAQ(よくある質問)を自動生成して追記し、FAQPage構造化データを注入する。

狙い: 検索意図に沿ったQ&AでSERPのFAQリッチリザルトを取り(占有面積↑・CTR↑)、
      同時にロングテール質問クエリの回収面を増やす。Cocoonは Article/Breadcrumb の
      schemaは出すが FAQPage は出さないので、ここが純粋な追加価値。

仕組み:
  - 対象: articles.json の status=publish かつ wp_id を持つ記事。
  - FAQは claude -p(サブスク枠・API課金ゼロ)で記事タイトル+メタ+意図から3〜4問生成。
  - 可視HTML(<h2>よくある質問> + Q/A)と FAQPage JSON-LD を同じ内容で出力
    (Googleの「回答は本文に可視であること」要件を満たす)。
  - マーカー <!-- auto-faq-start/end --> で挟み、冪等。既にブロックがある記事は
    既定でスキップ(クォータ節約)。--force で再生成。

日次運用: wp_sync後に走らせると、その日公開された新記事だけFAQが付く(既存はスキップ)。

usage:
  python faq_inject.py --dry-run        # 生成結果を表示(WP更新しない)
  python faq_inject.py --limit 1        # 1記事だけ処理(動作確認/クォータ節約)
  python faq_inject.py                   # FAQ未付与の公開記事すべてに付与
  python faq_inject.py --force --limit 1 # 既存FAQを作り直す(1記事)
"""
import os
import re
import json
import html
import argparse
import subprocess

import requests
from requests.auth import HTTPBasicAuth
from site_config import NICHES

import internal_links as il

HERE = os.path.dirname(os.path.abspath(__file__))
REG_PATH = os.path.join(HERE, "articles.json")
BASE = "https://it-career-navi.net/wp-json/wp/v2"
START = "<!-- auto-faq-start -->"
END = "<!-- auto-faq-end -->"

CLAUDE_BIN = os.environ.get("AFFI_CLAUDE_BIN", "/opt/homebrew/bin/claude")
MODEL = os.environ.get("AFFI_MODEL", "sonnet")

SYSTEM = (
    "あなたはIT転職メディアの編集者。記事タイトルと概要から、読者が実際に検索する"
    "『よくある質問』を作る。質問は検索意図に直結したロングテール(『〜は何歳まで？』"
    "『未経験でも〜できる？』『〜の年収は？』等)。回答は事実ベースで具体的、"
    "各2〜3文。煽り・誇大表現・断定的な保証は禁止。読者の不安を解消する実用的な内容に。"
    "出力は指定のJSON配列のみ。前置き・コードフェンス・解説は一切付けない。"
)


def call_claude(prompt):
    """claude -p(headless, サブスク枠)。JSON文字列を返す。"""
    cmd = [CLAUDE_BIN, "-p", "--output-format", "text",
           "--model", MODEL, "--append-system-prompt", SYSTEM]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI 失敗 rc={r.returncode}: {(r.stderr or '')[:300]}")
    return r.stdout.strip()


def build_prompt(title, meta, niche):
    n = NICHES[niche]
    return (
        f"記事タイトル: {title}\n"
        f"記事概要(meta): {meta}\n"
        f"テーマ: {n['category_name']}\n\n"
        "この記事の読者が検索しそうな『よくある質問』を3〜4問作成してください。\n"
        "出力は次の形式のJSON配列のみ(キーは q と a):\n"
        '[{"q":"質問文","a":"回答(2〜3文・事実ベース)"}, ...]\n'
    )


def parse_faqs(raw):
    """claudeの出力からQ&A配列を取り出す。コードフェンス/前後ノイズに耐える。"""
    s = raw.strip()
    s = re.sub(r"^```[a-z]*\n", "", s)
    s = re.sub(r"\n```\s*$", "", s).strip()
    # 本文に配列が埋もれていても拾う
    m = re.search(r"\[.*\]", s, re.DOTALL)
    if m:
        s = m.group(0)
    data = json.loads(s)
    out = []
    for item in data:
        q = (item.get("q") or "").strip()
        a = (item.get("a") or "").strip()
        if q and a:
            out.append({"q": q, "a": a})
    return out


def build_block(faqs):
    """可視HTML + FAQPage JSON-LD を同一内容で組む(可視テキスト要件を満たす)。"""
    if not faqs:
        return ""
    # 可視HTML(回答がページ上に見えていることがリッチリザルトの条件)
    vis = ["<h2>よくある質問</h2>"]
    for f in faqs:
        vis.append(f"<h3>{html.escape(f['q'])}</h3>")
        vis.append(f"<p>{html.escape(f['a'])}</p>")
    visible = "\n".join(vis)
    # FAQPage JSON-LD(json.dumps が文字列エスケープを担保)
    ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["q"],
             "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
            for f in faqs
        ],
    }
    script = ('<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return f"{START}\n{visible}\n{script}\n{END}"


def strip_block(content):
    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    return pat.sub("", content).rstrip() + "\n"


def has_block(content):
    return START in content


def main():
    il._load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="WP更新せず生成結果を表示")
    ap.add_argument("--limit", type=int, default=0, help="処理する記事数の上限(0=無制限)")
    ap.add_argument("--force", action="store_true", help="既存FAQブロックも作り直す")
    args = ap.parse_args()

    user = os.environ.get("WP_USER", "")
    app = os.environ.get("WP_APP_PASS", "")
    if not user or not app:
        raise SystemExit("WP_USER / WP_APP_PASS env 未設定")
    auth = HTTPBasicAuth(user, app)

    reg = json.load(open(REG_PATH, encoding="utf-8"))
    pub = [a for a in reg.get("articles", [])
           if a.get("status") == "publish" and a.get("wp_id")]

    done = 0
    for a in pub:
        if args.limit and done >= args.limit:
            break
        post = il.fetch_post(auth, a["wp_id"])
        if not post:
            print(f"⚠ 本文取得失敗 slug={a['slug']} id={a['wp_id']}")
            continue
        if has_block(post["content"]) and not args.force:
            continue  # 既にFAQあり → クォータ節約のためスキップ

        # メタ(excerpt)を取得して文脈に使う
        r = requests.get(BASE + f"/posts/{a['wp_id']}",
                         params={"context": "edit", "_fields": "excerpt"},
                         auth=auth, timeout=20)
        meta = ""
        if r.status_code == 200:
            meta = re.sub(r"<[^>]+>", "", r.json().get("excerpt", {}).get("raw", "")).strip()

        try:
            raw = call_claude(build_prompt(post["title"], meta, a["niche"]))
            faqs = parse_faqs(raw)
        except Exception as e:
            print(f"✗ FAQ生成失敗 slug={a['slug']}: {e}")
            continue
        if not faqs:
            print(f"✗ FAQ空 slug={a['slug']}(生成出力をパースできず)")
            continue

        block = build_block(faqs)
        new_content = strip_block(post["content"]).rstrip() + "\n\n" + block + "\n"

        if args.dry_run:
            print(f"\n[DRY] id={a['wp_id']} slug={a['slug']} FAQ{len(faqs)}問")
            for f in faqs:
                print(f"  Q: {f['q']}\n     A: {f['a']}")
            done += 1
            continue

        rr = requests.post(BASE + f"/posts/{a['wp_id']}", auth=auth,
                           json={"content": new_content}, timeout=30)
        if rr.status_code in (200, 201):
            print(f"✓ FAQ注入 id={a['wp_id']} slug={a['slug']} {len(faqs)}問")
            done += 1
        else:
            print(f"✗ 更新失敗 slug={a['slug']}: {rr.status_code} {rr.text[:160]}")

    print(f"\n完了: {done}件 処理 / 公開{len(pub)}本")


if __name__ == "__main__":
    main()
