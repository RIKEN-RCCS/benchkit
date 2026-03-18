"""TOTP認証セキュリティ機能のテスト

リプレイ攻撃対策、ブルートフォース対策、admin自己削除防止のテスト。
"""

import sys

# test_api_routes.pyがredisモジュールをスタブで上書きしている場合、
# fakeredisが正常に動作するよう本物のredisを復元する
if "redis" in sys.modules:
    _stub = sys.modules["redis"]
    if not hasattr(_stub, "ResponseError"):
        del sys.modules["redis"]

import fakeredis
import pyotp
import pytest

from utils.totp_manager import (
    MAX_LOGIN_ATTEMPTS,
    LOCKOUT_SECONDS,
    check_code_reuse,
    check_rate_limit,
    record_failed_attempt,
    clear_failed_attempts,
    generate_secret,
    verify_code,
)


@pytest.fixture
def redis_conn():
    """テスト用fakeredis接続"""
    return fakeredis.FakeRedis(decode_responses=True)


PREFIX = "test:"


class TestReplayAttackPrevention:
    """TOTPコードリプレイ攻撃対策のテスト"""

    def test_first_use_not_replay(self, redis_conn):
        """初回使用はリプレイではない"""
        assert check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456") is False

    def test_second_use_is_replay(self, redis_conn):
        """同じコードの2回目使用はリプレイとして検出"""
        check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456")
        assert check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456") is True

    def test_different_codes_not_replay(self, redis_conn):
        """異なるコードはリプレイではない"""
        check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456")
        assert check_code_reuse(redis_conn, PREFIX, "user@test.com", "654321") is False

    def test_different_users_not_replay(self, redis_conn):
        """異なるユーザーの同じコードはリプレイではない"""
        check_code_reuse(redis_conn, PREFIX, "user1@test.com", "123456")
        assert check_code_reuse(redis_conn, PREFIX, "user2@test.com", "123456") is False

    def test_replay_key_has_ttl(self, redis_conn):
        """リプレイ検出キーにTTLが設定されている"""
        check_code_reuse(redis_conn, PREFIX, "user@test.com", "123456")
        key = f"{PREFIX}totp_used:user@test.com:123456"
        ttl = redis_conn.ttl(key)
        assert 0 < ttl <= 90


class TestRateLimiting:
    """ブルートフォース対策のテスト"""

    def test_no_lockout_initially(self, redis_conn):
        """初期状態ではロックアウトされない"""
        is_locked, remaining = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is False
        assert remaining == 0

    def test_lockout_after_max_attempts(self, redis_conn):
        """最大試行回数超過でロックアウト"""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        is_locked, remaining = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is True
        assert remaining > 0

    def test_not_locked_before_max(self, redis_conn):
        """最大試行回数未満ではロックアウトされない"""
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        is_locked, _ = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is False

    def test_clear_resets_attempts(self, redis_conn):
        """成功時にカウンターがリセットされる"""
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        clear_failed_attempts(redis_conn, PREFIX, "user@test.com")
        is_locked, _ = check_rate_limit(redis_conn, PREFIX, "user@test.com")
        assert is_locked is False

    def test_record_returns_count(self, redis_conn):
        """record_failed_attemptは現在の試行回数を返す"""
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 1
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 2
        assert record_failed_attempt(redis_conn, PREFIX, "user@test.com") == 3

    def test_different_users_independent(self, redis_conn):
        """異なるユーザーのカウンターは独立"""
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_attempt(redis_conn, PREFIX, "user1@test.com")
        is_locked, _ = check_rate_limit(redis_conn, PREFIX, "user2@test.com")
        assert is_locked is False

    def test_attempts_key_has_ttl(self, redis_conn):
        """試行回数キーにTTLが設定されている"""
        record_failed_attempt(redis_conn, PREFIX, "user@test.com")
        key = f"{PREFIX}login_attempts:user@test.com"
        ttl = redis_conn.ttl(key)
        assert 0 < ttl <= LOCKOUT_SECONDS


# ============================================================
# Admin自己削除防止のテスト
# ============================================================

import os
import sys
import types
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask


class _StubUserStore:
    """テスト用インメモリUserStore"""

    def __init__(self):
        self._users = {}

    def create_user(self, email, totp_secret, affiliations):
        self._users[email] = {"email": email, "totp_secret": totp_secret, "affiliations": list(affiliations)}

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
        u = self._users.get(email)
        return u["affiliations"] if u else []

    def has_totp_secret(self, email):
        u = self._users.get(email)
        return bool(u and u.get("totp_secret"))


@pytest.fixture
def admin_app():
    """admin機能テスト用Flaskアプリ"""
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"))
    app.secret_key = "test-secret"
    app.config["TESTING"] = True

    store = _StubUserStore()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    store.create_user("user@test.com", "SECRET2", ["dev"])
    app.config["USER_STORE"] = store

    from routes.admin import admin_bp
    from routes.auth import auth_bp
    from routes.results import results_bp
    from routes.estimated import estimated_bp

    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")

    tmp = tempfile.mkdtemp()
    app.config["RECEIVED_DIR"] = tmp
    app.config["ESTIMATED_DIR"] = tmp

    @app.route("/systemlist")
    def systemlist():
        return "systems"

    yield app, store
    shutil.rmtree(tmp)


class TestAdminSelfDeletePrevention:
    """admin自己削除防止のテスト"""

    def test_admin_cannot_delete_self(self, admin_app):
        """adminは自分自身を削除できない"""
        app, store = admin_app
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]

            resp = client.post("/admin/users/admin@test.com/delete", follow_redirects=True)
            assert resp.status_code == 200
            # ユーザーがまだ存在することを確認
            assert store.user_exists("admin@test.com")

    def test_admin_can_delete_other_user(self, admin_app):
        """adminは他のユーザーを削除できる"""
        app, store = admin_app
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]

            resp = client.post("/admin/users/user@test.com/delete", follow_redirects=True)
            assert resp.status_code == 200
            # ユーザーが削除されたことを確認
            assert not store.user_exists("user@test.com")
