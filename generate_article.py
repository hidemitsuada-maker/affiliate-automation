"""毎日のドラフト自動生成(ローカルcron + Claude)。

フロー: キュー(niche|slug|keyword)を1件取得 → Claudeで本文生成 →
        A8アフィリンク/ピラーリンクをsite_configの正規値に置換 → 検証 →
        drafts/article-<slug>.md を status=draft で書き出し → articles.json追記 → キュー消化。

★公開はしない(status=draft)。目視 → articles.jsonをpublishに → wp_publish.py が公開ゲート。
★Claudeに A8の生HTMLは触らせない。本文中の {{AFFILIATE}} / {{PILLAR_LINK}} を後置換するので
  リンクのハルシネーション/ソースコード化が原理的に起きない。

バックエンド(AFFI_BACKEND):
  cli (デフォルト) … Claude Code を headless(claude -p)で実行。API課金なし・サブスク枠で動く。
                     APIキー不要。claude にログイン済みであればそのまま動く。
  api            … anthropic SDK。ANTHROPIC_API_KEY が必要(従量課金)。

usage:
  python generate_article.py            # キュー先頭を1件生成(cli=サブスク枠)
  python generate_article.py --dry-run  # Claudeを叩かずプロンプトだけ表示(配線確認)
  python generate_article.py -n 3       # 3件まとめて生成
  AFFI_BACKEND=api python generate_article.py   # API経由に切替
"""
import os
import re
import sys
import json
import argparse
import datetime
import subprocess

import kwqueue as kq
from site_config import NICHES, pillar_url
import wp_publish as wp  # md_to_html / extract_meta の検証に使う(import時ネットワーク無し)

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "articles.json")
LOG = os.path.join(HERE, "generate.log")

# 自動公開: AFFI_AUTO_PUBLISH=1 で、検証(validate)を通った記事を status=publish で登録する。
#   → WP_SYNC が publish としてWP公開 → gsc_submit がIndexing API送信、まで無人で進む。
#   未設定(デフォルト)は従来通り status=draft(手動公開ゲート)。検証NGはどちらでも公開されない。
AUTO_PUBLISH = os.environ.get("AFFI_AUTO_PUBLISH") == "1"

# バックエンド: "cli"=Claude Code headless(サブスク枠/API課金なし) / "api"=anthropic SDK(従量課金)
BACKEND = os.environ.get("AFFI_BACKEND", "cli")
# CLIは "sonnet" のようなエイリアス、APIは "claude-sonnet-4-6" のような正式IDを使う
MODEL = os.environ.get("AFFI_MODEL", "sonnet" if BACKEND == "cli" else "claude-sonnet-4-6")
CLAUDE_BIN = os.environ.get("AFFI_CLAUDE_BIN", "/opt/homebrew/bin/claude")

PR_LINE = "> **本記事にはプロモーション（広告）が含まれます。**"
DISCLAIMER = "*この記事は公開情報と一般的なキャリアアドバイスに基づいて作成しています。個別の転職結果を保証するものではありません。*"

SYSTEM = (
    "あなたは日本のIT転職アフィリエイトサイトの編集者です。検索意図に最短で答える、"
    "読者目線で実用的なSEO記事を書きます。誇張や嘘の断定を避け、一次情報(経産省のIT人材不足試算など)は"
    "正確に扱います。広告リンクのURLは絶対に自分で作らず、指定のプレースホルダのみを使います。"
)


def build_prompt(niche, slug, keyword):
    n = NICHES[niche]
    guidance = n.get("lead_guidance", "")
    return f"""次の条件で記事を1本、Markdownで書いてください。**出力は記事本文のみ**(前置き・コードフェンス・説明は一切不要)。

# 記事の条件
- 検索キーワード: 「{keyword}」(この検索意図に答える)
- カテゴリ(ニッチ): {n['category_name']}
- 提携サービス: {n['asp']}
- 確定率を守るための読者層ガイダンス(重要): {guidance}

# 構成(この順序で)
1. 1行目: `# タイトル`  ……日本語28字以内。検索意図が伝わる自然なタイトル(キーワードの要素を含める)。
2. 2行目: `<!-- meta: 説明 -->`  ……メタディスクリプション80字以内。
3. `{PR_LINE}`  ……この1行をそのまま(PR表記、ファーストビュー必須)。
4. `---`
5. `## この記事でわかること`  ……箇条書き3〜5点(結論先出し)。
6. 本文H2を3〜4本。各H2は具体的で実用的に。**どこか1箇所にMarkdownの表**を入れる(滞在時間対策)。結論先出し・理由後置。
7. `## 転職を成功させるための進め方`  ……なぜ{n['asp']}への無料相談が有効かを2〜3段落。否認条件に当たる層を煽らない。段落の直後に、次の1行を**そのまま単独行**で置く:
   {{{{AFFILIATE}}}}
   その後に「相談・利用は求職者側は無料です（採用した企業が報酬を払う仕組み）。複数登録して比較するのも一般的です。」の一文。
8. `## 関連記事`  ……本文に: `より体系的に知りたい方は総合ガイドへ → {{{{PILLAR_LINK}}}}`
9. `## まとめ`  ……箇条書き3〜4点で要点再掲 + 最後に行動喚起(まず無料相談から)。
10. 最終行: `{DISCLAIMER}`  ……そのまま。

# 文章ルール
- 全体3000〜3800字程度。冗長な前置きや初心者向け注意書きは省く。
- セクション区切りに `---` を使う。
- `{{{{AFFILIATE}}}}` と `{{{{PILLAR_LINK}}}}` は**指定箇所に正確に1回ずつ**。それ以外でURLやリンクを書かない。
- 嘘の数字・実在しない制度を作らない。一般論として正しい範囲で書く。
- 文体は敬体(ですます調)で統一する(「だ・である調」にしない)。
"""


def call_claude(system, prompt):
    """BACKEND に応じて Claude Code CLI(サブスク枠) か anthropic API を叩く。"""
    if BACKEND == "cli":
        return _call_cli(system, prompt)
    return _call_api(system, prompt)


def _call_cli(system, prompt):
    """Claude Code を headless(-p)で実行。API課金なし・サブスク枠で動く。
    プロンプトはstdin、編集者ペルソナは --append-system-prompt で付与。"""
    cmd = [CLAUDE_BIN, "-p", "--output-format", "text",
           "--model", MODEL, "--append-system-prompt", system]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=420)
    except FileNotFoundError:
        raise SystemExit(f"claude CLI が見つからない: {CLAUDE_BIN}(AFFI_CLAUDE_BIN で上書き可)")
    except subprocess.TimeoutExpired:
        raise SystemExit("claude CLI がタイムアウト(420s)")
    if r.returncode != 0:
        raise SystemExit(f"claude CLI 失敗 rc={r.returncode}: {(r.stderr or '')[:500]}")
    out = r.stdout.strip()
    if not out:
        raise SystemExit("claude CLI の出力が空")
    return out


def _call_api(system, prompt):
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY 未設定(.env か環境変数で渡してください)")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=MODEL, max_tokens=6000, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def inject(md, niche):
    """{{AFFILIATE}} / {{PILLAR_LINK}} を site_config の正規値に置換。"""
    n = NICHES[niche]
    md = md.replace("{{AFFILIATE}}", n["affiliate"] or "")
    link = f"[{n['pillar_title']}]({pillar_url(niche)})"
    md = md.replace("{{PILLAR_LINK}}", link)
    # 万一コードフェンスで囲ってきたら剥がす
    md = re.sub(r"^```[a-z]*\n", "", md)
    md = re.sub(r"\n```\s*$", "", md)
    return md.strip() + "\n"


def validate(md, niche):
    """公開前の自動チェック。問題があれば理由リストを返す(空=OK)。"""
    problems = []
    title, html = wp.md_to_html(md)
    meta = wp.extract_meta(md)
    if not title:
        problems.append("タイトル(# 見出し)が無い")
    elif len(title) > 32:
        problems.append(f"タイトル{len(title)}字(32字超)")
    if not meta:
        problems.append("metaコメントが無い")
    elif len(meta) > 90:
        problems.append(f"meta{len(meta)}字(90字超)")
    if "{{" in md:
        problems.append("未置換のプレースホルダが残存")
    if html.count("&lt;a") > 0:
        problems.append("生HTMLがエスケープされている(変換不整合)")
    if NICHES[niche]["affiliate"] and "px.a8.net" not in html:
        problems.append("A8アフィリンクが本文に無い")
    if pillar_url(niche).split("//")[1] not in html:
        problems.append("ピラー内部リンクが無い")
    return problems, title, meta


def register(file_rel, niche, slug):
    reg = json.load(open(REGISTRY, encoding="utf-8"))
    if any(a["slug"] == slug for a in reg["articles"]):
        return False
    status = "publish" if AUTO_PUBLISH else "draft"
    reg["articles"].append({"file": file_rel, "niche": niche, "slug": slug, "status": status})
    json.dump(reg, open(REGISTRY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return True


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    open(LOG, "a", encoding="utf-8").write(line + "\n")


def generate_one(dry_run=False):
    item = kq.next_pending()
    if not item:
        log("キューが空。生成スキップ。")
        return False
    path, niche, slug, keyword = item
    if niche not in NICHES:
        log(f"✗ 未知のniche '{niche}' ({os.path.basename(path)}) スキップ"); kq.mark_done(path); return False

    prompt = build_prompt(niche, slug, keyword)
    if dry_run:
        print("=" * 70)
        print(f"DRY-RUN  backend={BACKEND} model={MODEL}  niche={niche} slug={slug} kw={keyword}")
        print("=" * 70)
        print("[SYSTEM]\n" + SYSTEM + "\n")
        print("[USER]\n" + prompt)
        return True

    out_rel = f"drafts/article-{slug}.md"
    out_abs = os.path.join(HERE, out_rel)
    if os.path.exists(out_abs):
        log(f"✗ 既存ファイル {out_rel} スキップ(slug重複)"); kq.mark_done(path); return False

    log(f"生成開始: {keyword}  → {niche}/{slug}  (backend={BACKEND} model={MODEL})")
    raw = call_claude(SYSTEM, prompt)
    md = inject(raw, niche)
    problems, title, meta = validate(md, niche)
    if problems:
        # 不合格でも .review ファイルに残して人が直せるようにする(キューは消化しない)
        bad = os.path.join(HERE, f"drafts/_review-{slug}.md")
        open(bad, "w", encoding="utf-8").write(md)
        log(f"⚠ 検証NG {slug}: {', '.join(problems)} → {bad} に保存(キューは保持、要手直し)")
        return False

    open(out_abs, "w", encoding="utf-8").write(md)
    register(out_rel, niche, slug)
    kq.mark_done(path)
    status = "publish" if AUTO_PUBLISH else "draft"
    log(f"✓ 生成完了 {out_rel}  title={title}({len(title)}字) meta={len(meta)}字  status={status}")
    if AUTO_PUBLISH:
        log(f"  → 自動公開モード: WP_SYNCでWP公開 → gsc_submitでIndexing送信まで無人実行")
    else:
        log(f"  → 目視: drafts/article-{slug}.md / 公開はarticles.jsonをpublishにしてwp_publish.py")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=1, help="生成本数(default 1)")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かずプロンプト表示")
    args = ap.parse_args()
    made = 0
    for _ in range(args.count):
        if generate_one(dry_run=args.dry_run):
            made += 1
        elif not args.dry_run:
            break  # 失敗 or 空なら止める
    if not args.dry_run:
        log(f"バッチ終了: {made}/{args.count} 生成。残キュー {kq.pending_count()} 件。")


# .env を読む(python-dotenv非依存の簡易ローダ)
def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

if __name__ == "__main__":
    main()
