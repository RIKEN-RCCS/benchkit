"""Tests for the SQLite execution profile registry and admin display."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs()

from utils.execution_profiles import (  # noqa: E402
    ExecutionProfileStore,
    import_execution_profiles_json,
    load_execution_profiles,
    normalize_profile,
)


class _Store:
    def list_users(self):
        return []


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "admin@test.com"
        sess["user_affiliations"] = ["admin"]


def _admin_app(db_path):
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=received,
        estimated_dir=estimated,
        user_store=_Store(),
    )
    app.config["EXECUTION_PROFILE_DB_PATH"] = str(db_path)
    return app, (received, estimated)


def _cleanup(paths):
    for path in paths:
        shutil.rmtree(path)


def _profile(**overrides):
    profile = {
        "id": "rikyu-qws-nightly",
        "display_name": "RIKYU QWS nightly",
        "enabled": True,
        "status": "approved",
        "owner": "project-a",
        "activity": "FugakuNEXT",
        "code": "qws",
        "system": ["RIKYU"],
        "exp": ["case0"],
        "scheduler_extra_args": "--account=site-local",
        "visibility": "public-results",
        "valid_from": "2026-09-01",
        "valid_until": "2027-03-31",
        "approved_by": "admin@test.com",
        "approved_at": "2026-09-01T00:00:00Z",
        "metadata_json": {"terms_version": "v1"},
    }
    profile.update(overrides)
    normalized, errors = normalize_profile(profile)
    assert errors == []
    assert normalized is not None
    return normalized


def test_execution_profile_store_creates_sqlite_registry(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(), actor="admin@test.com")

    result = load_execution_profiles(str(db_path))

    assert result.exists is True
    assert result.errors == []
    assert result.enabled_count == 1
    assert result.disabled_count == 0
    assert result.profiles[0]["id"] == "rikyu-qws-nightly"
    assert result.profiles[0]["status"] == "approved"
    assert result.profiles[0]["code"] == ["qws"]
    assert result.profiles[0]["system"] == ["RIKYU"]
    assert result.profiles[0]["exp"] == ["case0"]
    assert result.profiles[0]["scheduler_extra_args"] == "--account=site-local"
    assert result.profiles[0]["metadata_json"] == {"terms_version": "v1"}


def test_execution_profile_store_updates_profile_and_scopes(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(system=["RIKYU"], exp=["case0"]), actor="admin")
    store.upsert_profile(
        _profile(
            system=["RIKYU", "MiyabiG"],
            exp=[],
            scheduler_extra_args="--account=updated",
        ),
        actor="admin",
    )

    result = load_execution_profiles(str(db_path))

    assert len(result.profiles) == 1
    assert result.profiles[0]["system"] == ["MiyabiG", "RIKYU"]
    assert result.profiles[0]["exp"] == []
    assert result.profiles[0]["scheduler_extra_args"] == "--account=updated"


def test_execution_profile_store_resolves_approved_matching_profile(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(
        _profile(id="generic", code=[], system=[], scheduler_extra_args="--account=generic"),
        actor="admin",
    )
    store.upsert_profile(
        _profile(
            id="rikyu-qws",
            code=["qws"],
            system=["RIKYU"],
            scheduler_extra_args="--account=rikyu-qws",
        ),
        actor="admin",
    )

    result = store.resolve_profile(code="qws", system="RIKYU")

    assert result.errors == []
    assert result.profile["id"] == "rikyu-qws"
    assert result.scheduler_extra_args == "--account=rikyu-qws"


def test_execution_profile_store_rejects_unapproved_or_disabled_matches(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(id="draft", status="draft"), actor="admin")
    store.upsert_profile(_profile(id="disabled", enabled=False), actor="admin")

    result = store.resolve_profile(code="qws", system="RIKYU")

    assert result.profile is None
    assert result.errors == ["no approved execution profile matches target"]


def test_execution_profile_store_reports_ambiguous_matching_profiles(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(
        _profile(id="rikyu-qws-a", code=["qws"], system=["RIKYU"]),
        actor="admin",
    )
    store.upsert_profile(
        _profile(id="rikyu-qws-b", code=["qws"], system=["RIKYU"]),
        actor="admin",
    )

    result = store.resolve_profile(code="qws", system="RIKYU")

    assert result.profile is None
    assert result.errors == [
        "multiple execution profiles match target: rikyu-qws-a, rikyu-qws-b"
    ]


def test_execution_profile_store_validates_requested_profile_scope(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(
        _profile(id="rikyu-qws", code=["qws"], system=["RIKYU"]),
        actor="admin",
    )

    result = store.resolve_profile(
        profile_id="rikyu-qws",
        code="genesis",
        system="RIKYU",
    )

    assert result.profile is None
    assert result.errors == ["execution profile is not approved for target: rikyu-qws"]


def test_execution_profile_store_records_dry_run_request(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))

    request_id = store.create_execution_request(
        request_type="gitlab_pipeline",
        status="dry_run_ready",
        dry_run=True,
        profile_id="rikyu-qws-nightly",
        target_ref="develop",
        code="qws",
        system="RIKYU",
        exp="case0",
        payload={"payload": {"ref": "develop", "variables": []}},
        actor="admin@test.com",
    )

    assert request_id == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, dry_run, profile_id, target_ref FROM execution_requests"
        ).fetchone()
    assert row == ("dry_run_ready", 1, "rikyu-qws-nightly", "develop")


def test_import_execution_profiles_json_seeds_sqlite_registry(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    seed_path = tmp_path / "execution_profiles.json"
    seed_path.write_text(
        json.dumps({"profiles": [_profile()]}),
        encoding="utf-8",
    )

    errors = import_execution_profiles_json(
        str(seed_path),
        str(db_path),
        actor="seed",
    )

    assert errors == []
    assert load_execution_profiles(str(db_path)).profiles[0]["id"] == "rikyu-qws-nightly"


def test_import_execution_profiles_json_reports_invalid_seed(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    seed_path = tmp_path / "execution_profiles.json"
    seed_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {"id": "bad id", "enabled": "yes"},
                    {"id": "dup"},
                    {"id": "dup"},
                    "not-a-profile",
                ]
            }
        ),
        encoding="utf-8",
    )

    errors = import_execution_profiles_json(str(seed_path), str(db_path))

    assert errors == [
        "profile[0] has invalid id: bad id",
        "profile[0] enabled must be boolean",
        "profile[2] duplicates id: dup",
        "profile[3] must be an object",
    ]


def test_load_execution_profiles_creates_empty_registry(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    result = load_execution_profiles(str(db_path))

    assert result.exists is True
    assert result.profiles == []
    assert result.errors == []
    assert db_path.exists()


def test_admin_execution_profiles_requires_admin(tmp_path):
    app, temp_dirs = _admin_app(tmp_path / "cx_portal.sqlite3")
    try:
        with app.test_client() as client:
            resp = client.get("/admin/execution-profiles")

        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_renders_profile_summary(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(_profile(), actor="admin")
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.get("/admin/execution-profiles")

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "RIKYU QWS nightly" in html
        assert "rikyu-qws-nightly" in html
        assert "--account=site-local" in html
        assert "approved" in html
        assert "admin@test.com" in html
        assert "qws" in html
        assert "RIKYU" in html
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_upserts_profile_from_form(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/upsert",
                data={
                    "id": "rikyu-qws-nightly",
                    "display_name": "RIKYU QWS nightly",
                    "enabled": "on",
                    "status": "approved",
                    "owner": "project-a",
                    "activity": "FugakuNEXT",
                    "code": "qws, genesis",
                    "system": "RIKYU\nMiyabiG",
                    "exp": "case0",
                    "scheduler_extra_args": "--account=site-local",
                    "visibility": "public-results",
                    "valid_from": "2026-09-01",
                    "valid_until": "2027-03-31",
                    "approved_by": "admin@test.com",
                    "approved_at": "2026-09-01T00:00:00Z",
                    "metadata_json": '{"terms_version":"v1"}',
                },
                follow_redirects=True,
            )

        result = load_execution_profiles(str(db_path))
        assert resp.status_code == 200
        assert b"Execution profile rikyu-qws-nightly saved." in resp.data
        assert len(result.profiles) == 1
        assert result.profiles[0]["code"] == ["genesis", "qws"]
        assert result.profiles[0]["system"] == ["MiyabiG", "RIKYU"]
        assert result.profiles[0]["metadata_json"] == {"terms_version": "v1"}
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_rejects_invalid_metadata_json(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/upsert",
                data={
                    "id": "bad-metadata",
                    "enabled": "on",
                    "metadata_json": "[1, 2, 3]",
                },
                follow_redirects=True,
            )

        result = load_execution_profiles(str(db_path))
        assert resp.status_code == 200
        assert b"metadata_json must be a JSON object" in resp.data
        assert result.profiles == []
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_dry_run_submit_renders_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(_profile(), actor="admin")
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/dry-run-submit",
                data={
                    "target_ref": "develop",
                    "code": "qws",
                    "system": "RIKYU",
                    "exp": "case0",
                },
            )

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "Dry-run request #1" in html
        assert "dry_run_ready" in html
        assert "https://gitlab.example.org/api/v4/projects/group%2Fbenchkit/pipeline" in html
        assert "--account=site-local" in html

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status, profile_id, code, system, payload_json FROM execution_requests"
            ).fetchone()
        assert row[:4] == ("dry_run_ready", "rikyu-qws-nightly", "qws", "RIKYU")
        payload_record = json.loads(row[4])
        variables = payload_record["payload"]["variables"]
        assert {"key": "code", "value": "qws", "variable_type": "env_var"} in variables
        assert {
            "key": "BK_SCHEDULER_EXTRA_ARGS_RIKYU",
            "value": "--account=site-local",
            "variable_type": "env_var",
        } in variables
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_dry_run_blocks_without_matching_profile(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    db_path = tmp_path / "cx_portal.sqlite3"
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/dry-run-submit",
                data={"target_ref": "develop", "code": "qws", "system": "RIKYU"},
            )

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "dry_run_blocked" in html
        assert "no approved execution profile matches target" in html
    finally:
        _cleanup(temp_dirs)
