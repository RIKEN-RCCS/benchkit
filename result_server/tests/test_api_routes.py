"""
API routes のユニットテスト

新パス (/api/ingest/*) と互換ルート (/write-api, /write-est, /upload-tgz) の
動作確認、APIキー認証、deprecatedログ出力を検証する。
"""

import os
import sys
import json
import types
import tempfile
import shutil
import logging

import pytest

# --- テスト用スタブモジュールの設定 ---
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

from flask import Flask
from routes.api import api_bp
from routes.results import results_bp
from routes.estimated import estimated_bp

API_KEY = "test-api-key-12345"


@pytest.fixture
def tmp_dirs():
    """テスト用の一時ディレクトリ（received, estimated）"""
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    yield received, estimated
    shutil.rmtree(received)
    shutil.rmtree(estimated)


@pytest.fixture
def app(tmp_dirs):
    """テスト用Flaskアプリ"""
    received, estimated = tmp_dirs

    # APIキーを環境変数に設定
    import routes.api as api_mod
    original_key = api_mod.EXPECTED_API_KEY
    api_mod.EXPECTED_API_KEY = API_KEY

    app = Flask(__name__)
    app.config["RECEIVED_DIR"] = received
    app.config["ESTIMATED_DIR"] = estimated
    app.config["TESTING"] = True

    app.register_blueprint(api_bp)
    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")

    yield app

    api_mod.EXPECTED_API_KEY = original_key


@pytest.fixture
def client(app):
    return app.test_client()


# ============================================================
# 新パス: /api/ingest/result
# ============================================================

class TestIngestResult:
    def test_post_valid_json(self, client, tmp_dirs):
        """正常なJSON POSTで200が返る"""
        data = {"code": "test", "FOM": 42.0}
        resp = client.post("/api/ingest/result",
                           data=json.dumps(data),
                           headers={"X-API-Key": API_KEY,
                                    "Content-Type": "application/json"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "id" in body
        assert "timestamp" in body
        assert "json_file" in body

        # ファイルが作成されたことを確認
        received = tmp_dirs[0]
        files = os.listdir(received)
        assert len(files) == 1
        assert files[0].startswith("result_")
        assert files[0].endswith(".json")
        with open(os.path.join(received, files[0]), "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["code"] == "test"
        assert saved["_server_uuid"] == body["id"]
        assert saved["_server_timestamp"] == body["timestamp"]

    def test_missing_api_key_returns_401(self, client):
        """APIキーなしで401が返る"""
        resp = client.post("/api/ingest/result",
                           data=b'{"code":"test"}',
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 401

    def test_wrong_api_key_returns_401(self, client):
        """不正なAPIキーで401が返る"""
        resp = client.post("/api/ingest/result",
                           data=b'{"code":"test"}',
                           headers={"X-API-Key": "wrong-key",
                                    "Content-Type": "application/json"})
        assert resp.status_code == 401


# ============================================================
# 新パス: /api/ingest/estimate
# ============================================================

class TestIngestEstimate:
    def test_post_valid_json(self, client, tmp_dirs):
        """正常なJSON POSTで200が返る"""
        data = {"code": "est-test", "performance_ratio": 1.5}
        resp = client.post("/api/ingest/estimate",
                           data=json.dumps(data),
                           headers={"X-API-Key": API_KEY,
                                    "Content-Type": "application/json"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"

        # estimated_dirにファイルが作成される
        estimated = tmp_dirs[1]
        files = os.listdir(estimated)
        assert len(files) == 1
        assert files[0].startswith("estimate_")
        with open(os.path.join(estimated, files[0]), "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["code"] == "est-test"
        assert saved["estimate_metadata"]["estimation_result_uuid"] == body["id"]
        assert "estimation_result_timestamp" in saved["estimate_metadata"]

    def test_missing_api_key_returns_401(self, client):
        resp = client.post("/api/ingest/estimate",
                           data=b'{}',
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 401


# ============================================================
# 新パス: /api/ingest/padata
# ============================================================

class TestIngestPadata:
    def test_upload_tgz_file(self, client, tmp_dirs):
        """正常なtgzアップロードで200が返る"""
        import io
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "timestamp": "20250101_120000",
            "file": (io.BytesIO(b"fake tgz content"), "test.tgz"),
        }
        resp = client.post("/api/ingest/padata",
                           data=data,
                           headers={"X-API-Key": API_KEY},
                           content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "uploaded"
        assert body["replaced"] is False

    def test_missing_uuid_returns_400(self, client):
        """UUIDなしで400が返る"""
        import io
        data = {
            "timestamp": "20250101_120000",
            "file": (io.BytesIO(b"data"), "test.tgz"),
        }
        resp = client.post("/api/ingest/padata",
                           data=data,
                           headers={"X-API-Key": API_KEY},
                           content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_missing_file_returns_400(self, client):
        """ファイルなしで400が返る"""
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "timestamp": "20250101_120000",
        }
        resp = client.post("/api/ingest/padata",
                           data=data,
                           headers={"X-API-Key": API_KEY},
                           content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_missing_api_key_returns_401(self, client):
        resp = client.post("/api/ingest/padata",
                           data={"id": "x", "timestamp": "t"},
                           content_type="multipart/form-data")
        assert resp.status_code == 401


# ============================================================
# 互換ルート (deprecated)
# ============================================================

class TestCompatRoutes:
    def test_write_api_compat(self, client, tmp_dirs):
        """/write-api が ingest_result と同じ動作をする"""
        data = {"code": "compat-test"}
        resp = client.post("/write-api",
                           data=json.dumps(data),
                           headers={"X-API-Key": API_KEY,
                                    "Content-Type": "application/json"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "json_file" in body

    def test_write_est_compat(self, client, tmp_dirs):
        """/write-est が ingest_estimate と同じ動作をする"""
        data = {"code": "compat-est"}
        resp = client.post("/write-est",
                           data=json.dumps(data),
                           headers={"X-API-Key": API_KEY,
                                    "Content-Type": "application/json"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"

    def test_upload_tgz_compat(self, client, tmp_dirs):
        """/upload-tgz が ingest_padata と同じ動作をする"""
        import io
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "timestamp": "20250101_120000",
            "file": (io.BytesIO(b"fake tgz"), "test.tgz"),
        }
        resp = client.post("/upload-tgz",
                           data=data,
                           headers={"X-API-Key": API_KEY},
                           content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "uploaded"

    def test_deprecated_log_on_write_api(self, app, client):
        """互換ルートアクセス時にdeprecatedログが出力される"""
        with _capture_logs(app.logger) as logs:
            client.post("/write-api",
                        data=b'{"x":1}',
                        headers={"X-API-Key": API_KEY,
                                 "Content-Type": "application/json"})
        assert any("Deprecated" in msg for msg in logs)


# ============================================================
# /estimated/ プレフィックス確認
# ============================================================

class TestEstimatedPrefix:
    def test_estimated_route_accessible(self, app):
        """/estimated/ でアクセス可能"""
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        assert any("/estimated/" in r for r in rules)


# ============================================================
# /api/query/result
# ============================================================

class TestQueryResult:
    def _seed_result(self, received_dir, data, filename="result_20250101_000000_aaaa.json"):
        path = os.path.join(received_dir, filename)
        with open(path, "w") as f:
            json.dump(data, f)

    def test_query_returns_latest_match(self, client, tmp_dirs):
        received, _ = tmp_dirs
        old = {"system": "Fugaku", "code": "qws", "Exp": "default", "FOM": 1.0}
        new = {"system": "Fugaku", "code": "qws", "Exp": "default", "FOM": 9.9}
        self._seed_result(received, old, "result_20250101_000000_aaaa.json")
        self._seed_result(received, new, "result_20250102_000000_bbbb.json")

        resp = client.get(
            "/api/query/result?system=Fugaku&code=qws",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.get_json()["FOM"] == 9.9

    def test_query_with_exp_filter(self, client, tmp_dirs):
        received, _ = tmp_dirs
        d1 = {"system": "Fugaku", "code": "qws", "Exp": "A", "FOM": 1.0}
        d2 = {"system": "Fugaku", "code": "qws", "Exp": "B", "FOM": 2.0}
        self._seed_result(received, d1, "result_20250101_000000_aaaa.json")
        self._seed_result(received, d2, "result_20250102_000000_bbbb.json")

        resp = client.get(
            "/api/query/result?system=Fugaku&code=qws&exp=A",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.get_json()["FOM"] == 1.0

    def test_query_no_match_returns_404(self, client, tmp_dirs):
        resp = client.get(
            "/api/query/result?system=Fugaku&code=nonexistent",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 404

    def test_query_missing_params_returns_400(self, client):
        resp = client.get(
            "/api/query/result?system=Fugaku",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 400

    def test_query_missing_api_key_returns_401(self, client):
        resp = client.get("/api/query/result?system=Fugaku&code=qws")
        assert resp.status_code == 401


class TestQueryByUuid:
    def _seed_json(self, directory, filename, data):
        path = os.path.join(directory, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_query_result_by_uuid(self, client, tmp_dirs):
        received, _ = tmp_dirs
        data = {"code": "qws", "_server_uuid": "12345678-1234-1234-1234-123456789abc"}
        self._seed_json(received, "result_20250101_000000_12345678-1234-1234-1234-123456789abc.json", data)

        resp = client.get(
            "/api/query/result?uuid=12345678-1234-1234-1234-123456789abc",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.get_json()["code"] == "qws"

    def test_query_estimate_by_uuid(self, client, tmp_dirs):
        _, estimated = tmp_dirs
        data = {
            "code": "qws",
            "estimate_metadata": {
                "estimation_result_uuid": "87654321-4321-4321-4321-cba987654321",
                "source_result_uuid": "12345678-1234-1234-1234-123456789abc",
            },
        }
        self._seed_json(estimated, "estimate_20250101_000000_87654321-4321-4321-4321-cba987654321.json", data)

        resp = client.get(
            "/api/query/estimate?uuid=87654321-4321-4321-4321-cba987654321",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.get_json()["estimate_metadata"]["source_result_uuid"] == "12345678-1234-1234-1234-123456789abc"

    def test_query_result_by_uuid_missing_api_key_returns_401(self, client):
        resp = client.get("/api/query/result?uuid=12345678-1234-1234-1234-123456789abc")
        assert resp.status_code == 401

    def test_query_estimate_by_uuid_missing_api_key_returns_401(self, client):
        resp = client.get("/api/query/estimate?uuid=87654321-4321-4321-4321-cba987654321")
        assert resp.status_code == 401


# ============================================================
# ヘルパー
# ============================================================

from contextlib import contextmanager

@contextmanager
def _capture_logs(logger):
    """ログメッセージをキャプチャするコンテキストマネージャ"""
    messages = []
    handler = logging.Handler()
    handler.emit = lambda record: messages.append(record.getMessage())
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)
