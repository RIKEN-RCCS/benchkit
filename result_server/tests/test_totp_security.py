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
from werkzeug.middleware.proxy_fix import ProxyFix

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import install_portal_test_stubs

install_portal_test_stubs(include_redis=False)

from utils.totp_manager import (
    FAILED_ATTEMPT_WINDOW_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    check_code_reuse,
    clear_failed_attempts,
    get_failed_attempt_count,
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
    """Tests for failed-login attempt tracking."""

    def test_no_attempts_initially(self, redis_conn):
        """A new user should have no recent failed attempts."""
        assert get_failed_attempt_count(redis_conn, PREFIX, "user@test.com") == 0

    def test_attempts_are_counted_after_max_attempts(self, redis_conn):
        """Failed-attempt counters should track repeated failures without locking."""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        assert get_failed_attempt_count(redis_conn, PREFIX, "user@test.com") == MAX_LOGIN_ATTEMPTS

    def test_attempts_before_max(self, redis_conn):
        """The counter should reflect attempts before the advisory threshold."""
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        assert get_failed_attempt_count(redis_conn, PREFIX, "user@test.com") == MAX_LOGIN_ATTEMPTS - 1

    def test_clear_resets_attempts(self, redis_conn):
        """Clearing failures should reset the failed-attempt counter."""
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        clear_failed_attempts(redis_conn, PREFIX, "user@test.com")
        assert get_failed_attempt_count(redis_conn, PREFIX, "user@test.com") == 0

    def test_record_returns_count(self, redis_conn):
        """record_failed_attempt() should return the current attempt count."""
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 1
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 2
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 3

    def test_different_users_independent(self, redis_conn):
        """Attempt counters should be tracked per user."""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_attempt(redis_conn, PREFIX, "user1@test.com")
        assert get_failed_attempt_count(redis_conn, PREFIX, "user2@test.com") == 0

    def test_attempts_key_has_ttl(self, redis_conn):
        """Attempt-counter keys should expire automatically."""
        record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        key = f"{PREFIX}login_attempts:user@test.com"
        ttl = redis_conn.ttl(key)
        assert 0 < ttl <= FAILED_ATTEMPT_WINDOW_SECONDS


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


class _BrokenRedis:
    def ping(self):
        raise ConnectionError("redis down")


class _BrokenRateLimitRedis(fakeredis.FakeRedis):
    def incr(self, _key):
        raise ConnectionError("redis down")


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


@pytest.fixture
def auth_app():
    """Create a Flask app for focused auth Redis availability tests."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.config["USER_STORE"] = _StubUserStore()

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

    yield app
    shutil.rmtree(temp_dir)


class TestAuthRedisFailClosed:
    """Tests production login behavior when Redis is unavailable."""

    def test_requires_redis_without_connection_returns_503(self, auth_app):
        auth_app.config["AUTH_REQUIRES_REDIS"] = True
        auth_app.config["REDIS_CONN"] = None

        with auth_app.test_client() as client:
            resp = client.post("/auth/login", data={"email": "user@test.com"})

        assert resp.status_code == 503

    def test_requires_redis_with_failed_ping_returns_503(self, auth_app):
        auth_app.config["AUTH_REQUIRES_REDIS"] = True
        auth_app.config["REDIS_CONN"] = _BrokenRedis()

        with auth_app.test_client() as client:
            resp = client.post("/auth/login", data={"email": "user@test.com"})

        assert resp.status_code == 503

    def test_dev_mode_without_redis_continues_login_flow(self, auth_app):
        auth_app.config["AUTH_REQUIRES_REDIS"] = False
        auth_app.config["REDIS_CONN"] = None

        with auth_app.test_client() as client:
            resp = client.post("/auth/login", data={"email": "user@test.com"})

        assert resp.status_code == 200
        assert b"Step 2 of 2" in resp.data


class TestLoginRateLimiting:
    """Tests source-scoped login rate limiting without account lockout."""

    def _configure_auth(self, app, monkeypatch, *, limit=20):
        import routes.auth as auth_routes

        app.config["REDIS_CONN"] = fakeredis.FakeRedis(decode_responses=True)
        app.config["REDIS_PREFIX"] = PREFIX
        app.config["RATE_LIMITS"] = {"login": limit}
        app.config["AUTH_REQUIRES_REDIS"] = True
        app.config["USER_STORE"].create_user("user@test.com", "SECRET", ["dev"])
        monkeypatch.setattr(auth_routes, "verify_code", lambda _secret, code: code == "000000")

    def test_login_post_rate_limit_returns_429(self, auth_app, monkeypatch):
        self._configure_auth(auth_app, monkeypatch, limit=1)

        with auth_app.test_client() as client:
            first = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "111111"},
            )
            second = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "222222"},
            )

        assert first.status_code == 200
        assert second.status_code == 429
        assert b"Too many login attempts" in second.data

    def test_proxyfix_separates_login_rate_keys_by_forwarded_client(self, auth_app, monkeypatch):
        self._configure_auth(auth_app, monkeypatch, limit=1)
        auth_app.wsgi_app = ProxyFix(auth_app.wsgi_app, x_for=1, x_proto=1)

        with auth_app.test_client() as client:
            first = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "111111"},
                headers={"X-Forwarded-For": "198.51.100.10"},
            )
            second = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "222222"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
            third_same_source = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "333333"},
                headers={"X-Forwarded-For": "198.51.100.10"},
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert third_same_source.status_code == 429

    def test_proxyfix_ignores_untrusted_extra_forwarded_for_values(self, auth_app, monkeypatch):
        self._configure_auth(auth_app, monkeypatch, limit=1)
        auth_app.wsgi_app = ProxyFix(auth_app.wsgi_app, x_for=1, x_proto=1)

        with auth_app.test_client() as client:
            spoofed = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "111111"},
                headers={"X-Forwarded-For": "198.51.100.99, 203.0.113.10"},
            )
            same_trusted_source = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "222222"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )

        assert spoofed.status_code == 200
        assert same_trusted_source.status_code == 429

    def test_login_rate_limit_redis_failure_fails_closed(self, auth_app, monkeypatch):
        self._configure_auth(auth_app, monkeypatch, limit=20)
        auth_app.config["REDIS_CONN"] = _BrokenRateLimitRedis(decode_responses=True)

        with auth_app.test_client() as client:
            resp = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "111111"},
            )

        assert resp.status_code == 503

    def test_totp_replay_check_still_blocks_reused_code(self, auth_app, monkeypatch):
        self._configure_auth(auth_app, monkeypatch, limit=100)
        auth_app.wsgi_app = ProxyFix(auth_app.wsgi_app, x_for=1, x_proto=1)

        with auth_app.test_client() as client:
            first = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "000000"},
                headers={"X-Forwarded-For": "198.51.100.10"},
            )
            replay = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "000000"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )

        assert first.status_code == 302
        assert replay.status_code == 200
        assert b"This code has already been used" in replay.data

    def test_failed_attempt_threshold_does_not_lock_out_valid_login(self, auth_app, monkeypatch):
        self._configure_auth(auth_app, monkeypatch, limit=100)
        auth_app.wsgi_app = ProxyFix(auth_app.wsgi_app, x_for=1, x_proto=1)

        with auth_app.test_client() as client:
            for _ in range(MAX_LOGIN_ATTEMPTS):
                failed = client.post(
                    "/auth/login",
                    data={"email": "user@test.com", "totp_code": "111111"},
                    headers={"X-Forwarded-For": "198.51.100.10"},
                )
                assert failed.status_code == 200

            valid = client.post(
                "/auth/login",
                data={"email": "user@test.com", "totp_code": "000000"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )

        assert valid.status_code == 302
        assert valid.headers["Location"].endswith("/results/")
        assert auth_app.config["REDIS_CONN"].get(f"{PREFIX}login_attempts:user@test.com") is None


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
