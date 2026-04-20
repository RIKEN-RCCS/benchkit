"""Tests for TOTP security behavior.

This covers replay protection, brute-force protection, and prevention of
admin self-deletion in the portal UI.
"""

import os
import shutil
import sys
import tempfile

# If another test replaced the redis module with a lightweight stub,
# restore the real package before importing fakeredis.
if "redis" in sys.modules:
    _redis_stub = sys.modules["redis"]
    if not hasattr(_redis_stub, "ResponseError"):
        del sys.modules["redis"]

import fakeredis
import pytest
from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import install_portal_test_stubs

install_portal_test_stubs(include_redis=False)

from utils.totp_manager import (
    LOCKOUT_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    check_code_reuse,
    check_rate_limit,
    clear_failed_attempts,
    record_failed_attempt,
)


@pytest.fixture
def redis_conn():
    """Return an isolated in-memory Redis instance for security tests."""
    return fakeredis.FakeRedis(decode_responses=True)


PREFIX = "test:"


class TestReplayAttackPrevention:
    """Tests for replay-attack protection on submitted TOTP codes."""

    def test_first_use_not_replay(self, redis_conn):
        """The first use of a code should not be flagged as a replay."""
        assert check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456") is False

    def test_second_use_is_replay(self, redis_conn):
        """A second use of the same code should be detected as a replay."""
        check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456")
        assert check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456") is True

    def test_different_codes_not_replay(self, redis_conn):
        """A different code should not be treated as a replay."""
        check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456")
        assert check_code_reuse(redis_conn, PREFIX, "user@test.com", "654321") is False

    def test_different_users_not_replay(self, redis_conn):
        """The same code used by another user should not be treated as a replay."""
        check_code_reuse(redis_conn, PREFIX, "user1@test.com", "123456")
        assert check_code_reuse(redis_conn, PREFIX, "user2@test.com", "123456") is False

    def test_replay_key_has_ttl(self, redis_conn):
        """Replay-detection keys should expire automatically."""
        check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456")
        key = f"{PREFIX}totp_used:user@test.com:123456"
        ttl = redis_conn.ttl(key)
        assert 0 < ttl <= 90


class TestRateLimiting:
    """Tests for brute-force protection on repeated login attempts."""

    def test_no_lockout_initially(self, redis_conn):
        """A new user should not be locked out."""
        is_locked, remaining = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is False
        assert remaining == 0

    def test_lockout_after_max_attempts(self, redis_conn):
        """The user should be locked out after the maximum number of failures."""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        is_locked, remaining = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is True
        assert remaining > 0

    def test_not_locked_before_max(self, redis_conn):
        """The user should remain unlocked before reaching the limit."""
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        is_locked, _ = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is False

    def test_clear_resets_attempts(self, redis_conn):
        """Clearing failures should reset the lockout state."""
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        clear_failed_attempts(redis_conn, PREFIX, "user@test.com")
        is_locked, _ = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is False

    def test_record_returns_count(self, redis_conn):
        """record_failed_attempt() should return the current attempt count."""
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 1
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 2
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 3

    def test_different_users_independent(self, redis_conn):
        """Attempt counters should be tracked per user."""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_attempt(redis_conn, PREFIX, "user1@test.com")
        is_locked, _ = check_rate_limit(redis_conn, PREFIX, "user2@test.com")
        assert is_locked is False

    def test_attempts_key_has_ttl(self, redis_conn):
        """Attempt-counter keys should expire automatically."""
        record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        key = f"{PREFIX}login_attempts:user@test.com"
        ttl = redis_conn.ttl(key)
        assert 0 < ttl <= LOCKOUT_SECONDS


class _StubUserStore:
    """Minimal in-memory user store for admin route tests."""

    def __init__(self):
        self._users = {}

    def create_user(self, email, totp_secret, affiliations):
        self._users[email] = {
            "email": email,
            "totp_secret": totp_secret,
            "affiliations": list(affiliations),
        }

    def get_user(self, email):
        return self._users.get(email)

    def delete_user(self, email):
        return self._users.pop(email, None) is not None

    def list_users(self):
        return list(self._users.values())

    def update_affiliations(self, email, affiliations):
        if email in self._users:
            self._users[email]["affiliations"] = list(affiliations)
            return True
        return False

    def user_exists(self, email):
        return email in self._users

    def get_affiliations(self, email):
        user = self._users.get(email)
        return user["affiliations"] if user else []

    def has_totp_secret(self, email):
        user = self._users.get(email)
        return bool(user and user.get("totp_secret"))


@pytest.fixture
def admin_app():
    """Create a Flask app for admin self-delete protection tests."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True

    store = _StubUserStore()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    store.create_user("user@test.com", "SECRET2", ["dev"])
    app.config["USER_STORE"] = store

    from routes.admin import admin_bp
    from routes.auth import auth_bp
    from routes.estimated import estimated_bp
    from routes.home import register_home_routes
    from routes.results import results_bp

    register_home_routes(app)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")

    temp_dir = tempfile.mkdtemp()
    app.config["RECEIVED_DIR"] = temp_dir
    app.config["ESTIMATED_DIR"] = temp_dir

    @app.route("/systemlist")
    def systemlist():
        return "systems"

    yield app, store
    shutil.rmtree(temp_dir)


class TestAdminSelfDeletePrevention:
    """Tests that admins cannot delete their own account."""

    def test_admin_cannot_delete_self(self, admin_app):
        """An admin should not be able to delete their own account."""
        app, store = admin_app
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]

            resp = client.post("/admin/users/admin@test.com/delete", follow_redirects=True)
            assert resp.status_code == 200
            assert store.user_exists("admin@test.com")

    def test_admin_can_delete_other_user(self, admin_app):
        """An admin should still be able to delete another user."""
        app, store = admin_app
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]

            resp = client.post("/admin/users/user@test.com/delete", follow_redirects=True)
            assert resp.status_code == 200
            assert not store.user_exists("user@test.com")
