"""Tests for ingest and query API routes."""

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

from test_support import build_api_route_app, install_portal_test_stubs

install_portal_test_stubs()

API_KEY = "test-api-key-12345678901234567890"


@pytest.fixture
def tmp_dirs():
    """Create temporary directories used by the API tests."""
    received = tempfile.mkdtemp()
    received_padata = tempfile.mkdtemp()
    received_estimation_artifacts = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    yield received, received_padata, received_estimation_artifacts, estimated
    shutil.rmtree(received)
    shutil.rmtree(received_padata)
    shutil.rmtree(received_estimation_artifacts)
    shutil.rmtree(estimated)


@pytest.fixture
def app(tmp_dirs):
    """Build a Flask app configured for API route tests."""
    received, received_padata, received_estimation_artifacts, estimated = tmp_dirs

    app = build_api_route_app(
        received_dir=received,
        received_padata_dir=received_padata,
        received_estimation_artifacts_dir=received_estimation_artifacts,
        estimated_dir=estimated,
    )
    app.config["INGEST_KEYS"] = {API_KEY: "test-runner"}

    yield app


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

    def test_valid_key_logs_runner_id(self, client, caplog):
        """Accepted API requests should include the resolved runner id in logs."""
        with caplog.at_level(logging.INFO):
            resp = client.post("/api/ingest/result",
                               data=b'{"code":"test"}',
                               headers={"X-API-Key": API_KEY,
                                        "Content-Type": "application/json"})

        assert resp.status_code == 200
        assert any(
            record.message == "api key accepted"
            and getattr(record, "runner_id", None) == "test-runner"
            and getattr(record, "endpoint", None) == "/api/ingest/result"
            for record in caplog.records
        )

    def test_multiple_ingest_keys_accept_individual_runner_keys(self, app):
        """RESULT_SERVER_KEYS-style config should accept each runner key."""
        app.config["INGEST_KEYS"] = {
            "runner-a-key-12345678901234567890": "runner-a",
            "runner-b-key-12345678901234567890": "runner-b",
        }

        with app.test_client() as client:
            resp_a = client.post("/api/ingest/result",
                                 data=b'{"code":"a"}',
                                 headers={"X-API-Key": "runner-a-key-12345678901234567890",
                                          "Content-Type": "application/json"})
            resp_b = client.post("/api/ingest/result",
                                 data=b'{"code":"b"}',
                                 headers={"X-API-Key": "runner-b-key-12345678901234567890",
                                          "Content-Type": "application/json"})

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

    def test_legacy_result_server_key_env_is_still_accepted(self, tmp_dirs, monkeypatch):
        """RESULT_SERVER_KEY should remain valid as the default runner fallback."""
        monkeypatch.delenv("RESULT_SERVER_KEYS", raising=False)
        monkeypatch.setenv("RESULT_SERVER_KEY", "legacy-key-12345678901234567890")
        received, received_padata, received_estimation_artifacts, estimated = tmp_dirs
        app = build_api_route_app(
            received_dir=received,
            received_padata_dir=received_padata,
            received_estimation_artifacts_dir=received_estimation_artifacts,
            estimated_dir=estimated,
        )

        with app.test_client() as client:
            resp = client.post("/api/ingest/result",
                               data=b'{"code":"legacy"}',
                               headers={"X-API-Key": "legacy-key-12345678901234567890",
                                        "Content-Type": "application/json"})

        assert resp.status_code == 200

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

    def test_post_valid_json_with_uuid_header(self, client, tmp_dirs):
        """A valid X-UUID header should be used as the persisted estimate id."""
        estimate_uuid = "12345678-1234-1234-1234-123456789abc"
        resp = client.post("/api/ingest/estimate",
                           data=b'{"code":"est-test"}',
                           headers={"X-API-Key": API_KEY,
                                    "X-UUID": estimate_uuid,
                                    "Content-Type": "application/json"})

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["id"] == estimate_uuid
        assert estimate_uuid in body["json_file"]

        estimated = tmp_dirs[3]
        files = os.listdir(estimated)
        assert files == [body["json_file"]]

    @pytest.mark.parametrize("header_value", [
        "../../../etc/passwd_evil",
        "..%2F..%2Fetc%2Fpasswd",
        "not-a-uuid",
        "",
    ])
    def test_rejects_invalid_uuid_header(self, client, header_value):
        """X-UUID must be a canonical UUID before it reaches file naming."""
        resp = client.post("/api/ingest/estimate",
                           data=b'{}',
                           headers={"X-API-Key": API_KEY,
                                    "X-UUID": header_value,
                                    "Content-Type": "application/json"})
        assert resp.status_code == 400

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

    @pytest.mark.parametrize("timestamp", [
        "../bad",
        "20250101",
        "2025/01/01_12:00:00",
        "",
    ])
    def test_rejects_invalid_timestamp(self, client, timestamp):
        """PA Data timestamps must match YYYYMMDD_HHMMSS before file naming."""
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "timestamp": timestamp,
            "file": (io.BytesIO(b"data"), "test.tgz"),
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

    def test_ingest_estimation_artifacts_expands_under_result_stem(self, client, tmp_dirs):
        received = tmp_dirs[0]
        estimation_artifacts_dir = tmp_dirs[2]
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
            "/api/ingest/estimation-artifacts",
            data={"id": uuid_value, "file": (archive_bytes, "estimation_artifacts.tgz")},
            headers={"X-API-Key": API_KEY},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        saved_path = os.path.join(estimation_artifacts_dir, result_stem, "prepare_rhs_interval.json")
        assert os.path.exists(saved_path)

    def test_ingest_estimation_artifacts_rejects_parent_path_entry(self, client, tmp_dirs):
        received = tmp_dirs[0]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        self._seed_result(received, uuid_value)

        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            payload = b"bad"
            info = tarfile.TarInfo(name="../outside.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        archive_bytes.seek(0)

        resp = client.post(
            "/api/ingest/estimation-artifacts",
            data={"id": uuid_value, "file": (archive_bytes, "estimation_artifacts.tgz")},
            headers={"X-API-Key": API_KEY},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_ingest_estimation_artifacts_keeps_existing_data_on_bad_archive(self, client, tmp_dirs):
        received = tmp_dirs[0]
        estimation_artifacts_dir = tmp_dirs[2]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        result_stem = self._seed_result(received, uuid_value)
        target_dir = os.path.join(estimation_artifacts_dir, result_stem)
        os.makedirs(target_dir, exist_ok=True)
        existing_path = os.path.join(target_dir, "existing.json")
        with open(existing_path, "w", encoding="utf-8") as f:
            json.dump({"keep": True}, f)

        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            payload = b"bad"
            info = tarfile.TarInfo(name="../outside.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        archive_bytes.seek(0)

        resp = client.post(
            "/api/ingest/estimation-artifacts",
            data={"id": uuid_value, "file": (archive_bytes, "estimation_artifacts.tgz")},
            headers={"X-API-Key": API_KEY},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert os.path.exists(existing_path)

    def test_ingest_estimation_artifacts_rejects_absolute_path_entry(self, client, tmp_dirs):
        received = tmp_dirs[0]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        self._seed_result(received, uuid_value)

        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            payload = b"bad"
            info = tarfile.TarInfo(name="/outside.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        archive_bytes.seek(0)

        resp = client.post(
            "/api/ingest/estimation-artifacts",
            data={"id": uuid_value, "file": (archive_bytes, "estimation_artifacts.tgz")},
            headers={"X-API-Key": API_KEY},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_ingest_estimation_artifacts_rejects_absolute_symlink(self, client, tmp_dirs):
        received = tmp_dirs[0]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        self._seed_result(received, uuid_value)

        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        archive_bytes.seek(0)

        resp = client.post(
            "/api/ingest/estimation-artifacts",
            data={"id": uuid_value, "file": (archive_bytes, "estimation_artifacts.tgz")},
            headers={"X-API-Key": API_KEY},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_ingest_estimation_artifacts_rejects_absolute_hardlink(self, client, tmp_dirs):
        received = tmp_dirs[0]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        self._seed_result(received, uuid_value)

        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="hardlink")
            info.type = tarfile.LNKTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        archive_bytes.seek(0)

        resp = client.post(
            "/api/ingest/estimation-artifacts",
            data={"id": uuid_value, "file": (archive_bytes, "estimation_artifacts.tgz")},
            headers={"X-API-Key": API_KEY},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_query_estimation_artifacts_returns_archive(self, client, tmp_dirs):
        received = tmp_dirs[0]
        estimation_artifacts_dir = tmp_dirs[2]
        uuid_value = "12345678-1234-1234-1234-123456789abc"
        result_stem = self._seed_result(received, uuid_value)
        target_dir = os.path.join(estimation_artifacts_dir, result_stem)
        os.makedirs(target_dir, exist_ok=True)
        with open(os.path.join(target_dir, "compute_solver_papi.tgz"), "wb") as f:
            f.write(b"dummy")

        resp = client.get(
            f"/api/query/estimation-artifacts?uuid={uuid_value}",
            headers={"X-API-Key": API_KEY},
        )
        assert resp.status_code == 200
        assert resp.mimetype == "application/gzip"

        archive_bytes = io.BytesIO(resp.data)
        with tarfile.open(fileobj=archive_bytes, mode="r:gz") as tar:
            names = tar.getnames()
        assert "compute_solver_papi.tgz" in names
