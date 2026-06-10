"""記事アイキャッチ(サムネ)をローカル生成する。API/課金なし・Pillowのみ。

1200x630(OGP標準)のタイトルテキスト型サムネ。ニッチ別カラー・自動折り返し・
auto-shrink(枠に収まる最大フォントを選ぶ)。日本語フォントはmacのヒラギノ角ゴを使う。

wp_publish.py が公開直前に make_thumbnail() を呼び、生成PNGをWPへアップして
featured_media に設定する(=記事のアイキャッチ)。
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
THUMB_DIR = os.path.join(HERE, "thumbs")

W, H = 1200, 630
MARGIN = 80

# macOS同梱の日本語フォント(太さ違い)
FONT_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc"  # タイトル
FONT_MED = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"   # サイト名
FONT_REG = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"   # ドメイン/バッジ

SITE_NAME = "IT転職ナビ"
DOMAIN = "it-career-navi.net"

# niche → (背景色, アクセント色)。濃色背景に白文字で可読性を確保する。
THEME = {
    "tax-accountant":     ("#1f4d3d", "#e3b84e"),  # 深緑 × 金(会計=信頼)
    "inhouse-se":         ("#16335c", "#4da3ff"),  # 紺 × 水色(IT/SE)
    "vocational-support": ("#43386b", "#f0a35e"),  # 紫 × オレンジ(やわらか)
    "construction":       ("#37404a", "#ff8c42"),  # グレー × オレンジ(現場)
}
_DEFAULT_THEME = ("#23303a", "#4da3ff")


def _wrap(draw, text, font, max_w):
    """日本語向けに文字単位で折り返す(英単語の途中改行は許容)。"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if draw.textlength(cur + ch, font=font) <= max_w or not cur:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _fit_title(draw, text, max_w, max_lines, sizes):
    """max_lines行以内に収まる最大フォントサイズを選ぶ(auto-shrink)。"""
    for sz in sizes:
        font = ImageFont.truetype(FONT_BOLD, sz)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines, sz
    font = ImageFont.truetype(FONT_BOLD, sizes[-1])
    return font, _wrap(draw, text, font, max_w), sizes[-1]


def make_thumbnail(title, niche, category_name, out_path=None):
    """title/niche/category_name からサムネPNGを生成し、保存パスを返す。"""
    os.makedirs(THUMB_DIR, exist_ok=True)
    bg, accent = THEME.get(niche, _DEFAULT_THEME)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # 左の縦アクセントバー
    draw.rectangle([0, 0, 14, H], fill=accent)
    # 上下の細いアクセントライン
    draw.rectangle([0, 0, W, 6], fill=accent)
    draw.rectangle([0, H - 6, W, H], fill=accent)

    content_w = W - MARGIN * 2

    # カテゴリバッジ(上部・角丸・アクセント枠)
    badge_font = ImageFont.truetype(FONT_REG, 30)
    bt = category_name
    btw = draw.textlength(bt, font=badge_font)
    bx0, by0 = MARGIN, 70
    pad_x, pad_y = 22, 12
    draw.rounded_rectangle(
        [bx0, by0, bx0 + btw + pad_x * 2, by0 + 30 + pad_y * 2],
        radius=10, fill=accent,
    )
    draw.text((bx0 + pad_x, by0 + pad_y), bt, font=badge_font, fill=bg)

    # タイトル(中央寄せ・auto-shrink・最大3行)
    title_font, lines, sz = _fit_title(
        draw, title, content_w, max_lines=3, sizes=[78, 70, 62, 56, 50, 44],
    )
    line_h = int(sz * 1.34)
    block_h = line_h * len(lines)
    ty = (H - block_h) // 2 + 20  # バッジ/フッタを避けてやや下げる
    for ln in lines:
        draw.text((MARGIN, ty), ln, font=title_font, fill="#ffffff")
        ty += line_h

    # フッタ: サイト名(白) + ドメイン(アクセント)
    site_font = ImageFont.truetype(FONT_MED, 38)
    dom_font = ImageFont.truetype(FONT_REG, 28)
    fy = H - 90
    draw.text((MARGIN, fy), SITE_NAME, font=site_font, fill="#ffffff")
    sw = draw.textlength(SITE_NAME, font=site_font)
    draw.text((MARGIN + sw + 20, fy + 9), DOMAIN, font=dom_font, fill=accent)

    if out_path is None:
        out_path = os.path.join(THUMB_DIR, "article-thumb.png")
    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    # スモークテスト: 4ニッチ分を生成
    samples = [
        ("税理士科目合格で諦めた後の転職ガイド", "tax-accountant", "税理士からのIT転職"),
        ("社内SE 未経験から子育てと両立できる働き方", "inhouse-se", "社内SE転職"),
        ("うつの休職からITエンジニアへ復帰する方法", "vocational-support", "IT就労移行・社会復帰"),
        ("施工管理から未経験でITに転職する完全ロードマップ案件", "construction", "施工管理からのIT転職"),
    ]
    for t, n, c in samples:
        p = make_thumbnail(t, n, c, os.path.join(THUMB_DIR, f"_sample-{n}.png"))
        print("✓", p)
