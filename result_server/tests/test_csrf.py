"""Tests for CSRF enforcement on browser POST routes."""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_api_route_app, build_portal_route_app, install_portal_test_stubs
from utils.csrf import init_csrf

install_portal_test_stubs()

API_KEY = "test-api-key-12345678901234567890"


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


def _portal_app():
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=received,
        estimated_dir=estimated,
        user_store=_Store(),
    )
    init_csrf(app)
    return app, (received, estimated)


def test_admin_post_without_csrf_token_is_rejected():
    app, temp_dirs = _portal_app()
    try:
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]
            resp = client.post("/admin/users/user@test.com/delete")

        assert resp.status_code == 400
    finally:
        for path in temp_dirs:
            shutil.rmtree(path)


def test_admin_post_with_invalid_csrf_token_is_rejected():
    app, temp_dirs = _portal_app()
    try:
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]
            resp = client.post(
                "/admin/users/user@test.com/delete",
                data={"csrf_token": "not-a-valid-token"},
            )

        assert resp.status_code == 400
    finally:
        for path in temp_dirs:
            shutil.rmtree(path)


def test_api_ingest_is_exempt_from_csrf():
    received = tempfile.mkdtemp()
    received_padata = tempfile.mkdtemp()
    received_estimation_inputs = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    try:
        app = build_api_route_app(
            received_dir=received,
            received_padata_dir=received_padata,
            received_estimation_inputs_dir=received_estimation_inputs,
            estimated_dir=estimated,
        )
        app.secret_key = "test-secret"
        app.config["INGEST_KEYS"] = {API_KEY: "test-runner"}

        from routes.api import api_bp

        init_csrf(app, exempt_blueprints=(api_bp,))

        with app.test_client() as client:
            resp = client.post(
                "/api/ingest/result",
                data=json.dumps({"code": "test"}),
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            )

        assert resp.status_code == 200
    finally:
        for path in (received, received_padata, received_estimation_inputs, estimated):
            shutil.rmtree(path)
