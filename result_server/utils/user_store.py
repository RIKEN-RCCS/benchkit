"""Redis-backed user and invitation storage helpers."""

import secrets
from typing import Dict, List, Optional

from flask import current_app

INVITATION_TTL = 86400  # 24 hours


class UserStore:
    def __init__(self, redis_conn, key_prefix: str = ""):
        """
        Args:
            redis_conn: Redis client instance.
            key_prefix: Prefix used to separate environments, for example
                ``main:`` or ``dev:``.
        """
        self.r = redis_conn
        self.prefix = key_prefix

    # --- Key helpers ---

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

    # --- User operations ---

    def create_user(
        self, email: str, totp_secret: str, affiliations: List[str]
    ) -> None:
        """Create a user with a TOTP secret and affiliations."""
        pipe = self.r.pipeline()
        pipe.sadd(self._users_key(), email)
        pipe.set(self._secret_key(email), totp_secret)

        # Replace the affiliation list instead of appending duplicates.
        aff_key = self._affiliations_key(email)
        pipe.delete(aff_key)
        for aff in affiliations:
            pipe.rpush(aff_key, aff)
        pipe.execute()

    def get_user(self, email: str) -> Optional[Dict]:
        """
        Return the stored user record.

        Returns:
            ``{"email": str, "totp_secret": str, "affiliations": list}``
            or ``None`` when the user does not exist.
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
        """Delete a user and its related keys."""
        if not self.user_exists(email):
            return False
        pipe = self.r.pipeline()
        pipe.srem(self._users_key(), email)
        pipe.delete(self._secret_key(email))
        pipe.delete(self._affiliations_key(email))
        pipe.execute()
        return True

    def list_users(self) -> List[Dict]:
        """Return every user record in sorted order."""
        emails = self.r.smembers(self._users_key())
        users = []
        for email in sorted(emails):
            user = self.get_user(email)
            if user:
                users.append(user)
        return users

    def update_affiliations(self, email: str, affiliations: List[str]) -> bool:
        """Replace a user's affiliations."""
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
        """Return whether a user exists."""
        return self.r.sismember(self._users_key(), email)

    def get_affiliations(self, email: str) -> List[str]:
        """Return the stored affiliations for a user."""
        return self.r.lrange(self._affiliations_key(email), 0, -1)

    def clear_totp_secret(self, email: str) -> bool:
        """Delete the TOTP secret for an existing user."""
        if not self.user_exists(email):
            return False
        self.r.delete(self._secret_key(email))
        return True

    def has_totp_secret(self, email: str) -> bool:
        """Return whether the user currently has a TOTP secret."""
        return bool(self.r.exists(self._secret_key(email)))

    # --- Invitation operations ---

    def create_invitation(self, email: str, affiliations: List[str]) -> str:
        """
        Create and persist an invitation token in Redis.

        Returns:
            The generated invitation token.
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
        """
        Return the stored invitation payload.

        Returns:
            ``{"email": str, "affiliations": list}`` or ``None`` when
            the invitation does not exist or has expired.
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
        """Delete an invitation token."""
        self.r.delete(self._invitation_key(token))


def get_user_store() -> UserStore:
    """Return the configured application UserStore instance."""
    return current_app.config["USER_STORE"]
