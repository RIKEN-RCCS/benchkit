"""Tests for Redis-backed endpoint rate limits."""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_api_route_app, build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs()

API_KEY = "test-api-key-12345678901234567890"
SECOND_API_KEY = "second-api-key-123456789012345678"


class FakeRedis:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.counts = {}
        self.expirations = {}

    def incr(self, key):
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.expirations[key] = seconds


class _Store:
    def __init__(self):
        self._users = {
            "admin@test.com": {
                "email": "admin@test.com",
                "totp_secret": "SECRET",
                "affiliations": ["admin"],
            },
            "user@test.com": {
                "email": "user@test.com",
                "totp_secret": "SECRET2",
                "affiliations": ["dev"],
            },
        }

    def get_affiliations(self, email):
        user = self._users.get(email)
        return user["affiliations"] if user else []

    def list_users(self):
        return list(self._users.values())

    def has_totp_secret(self, email):
        user = self._users.get(email)
        return bool(user and user.get("totp_secret"))

    def delete_user(self, email):
        return self._users.pop(email, None) is not None

    def user_exists(self, email):
        return email in self._users

    def update_affiliations(self, email, affiliations):
        self._users[email]["affiliations"] = affiliations
        return True

    def clear_totp_secret(self, email):
        self._users[email]["totp_secret"] = ""
        return True

    def create_invitation(self, email, affiliations):
        return "token-1"


def _api_app():
    received = tempfile.mkdtemp()
    received_padata = tempfile.mkdtemp()
    received_estimation_inputs = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_api_route_app(
        received_dir=received,
        received_padata_dir=received_padata,
        received_estimation_inputs_dir=received_estimation_inputs,
        estimated_dir=estimated,
    )
    app.config["INGEST_KEYS"] = {
        API_KEY: "test-runner",
        SECOND_API_KEY: "second-runner",
    }
    app.config["REDIS_CONN"] = FakeRedis()
    app.config["REDIS_PREFIX"] = "test:"
    app.config["RATE_LIMITS"] = {"api_ingest": 1, "api_query": 1}
    return app, (received, received_padata, received_estimation_inputs, estimated)


def _portal_app():
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=received,
        estimated_dir=estimated,
        user_store=_Store(),
    )
    app.config["REDIS_CONN"] = FakeRedis()
    app.config["REDIS_PREFIX"] = "test:"
    app.config["RATE_LIMITS"] = {"admin_write": 1}
    return app, (received, estimated)


def _cleanup(paths):
    for path in paths:
        shutil.rmtree(path)


def test_api_ingest_rate_limit_returns_429():
    app, temp_dirs = _api_app()
    try:
        with app.test_client() as client:
            first = client.post(
                "/api/ingest/result",
                data=json.dumps({"code": "first"}),
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            )
            second = client.post(
                "/api/ingest/result",
                data=json.dumps({"code": "second"}),
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            )

        assert first.status_code == 200
        assert second.status_code == 429
    finally:
        _cleanup(temp_dirs)


def test_api_rate_limit_is_runner_scoped():
    app, temp_dirs = _api_app()
    try:
        with app.test_client() as client:
            first = client.post(
                "/api/ingest/result",
                data=json.dumps({"code": "first"}),
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            )
            second_runner = client.post(
                "/api/ingest/result",
                data=json.dumps({"code": "second"}),
                headers={"X-API-Key": SECOND_API_KEY, "Content-Type": "application/json"},
            )

        assert first.status_code == 200
        assert second_runner.status_code == 200
    finally:
        _cleanup(temp_dirs)


def test_rate_limit_redis_failure_fails_closed_when_required():
    app, temp_dirs = _api_app()
    app.config["REDIS_CONN"] = FakeRedis(fail=True)
    app.config["AUTH_REQUIRES_REDIS"] = True
    try:
        with app.test_client() as client:
            resp = client.post(
                "/api/ingest/result",
                data=json.dumps({"code": "first"}),
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            )

        assert resp.status_code == 503
    finally:
        _cleanup(temp_dirs)


def test_rate_limit_missing_redis_fails_closed_when_required():
    app, temp_dirs = _api_app()
    app.config["REDIS_CONN"] = None
    app.config["AUTH_REQUIRES_REDIS"] = True
    try:
        with app.test_client() as client:
            resp = client.post(
                "/api/ingest/result",
                data=json.dumps({"code": "first"}),
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            )

        assert resp.status_code == 503
    finally:
        _cleanup(temp_dirs)


def test_admin_write_rate_limit_returns_429():
    app, temp_dirs = _portal_app()
    try:
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]

            first = client.post("/admin/users/user@test.com/delete")
            second = client.post("/admin/users/user@test.com/delete")

        assert first.status_code == 302
        assert second.status_code == 429
    finally:
        _cleanup(temp_dirs)
