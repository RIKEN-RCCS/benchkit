"""Encrypted identity and expiring session adapters."""

import json
import secrets
import time
import hashlib

from flask.json.tag import TaggedJSONSerializer
from flask_session.cachelib import CacheLibSessionInterface
from utils.encrypted_sqlite import EncryptedDatabaseError

from utils.user_store import INVITATION_TTL


def legacy_session_keys(key):
    raw = key.encode()
    return (hashlib.md5(raw, usedforsecurity=False).hexdigest(), hashlib.sha256(raw).hexdigest())


def identity_from_environment():
    """CLI/trigger identity binding, with no Redis or legacy fallback when enabled."""
    from utils.cx_persistence import CxPersistence
    from utils.profile_storage import persistence_settings
    database, key, artifacts = persistence_settings()
    if not database and not key:
        return None
    store = CxPersistence.open_existing(database, key, artifact_path=artifacts)
    with store._connect(readonly=True) as conn:
        if not conn.execute('SELECT ready FROM catalog_state').fetchone()[0]:
            raise EncryptedDatabaseError('Encrypted identity migration is incomplete')
    return EncryptedUserStore(store)


class EncryptedUserStore:
    def __init__(self, storage):
        self.storage = storage

    def get_user(self, email):
        return self.storage.value_get("users", email)

    def user_exists(self, email):
        return self.get_user(email) is not None

    def create_user(self, email, totp_secret, affiliations):
        self.storage.value_set("users", email, dict(
            email=email, totp_secret=totp_secret, affiliations=list(affiliations)))

    def delete_user(self, email):
        return self.storage.value_delete("users", email)

    def list_users(self):
        with self.storage._connect(readonly=True) as conn:
            return [json.loads(row[0]) for row in conn.execute(
                "SELECT value FROM cx_values WHERE namespace='users' ORDER BY key")]

    def get_affiliations(self, email):
        return (self.get_user(email) or {}).get("affiliations", [])

    def _update(self, email, **changes):
        with self.storage.transaction() as conn:
            row = conn.execute("SELECT value FROM cx_values WHERE namespace='users' AND key=?", (email,)).fetchone()
            if not row:
                return False
            user = json.loads(row[0])
            user.update(changes)
            conn.execute("UPDATE cx_values SET value=? WHERE namespace='users' AND key=?", (json.dumps(user), email))
            return True

    def update_affiliations(self, email, affiliations):
        return self._update(email, affiliations=list(affiliations))

    def clear_totp_secret(self, email):
        return self._update(email, totp_secret="")

    def has_totp_secret(self, email):
        return bool((self.get_user(email) or {}).get("totp_secret"))

    def create_invitation(self, email, affiliations):
        token = secrets.token_urlsafe(32)
        self.storage.value_set("invitations", token,
                               dict(email=email, affiliations=list(affiliations)), ttl=INVITATION_TTL)
        return token

    def get_invitation(self, token):
        return self.storage.value_get("invitations", token)

    def delete_invitation(self, token):
        self.storage.value_delete("invitations", token)

    def register_invited_user(self, token, email, secret, affiliations):
        """Consume an unexpired invitation and register the user exactly once."""
        with self.storage.transaction() as conn:
            row = conn.execute("SELECT value FROM cx_values WHERE namespace='invitations' AND key=? AND expires>?",
                               (token, time.time())).fetchone()
            invitation = json.loads(row[0]) if row else {}
            if not row or invitation.get('email') != email or invitation.get('affiliations') != list(affiliations):
                return False
            conn.execute("INSERT INTO cx_values VALUES('users',?,?,NULL) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value",
                         (email, json.dumps(dict(email=email, totp_secret=secret, affiliations=list(affiliations)))))
            conn.execute("DELETE FROM cx_values WHERE namespace='invitations' AND key=?", (token,))
            return True


class EncryptedSessionCache:
    """Flask-Session cachelib contract without pickle or plaintext cache files."""

    def __init__(self, storage):
        self.storage = storage
        self.serializer = TaggedJSONSerializer()

    def get(self, key):
        value = self.storage.value_get("sessions", key)
        if value is None:
            candidates = [self.storage.value_get("legacy_sessions", digest) for digest in legacy_session_keys(key)]
            present = [item for item in candidates if item is not None]
            if len(set(present)) > 1:
                raise EncryptedDatabaseError("Conflicting legacy session records")
            value = next(iter(present), None)
        if value is None:
            return None
        try:
            result = self.serializer.loads(value)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (TypeError, ValueError):
            raise EncryptedDatabaseError('Invalid encrypted session record') from None

    def set(self, key, value, timeout=1800):
        with self.storage.transaction() as conn:
            conn.execute("INSERT INTO cx_values VALUES('sessions',?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value,expires=excluded.expires",
                         (key, json.dumps(self.serializer.dumps(value)), None if timeout == 0 else time.time() + timeout))
            conn.executemany("DELETE FROM cx_values WHERE namespace='legacy_sessions' AND key=?", [(digest,) for digest in legacy_session_keys(key)])
        return True

    def delete(self, key):
        with self.storage.transaction() as conn:
            removed = conn.execute("DELETE FROM cx_values WHERE namespace='sessions' AND key=?", (key,)).rowcount
            for digest in legacy_session_keys(key):
                removed += conn.execute("DELETE FROM cx_values WHERE namespace='legacy_sessions' AND key=?", (digest,)).rowcount
            return removed > 0


class EncryptedSessionInterface(CacheLibSessionInterface):
    """Keep signed-SID compatibility without treating an unavailable DB as logout."""

    def open_session(self, app, request):
        try:
            return super().open_session(app, request)
        except EncryptedDatabaseError:
            result = self.session_class()
            result.storage_unavailable = True
            return result

    def save_session(self, app, session, response):
        if not getattr(session, 'storage_unavailable', False):
            return super().save_session(app, session, response)
