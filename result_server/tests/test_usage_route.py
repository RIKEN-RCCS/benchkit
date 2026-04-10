"""
/results/usage ルートと Usage ナビゲーションのテスト
"""

import json
import os
import sys
import tempfile
import shutil
import types

import fakeredis
import pytest
from flask import Flask


def _setup_stubs():
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")

    otp_mod = types.ModuleType("utils.otp_manager")
    otp_mod.get_affiliations = lambda email: ["dev"]
    otp_mod.is_allowed = lambda email: True
    sys.modules["utils.otp_manager"] = otp_mod

    otp_redis_mod = types.ModuleType("utils.otp_redis_manager")
    otp_redis_mod.get_affiliations = lambda email: ["dev"]
    otp_redis_mod.is_allowed = lambda email: True
    otp_redis_mod.send_otp = lambda email: (True, "stub")
    otp_redis_mod.verify_otp = lambda email, code: True
    otp_redis_mod.invalidate_otp = lambda email: None
    sys.modules["utils.otp_redis_manager"] = otp_redis_mod


_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.home import register_home_routes
from routes.results import results_bp
from routes.estimated import estimated_bp
from routes.auth import auth_bp
from routes.admin import admin_bp
from utils.user_store import UserStore


@pytest.fixture
def tmp_dirs():
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    yield received, estimated
    shutil.rmtree(received)
    shutil.rmtree(estimated)


@pytest.fixture
def app(tmp_dirs):
    received, estimated = tmp_dirs
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")

    app = Flask(__name__, template_folder=template_dir)
    app.config["RECEIVED_DIR"] = received
    app.config["ESTIMATED_DIR"] = estimated
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    r_conn = fakeredis.FakeRedis(decode_responses=True)
    app.config["REDIS_CONN"] = r_conn
    app.config["REDIS_PREFIX"] = "test:"
    store = UserStore(r_conn, "test:")
    app.config["USER_STORE"] = store
    app.config["TOTP_ISSUER"] = "BenchKit-Test"

    store.create_user("admin@example.com", "SECRET", ["admin"])
    store.create_user("user@example.com", "SECRET", ["dev"])

    register_home_routes(app)

    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.route("/systemlist")
    def systemlist():
        return ""

    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def _login_session(client, email, affiliations):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = email
        sess["user_affiliations"] = affiliations


def _write_result(directory, filename, data):
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestUsageRoute:
    def test_confidential_results_hides_table_when_unauthenticated(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {"code": "qws", "system": "Fugaku", "Exp": "CASE0", "FOM": 1.0},
        )
        resp = client.get("/results/confidential")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Authentication required to view confidential data." in text
        assert '<table id="resultsTable"' not in text
        assert "no-store" in resp.headers.get("Cache-Control", "")

    def test_unauthenticated_user_is_redirected_to_login(self, client):
        resp = client.get("/results/usage")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
        assert "no-store" in resp.headers.get("Cache-Control", "")

    def test_non_admin_user_gets_403(self, client):
        _login_session(client, "user@example.com", ["dev"])
        resp = client.get("/results/usage")
        assert resp.status_code == 403

    def test_admin_user_can_access_usage_page(self, client):
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        assert resp.status_code == 200
        assert "Usage Report" in resp.get_data(as_text=True)
        assert "no-store" in resp.headers.get("Cache-Control", "")

    def test_usage_page_shows_app_system_coverage(self, client):
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        assert resp.status_code == 200
        text = resp.get_data(as_text=True)
        assert "Application/System Coverage" in text
        assert "qws" in text

    def test_usage_route_uses_default_parameters(self, app, client, monkeypatch):
        _login_session(client, "admin@example.com", ["admin"])

        captured = {}

        def fake_aggregate(directory, fiscal_year, period_type):
            captured["directory"] = directory
            captured["fiscal_year"] = fiscal_year
            captured["period_type"] = period_type
            return {
                "apps": [],
                "systems": [],
                "periods": ["FY2025"],
                "table": {},
                "row_totals": {},
                "col_totals": {},
                "grand_totals": {},
                "available_fiscal_years": [2025],
            }

        import routes.results as results_mod

        monkeypatch.setattr(results_mod, "aggregate_node_hours", fake_aggregate)
        monkeypatch.setattr(results_mod, "get_fiscal_year", lambda dt: 2025)

        resp = client.get("/results/usage")
        assert resp.status_code == 200
        assert captured["directory"] == app.config["RECEIVED_DIR"]
        assert captured["fiscal_year"] == 2025
        assert captured["period_type"] == "fiscal_year"

    def test_usage_page_shows_no_data_message(self, client):
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        assert resp.status_code == 200
        assert "該当期間のデータがありません" in resp.get_data(as_text=True)

    def test_admin_navigation_shows_usage_link(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {"code": "qws", "system": "Fugaku", "Exp": "CASE0", "FOM": 1.0},
        )
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/confidential")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "/results/usage" in text

    def test_non_admin_navigation_hides_usage_link(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {"code": "qws", "system": "Fugaku", "Exp": "CASE0", "FOM": 1.0},
        )
        _login_session(client, "user@example.com", ["dev"])
        resp = client.get("/results/confidential")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "/results/usage" not in text
