import json
import os
import shutil
import sys
import tempfile
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
from routes.estimated import estimated_bp
from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.results import results_bp
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


def _login_session(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "user@example.com"
        sess["user_affiliations"] = ["dev"]


def _write_estimate(directory, filename):
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "code": "qws",
                "exp": "CASE0",
                "performance_ratio": 0.104,
                "applicability": {"status": "applicable"},
                "estimate_metadata": {
                    "requested_estimation_package": "instrumented_app_sections_dummy",
                    "estimation_package": "instrumented_app_sections_dummy",
                    "method_class": "detailed",
                    "detail_level": "intermediate",
                    "current_package": {"estimation_package": "weakscaling"},
                    "future_package": {"estimation_package": "instrumented_app_sections_dummy"},
                },
                "current_system": {"system": "Fugaku"},
                "future_system": {"system": "FugakuNEXT"},
            },
            f,
            ensure_ascii=False,
        )
    return path


def test_estimated_detail_requires_authentication(client, tmp_dirs):
    _, estimated = tmp_dirs
    _write_estimate(estimated, "estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")

    resp = client.get("/estimated/detail/estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")

    assert resp.status_code == 403


def test_estimated_detail_renders_for_authenticated_user(client, tmp_dirs):
    _, estimated = tmp_dirs
    _write_estimate(estimated, "estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")
    _login_session(client)

    resp = client.get("/estimated/detail/estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Estimate Detail" in html
    assert "Package Resolution" in html
    assert "FugakuNEXT" in html
