"""Tests for authentication route security headers."""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs()


class _SetupStore:
    def get_invitation(self, token):
        if token != "token-1":
            return None
        return {"email": "user@example.com", "affiliations": ["dev"]}


def _portal_app():
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=received,
        estimated_dir=estimated,
        user_store=_SetupStore(),
        include_admin=False,
    )
    return app, (received, estimated)


def _cleanup(paths):
    for path in paths:
        shutil.rmtree(path)


def test_setup_page_sets_no_store_headers(monkeypatch):
    app, temp_dirs = _portal_app()
    try:
        from routes import auth as auth_routes

        monkeypatch.setattr(auth_routes, "generate_qr_base64", lambda secret, email, issuer: "qr")
        with app.test_client() as client:
            resp = client.get("/auth/setup/token-1")

        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("Cache-Control", "")
        assert resp.headers.get("Pragma") == "no-cache"
    finally:
        _cleanup(temp_dirs)


def test_invalid_setup_link_sets_no_store_headers():
    app, temp_dirs = _portal_app()
    try:
        with app.test_client() as client:
            resp = client.get("/auth/setup/bad-token")

        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("Cache-Control", "")
        assert resp.headers.get("Pragma") == "no-cache"
    finally:
        _cleanup(temp_dirs)
