"""Public portal route tests for result detail and compare views."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import (  # noqa: E402
    StaticAffiliationUserStore,
    build_results_route_app,
    install_portal_test_stubs,
)

install_portal_test_stubs()


def _add_navigation_routes(app):
    app.add_url_rule("/", "home", lambda: "home")
    app.add_url_rule("/changes", "changes", lambda: "changes")
    app.add_url_rule("/systems", "systemlist", lambda: "systems")
    app.add_url_rule("/login", "auth.login", lambda: "login")
    app.add_url_rule("/logout", "auth.logout", lambda: "logout")


def _write_result(received_dir, filename, payload):
    with open(received_dir / filename, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _eligible_public_result_payload():
    return {
        "code": "demoapp",
        "system": "DemoSystem",
        "Exp": "CASE1",
        "FOM": 1.0,
        "FOM_unit": "s",
        "FOM_version": "demo-v1",
        "node_count": 1,
        "numproc_node": 2,
        "nthreads": 8,
        "pipeline_id": 1234,
        "parent_pipeline_id": 1200,
        "_server_uuid": "11111111-2222-3333-4444-555555555555",
        "_server_timestamp": "20260824_090000",
        "source_info": {
            "source_type": "git",
            "repo_url": "https://example.test/repo.git",
            "ref_name": "main",
            "resolved_commit": "abcdef1234567890",
        },
        "input_info": {
            "dataset_id": "demoapp-small",
            "dataset_version": "v1",
            "kind": "public-git",
            "source": "public_url",
            "public_url": "https://example.test/inputs.git",
            "source_ref": "main",
            "resolved_commit": "1234567890abcdef",
            "repo_relative_path": "inputs/demoapp-small",
            "verification_status": "public_source_commit",
            "local_path": "local-input-placeholder",
        },
        "profile_data": {
            "tool": "ncu",
            "level": "kernel",
            "report_format": "csv",
            "run_count": 1,
        },
        "fom_breakdown": {
            "sections": [
                {
                    "name": "solve",
                    "estimation_package": "demo-kernel-package",
                    "artifacts": [
                        {
                            "type": "file_reference",
                            "path": "results/demo-profile.tgz",
                        }
                    ],
                }
            ]
        },
        "build_cache": {
            "status": "hit",
            "reason": "non-public-cache-note",
            "stored": False,
            "entry": {
                "created_at": "2026-08-24T09:00:00Z",
                "source": {
                    "type": "git",
                    "ref_name": "main",
                    "resolved_commit": "abcdef1234567890",
                },
                "digests": {
                    "build_inputs": "sha256:build-inputs",
                    "source_info": "sha256:source-info",
                    "artifacts": "sha256:artifacts",
                },
            },
        },
        "environment_snapshot": {
            "hash": "sha256:env",
            "summary": {
                "allocation_project_id": "omitted-a",
                "runner": "omitted-r",
            },
        },
    }


def _build_public_app(tmp_path):
    received_dir = tmp_path / "received"
    received_dir.mkdir()
    app = build_results_route_app(received_dir=str(received_dir))
    _add_navigation_routes(app)
    app.config["PUBLIC_PORTAL_MODE"] = True
    app.config["USER_STORE"] = StaticAffiliationUserStore({"dev@example.test": ["dev"]})
    return app, received_dir


def _authenticate_dev(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "dev@example.test"


def test_public_portal_detail_hides_confidential_result_for_authorized_session(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    _write_result(
        received_dir,
        filename,
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE1",
            "FOM": 1.0,
            "confidential": ["dev"],
        },
    )

    with app.test_client() as client:
        _authenticate_dev(client)
        response = client.get(f"/results/detail/{filename}")

    assert response.status_code == 404


def test_public_portal_compare_hides_confidential_result_for_authorized_session(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    public_filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    confidential_filename = "result_20260824_091000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    _write_result(
        received_dir,
        public_filename,
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE1",
            "FOM": 1.0,
        },
    )
    _write_result(
        received_dir,
        confidential_filename,
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE2",
            "FOM": 1.1,
            "confidential": ["dev"],
        },
    )

    with app.test_client() as client:
        _authenticate_dev(client)
        response = client.get(
            f"/results/compare?files={public_filename},{confidential_filename}"
        )

    assert response.status_code == 404


def test_public_portal_compare_explains_operator_evidence_is_omitted(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    first = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    second = "result_20260824_091000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    for filename, fom in ((first, 1.0), (second, 1.1)):
        _write_result(
            received_dir,
            filename,
            {
                "code": "demoapp",
                "system": "PublicSystem",
                "Exp": "CASE1",
                "FOM": fom,
                "source_info": {
                    "source_type": "git",
                    "repo_url": "https://example.test/repo.git",
                    "ref_name": "main",
                    "resolved_commit": "abcdef1234567890",
                },
                "build_cache": {"status": "hit"},
            },
        )

    with app.test_client() as client:
        response = client.get(f"/results/compare?files={first},{second}")

    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "operator evidence is omitted on this surface" in text
    assert "highlights FOM and evidence differences for review" not in text
    assert "Source" not in text
    assert "Build Cache" not in text


def test_public_portal_detail_does_not_link_evidence_packet(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    _write_result(
        received_dir,
        filename,
        _eligible_public_result_payload(),
    )

    with app.test_client() as client:
        response = client.get(f"/results/detail/{filename}")

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Download Evidence Packet" not in text
    assert "evidence-packet.md" not in text
    assert "Reuse Package" in text
    assert "Download Reuse Packet" in text
    assert "Download Manifest" in text
    assert "reuse-packet.md" in text
    assert "reuse-manifest.json" in text


def test_public_reuse_packet_exports_only_public_projection(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    padata_dir = tmp_path / "padata"
    padata_dir.mkdir()
    app.config["RECEIVED_PADATA_DIR"] = str(padata_dir)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    payload = _eligible_public_result_payload()
    archive = "padata_20260824_090000_11111111-2222-3333-4444-555555555555_demo-profile.tgz"
    _write_result(received_dir, filename, payload)
    (padata_dir / archive).write_bytes(b"public profile archive placeholder")

    with app.test_client() as client:
        response = client.get(f"/results/detail/{filename}/reuse-packet.md")

    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.content_type == "text/markdown; charset=utf-8"
    assert "Benchkit Public Reuse Packet" in text
    assert "demoapp / DemoSystem / CASE1" in text
    assert "https://example.test/repo.git" in text
    assert "abcdef1234567890" in text
    assert "dataset_id: demoapp-small" in text
    assert "resolved_commit: 1234567890abcdef" in text
    assert "sha256:build-inputs" in text
    assert "demo-kernel-package" in text
    assert archive in text
    assert "Pipeline ID" not in text
    assert "pipeline_id" not in text
    assert "parent_pipeline_id" not in text
    assert "local-input-placeholder" not in text
    assert "non-public-cache-note" not in text
    assert "omitted-a" not in text
    assert "omitted-r" not in text


def test_public_reuse_manifest_exports_machine_readable_projection(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    _write_result(received_dir, filename, _eligible_public_result_payload())

    with app.test_client() as client:
        response = client.get(f"/results/detail/{filename}/reuse-manifest.json")

    assert response.status_code == 200
    assert response.content_type == "application/json; charset=utf-8"
    manifest = response.get_json()
    assert manifest["schema_version"] == 1
    assert manifest["kind"] == "benchkit_public_reuse_packet"
    assert manifest["eligibility"]["status"] == "eligible"
    assert manifest["result"]["experiment"] == "CASE1"
    assert manifest["source"]["repository_url"] == "https://example.test/repo.git"
    assert manifest["input"]["items"][0]["public_url"] == "https://example.test/inputs.git"
    assert manifest["build"]["cache_entry"]["digests"]["artifacts"] == "sha256:artifacts"
    assert manifest["estimation"]["package_bindings"][0]["estimation_package"] == "demo-kernel-package"
    assert "environment_snapshot" not in manifest
    assert "pipeline_id" not in json.dumps(manifest)
    assert "local-input-placeholder" not in json.dumps(manifest)


def test_public_reuse_packet_requires_public_input_binding(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    payload = _eligible_public_result_payload()
    payload["input_info"] = {"dataset_id": "demoapp-small", "verification_status": "declared"}
    _write_result(received_dir, filename, payload)

    with app.test_client() as client:
        response = client.get(f"/results/detail/{filename}/reuse-packet.md")
        manifest_response = client.get(f"/results/detail/{filename}/reuse-manifest.json")
        detail_response = client.get(f"/results/detail/{filename}")

    assert response.status_code == 404
    assert manifest_response.status_code == 404
    text = detail_response.get_data(as_text=True)
    assert detail_response.status_code == 200
    assert "Public packet" in text
    assert "needs public input" in text
    assert "Download Reuse Packet" not in text


def test_public_portal_evidence_packet_route_is_blocked_until_release_review(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    _write_result(
        received_dir,
        filename,
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE1",
            "FOM": 1.0,
        },
    )

    with app.test_client() as client:
        response = client.get(f"/results/detail/{filename}/evidence-packet.md")

    assert response.status_code == 404


def test_public_portal_evidence_packet_hides_confidential_result_for_authorized_session(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    _write_result(
        received_dir,
        filename,
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE1",
            "FOM": 1.0,
            "confidential": ["dev"],
        },
    )

    with app.test_client() as client:
        _authenticate_dev(client)
        response = client.get(f"/results/detail/{filename}/evidence-packet.md")

    assert response.status_code == 404


def test_console_evidence_packet_uses_result_permissions(tmp_path):
    received_dir = tmp_path / "received"
    received_dir.mkdir()
    app = build_results_route_app(received_dir=str(received_dir))
    app.config["USER_STORE"] = StaticAffiliationUserStore({"dev@example.test": ["dev"]})
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    _write_result(
        received_dir,
        filename,
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE1",
            "FOM": 1.0,
            "confidential": ["dev"],
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.test/demoapp.git",
                "ref_name": "main",
                "resolved_commit": "abcdef1234567890",
            },
        },
    )

    with app.test_client() as client:
        response = client.get(f"/results/detail/{filename}/evidence-packet.md")
        assert response.status_code == 403

        _authenticate_dev(client)
        response = client.get(f"/results/detail/{filename}/evidence-packet.md")

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "portable review note for one Benchkit benchmark result" in text
    assert "readers who may not know the surrounding Benchkit operation" in text
    assert "does not guarantee independent reproduction" in text
    assert "Pipeline ID" not in text
    assert "Raw Result JSON" in text
    assert "https://example.test/demoapp.git" in text
