"""Redisベースのユーザーストア

ユーザーCRUDと招待トークン管理を提供する。
Redisキー構造:
  {prefix}:users                     → Set型: 登録済みメールアドレスの集合
  {prefix}:user:{email}:totp_secret  → String型: Base32エンコードされたTOTP秘密鍵
  {prefix}:user:{email}:affiliations → List型: 所属グループのリスト
  {prefix}:invitation:{token}        → Hash型: {email, affiliations} (TTL: 24時間)
"""

import secrets
from typing import Dict, List, Optional

from flask import current_app

INVITATION_TTL = 86400  # 24時間


class UserStore:
    def __init__(self, redis_conn, key_prefix: str = ""):
        """
        Args:
            redis_conn: Redisクライアント接続
            key_prefix: 環境ごとのキープレフィックス（"main:" or "dev:"）
        """
        self.r = redis_conn
        self.prefix = key_prefix

    # --- キーヘルパー ---

    def _key(self, *parts: str) -> str:
        return f"{self.prefix}{''.join(parts)}"

    def _users_key(self) -> str:
        return self._key("users")

    def _secret_key(self, email: str) -> str:
        return self._key(f"user:{email}:totp_secret")

    def _affiliations_key(self, email: str) -> str:
        return self._key(f"user:{email}:affiliations")

    def _invitation_key(self, token: str) -> str:
        return self._key(f"invitation:{token}")

    # --- ユーザー管理 ---

    def create_user(
        self, email: str, totp_secret: str, affiliations: List[str]
    ) -> None:
        """ユーザーを登録する。usersセットへの追加、秘密鍵・所属情報の保存。"""
        pipe = self.r.pipeline()
        pipe.sadd(self._users_key(), email)
        pipe.set(self._secret_key(email), totp_secret)
        # 所属情報: 既存リストを削除してから新規追加
        aff_key = self._affiliations_key(email)
        pipe.delete(aff_key)
        for aff in affiliations:
            pipe.rpush(aff_key, aff)
        pipe.execute()

    def get_user(self, email: str) -> Optional[Dict]:
        """ユーザー情報を取得する。

        Returns:
            {"email": str, "totp_secret": str, "affiliations": list} or None
        """
        if not self.user_exists(email):
            return None
        totp_secret = self.r.get(self._secret_key(email)) or ""
        affiliations = self.r.lrange(self._affiliations_key(email), 0, -1)
        return {
            "email": email,
            "totp_secret": totp_secret,
            "affiliations": affiliations,
        }

    def delete_user(self, email: str) -> bool:
        """ユーザーを削除する。全関連キーを削除。"""
        if not self.user_exists(email):
            return False
        pipe = self.r.pipeline()
        pipe.srem(self._users_key(), email)
        pipe.delete(self._secret_key(email))
        pipe.delete(self._affiliations_key(email))
        pipe.execute()
        return True

    def list_users(self) -> List[Dict]:
        """全ユーザーの一覧を返す。"""
        emails = self.r.smembers(self._users_key())
        users = []
        for email in sorted(emails):
            user = self.get_user(email)
            if user:
                users.append(user)
        return users

    def update_affiliations(self, email: str, affiliations: List[str]) -> bool:
        """ユーザーの所属情報を更新する。"""
        if not self.user_exists(email):
            return False
        aff_key = self._affiliations_key(email)
        pipe = self.r.pipeline()
        pipe.delete(aff_key)
        for aff in affiliations:
            pipe.rpush(aff_key, aff)
        pipe.execute()
        return True

    def user_exists(self, email: str) -> bool:
        """ユーザーが登録済みか確認する。"""
        return self.r.sismember(self._users_key(), email)

    def get_affiliations(self, email: str) -> List[str]:
        """ユーザーの所属情報を取得する。"""
        return self.r.lrange(self._affiliations_key(email), 0, -1)

    def clear_totp_secret(self, email: str) -> bool:
        """ユーザーのTOTP秘密鍵を削除する（再登録用）。"""
        if not self.user_exists(email):
            return False
        self.r.delete(self._secret_key(email))
        return True

    def has_totp_secret(self, email: str) -> bool:
        """ユーザーがTOTP秘密鍵を持っているか確認する。"""
        return bool(self.r.exists(self._secret_key(email)))

    # --- 招待トークン管理 ---

    def create_invitation(self, email: str, affiliations: List[str]) -> str:
        """招待トークンを生成してRedisに保存する。

        Returns:
            招待トークン文字列
        """
        token = secrets.token_urlsafe(32)
        key = self._invitation_key(token)
        self.r.hset(
            key,
            mapping={
                "email": email,
                "affiliations": ",".join(affiliations),
            },
        )
        self.r.expire(key, INVITATION_TTL)
        return token

    def get_invitation(self, token: str) -> Optional[Dict]:
        """招待トークンの情報を取得する。

        Returns:
            {"email": str, "affiliations": list} or None（無効/期限切れ）
        """
        data = self.r.hgetall(self._invitation_key(token))
        if not data:
            return None
        affiliations_str = data.get("affiliations", "")
        affiliations = (
            [a.strip() for a in affiliations_str.split(",") if a.strip()]
            if affiliations_str
            else []
        )
        return {"email": data["email"], "affiliations": affiliations}

    def delete_invitation(self, token: str) -> None:
        """招待トークンを削除する。"""
        self.r.delete(self._invitation_key(token))


def get_user_store() -> UserStore:
    """現在のアプリコンテキストからUserStoreインスタンスを取得する。"""
    return current_app.config["USER_STORE"]
