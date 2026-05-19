"""Tests for result_server upload size limits."""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_api_route_app, install_portal_test_stubs

install_portal_test_stubs()

API_KEY = "test-api-key-12345678901234567890"


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
    app.config["INGEST_KEYS"] = {API_KEY: "test-runner"}
    return app, (received, received_padata, received_estimation_inputs, estimated)


def _cleanup(paths):
    for path in paths:
        shutil.rmtree(path)


def test_padata_upload_over_max_content_length_returns_413():
    app, temp_dirs = _api_app()
    app.config["MAX_CONTENT_LENGTH"] = 128
    try:
        with app.test_client() as client:
            resp = client.post(
                "/api/ingest/padata",
                data={
                    "id": "12345678-1234-1234-1234-123456789abc",
                    "timestamp": "20250101_120000",
                    "file": (io.BytesIO(b"x" * 512), "large.tgz"),
                },
                headers={"X-API-Key": API_KEY},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 413
    finally:
        _cleanup(temp_dirs)


def test_estimation_inputs_rejects_archive_member_over_limit():
    app, temp_dirs = _api_app()
    received = temp_dirs[0]
    app.config["MAX_ARCHIVE_MEMBER_SIZE"] = 3
    uuid_value = "12345678-1234-1234-1234-123456789abc"
    result_filename = f"result_20250101_000000_{uuid_value}.json"
    with open(os.path.join(received, result_filename), "w", encoding="utf-8") as f:
        json.dump({"code": "qws", "_server_uuid": uuid_value}, f)

    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
        payload = b"too large"
        info = tarfile.TarInfo(name="input.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    archive_bytes.seek(0)

    try:
        with app.test_client() as client:
            resp = client.post(
                "/api/ingest/estimation-inputs",
                data={"id": uuid_value, "file": (archive_bytes, "inputs.tgz")},
                headers={"X-API-Key": API_KEY},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 400
    finally:
        _cleanup(temp_dirs)
