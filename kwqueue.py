"""keyword-queue の共有パーサ。

キューファイル形式: 1行 `niche|slug|keyword`
  - niche : site_config.NICHES のキー(tax-accountant 等)
  - slug  : 記事URLのslug(英数ハイフン)
  - keyword: 対象検索KW(日本語)
ファイル名 YYYY-MM-DD-NNN.txt の昇順=処理順。処理済みは .done にリネーム。
"""
import os
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE_DIR = os.path.join(HERE, "keyword-queue")


def _parse(path):
    line = open(path, encoding="utf-8").read().strip()
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"キュー形式不正(niche|slug|keyword 期待): {os.path.basename(path)} -> {line!r}")
    niche, slug, keyword = parts
    return niche, slug, keyword


def next_pending():
    """最古の未処理キューを (path, niche, slug, keyword) で返す。無ければ None。"""
    for f in sorted(glob.glob(os.path.join(QUEUE_DIR, "*.txt"))):
        niche, slug, keyword = _parse(f)
        return f, niche, slug, keyword
    return None


def pending_count():
    return len(glob.glob(os.path.join(QUEUE_DIR, "*.txt")))


def mark_done(path):
    os.rename(path, path + ".done")
