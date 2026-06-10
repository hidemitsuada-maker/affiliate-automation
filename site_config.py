"""サイト共通設定。ニッチ(=カテゴリ)ごとのメタ情報とA8アフィリエイトブロックを一元管理する。

- wp_publish.py / new_article.py が共通で参照する単一ソース。
- 新しい記事を追加するとき、ここに登録されたニッチの affiliate ブロックが自動で本文に挿入される。
- affiliate=None のニッチ(提携先未確保)はリンク無しでスキャフォールドされる。
"""

DOMAIN = "https://it-career-navi.net"

# A8アフィリエイトブロック(テキストリンク + バナー + 計測gif)。本文にそのまま挿入される生HTML。
# wp_publish.py の md_to_html は「<」始まりブロックをエスケープせず通すので、この形のまま貼れる。
_AFFILIATE = {
    "inhouse-se": """<a href="https://px.a8.net/svt/ejp?a8mat=4B5OO4+G0X1YQ+3IZO+HV7V6" rel="nofollow">顧客常駐はもう嫌だ！社内SEへ転職するなら【社内SE転職ナビ】</a>
<img border="0" width="1" height="1" src="https://www15.a8.net/0.gif?a8mat=4B5OO4+G0X1YQ+3IZO+HV7V6" alt="">

<a href="https://px.a8.net/svt/ejp?a8mat=4B5OO4+G0X1YQ+3IZO+I2I7L" rel="nofollow">
<img border="0" width="728" height="90" alt="社内SE転職ナビ" src="https://www21.a8.net/svt/bgt?aid=260605732969&wid=001&eno=01&mid=s00000016458003035000&mc=1"></a>
<img border="0" width="1" height="1" src="https://www10.a8.net/0.gif?a8mat=4B5OO4+G0X1YQ+3IZO+I2I7L" alt="">""",

    "tax-accountant": """<a href="https://px.a8.net/svt/ejp?a8mat=4B5OO4+G2PCS2+5B0Y+BWVTE" rel="nofollow">会計士・税理士のキャリア相談ならツインプロ</a>
<img border="0" width="1" height="1" src="https://www19.a8.net/0.gif?a8mat=4B5OO4+G2PCS2+5B0Y+BWVTE" alt="">

<a href="https://px.a8.net/svt/ejp?a8mat=4B5OO4+G2PCS2+5B0Y+BXYE9" rel="nofollow">
<img border="0" width="300" height="250" alt="ツインプロ｜会計士・税理士特化の転職エージェント" src="https://www29.a8.net/svt/bgt?aid=260605732972&wid=001&eno=01&mid=s00000024757002006000&mc=1"></a>
<img border="0" width="1" height="1" src="https://www13.a8.net/0.gif?a8mat=4B5OO4+G2PCS2+5B0Y+BXYE9" alt="">""",

    "vocational-support": """<a href="https://px.a8.net/svt/ejp?a8mat=4B5OO4+G3ASDU+47GS+HV7V6" rel="nofollow">AIやデータサイエンスが学べるIT特化の就労移行支援【Neuro Dive】</a>
<img border="0" width="1" height="1" src="https://www17.a8.net/0.gif?a8mat=4B5OO4+G3ASDU+47GS+HV7V6" alt="">

<a href="https://px.a8.net/svt/ejp?a8mat=4B5OO4+G3ASDU+47GS+HVNAP" rel="nofollow">
<img border="0" width="300" height="250" alt="Neuro Dive" src="https://www28.a8.net/svt/bgt?aid=260605732973&wid=001&eno=01&mid=s00000019630003003000&mc=1"></a>
<img border="0" width="1" height="1" src="https://www13.a8.net/0.gif?a8mat=4B5OO4+G3ASDU+47GS+HVNAP" alt="">""",
}

# niche(=category slug) → メタ情報。
# category_name: WP上の表示名 / pillar_slug: クラスタ記事が内部リンクする総合ガイドのslug
# asp: 主要提携先(確定率の根拠) / affiliate: 本文挿入用HTML(None=提携先未確保)
NICHES = {
    "construction": {
        "category_name": "施工管理からのIT転職",
        "pillar_slug": "construction-it-guide",
        "pillar_title": "施工管理・現場職からのIT転職 完全ガイド",
        "asp": None,            # 提携否認。記事はdraft塩漬け。
        "affiliate": None,
        "epc": 0,
    },
    "inhouse-se": {
        "category_name": "社内SE転職",
        "pillar_slug": "sier-inhouse-se-guide",
        "pillar_title": "SIer・社内SEへの転職 完全ガイド",
        "asp": "社内SE転職ナビ",
        "affiliate": _AFFILIATE["inhouse-se"],
        "epc": 170,             # 確定率43.21%
        # 確定率を守るための読者層ガイダンス(ASPの否認条件回避)。プロンプトに渡す。
        "lead_guidance": (
            "社内SE転職ナビは登録対象が【関東/関西/北海道エリア・正社員志望・IT実務 or 近接経験】。"
            "確定率を落とさないため、時短勤務希望/45歳以上/完全未経験すぎる層/精神疾患を理由にした転職を"
            "煽る訴求は避ける。正社員フルタイムで残業の少ない働き方を軸に書く。"
        ),
    },
    "tax-accountant": {
        "category_name": "税理士からのIT転職",
        "pillar_slug": "tax-accountant-it-guide",
        "pillar_title": "税理士・士業からのIT転職 完全ガイド",
        "asp": "ツインプロ",
        "affiliate": _AFFILIATE["tax-accountant"],
        "epc": 872,             # 確定率56.25% / 最優先(EPC最高)
        "lead_guidance": (
            "ツインプロは【24〜49歳・会計事務所/税理士法人/経理など会計実務の経験者】が対象。"
            "会計経験者に向けて書き、完全未経験・50歳以上を主対象にした訴求は避ける。"
            "『ITに行くか会計の専門性を活かすか迷う段階での無料キャリア相談』として自然に繋ぐと確定率が高い。"
        ),
    },
    "vocational-support": {
        "category_name": "IT就労移行・社会復帰",
        "pillar_slug": "vocational-it-guide",
        "pillar_title": "発達障害・うつからのIT就労 完全ガイド",
        "asp": "Neuro Dive",
        "affiliate": _AFFILIATE["vocational-support"],
        "epc": 66,              # 確定率51.85%
        "lead_guidance": (
            "Neuro Diveは障害者手帳を持つ(または取得予定の)発達障害・うつ等の当事者が対象の就労移行支援。"
            "当事者に寄り添い、無料見学・相談へ繋ぐ。手帳が無い一般転職層を主対象にした訴求は避ける。"
        ),
    },
}


def pillar_url(niche):
    """クラスタ記事が貼る内部リンク先(=総合ガイドのパーマリンク)。
    パーマリンク構造はフラット(/%postname%/)。カテゴリ階層は付けない(付けると301になる)。"""
    return f"{DOMAIN}/{NICHES[niche]['pillar_slug']}/"
