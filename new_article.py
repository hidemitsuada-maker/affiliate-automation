"""半自動の記事追加: キーワードから記事ドラフトの雛形を生成する。

役割は「toilの自動化」だけ。本文(プロのコピー)は人(またはClaude)が後から埋める。
  1. keyword-queue から次のKWを取得(または引数で指定)
  2. ニッチ(=カテゴリ)に応じたA8アフィリエイトブロックと内部リンクを自動挿入
  3. PR表記・構成見出し・免責などの定型を雛形化
  4. articles.json に status=draft で追記(wp_publish.pyが拾えるようになる)
  5. 消化したキューを .done にリネーム

これは「手書き用」の雛形フォールバック。AIで本文ごと自動生成する常用パスは generate_article.py。

usage:
  # キュー先頭(niche|slug|keyword)から雛形を起こす
  python new_article.py
  # KW/niche/slugを明示(キュー外で1本作る)
  python new_article.py --niche tax-accountant --slug accounting-office-quit "会計事務所 辞めたい 転職"

生成後の流れ: ドラフトの【】を加筆/目視 → articles.json の status を publish に → wp_publish.py 実行。
"""
import os
import sys
import json
import argparse
import kwqueue as kq
from site_config import NICHES, pillar_url

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "articles.json")


def scaffold(keyword, niche, slug):
    n = NICHES[niche]
    aff = n["affiliate"]
    # アフィリエイトCTAブロック(提携先がある場合のみ)。無ければ内部リンクのみ。
    if aff:
        cta = f"""## 転職を成功させるための進め方

【ここに、なぜエージェント相談が有効かを2〜3段落。{n['asp']}の強み(非公開求人/実態確認/書類添削)に自然につなぐ。確定率を守るため、否認条件に当たる層(時短希望・45歳以上・未経験すぎる等)を煽らない構成にする。】

{aff}

相談・利用は求職者側は無料です（採用した企業が報酬を払う仕組み）。複数登録して比較するのも一般的です。
"""
    else:
        cta = """## 転職を成功させるための進め方

【提携先未確保のニッチ。アフィリンクは入れず、内部リンクと情報提供に徹する。】
"""

    return f"""# 【タイトル30字以内 / 「{keyword}」を含める】
<!-- meta: 【メタディスクリプション80字以内。{keyword}の検索意図に答える要約。】 -->

<!-- PR表記(ファーストビュー必須) -->
> **本記事にはプロモーション（広告）が含まれます。**

---

## この記事でわかること

- 【箇条書き3〜5点。読者が得られる結論を先出し】

---

## 【H2: 検索意図の核心に最短で答える見出し】

【結論先出し。「{keyword}」で来た読者がまず知りたい答えを冒頭に置く。】

---

## 【H2: 根拠・背景の解説】

【データ・構造的な理由。IT人材不足(2030年最大79万人/経産省2019)などの一次情報を必要に応じて。】

---

## 【H2: 具体的な職種 or 進め方(表を使うと滞在時間が伸びる)】

| 項目 | 内容 | 補足 |
|------|------|------|
| 【】 | 【】 | 【】 |

---

{cta}
---

## 関連記事

より体系的に知りたい方は総合ガイドへ → [{n['pillar_title']}]({pillar_url(niche)})

---

## まとめ

【3〜4点の箇条書きで要点を再掲。最後に行動喚起(まず無料相談から)。】

---

*この記事は公開情報と一般的なキャリアアドバイスに基づいて作成しています。個別の転職結果を保証するものではありません。*
"""


def register(file_rel, niche, slug):
    reg = json.load(open(REGISTRY, encoding="utf-8"))
    if any(a["slug"] == slug for a in reg["articles"]):
        print(f"⚠ slug='{slug}' は既に articles.json に存在。追記スキップ。")
        return
    reg["articles"].append({"file": file_rel, "niche": niche, "slug": slug, "status": "draft"})
    json.dump(reg, open(REGISTRY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ articles.json に追記(status=draft): {slug}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword", nargs="?", help="対象KW(省略時はキュー先頭の niche|slug|keyword から取得)")
    ap.add_argument("--niche", choices=list(NICHES.keys()), help="キュー外で1本作るとき必須")
    ap.add_argument("--slug", help="英数ハイフンのURL slug(キュー外で1本作るとき必須)")
    args = ap.parse_args()

    queue_path = None
    keyword, niche, slug = args.keyword, args.niche, args.slug

    # キーワード or niche/slug のいずれかが欠けていればキュー先頭から補完する
    if not (keyword and niche and slug):
        item = kq.next_pending()
        if not item:
            print("キューが空です。keyword/--niche/--slug を全て渡すか keyword-queue/ に投入してください。"); sys.exit(1)
        queue_path, q_niche, q_slug, q_kw = item
        keyword = keyword or q_kw
        niche = niche or q_niche
        slug = slug or q_slug
        print(f"キューから取得: {niche}|{slug}|{keyword}  ({os.path.basename(queue_path)})")

    if niche not in NICHES:
        print(f"✗ 未知のniche '{niche}'"); sys.exit(1)

    out_rel = f"drafts/article-{slug}.md"
    out_abs = os.path.join(HERE, out_rel)
    if os.path.exists(out_abs):
        print(f"✗ 既に存在: {out_rel}  (slugを変えるか削除してから)"); sys.exit(1)

    open(out_abs, "w", encoding="utf-8").write(scaffold(keyword, niche, slug))
    print(f"✓ 雛形生成: {out_rel}  niche={niche}  ASP={NICHES[niche]['asp']}")
    register(out_rel, niche, slug)

    if queue_path:
        kq.mark_done(queue_path)
        print(f"✓ キュー消化: {os.path.basename(queue_path)}.done")

    print("\n次の手順:")
    print(f"  1. {out_rel} の【】を埋める(本文加筆)")
    print(f"  2. 目視OKなら articles.json の '{slug}' を status=publish に")
    print(f'  3. WP_USER=... WP_APP_PASS=... {sys.executable} wp_publish.py')


if __name__ == "__main__":
    main()
