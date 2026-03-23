#!/usr/bin/env python3
"""初回adminユーザーの招待リンクを生成するCLIスクリプト

使い方:
  cd result_server
  python create_admin.py <email> [--affiliations admin,groupA] [--redis-url redis://localhost:6379/0] [--prefix main:]

例（本番 — prefix はデフォルト "main:" なので省略可、affiliations はデフォルト "admin" なので省略可）:
  python create_admin.py admin@example.com --base-url https://server
  python create_admin.py admin@example.com --affiliations admin,riken --base-url https://server

例（dev — prefix を "dev:" に、base-url に /dev を付ける）:
  python create_admin.py admin@example.com --prefix dev: --base-url https://server/dev

Redis確認コマンド:
  redis-cli KEYS "*"                                          # 全キー一覧
  redis-cli SMEMBERS "main:users"                             # 本番ユーザー一覧
  redis-cli SMEMBERS "dev:users"                              # devユーザー一覧
  redis-cli GET "main:user:<email>:totp_secret"               # TOTP秘密鍵
  redis-cli LRANGE "main:user:<email>:affiliations" 0 -1      # 所属（adminか確認）
  redis-cli INFO keyspace                                     # DB統計
"""

import argparse
import redis

# user_store を直接使う
from utils.user_store import UserStore


def main():
    parser = argparse.ArgumentParser(description="Create admin invitation link")
    parser.add_argument("email", help="Admin user email address")
    parser.add_argument("--affiliations", default="admin",
                        help="Comma-separated affiliations (default: admin)")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0",
                        help="Redis URL (default: redis://localhost:6379/0)")
    parser.add_argument("--prefix", default="main:",
                        help="Redis key prefix (default: main:)")
    parser.add_argument("--base-url", default="https://localhost",
                        help="Base URL for invitation link")
    args = parser.parse_args()

    affiliations = [a.strip() for a in args.affiliations.split(",") if a.strip()]

    r_conn = redis.from_url(args.redis_url, decode_responses=True)
    store = UserStore(r_conn, args.prefix)

    # 既存ユーザーチェック
    if store.user_exists(args.email):
        print(f"User {args.email} already exists.")
        ans = input("Generate reinvite link? [y/N]: ").strip().lower()
        if ans != "y":
            return
        store.clear_totp_secret(args.email)
        token = store.create_invitation(args.email, affiliations)
    else:
        token = store.create_invitation(args.email, affiliations)

    print(f"\nInvitation created for: {args.email}")
    print(f"Affiliations: {affiliations}")
    print(f"\nSetup URL:")
    print(f"  {args.base_url}/auth/setup/{token}")
    print(f"\nShare this URL with the user to complete TOTP registration.")


if __name__ == "__main__":
    main()
