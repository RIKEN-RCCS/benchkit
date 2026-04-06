import json
import os
import shutil
import sys
import tempfile
import types
import uuid

import pytest


def _setup_stubs():
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

from flask import Flask
from utils.results_loader import load_estimated_results_table


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def flask_app(tmp_dir):
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    app = Flask(__name__, template_folder=template_dir)
    app.config["RECEIVED_DIR"] = tmp_dir
    app.config["ESTIMATED_DIR"] = tmp_dir
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    yield app


def _write_json(directory, filename, data):
    filepath = os.path.join(directory, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return filepath


def test_estimated_rows_prefer_metadata_fields(flask_app, tmp_dir):
    uid = str(uuid.uuid4())
    _write_json(tmp_dir, f"estimate_20250101_000000_{uid}.json", {
        "code": "est-app",
        "exp": "exp1",
        "current_system": {"system": "SysA", "fom": 1.0, "benchmark": {}},
        "future_system": {"system": "SysB", "fom": 2.0, "benchmark": {}},
        "performance_ratio": 2.0,
        "estimate_metadata": {
            "requested_estimation_package": "instrumented_app_sections_dummy",
            "estimation_package": "lightweight_fom_scaling",
            "estimation_result_uuid": "11111111-2222-3333-4444-555555555555",
            "estimation_result_timestamp": "2026-04-06 12:34:56",
        },
        "applicability": {"status": "fallback"},
    })

    with flask_app.test_request_context():
        rows, _, info = load_estimated_results_table(tmp_dir, public_only=True)

    assert info["total"] == 1
    assert rows[0]["timestamp"] == "2026-04-06 12:34:56"
    assert rows[0]["estimate_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert rows[0]["requested_estimation_package"] == "instrumented_app_sections_dummy"
    assert rows[0]["estimation_package"] == "lightweight_fom_scaling"
    assert rows[0]["applicability_status"] == "fallback"
