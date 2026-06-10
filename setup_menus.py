"""WordPress(it-career-navi.net)のメニューをREST APIで構築する。

- 認証は環境変数 WP_USER / WP_APP_PASS から(秘密はファイルに持たせない)。
- グローバル(ヘッダー/モバイル) = 4テーマのPillar記事へ直リンク。
- フッター = 必須固定ページ4本(運営者情報/プライバシー/免責/お問い合わせ)。
- 冪等: 同名メニューが在れば再利用し、既存項目を消してから貼り直す。

usage:
  WP_USER=ken_takahashi WP_APP_PASS="xxxx ..." python setup_menus.py
"""
import os
import sys
import requests
from requests.auth import HTTPBasicAuth

BASE = "https://it-career-navi.net/wp-json/wp/v2"
AUTH = HTTPBasicAuth(os.environ.get("WP_USER", ""), os.environ.get("WP_APP_PASS", ""))

# (メニュー名, 割当ロケーション, 項目[(ラベル, object種別, object_id), ...])
MENUS = [
    ("グローバル", ["navi-header", "navi-mobile", "navi-mobile-slide-in"], [
        # 施工管理(P1 post 23)は提携先未確保で保留(draft)のためメニューから除外。
        # 提携先承認→P1公開後に復活させる。
        ("SIer・社内SE", "post", 24),       # Pillar P2
        ("士業・税理士から", "post", 25),    # Pillar P3
        ("発達障害・うつから", "post", 26),  # Pillar P4
    ]),
    ("フッター", ["navi-footer"], [
        ("運営者情報", "page", 27),
        ("プライバシーポリシー", "page", 3),
        ("免責事項", "page", 29),
        ("お問い合わせ", "page", 30),
    ]),
]


def find_menu(name):
    r = requests.get(BASE + "/menus", auth=AUTH, params={"per_page": 100}, timeout=20)
    r.raise_for_status()
    for m in r.json():
        if m["name"] == name:
            return m["id"]
    return None


def clear_items(menu_id):
    r = requests.get(BASE + "/menu-items", auth=AUTH,
                     params={"menus": menu_id, "per_page": 100}, timeout=20)
    for it in (r.json() if r.status_code == 200 else []):
        requests.delete(BASE + f"/menu-items/{it['id']}", auth=AUTH,
                        params={"force": True}, timeout=20)


def main():
    if not AUTH.username or not AUTH.password:
        print("WP_USER / WP_APP_PASS env 未設定"); sys.exit(1)
    for name, locations, items in MENUS:
        mid = find_menu(name)
        payload = {"name": name, "locations": locations}
        if mid:
            requests.post(BASE + f"/menus/{mid}", auth=AUTH, json=payload, timeout=20)
            clear_items(mid)
            print(f"= メニュー再利用 '{name}' id={mid} loc={locations}")
        else:
            r = requests.post(BASE + "/menus", auth=AUTH, json=payload, timeout=20)
            r.raise_for_status()
            mid = r.json()["id"]
            print(f"+ メニュー作成 '{name}' id={mid} loc={locations}")
        for order, (label, otype, oid) in enumerate(items, 1):
            ip = {"title": label, "menus": mid, "status": "publish",
                  "type": "post_type", "object": otype, "object_id": oid, "menu_order": order}
            r = requests.post(BASE + "/menu-items", auth=AUTH, json=ip, timeout=20)
            if r.status_code in (200, 201):
                print(f"    ✓ {label} → {otype}#{oid}")
            else:
                print(f"    ✗ {label}: {r.status_code} {r.text[:140]}")


if __name__ == "__main__":
    main()
