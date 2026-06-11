#!/bin/zsh
# 日次パイプライン(launchd net.itcareernavi.generate から毎朝6:00に起動)。
#   1) キュー補充: 残が AFFI_MIN_PENDING を下回ってたら claude(サブスク枠)で補充。足りてれば即return。
#   2) 記事1本生成(サブスク枠)。
#   3) GSC送信: GSC_SA_JSON があれば未送信のpublish記事URLを Indexing API へ。無ければskip。
# 各段は独立に続行(前段が失敗しても後段は走らせる)。全課金ゼロ(サブスク枠+ローカル)。
PY=/Users/insta/instagram/venv/bin/python
cd "$(dirname "$0")" || exit 1

echo "===== run_daily $(date '+%Y-%m-%d %H:%M:%S') ====="

"$PY" refill_queue.py        || echo "[run_daily] refill 失敗(続行)"
"$PY" generate_article.py    || echo "[run_daily] generate 失敗(続行)"
# 生成した記事をWP下書きとして同期(WP管理画面で目視・公開できるように)。
# WP側で公開された記事は articles.json を publish に同期 → 次段gsc_submitが送信。
WP_SYNC=1 "$PY" wp_publish.py || echo "[run_daily] wp_sync 失敗(続行)"
"$PY" gsc_submit.py --if-configured || echo "[run_daily] gsc(URL送信) 失敗(続行)"
# サイトマップ登録(冪等。一度通れば以降は204。所有権の伝播前は権限不足で空振り)
# .envはgsc_submit内の_load_envが読む。--if-configuredでSA未設定時は正常skip。
"$PY" gsc_submit.py --sitemap --if-configured || echo "[run_daily] gsc(sitemap) 失敗(続行)"

echo "===== run_daily done ====="
