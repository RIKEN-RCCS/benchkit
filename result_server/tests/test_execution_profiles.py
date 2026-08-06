"""Tests for the SQLite execution profile registry and admin display."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs()

from utils.execution_profiles import (  # noqa: E402
    ExecutionProfileStore,
    import_execution_profiles_json,
    load_execution_profiles,
    normalize_profile,
    normalize_trigger_definition,
)
from utils.gitlab_pipeline import (  # noqa: E402
    GitLabPipelineSubmitResult,
    build_pipeline_plan,
    configured_gitlab_target,
    configured_gitlab_targets,
    configured_gitlab_trigger_token,
    submit_pipeline_plan,
)
from routes.admin import _portal_result_server_url  # noqa: E402
from trigger_runner import (  # noqa: E402
    cron_matches,
    run_triggers,
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
        "allocation_project_id": "rkp00010",
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
    assert result.profiles[0]["allocation_project_id"] == "rkp00010"
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


def test_execution_profile_summary_counts_status_and_expiration(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(id="approved"), actor="admin")
    store.upsert_profile(_profile(id="paused", status="paused"), actor="admin")
    store.upsert_profile(
        _profile(id="expired", valid_until="2000-01-01"),
        actor="admin",
    )

    result = load_execution_profiles(str(db_path))

    assert result.approved_count == 2
    assert result.inactive_count == 1
    assert result.expired_count == 1


def test_execution_profile_store_sets_approval_fields_from_actor(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    profile = _profile(
        approved_by="manual@example.org",
        approved_at="1999-01-01T00:00:00Z",
    )

    store.upsert_profile(profile, actor="admin@test.com")

    result = load_execution_profiles(str(db_path))
    assert result.profiles[0]["approved_by"] == "admin@test.com"
    assert result.profiles[0]["approved_at"].endswith("Z")
    assert result.profiles[0]["approved_at"] != "1999-01-01T00:00:00Z"


def test_execution_profile_store_preserves_existing_approval_on_update(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(system=["RIKYU"]), actor="approver@test.com")
    first = load_execution_profiles(str(db_path)).profiles[0]

    store.upsert_profile(_profile(system=["RIKYU", "MiyabiG"]), actor="editor@test.com")

    result = load_execution_profiles(str(db_path))
    assert result.profiles[0]["approved_by"] == "approver@test.com"
    assert result.profiles[0]["approved_at"] == first["approved_at"]


def test_execution_profile_store_creates_scheduled_trigger_definition(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(), actor="admin@test.com")
    trigger, errors = normalize_trigger_definition(
        {
            "id": "rikyu-qws-nightly",
            "trigger_type": "scheduled",
            "profile_id": "rikyu-qws-nightly",
            "enabled": True,
            "gitlab_target": "swc",
            "cron_expr": "0 2 * * *",
            "timezone": "Asia/Tokyo",
        }
    )
    assert errors == []
    assert trigger is not None

    store.upsert_trigger_definition(trigger, actor="admin@test.com")

    triggers = store.list_trigger_definitions()
    assert len(triggers) == 1
    assert triggers[0]["id"] == "rikyu-qws-nightly"
    assert triggers[0]["trigger_type"] == "scheduled"
    assert triggers[0]["profile_id"] == "rikyu-qws-nightly"
    assert triggers[0]["cron_expr"] == "0 2 * * *"
    assert triggers[0]["timezone"] == "Asia/Tokyo"
    assert triggers[0]["gitlab_target"] == "swc"


def test_execution_profile_store_creates_watch_event_trigger_definition(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(), actor="admin@test.com")
    trigger, errors = normalize_trigger_definition(
        {
            "id": "rikyu-qws-watch",
            "trigger_type": "watch_event",
            "profile_id": "rikyu-qws-nightly",
            "enabled": True,
            "watch_kind": "repo_ref",
            "watch_targets": (
                "https://github.com/RIKEN-LQCD/qws.git@master\n"
                "https://github.com/RIKEN-LQCD/qws.git@develop"
            ),
            "match_mode": "any",
        }
    )
    assert errors == []
    assert trigger is not None

    store.upsert_trigger_definition(trigger, actor="admin@test.com")

    triggers = store.list_trigger_definitions()
    assert triggers[0]["trigger_type"] == "watch_event"
    assert triggers[0]["watch_kind"] == "repo_ref"
    assert triggers[0]["watch_targets"] == [
        "https://github.com/RIKEN-LQCD/qws.git@master",
        "https://github.com/RIKEN-LQCD/qws.git@develop",
    ]
    assert triggers[0]["match_mode"] == "any"


def test_execution_profile_store_records_trigger_observations_and_runs(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(), actor="admin@test.com")
    trigger, errors = normalize_trigger_definition(
        {
            "id": "rikyu-qws-watch",
            "trigger_type": "watch_event",
            "profile_id": "rikyu-qws-nightly",
            "enabled": True,
            "watch_kind": "repo_ref",
            "watch_targets": "https://github.com/RIKEN-LQCD/qws.git@master",
            "match_mode": "any",
        }
    )
    assert errors == []
    assert trigger is not None
    store.upsert_trigger_definition(trigger, actor="admin@test.com")

    store.upsert_trigger_observation(
        "rikyu-qws-watch",
        "https://github.com/RIKEN-LQCD/qws.git@master",
        "abc123",
        observed_at="2026-08-06T00:00:00Z",
    )
    run_id = store.create_trigger_run(
        trigger_id="rikyu-qws-watch",
        trigger_type="watch_event",
        status="would_submit",
        dry_run=True,
        reason="repo_ref:https://github.com/RIKEN-LQCD/qws.git@master",
        payload={"payload": {"variables": {"BK_TRIGGER_ID": "rikyu-qws-watch"}}},
        errors=[],
        actor="trigger_runner",
    )

    observations = store.list_trigger_observations("rikyu-qws-watch")
    runs = store.list_trigger_runs("rikyu-qws-watch")
    assert observations == [
        {
            "trigger_id": "rikyu-qws-watch",
            "target": "https://github.com/RIKEN-LQCD/qws.git@master",
            "fingerprint": "abc123",
            "observed_at": "2026-08-06T00:00:00Z",
        }
    ]
    assert runs[0]["id"] == run_id
    assert runs[0]["status"] == "would_submit"
    assert runs[0]["payload_json"]["payload"]["variables"]["BK_TRIGGER_ID"] == "rikyu-qws-watch"


def test_execution_profile_store_acquires_and_releases_trigger_runner_lock(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))

    assert store.acquire_trigger_runner_lock(
        "default",
        owner="runner-a",
        ttl_seconds=60,
        now="2026-08-06T00:00:00Z",
    )
    assert not store.acquire_trigger_runner_lock(
        "default",
        owner="runner-b",
        ttl_seconds=60,
        now="2026-08-06T00:00:30Z",
    )
    assert store.acquire_trigger_runner_lock(
        "default",
        owner="runner-b",
        ttl_seconds=60,
        now="2026-08-06T00:01:01Z",
    )
    assert not store.release_trigger_runner_lock(
        "default",
        owner="runner-a",
        now="2026-08-06T00:01:02Z",
    )
    assert store.release_trigger_runner_lock(
        "default",
        owner="runner-b",
        now="2026-08-06T00:01:02Z",
    )
    assert store.acquire_trigger_runner_lock(
        "default",
        owner="runner-a",
        ttl_seconds=60,
        now="2026-08-06T00:01:02Z",
    )


def test_trigger_runner_cron_matches_basic_fields():
    now = datetime(2026, 8, 10, 1, 30, tzinfo=UTC)

    assert cron_matches("30 1 * * 1", now) == (True, [])
    assert cron_matches("*/15 * * * *", now) == (True, [])
    assert cron_matches("0 2 * * *", now) == (False, [])
    assert cron_matches("0 2 *", now) == (False, ["cron expression must have 5 fields"])


def test_trigger_runner_dry_run_detects_repo_ref_change_and_records_run(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(system=["Fugaku"]), actor="admin@test.com")
    trigger, errors = normalize_trigger_definition(
        {
            "id": "rikyu-qws-watch",
            "trigger_type": "watch_event",
            "profile_id": "rikyu-qws-nightly",
            "enabled": True,
            "watch_kind": "repo_ref",
            "watch_targets": (
                "https://github.com/RIKEN-LQCD/qws.git@master\n"
                "https://github.com/RIKEN-LQCD/qws.git@develop"
            ),
            "match_mode": "any",
        }
    )
    assert errors == []
    assert trigger is not None
    store.upsert_trigger_definition(trigger, actor="admin@test.com")

    fingerprint_suffix = "initial"

    def fake_ls_remote(repo, ref):
        return f"{repo}:{ref}:{fingerprint_suffix}"

    evaluations = run_triggers(
        db_path=str(db_path),
        dry_run=True,
        result_server_url="https://fncx.r-ccs.riken.jp/dev2",
        record_observations=True,
        ls_remote=fake_ls_remote,
    )

    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation.should_fire is False
    assert evaluation.status == "would_initialize"
    assert all(item["initialized"] is True for item in evaluation.observations)
    assert all(item["changed"] is False for item in evaluation.observations)
    variables = evaluation.payload["payload"]["variables"]
    assert variables["code"] == "qws"
    assert variables["system"] == "Fugaku"
    assert variables["RESULT_SERVER"] == "https://fncx.r-ccs.riken.jp/dev2"
    assert variables["BK_TRIGGER_ID"] == "rikyu-qws-watch"
    assert variables["BK_TRIGGER_TYPE"] == "watch_event"
    assert variables["BK_TRIGGER_REASON"].startswith("repo_ref:")

    stored = ExecutionProfileStore(str(db_path))
    observations = stored.list_trigger_observations("rikyu-qws-watch")
    runs = stored.list_trigger_runs("rikyu-qws-watch")
    assert len(observations) == 2
    assert runs[0]["status"] == "would_initialize"

    second = run_triggers(
        db_path=str(db_path),
        dry_run=True,
        result_server_url="https://fncx.r-ccs.riken.jp/dev2",
        record_observations=True,
        ls_remote=fake_ls_remote,
    )
    assert second[0].should_fire is False
    assert second[0].status == "unchanged"

    fingerprint_suffix = "changed"
    third = run_triggers(
        db_path=str(db_path),
        dry_run=True,
        result_server_url="https://fncx.r-ccs.riken.jp/dev2",
        record_observations=True,
        ls_remote=fake_ls_remote,
    )
    assert third[0].should_fire is True
    assert third[0].status == "would_submit"


def test_trigger_runner_submit_records_submitted_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN", "trigger-token")
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(system=["Fugaku"]), actor="admin@test.com")
    trigger, errors = normalize_trigger_definition(
        {
            "id": "rikyu-qws-watch",
            "trigger_type": "watch_event",
            "profile_id": "rikyu-qws-nightly",
            "enabled": True,
            "watch_kind": "repo_ref",
            "watch_targets": "https://github.com/RIKEN-LQCD/qws.git@master",
            "match_mode": "any",
        }
    )
    assert errors == []
    assert trigger is not None
    store.upsert_trigger_definition(trigger, actor="admin@test.com")
    store.upsert_trigger_observation(
        "rikyu-qws-watch",
        "https://github.com/RIKEN-LQCD/qws.git@master",
        "old-fingerprint",
    )
    submitted = []

    def fake_ls_remote(repo, ref):
        return f"{repo}:{ref}:new-fingerprint"

    def fake_submit(plan, *, token):
        submitted.append((plan, token))
        return GitLabPipelineSubmitResult(
            status_code=201,
            response={"id": 123},
            errors=[],
        )

    evaluations = run_triggers(
        db_path=str(db_path),
        dry_run=False,
        result_server_url="https://fncx.r-ccs.riken.jp/dev2",
        record_observations=True,
        submit=True,
        ls_remote=fake_ls_remote,
        submit_pipeline=fake_submit,
    )

    assert len(submitted) == 1
    plan, token = submitted[0]
    assert token == "trigger-token"
    assert plan.api_url == "https://gitlab.example.org/api/v4/projects/group%2Fbenchkit/trigger/pipeline"
    assert plan.payload["ref"] == "develop"
    assert plan.payload["variables"]["RESULT_SERVER"] == "https://fncx.r-ccs.riken.jp/dev2"
    assert evaluations[0].status == "submitted"
    assert evaluations[0].errors == []

    stored = ExecutionProfileStore(str(db_path))
    runs = stored.list_trigger_runs("rikyu-qws-watch")
    assert runs[0]["status"] == "submitted"
    assert runs[0]["dry_run"] is False
    assert runs[0]["errors"] == []


def test_trigger_runner_skips_when_lock_is_held(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(system=["Fugaku"]), actor="admin@test.com")
    trigger, errors = normalize_trigger_definition(
        {
            "id": "rikyu-qws-watch",
            "trigger_type": "watch_event",
            "profile_id": "rikyu-qws-nightly",
            "enabled": True,
            "watch_kind": "repo_ref",
            "watch_targets": "https://github.com/RIKEN-LQCD/qws.git@master",
            "match_mode": "any",
        }
    )
    assert errors == []
    assert trigger is not None
    store.upsert_trigger_definition(trigger, actor="admin@test.com")
    assert store.acquire_trigger_runner_lock(
        "default",
        owner="other-runner",
        ttl_seconds=300,
        now="2026-08-06T00:00:00Z",
    )

    def fail_ls_remote(repo, ref):
        raise AssertionError("locked runner must not observe watch targets")

    evaluations = run_triggers(
        db_path=str(db_path),
        dry_run=True,
        result_server_url="https://fncx.r-ccs.riken.jp/dev2",
        now=datetime(2026, 8, 6, 0, 1, tzinfo=UTC),
        ls_remote=fail_ls_remote,
    )

    assert len(evaluations) == 1
    assert evaluations[0].trigger_id == "__runner__"
    assert evaluations[0].status == "runner_locked"
    runs = ExecutionProfileStore(str(db_path)).list_trigger_runs("__runner__")
    assert runs[0]["status"] == "runner_locked"


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
    ExecutionProfileStore(str(db_path)).upsert_profile(
        _profile(),
        actor="admin@test.com",
    )
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.get("/admin/execution-profiles")

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "RIKYU QWS nightly" not in html
        assert "rikyu-qws-nightly" in html
        assert "Approved</span>" in html
        assert "Inactive</span>" in html
        assert "Expired</span>" in html
        assert "rkp00010" in html
        assert "approved" in html
        assert "admin@test.com" in html
        assert "qws" in html
        assert "RIKYU" in html
        assert 'href="/admin/execution-profiles?edit=rikyu-qws-nightly"' in html
        assert 'name="profile_id" value="rikyu-qws-nightly"' in html
        assert 'name="target_ref" value="main"' in html
        assert 'name="confirm_submit" value="on"' in html
        assert 'aria-label="Trigger pipeline on main"' in html
        assert "Preview" not in html
        assert "Manual triggers are launched from Registered Profiles" not in html
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_filters_registered_profiles_by_status(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(id="approved-profile"), actor="admin@test.com")
    store.upsert_profile(
        _profile(id="paused-profile", status="paused"),
        actor="admin@test.com",
    )
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.get("/admin/execution-profiles")

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "paused-profile" in html
        assert "approved-profile" in html
        assert 'data-profile-filter="paused"' in html
        assert 'data-status="paused"' in html
        assert 'data-status="approved"' in html
        assert "profile-filter-active" in html
        assert "document.addEventListener" in html
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
                    "enabled": "on",
                    "status": "approved",
                    "activity": "FugakuNEXT",
                    "allocation_project_id": "rkp00010",
                    "code": "qws, genesis",
                    "system": "RIKYU",
                    "exp": "case0",
                    "valid_from": "2026-09-01",
                    "valid_until": "2027-03-31",
                },
                follow_redirects=True,
            )

        result = load_execution_profiles(str(db_path))
        assert resp.status_code == 200
        assert b"Execution profile rikyu-qws-nightly saved." in resp.data
        assert len(result.profiles) == 1
        assert result.profiles[0]["display_name"] == "rikyu-qws-nightly"
        assert result.profiles[0]["code"] == ["genesis", "qws"]
        assert result.profiles[0]["system"] == ["RIKYU"]
        assert result.profiles[0]["allocation_project_id"] == "rkp00010"
        assert result.profiles[0]["approved_by"] == "admin@test.com"
        assert result.profiles[0]["approved_at"].endswith("Z")
        assert result.profiles[0]["metadata_json"] == {}
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_upserts_scheduled_trigger_from_form(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(
        _profile(),
        actor="admin@test.com",
    )
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/triggers/upsert",
                data={
                    "id": "rikyu-qws-nightly",
                    "trigger_type": "scheduled",
                    "profile_id": "rikyu-qws-nightly",
                    "enabled": "on",
                    "gitlab_target": "swc",
                    "cron_expr": "0 2 * * *",
                    "timezone": "Asia/Tokyo",
                },
                follow_redirects=True,
            )

        triggers = ExecutionProfileStore(str(db_path)).list_trigger_definitions()
        html = resp.data.decode()
        assert resp.status_code == 200
        assert b"Trigger definition rikyu-qws-nightly saved." in resp.data
        assert triggers[0]["cron_expr"] == "0 2 * * *"
        assert "Registered Triggers" in html
        assert "rikyu-qws-nightly" in html
        assert "0 2 * * *" in html
        assert "0 */6 * * * = every 6 hours" in html
        assert 'type="checkbox" name="enabled"' not in html
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_upserts_watch_event_trigger_from_form(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(
        _profile(),
        actor="admin@test.com",
    )
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/triggers/upsert",
                data={
                    "id": "rikyu-qws-watch",
                    "trigger_type": "watch_event",
                    "profile_id": "rikyu-qws-nightly",
                    "enabled": "on",
                    "watch_kind": "repo_ref",
                    "watch_targets": (
                        "https://github.com/RIKEN-LQCD/qws.git@master\n"
                        "https://github.com/RIKEN-LQCD/qws.git@develop"
                    ),
                    "match_mode": "all",
                },
                follow_redirects=True,
            )

        triggers = ExecutionProfileStore(str(db_path)).list_trigger_definitions()
        html = resp.data.decode()
        assert resp.status_code == 200
        assert triggers[0]["watch_kind"] == "repo_ref"
        assert triggers[0]["watch_targets"] == [
            "https://github.com/RIKEN-LQCD/qws.git@master",
            "https://github.com/RIKEN-LQCD/qws.git@develop",
        ]
        assert triggers[0]["match_mode"] == "all"
        assert (
            "https://github.com/RIKEN-LQCD/qws.git@master, "
            "https://github.com/RIKEN-LQCD/qws.git@develop"
        ) in html
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_edits_pauses_resumes_and_deletes_trigger(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(), actor="admin@test.com")
    trigger, errors = normalize_trigger_definition(
        {
            "id": "rikyu-qws-nightly",
            "trigger_type": "scheduled",
            "profile_id": "rikyu-qws-nightly",
            "enabled": True,
            "cron_expr": "0 2 * * *",
            "timezone": "Asia/Tokyo",
        }
    )
    assert errors == []
    assert trigger is not None
    store.upsert_trigger_definition(trigger, actor="admin@test.com")
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            edit_resp = client.get(
                "/admin/execution-profiles?edit_trigger=rikyu-qws-nightly"
            )
            pause_resp = client.post(
                "/admin/execution-profiles/triggers/rikyu-qws-nightly/pause",
                follow_redirects=True,
            )
            resume_resp = client.post(
                "/admin/execution-profiles/triggers/rikyu-qws-nightly/resume",
                follow_redirects=True,
            )
            delete_resp = client.post(
                "/admin/execution-profiles/triggers/rikyu-qws-nightly/delete",
                follow_redirects=True,
            )

        edit_html = edit_resp.data.decode()
        assert edit_resp.status_code == 200
        assert "Edit Trigger" in edit_html
        assert 'name="id" required placeholder="qws-fugaku-nightly" value="rikyu-qws-nightly"' in edit_html
        assert pause_resp.status_code == 200
        assert b"Trigger definition rikyu-qws-nightly paused." in pause_resp.data
        assert resume_resp.status_code == 200
        assert b"Trigger definition rikyu-qws-nightly resumed." in resume_resp.data
        assert delete_resp.status_code == 200
        assert b"Trigger definition rikyu-qws-nightly deleted." in delete_resp.data
        assert ExecutionProfileStore(str(db_path)).list_trigger_definitions() == []
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_deletes_profile(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(
        _profile(),
        actor="admin@test.com",
    )
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/rikyu-qws-nightly/delete",
                follow_redirects=True,
            )

        result = load_execution_profiles(str(db_path))
        assert resp.status_code == 200
        assert b"Execution profile rikyu-qws-nightly deleted." in resp.data
        assert result.profiles == []
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_edit_link_prefills_form(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(
        _profile(
            id="qws-fugaku",
            code=["qws"],
            system=["Fugaku"],
            exp=[],
            allocation_project_id="rkp00010",
            activity="CX",
            valid_from="2026-08-01",
            valid_until="2026-09-30",
        ),
        actor="admin@test.com",
    )
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.get("/admin/execution-profiles?edit=qws-fugaku")

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "Edit Profile" in html
        assert 'name="id" required placeholder="qws-fugaku-rkp00010" value="qws-fugaku"' in html
        assert 'name="activity" placeholder="FugakuNEXT" value="CX"' in html
        assert 'name="allocation_project_id" required placeholder="rkp00010" value="rkp00010"' in html
        assert 'name="system" placeholder="Fugaku" value="Fugaku"' in html
        assert "qws</textarea>" in html
        assert "Cancel Edit" in html
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_rejects_allocation_without_single_system(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/upsert",
                data={
                    "id": "bad-allocation-scope",
                    "status": "approved",
                    "allocation_project_id": "rkp00010",
                    "code": "qws",
                    "system": "Fugaku,MiyabiG",
                },
                follow_redirects=True,
            )

        result = load_execution_profiles(str(db_path))
        assert resp.status_code == 200
        assert b"allocation_project_id requires exactly one system" in resp.data
        assert result.profiles == []
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_rejects_approved_profile_without_allocation(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/upsert",
                data={
                    "id": "missing-allocation",
                    "status": "approved",
                    "code": "qws",
                    "system": "Fugaku",
                },
                follow_redirects=True,
            )

        result = load_execution_profiles(str(db_path))
        assert resp.status_code == 200
        assert b"approved profiles require allocation_project_id" in resp.data
        assert result.profiles == []
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_dry_run_submit_records_payload(tmp_path, monkeypatch):
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
                    "profile_id": "rikyu-qws-nightly",
                },
            )

        assert resp.status_code == 200

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status, profile_id, code, system, payload_json FROM execution_requests"
            ).fetchone()
        assert row[:4] == ("dry_run_ready", "rikyu-qws-nightly", "qws", "RIKYU")
        payload_record = json.loads(row[4])
        variables = payload_record["payload"]["variables"]
        assert variables["code"] == "qws"
        assert variables["BK_ALLOCATION_PROJECT_ID"] == "rkp00010"
        assert variables["RESULT_SERVER"] == "http://localhost"
        assert "BK_SCHEDULER_EXTRA_ARGS_RIKYU" not in variables
        assert "exp" not in variables
        assert payload_record["gitlab_project"] == "gitlab.example.org/group/benchkit.git"
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_dry_run_uses_profile_scope_values(
    tmp_path,
    monkeypatch,
):
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
                    "profile_id": "rikyu-qws-nightly",
                },
            )

        assert resp.status_code == 200

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT status, profile_id, code, system, exp, payload_json
                FROM execution_requests
                """
            ).fetchone()
        assert row[:5] == (
            "dry_run_ready",
            "rikyu-qws-nightly",
            "qws",
            "RIKYU",
            "case0",
        )
        payload_record = json.loads(row[5])
        variables = payload_record["payload"]["variables"]
        assert variables["code"] == "qws"
        assert variables["system"] == "RIKYU"
        assert variables["BK_ALLOCATION_PROJECT_ID"] == "rkp00010"
        assert variables["RESULT_SERVER"] == "http://localhost"
        assert "exp" not in variables
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_dry_run_uses_portal_prefix_for_result_server(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "cx_portal.sqlite3"
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_request_context(
            "/dev2/admin/execution-profiles/dry-run-submit",
            base_url="https://fncx.r-ccs.riken.jp",
        ):
            assert _portal_result_server_url() == "https://fncx.r-ccs.riken.jp/dev2"
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_dry_run_uses_configured_result_server_url(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    monkeypatch.setenv("RESULT_SERVER_PUBLIC_URL", "https://portal.example.org/dev2/")
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
                    "profile_id": "rikyu-qws-nightly",
                },
            )

        assert resp.status_code == 200
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT payload_json FROM execution_requests").fetchone()
        payload_record = json.loads(row[0])
        variables = payload_record["payload"]["variables"]
        assert variables["RESULT_SERVER"] == "https://portal.example.org/dev2"
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
                data={"target_ref": "develop"},
            )

        assert resp.status_code == 200
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status, errors_json FROM execution_requests"
            ).fetchone()
        assert row[0] == "dry_run_blocked"
        assert "profile_id is required" in json.loads(row[1])
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_dry_run_blocks_profile_without_allocation(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(
        _profile(allocation_project_id=""),
        actor="admin",
    )
    app, temp_dirs = _admin_app(db_path)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/dry-run-submit",
                data={
                    "target_ref": "develop",
                    "profile_id": "rikyu-qws-nightly",
                },
            )

        assert resp.status_code == 200
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status, errors_json FROM execution_requests"
            ).fetchone()
        assert row[0] == "dry_run_blocked"
        assert "profile allocation_project_id is required" in json.loads(row[1])
    finally:
        _cleanup(temp_dirs)


def test_gitlab_pipeline_submit_posts_trigger_token_without_storing_it(monkeypatch):
    plan = build_pipeline_plan(
        gitlab_repo="gitlab.example.org/group/benchkit.git",
        target_ref="develop",
        code="qws",
    )
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 201

        def read(self):
            return b'{"id":123,"web_url":"https://gitlab.example.org/p/123"}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["data"] = request.data.decode()
        captured["timeout"] = timeout
        return _Response()

    result = submit_pipeline_plan(plan, token="secret-token", urlopen=fake_urlopen)

    assert result.ok is True
    assert result.status_code == 201
    assert result.response["id"] == 123
    assert captured["url"] == "https://gitlab.example.org/api/v4/projects/group%2Fbenchkit/trigger/pipeline"
    assert "Private-token" not in captured["headers"]
    assert captured["headers"]["Content-type"] == "application/x-www-form-urlencoded"
    fields = urllib.parse.parse_qs(captured["data"])
    assert fields["token"] == ["secret-token"]
    assert fields["ref"] == ["develop"]
    assert fields["variables[code]"] == ["qws"]


def test_gitlab_pipeline_submit_blocks_without_token():
    plan = build_pipeline_plan(
        gitlab_repo="gitlab.example.org/group/benchkit.git",
        target_ref="develop",
        code="qws",
    )

    result = submit_pipeline_plan(plan, token="")

    assert result.ok is False
    assert result.status_code == 0
    assert result.errors == ["RESULT_SERVER_GITLAB_TRIGGER_TOKEN is not set"]


def test_gitlab_pipeline_targets_parse_multiple_destinations():
    env = {
        "RESULT_SERVER_GITLAB_TARGETS": (
            "swc=gitlab.swc.example.org/fugakunext/benchmark/benchkit,"
            "gitlab_com=gitlab.com/yoshifuminakamura/benchkit"
        ),
        "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_SWC": "swc-token",
        "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_GITLAB_COM": "com-token",
    }

    targets, errors = configured_gitlab_targets(env)
    selected, selected_errors = configured_gitlab_target("gitlab_com", env)

    assert errors == []
    assert [target.id for target in targets] == ["swc", "gitlab_com"]
    assert targets[0].token_env == "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_SWC"
    assert selected_errors == []
    assert selected.repo == "gitlab.com/yoshifuminakamura/benchkit"
    assert configured_gitlab_trigger_token(selected, env) == "com-token"


def test_admin_execution_profiles_submit_posts_pipeline_and_records_request(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN", "secret-token")
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(_profile(), actor="admin")
    app, temp_dirs = _admin_app(db_path)

    def fake_submit(plan, *, token):
        assert token == "secret-token"
        assert plan.api_url == "https://gitlab.example.org/api/v4/projects/group%2Fbenchkit/trigger/pipeline"
        return GitLabPipelineSubmitResult(
            status_code=201,
            response={"id": 123, "web_url": "https://gitlab.example.org/p/123"},
            errors=[],
        )

    monkeypatch.setattr("routes.admin.submit_pipeline_plan", fake_submit)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/submit",
                data={
                    "target_ref": "develop",
                    "profile_id": "rikyu-qws-nightly",
                    "confirm_submit": "on",
                },
            )

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "Submit request #1" in html
        assert "submitted" in html
        assert "HTTP 201" in html
        assert "secret-token" not in html
        assert "https://gitlab.example.org/p/123" in html

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT status, dry_run, profile_id, payload_json, errors_json
                FROM execution_requests
                """
            ).fetchone()
        assert row[:3] == ("submitted", 0, "rikyu-qws-nightly")
        assert json.loads(row[4]) == []
        payload_record = json.loads(row[3])
        assert payload_record["submit"]["status_code"] == 201
        assert payload_record["submit"]["response"]["id"] == 123
        assert payload_record["gitlab_project"] == "gitlab.example.org/group/benchkit.git"
        assert "exp" not in payload_record["payload"]["variables"]
        assert "secret-token" not in row[3]
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_submit_uses_selected_gitlab_target(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("RESULT_SERVER_GITLAB_REPO", raising=False)
    monkeypatch.delenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN", raising=False)
    monkeypatch.setenv(
        "RESULT_SERVER_GITLAB_TARGETS",
        "swc=gitlab.swc.example.org/fugakunext/benchmark/benchkit,"
        "gitlab_com=gitlab.com/yoshifuminakamura/benchkit",
    )
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN_GITLAB_COM", "com-token")
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(_profile(), actor="admin")
    app, temp_dirs = _admin_app(db_path)

    def fake_submit(plan, *, token):
        assert token == "com-token"
        assert plan.target_id == "gitlab_com"
        assert plan.api_url == "https://gitlab.com/api/v4/projects/yoshifuminakamura%2Fbenchkit/trigger/pipeline"
        return GitLabPipelineSubmitResult(
            status_code=201,
            response={"id": 456, "web_url": "https://gitlab.com/p/456"},
            errors=[],
        )

    monkeypatch.setattr("routes.admin.submit_pipeline_plan", fake_submit)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/submit",
                data={
                    "gitlab_target": "gitlab_com",
                    "target_ref": "develop",
                    "profile_id": "rikyu-qws-nightly",
                    "confirm_submit": "on",
                },
            )

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "submitted" in html
        assert "gitlab_com" in html

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM execution_requests"
            ).fetchone()
        payload_record = json.loads(row[0])
        assert payload_record["gitlab_target"] == "gitlab_com"
        assert payload_record["gitlab_project"] == "gitlab.com/yoshifuminakamura/benchkit"
        assert payload_record["submit"]["response"]["id"] == 456
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_submit_uses_profile_scope_values(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN", "secret-token")
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(
        _profile(system=["Fugaku"]),
        actor="admin",
    )
    app, temp_dirs = _admin_app(db_path)

    def fake_submit(plan, *, token):
        assert token == "secret-token"
        assert plan.payload["variables"]["code"] == "qws"
        assert plan.payload["variables"]["system"] == "Fugaku"
        assert plan.payload["variables"]["BK_ALLOCATION_PROJECT_ID"] == "rkp00010"
        assert plan.payload["variables"]["RESULT_SERVER"] == "http://localhost"
        assert "exp" not in plan.payload["variables"]
        return GitLabPipelineSubmitResult(
            status_code=201,
            response={"id": 789, "web_url": "https://gitlab.example.org/p/789"},
            errors=[],
        )

    monkeypatch.setattr("routes.admin.submit_pipeline_plan", fake_submit)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/submit",
                data={
                    "target_ref": "develop",
                    "profile_id": "rikyu-qws-nightly",
                    "confirm_submit": "on",
                },
            )

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "submitted" in html

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT status, profile_id, code, system, exp, payload_json
                FROM execution_requests
                """
            ).fetchone()
        assert row[:5] == (
            "submitted",
            "rikyu-qws-nightly",
            "qws",
            "Fugaku",
            "case0",
        )
        payload_record = json.loads(row[5])
        assert payload_record["submit"]["response"]["id"] == 789
    finally:
        _cleanup(temp_dirs)


def test_admin_execution_profiles_submit_requires_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_REPO", "gitlab.example.org/group/benchkit.git")
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN", "secret-token")
    db_path = tmp_path / "cx_portal.sqlite3"
    ExecutionProfileStore(str(db_path)).upsert_profile(_profile(), actor="admin")
    app, temp_dirs = _admin_app(db_path)

    def fail_submit(*_args, **_kwargs):
        raise AssertionError("submit should not be called without confirmation")

    monkeypatch.setattr("routes.admin.submit_pipeline_plan", fail_submit)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/execution-profiles/submit",
                data={
                    "target_ref": "develop",
                    "profile_id": "rikyu-qws-nightly",
                },
            )

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "submit_blocked" in html
        assert "confirm_submit is required" in html
    finally:
        _cleanup(temp_dirs)
