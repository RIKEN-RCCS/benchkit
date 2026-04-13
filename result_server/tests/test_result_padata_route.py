import json
import os
import shutil
import sys
import tempfile
import types

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

from routes.results import results_bp


@pytest.fixture
def tmp_dirs():
    received = tempfile.mkdtemp()
    received_padata = tempfile.mkdtemp()
    yield received, received_padata
    shutil.rmtree(received)
    shutil.rmtree(received_padata)


@pytest.fixture
def app(tmp_dirs):
    received, received_padata = tmp_dirs
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["RECEIVED_DIR"] = received
    app.config["RECEIVED_PADATA_DIR"] = received_padata
    app.config["TESTING"] = True
    app.register_blueprint(results_bp, url_prefix="/results")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_results_route_serves_padata_from_received_padata_dir(client, tmp_dirs):
    received, received_padata = tmp_dirs
    uid = "12345678-1234-1234-1234-123456789abc"
    json_name = f"result_20250101_120000_{uid}.json"
    tgz_name = f"padata_20250101_120000_{uid}.tgz"

    with open(os.path.join(received, json_name), "w", encoding="utf-8") as f:
        json.dump({"code": "qws", "system": "Fugaku", "FOM": 1.0}, f)

    with open(os.path.join(received_padata, tgz_name), "wb") as f:
        f.write(b"fake tgz content")

    resp = client.get(f"/results/{tgz_name}")
    assert resp.status_code == 200
    assert resp.data == b"fake tgz content"
