"""Tests for ingest and legacy write API routes."""

import io
import json
import logging
import os
import shutil
import sys
import tarfile
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import install_portal_test_stubs

install_portal_test_stubs()

from flask import Flask
from routes.api import api_bp
from routes.estimated import estimated_bp
from routes.results import results_bp

API_KEY = "test-api-key-12345"


@pytest.fixture
def tmp_dirs():
    """Create temporary directories used by the API tests."""
    received = tempfile.mkdtemp()
    received_padata = tempfile.mkdtemp()
    received_estimation_inputs = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    yield received, received_padata, received_estimation_inputs, estimated
    shutil.rmtree(received)
    shutil.rmtree(received_padata)
    shutil.rmtree(received_estimation_inputs)
    shutil.rmtree(estimated)


@pytest.fixture
def app(tmp_dirs):
    """Build a Flask app configured for API route tests."""
    received, received_padata, received_estimation_inputs, estimated = tmp_dirs

    # Override the expected API key for this test app.
    import routes.api as api_mod
    original_key = api_mod.EXPECTED_API_KEY
    api_mod.EXPECTED_API_KEY = API_KEY

    app = Flask(__name__)
    app.config["RECEIVED_DIR"] = received
    app.config["RECEIVED_PADATA_DIR"] = received_padata
    app.config["RECEIVED_ESTIMATION_INPUTS_DIR"] = received_estimation_inputs
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
# /api/ingest/result
# ============================================================

class TestIngestResult:
    def test_post_valid_json(self, client, tmp_dirs):
        """Test case."""
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

        # The uploaded payload should be saved to the configured received directory.
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
        """Test case."""
        resp = client.post("/api/ingest/result",
                           data=b'{"code":"test"}',
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 401

    def test_wrong_api_key_returns_401(self, client):
        """Test case."""
        resp = client.post("/api/ingest/result",
                           data=b'{"code":"test"}',
                           headers={"X-API-Key": "wrong-key",
                                    "Content-Type": "application/json"})
        assert resp.status_code == 401


# ============================================================
# /api/ingest/estimate
# ============================================================

class TestIngestEstimate:
    def test_post_valid_json(self, client, tmp_dirs):
        """Test case."""
        data = {"code": "est-test", "performance_ratio": 1.5}
        resp = client.post("/api/ingest/estimate",
                           data=json.dumps(data),
                           headers={"X-API-Key": API_KEY,
                                    "Content-Type": "application/json"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"

        # The uploaded estimate should be written to the configured estimate directory.
        estimated = tmp_dirs[3]
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
# /api/ingest/padata
# ============================================================

class TestIngestPadata:
    def test_upload_tgz_file(self, client, tmp_dirs):
        """Test case."""
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
        saved_files = os.listdir(tmp_dirs[1])
        assert saved_files == ["padata_20250101_120000_12345678-1234-1234-1234-123456789abc.tgz"]

    def test_missing_uuid_returns_400(self, client):
        """Test case."""
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
        """Test case."""
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
# Deprecated compatibility routes
# ============================================================

class TestCompatRoutes:
    def test_write_api_compat(self, client, tmp_dirs):
        """Test case."""
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
        """Test case."""
        data = {"code": "compat-est"}
        resp = client.post("/write-est",
                           data=json.dumps(data),
                           headers={"X-API-Key": API_KEY,
                                    "Content-Type": "application/json"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"

    def test_upload_tgz_compat(self, client, tmp_dirs):
        """Test case."""
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
        """Test case."""
        with _capture_logs(app.logger) as logs:
            client.post("/write-api",
                        data=b'{"x":1}',
                        headers={"X-API-Key": API_KEY,
                                 "Content-Type": "application/json"})
        assert any("Deprecated" in msg for msg in logs)


# ============================================================
# /estimated/ route registration

class TestEstimatedPrefix:
    def test_estimated_route_accessible(self, app):
        """Test case."""
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
        received = tmp_dirs[0]
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
        received = tmp_dirs[0]
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
        received = tmp_dirs[0]
        data = {"code": "qws", "_server_uuid": "12345678-1234-1234-1234-123456789abc"}
        self._seed_json(received, "result_20250101_000000_12345678-1234-1234-1234-123456789abc.json", data)

        resp = client.get(
            "/api/query/result?uuid=12345678-1234-1234-1234-123456789abc",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.get_json()["code"] == "qws"

    def test_query_estimate_by_uuid(self, client, tmp_dirs):
        estimated = tmp_dirs[3]
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


class TestEstimationInputs:
    def _seed_result(self, received_dir, uuid_value):
        filename = f"result_20250101_000000_{uuid_value}.json"
        path = os.path.join(received_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"code": "qws", "_server_uuid": uuid_value}, f)
        return os.path.splitext(filename)[0]

    def test_ingest_estimation_inputs_expands_under_result_stem(self, client, tmp_dirs):
        received = tmp_dirs[0]
        estimation_inputs_dir = tmp_dirs[2]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        result_stem = self._seed_result(received, uuid_value)

        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            payload = b'{"dummy": true}'
            info = tarfile.TarInfo(name="prepare_rhs_interval.json")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        archive_bytes.seek(0)

        resp = client.post(
            "/api/ingest/estimation-inputs",
            data={"id": uuid_value, "file": (archive_bytes, "estimation_inputs.tgz")},
            headers={"X-API-Key": API_KEY},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        saved_path = os.path.join(estimation_inputs_dir, result_stem, "prepare_rhs_interval.json")
        assert os.path.exists(saved_path)

    def test_query_estimation_inputs_returns_archive(self, client, tmp_dirs):
        received = tmp_dirs[0]
        estimation_inputs_dir = tmp_dirs[2]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        result_stem = self._seed_result(received, uuid_value)
        target_dir = os.path.join(estimation_inputs_dir, result_stem)
        os.makedirs(target_dir, exist_ok=True)
        with open(os.path.join(target_dir, "compute_solver_papi.tgz"), "wb") as f:
            f.write(b"dummy")

        resp = client.get(
            f"/api/query/estimation-inputs?uuid={uuid_value}",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.mimetype == "application/gzip"

        archive_bytes = io.BytesIO(resp.data)
        with tarfile.open(fileobj=archive_bytes, mode="r:gz") as tar:
            names = tar.getnames()
        assert "compute_solver_papi.tgz" in names


# ============================================================
# Section
# ============================================================

from contextlib import contextmanager

@contextmanager
def _capture_logs(logger):
    """Test case."""
    messages = []
    handler = logging.Handler()
    handler.emit = lambda record: messages.append(record.getMessage())
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)
