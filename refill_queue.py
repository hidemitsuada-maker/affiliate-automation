"""keyword-queue を自動補充する(claude -p / サブスク枠・API課金なし)。

残キューが MIN_PENDING を下回ったら、TARGET_PENDING 件まで claude にKWを生成させ、
keyword-queue/YYYY-MM-DD-NNN.txt(1行 niche|slug|keyword)として書き出す。

重複対策: 既存記事(articles.json)・現キュー・処理済み(.done)・drafts の全slugを渡し、
          カニバリ(共食い)するKW/slugは生成側で避けさせ、さらにこちら側でも弾く。
ニッチ配分: EPCで重み付け(税理士>社内SE>就労移行)。construction(asp=None)は除外。

usage:
  python refill_queue.py            # 残キューが閾値割れなら補充(launchd/手動共通)
  python refill_queue.py --force    # 閾値に関係なく TARGET まで補充
  python refill_queue.py -n 8       # 補充目標を一時的に8件に
  python refill_queue.py --dry-run  # claudeを叩かずプロンプトだけ表示
"""
import os
import re
import sys
import json
import glob
import argparse
import datetime
import subprocess

from site_config import NICHES
import kwqueue as kq

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "articles.json")
QUEUE_DIR = kq.QUEUE_DIR
LOG = os.path.join(HERE, "refill.log")
CLAUDE_BIN = os.environ.get("AFFI_CLAUDE_BIN", "/opt/homebrew/bin/claude")
MODEL = os.environ.get("AFFI_MODEL", "sonnet")

MIN_PENDING = int(os.environ.get("AFFI_MIN_PENDING", "5"))     # これを下回ったら補充
TARGET_PENDING = int(os.environ.get("AFFI_TARGET_PENDING", "12"))  # ここまで積む

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# 提携先のあるニッチのみ。EPCを重みにして配分(高EPC=多め)。
ACTIVE_NICHES = {k: v for k, v in NICHES.items() if v.get("asp")}

SYSTEM = (
    "あなたは日本のIT転職アフィリエイトサイトのSEOキーワード設計者です。"
    "CVR(無料相談・登録への転換)が高い『購買・行動直前』のロングテールKWを最優先します。"
    "読者が既に行動を決めかけている検索意図(おすすめ/比較/選び方/評判/口コミ/エージェント/"
    "辞めたい→次の一手 など)を狙い、新規ドメインでも数週間で拾える競合の弱い複合KW(3〜5語)を"
    "設計します。提携ASPの否認条件を踏む層は避け、既存記事と共食い(カニバリ)しないテーマを選びます。"
)


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    open(LOG, "a", encoding="utf-8").write(line + "\n")


def existing_slugs():
    """既存の全slug(記事/ページ/キュー/done/drafts)を集める。重複除外の母集合。"""
    slugs = set()
    if os.path.exists(REGISTRY):
        reg = json.load(open(REGISTRY, encoding="utf-8"))
        for a in reg.get("articles", []):
            slugs.add(a.get("slug", ""))
        for p in reg.get("pages", []):
            slugs.add(p.get("slug", ""))
    for f in glob.glob(os.path.join(QUEUE_DIR, "*.txt")) + glob.glob(os.path.join(QUEUE_DIR, "*.txt.done")):
        try:
            line = open(f, encoding="utf-8").read().strip()
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3:
                slugs.add(parts[1])
        except OSError:
            pass
    for f in glob.glob(os.path.join(HERE, "drafts", "article-*.md")):
        slugs.add(os.path.basename(f)[len("article-"):-len(".md")])
    slugs.discard("")
    return slugs


def existing_keywords():
    """既存キュー/done のKW文字列(共食い説明用にプロンプトへ渡す)。"""
    kws = []
    for f in sorted(glob.glob(os.path.join(QUEUE_DIR, "*.txt")) + glob.glob(os.path.join(QUEUE_DIR, "*.txt.done"))):
        try:
            parts = [p.strip() for p in open(f, encoding="utf-8").read().strip().split("|")]
            if len(parts) == 3:
                kws.append(parts[2])
        except OSError:
            pass
    return kws


def niche_allocation(need):
    """need件を各ニッチに配分。まず各activeに最低1件、残りをEPC重みで上乗せ。
    (高EPCニッチを優先しつつ、低EPCニッチを完全に枯らさない=SEO網羅性を維持)"""
    if need <= 0:
        return {}
    weights = {k: max(v.get("epc", 0), 1) for k, v in ACTIVE_NICHES.items()}
    alloc = {k: 0 for k in ACTIVE_NICHES}
    # 各activeに最低1件(needが足りなければEPC上位から埋める)
    for k in sorted(weights, key=weights.get, reverse=True):
        if sum(alloc.values()) >= need:
            break
        alloc[k] = 1
    # 残りをEPC重みで上乗せ
    remaining = need - sum(alloc.values())
    if remaining > 0:
        total = sum(weights.values())
        for k, w in weights.items():
            alloc[k] += int(remaining * w / total)
        # 端数を高EPCニッチへ(軽く減衰させて偏り過ぎを防ぐ)
        while sum(alloc.values()) < need:
            top = max(weights, key=weights.get)
            alloc[top] += 1
            weights[top] = max(weights[top] // 2, 1)
    return {k: v for k, v in alloc.items() if v > 0}


def build_prompt(alloc, slugs, kws):
    lines = []
    for niche, count in alloc.items():
        n = ACTIVE_NICHES[niche]
        lines.append(
            f"- niche=`{niche}` ({n['category_name']} / 提携:{n['asp']}) … {count}件\n"
            f"  読者層の制約(否認条件・厳守): {n.get('lead_guidance', '')}"
        )
    niche_block = "\n".join(lines)
    avoid_slugs = ", ".join(sorted(slugs)) or "(なし)"
    avoid_kws = "\n".join(f"  - {k}" for k in kws) or "  (なし)"
    total = sum(alloc.values())
    return f"""IT転職アフィサイトの新規記事KWを **{total}件** 設計してください。

# ニッチ別の必要数と読者層制約
{niche_block}

# 既存slug(これらと重複/酷似させない)
{avoid_slugs}

# 既存KW(これらと検索意図が被るテーマは避ける=カニバリ防止)
{avoid_kws}

# 狙う検索意図(最優先・CVR重視)
収益化(無料相談・登録)に直結する「行動直前」の複合KWを優先する。次の型を意識:
- 〈職種/状況〉× おすすめ / 比較 / 選び方 / エージェント
  例: 未経験 ITエンジニア 転職 エージェント おすすめ
- 〈悩み〉→ 次の一手(転職先・異業種・抜け出し方)
  例: 客先常駐 辞めたい 異業種 / SES つらい 転職
- 〈属性〉× 向いてる仕事 / 転職できる / 未経験
  例: 30代 未経験 IT 転職 できる
- 評判 / 口コミ / 体験談(実在サービスの虚偽評価は書かない範囲で、一般論として)
避けるもの: 用語解説だけ・広すぎる単KW(例「ITとは」)・競合の強いビッグKW。
→ 「検索したら申し込みに近い人」を狙う。ボリューム小でもインテントが濃いものを選ぶ。

# 出力仕様(厳守)
- **JSON配列のみ**を出力。前置き・説明・コードフェンス一切不要。
- 各要素: {{"niche": "<上記nicheのいずれか>", "slug": "<英小文字数字とハイフンのみ>", "keyword": "<日本語の検索KW>"}}
- slugは内容を表す英語(例: inhouse-se-agent-osusume)。既存slugと重複させない。
- keywordは行動直前のロングテール(3〜5語中心)。情報収集だけの薄いKW・読者層制約を踏む層は狙わない。
- nicheごとに指定件数ちょうど。合計{total}件。
"""


def call_claude(prompt):
    cmd = [CLAUDE_BIN, "-p", "--output-format", "text",
           "--model", MODEL, "--append-system-prompt", SYSTEM]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        raise SystemExit(f"claude CLI が見つからない: {CLAUDE_BIN}")
    except subprocess.TimeoutExpired:
        raise SystemExit("claude CLI がタイムアウト(300s)")
    if r.returncode != 0:
        raise SystemExit(f"claude CLI 失敗 rc={r.returncode}: {(r.stderr or '')[:400]}")
    return r.stdout.strip()


def parse_items(raw):
    """claude出力からJSON配列を取り出す。コードフェンスや前後ノイズを許容。"""
    s = raw.strip()
    s = re.sub(r"^```[a-z]*\n", "", s)
    s = re.sub(r"\n```\s*$", "", s)
    # 最初の '[' から対応する最後の ']' まで
    i, j = s.find("["), s.rfind("]")
    if i == -1 or j == -1 or j < i:
        raise ValueError(f"JSON配列が見つからない: {s[:200]!r}")
    return json.loads(s[i:j + 1])


def validate_items(items, slugs):
    """niche/slug/keyword の妥当性 + 重複除外。採用リストを返す。"""
    seen = set(slugs)
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        niche = str(it.get("niche", "")).strip()
        slug = str(it.get("slug", "")).strip().lower()
        kw = str(it.get("keyword", "")).strip()
        if niche not in ACTIVE_NICHES:
            log(f"  skip: 未知/非activeなniche '{niche}'")
            continue
        if not SLUG_RE.match(slug):
            log(f"  skip: 不正slug '{slug}'")
            continue
        if not kw or "|" in kw:
            log(f"  skip: 不正keyword '{kw}'")
            continue
        if slug in seen:
            log(f"  skip: 重複slug '{slug}'")
            continue
        seen.add(slug)
        out.append((niche, slug, kw))
    return out


def next_date_start():
    """既存キューの最大日付の翌日を、新規ファイルの開始日にする(処理順序が後ろに積まれる)。"""
    dates = []
    for f in glob.glob(os.path.join(QUEUE_DIR, "*.txt")) + glob.glob(os.path.join(QUEUE_DIR, "*.txt.done")):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})-\d+\.txt", os.path.basename(f))
        if m:
            dates.append(datetime.date(int(m[1]), int(m[2]), int(m[3])))
    base = max(dates) if dates else datetime.date.today()
    return base + datetime.timedelta(days=1)


def write_queue(items):
    """採用items を 1日1ファイル(YYYY-MM-DD-001.txt)で書き出す。"""
    d = next_date_start()
    written = []
    for niche, slug, kw in items:
        fname = f"{d:%Y-%m-%d}-001.txt"
        path = os.path.join(QUEUE_DIR, fname)
        while os.path.exists(path):  # 念のため衝突回避
            d += datetime.timedelta(days=1)
            fname = f"{d:%Y-%m-%d}-001.txt"
            path = os.path.join(QUEUE_DIR, fname)
        open(path, "w", encoding="utf-8").write(f"{niche}|{slug}|{kw}\n")
        written.append((fname, niche, slug, kw))
        d += datetime.timedelta(days=1)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--target", type=int, default=TARGET_PENDING, help=f"補充目標(default {TARGET_PENDING})")
    ap.add_argument("--force", action="store_true", help="閾値に関係なく補充")
    ap.add_argument("--dry-run", action="store_true", help="claudeを叩かずプロンプト表示")
    args = ap.parse_args()

    os.makedirs(QUEUE_DIR, exist_ok=True)
    pending = kq.pending_count()
    if not args.force and not args.dry_run and pending >= MIN_PENDING:
        log(f"残キュー {pending} 件(>= MIN {MIN_PENDING})。補充不要。")
        return
    need = max(args.target - pending, 0)
    if need == 0:
        log(f"残キュー {pending} 件(>= target {args.target})。補充不要。")
        return

    alloc = niche_allocation(need)
    slugs = existing_slugs()
    kws = existing_keywords()
    prompt = build_prompt(alloc, slugs, kws)

    if args.dry_run:
        print("=" * 70)
        print(f"DRY-RUN  pending={pending} need={need} alloc={alloc}")
        print("=" * 70)
        print("[SYSTEM]\n" + SYSTEM + "\n\n[USER]\n" + prompt)
        return

    log(f"補充開始: pending={pending} → target={args.target} (need={need}) alloc={alloc}")
    raw = call_claude(prompt)
    try:
        items = parse_items(raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise SystemExit(f"claude出力のパース失敗: {e}")
    good = validate_items(items, slugs)
    if not good:
        log("⚠ 採用できるKWが0件(全て重複/不正)。補充なし。")
        return
    written = write_queue(good)
    for fname, niche, slug, kw in written:
        log(f"  + {fname}  {niche}|{slug}|{kw}")
    log(f"✓ 補充完了 {len(written)}件。残キュー {kq.pending_count()} 件。")


if __name__ == "__main__":
    main()
