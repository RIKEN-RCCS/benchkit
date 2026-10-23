"""Authenticated, Result-bound measurement queries with synthetic inputs."""

import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_api_route_app, install_portal_test_stubs

install_portal_test_stubs()

UUID = "12345678-1234-5678-1234-567812345678"
TIMESTAMP = "20250101_120000"
KEY = "test-measurement-query-key"


@pytest.fixture
def storage(tmp_path):
    directories = [tmp_path / name for name in ("results", "measurement", "estimation", "estimates")]
    for directory in directories:
        directory.mkdir()
    app = build_api_route_app(
        received_dir=str(directories[0]), received_padata_dir=str(directories[1]),
        received_estimation_artifacts_dir=str(directories[2]), estimated_dir=str(directories[3]),
    )
    app.config["INGEST_KEYS"] = {KEY: "query-runner"}
    return app.test_client(), directories


def write_result(directories, paths):
    filename = directories[0] / f"result_{TIMESTAMP}_{UUID}.json"
    filename.write_text(json.dumps({"_server_uuid": UUID, "fom_breakdown": {"sections": [{
        "artifacts": [{"type": "file_reference", "path": path} for path in paths],
    }]}}))
    return filename


def query(client, path, uuid=UUID, authenticated=True):
    return client.get("/api/query/measurement-artifact", query_string={
        "uuid": uuid, "artifact_path": path,
    }, headers={"X-API-Key": KEY} if authenticated else {})


@pytest.mark.parametrize("path,stored", [
    ("results/profile.tgz", f"padata_{TIMESTAMP}_{UUID}_profile.tgz"),
    ("results/profile.tar.gz", f"measurement_artifact_{TIMESTAMP}_{UUID}_profile.tar.gz"),
    ("results/timing.json", f"measurement_artifact_{TIMESTAMP}_{UUID}_timing.json"),
    ("results/padata0.tgz", f"padata_{TIMESTAMP}_{UUID}.tgz"),
])
def test_query_restores_stored_formats_and_legacy_pair(storage, path, stored):
    client, directories = storage
    write_result(directories, [path])
    (directories[1] / stored).write_bytes(b"measurement payload")
    response = query(client, path)
    assert response.status_code == 200
    assert response.data == b"measurement payload"
    assert response.headers["Cache-Control"] == "no-store"
    assert Path(path).name in response.headers["Content-Disposition"]


def test_query_requires_auth_and_result_reference(storage):
    client, directories = storage
    write_result(directories, ["results/profile.tgz"])
    (directories[1] / f"padata_{TIMESTAMP}_{UUID}_profile.tgz").write_bytes(b"private")
    assert query(client, "results/profile.tgz", authenticated=False).status_code == 401
    assert query(client, "results/other.tgz").status_code == 404
    assert query(client, "results/profile.tgz", uuid="87654321-4321-8765-4321-876543218765").status_code == 404


@pytest.mark.parametrize("path", ["../profile.tgz", "/tmp/profile.tgz", "results/../profile.tgz",
                                  "results/./profile.tgz", "results//profile.tgz"])
def test_query_rejects_unsafe_paths(storage, path):
    client, directories = storage
    write_result(directories, [path])
    assert query(client, path).status_code == 400


def test_legacy_archive_is_not_reused_for_multiple_section_references(storage):
    client, directories = storage
    write_result(directories, ["results/padata0.tgz", "results/padata1.tgz"])
    (directories[1] / f"padata_{TIMESTAMP}_{UUID}.tgz").write_bytes(b"ambiguous")
    assert query(client, "results/padata0.tgz").status_code == 404


def test_query_does_not_serve_symlink(storage, tmp_path):
    client, directories = storage
    write_result(directories, ["results/profile.tgz"])
    outside = tmp_path / "outside"
    outside.write_bytes(b"unrelated")
    (directories[1] / f"padata_{TIMESTAMP}_{UUID}_profile.tgz").symlink_to(outside)
    assert query(client, "results/profile.tgz").status_code == 404


def test_query_rejects_ambiguous_stored_basename(storage):
    client, directories = storage
    write_result(directories, ["results/profile.tgz", "results/nested/profile.tgz"])
    (directories[1] / f"padata_{TIMESTAMP}_{UUID}_profile.tgz").write_bytes(b"ambiguous")
    assert query(client, "results/profile.tgz").status_code == 409


def test_declared_observation_bundle_uses_existing_measurement_endpoint(storage):
    client, directories = storage
    filename = write_result(directories, [])
    data = json.loads(filename.read_text())
    data['timing_observations'] = dict(observations=[dict(format='benchkit-observation-bundle/v1',
        summary=dict(bundle=dict(type='file_reference', path='results/observations.tgz')))])
    filename.write_text(json.dumps(data))
    (directories[1] / f'padata_{TIMESTAMP}_{UUID}_observations.tgz').write_bytes(b'observation bundle')
    assert query(client, 'results/observations.tgz').data == b'observation bundle'
    assert query(client, 'results/observations.tgz', authenticated=False).status_code == 401
