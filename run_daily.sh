#!/bin/zsh
# 日次パイプライン(launchd net.itcareernavi.generate から毎朝6:00に起動)。完全無人で公開まで。
#   1) キュー補充: 残が AFFI_MIN_PENDING を下回ってたら claude(サブスク枠)で補充。足りてれば即return。
#   2) 記事1本生成(サブスク枠) + 検証通過なら status=publish(AFFI_AUTO_PUBLISH=1)。
#   3) WP同期: 生成記事をWPに公開(publish)。WP側の編集/公開状態も articles.json に反映。
#   4) GSC送信: 未送信のpublish記事URLを Indexing API へ。
#   5) サイトマップ登録(冪等)。
# 各段は独立に続行(前段が失敗しても後段は走らせる)。全課金ゼロ(サブスク枠+ローカル)。
# 安全弁: 検証NG(タイトル長/meta欠落/A8リンク欠落等)の記事は公開されず _review- に退避。
PY=/Users/insta/instagram/venv/bin/python
cd "$(dirname "$0")" || exit 1

echo "===== run_daily $(date '+%Y-%m-%d %H:%M:%S') ====="

"$PY" refill_queue.py        || echo "[run_daily] refill 失敗(続行)"
# AFFI_AUTO_PUBLISH=1: 検証(validate)を通った記事を status=publish で登録 → 無人で公開まで。
# 検証NG(タイトル長/meta/A8リンク欠落等)は _review- に退避され公開されない安全弁つき。
AFFI_AUTO_PUBLISH=1 "$PY" generate_article.py || echo "[run_daily] generate 失敗(続行)"
# 生成した記事をWP下書きとして同期(WP管理画面で目視・公開できるように)。
# WP側で公開された記事は articles.json を publish に同期 → 次段gsc_submitが送信。
WP_SYNC=1 "$PY" wp_publish.py || echo "[run_daily] wp_sync 失敗(続行)"
# 同一ニッチの公開記事を相互内部リンク(トピッククラスタ強化)。冪等。新記事公開のたび全記事を最新化。
"$PY" internal_links.py || echo "[run_daily] internal_links 失敗(続行)"
# FAQ自動生成 + FAQPage構造化データ注入(SERPのFAQリッチリザルト→CTR↑)。FAQ未付与の公開記事のみ処理(冪等)。
"$PY" faq_inject.py || echo "[run_daily] faq_inject 失敗(続行)"
"$PY" gsc_submit.py --if-configured || echo "[run_daily] gsc(URL送信) 失敗(続行)"
# サイトマップ登録(冪等。一度通れば以降は204。所有権の伝播前は権限不足で空振り)
# .envはgsc_submit内の_load_envが読む。--if-configuredでSA未設定時は正常skip。
"$PY" gsc_submit.py --sitemap --if-configured || echo "[run_daily] gsc(sitemap) 失敗(続行)"
# 検索パフォーマンスの日次スナップショットを履歴に追記(効果測定の土台)。
# GSC_SA_JSON未設定なら get_session が落ちるが || で続行。サイト追加の自己修復も兼ねる。
"$PY" gsc_report.py --save >/dev/null 2>&1 || echo "[run_daily] gsc_report 失敗(続行)"

echo "===== run_daily done ====="
