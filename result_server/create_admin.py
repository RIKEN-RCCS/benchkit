#!/usr/bin/env python3
"""CLI helper to generate an initial admin invitation link.

Usage:
  cd result_server
  python create_admin.py <email> [--affiliations admin,groupA] [--redis-url redis://localhost:6379/0] [--prefix main:]

Examples:
  python create_admin.py admin@example.com --base-url https://server
  python create_admin.py admin@example.com --affiliations admin,riken --base-url https://server

Dev example:
  python create_admin.py admin@example.com --prefix dev: --base-url https://server/dev

Useful Redis checks:
  redis-cli KEYS "*"
  redis-cli SMEMBERS "main:users"
  redis-cli SMEMBERS "dev:users"
  redis-cli GET "main:user:<email>:totp_secret"
  redis-cli LRANGE "main:user:<email>:affiliations" 0 -1
  redis-cli INFO keyspace
"""

import argparse

import redis

from utils.user_store import UserStore


def main():
    parser = argparse.ArgumentParser(description="Create admin invitation link")
    parser.add_argument("email", help="Admin user email address")
    parser.add_argument(
        "--affiliations",
        default="admin",
        help="Comma-separated affiliations (default: admin)",
    )
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379/0",
        help="Redis URL (default: redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--prefix",
        default="main:",
        help="Redis key prefix (default: main:)",
    )
    parser.add_argument(
        "--base-url",
        default="https://localhost",
        help="Base URL for invitation link",
    )
    args = parser.parse_args()

    affiliations = [item.strip() for item in args.affiliations.split(",") if item.strip()]

    r_conn = redis.from_url(args.redis_url, decode_responses=True)
    store = UserStore(r_conn, args.prefix)

    # Reuse an existing account by clearing the current secret and issuing a new invite.
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
    print("\nSetup URL:")
    print(f"  {args.base_url}/auth/setup/{token}")
    print("\nShare this URL with the user to complete TOTP registration.")


if __name__ == "__main__":
    main()
