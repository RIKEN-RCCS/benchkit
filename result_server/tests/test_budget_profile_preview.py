"""Structural preview, read-only storage and output minimization contracts."""

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.budget_profile_preview import compare_profiles, preview_profiles, read_profiles
from utils.budget_registry import BudgetRegistry, RegistryActor, RegistryError, RegistryPermissionError
from utils.encrypted_sqlite import generate_key
from utils.execution_profiles import ExecutionProfileStore, normalize_profile, normalize_trigger_definition


ADMIN = RegistryActor("admin@example.org", is_admin=True)


@pytest.fixture
def catalog():
    return dict(revision=7, schema_version=4,
                budgets=[dict(id="budget", system="Managed", enabled=True, valid_from="", valid_until="")],
                execution_accounts=[dict(id="settings", system="Managed", connection_id="gitlab:example")],
                connections=[dict(id="gitlab:example", target_id="example", available=True,
                                  server_url="https://gitlab.example.org", project_path="group/project",
                                  token_env="PRIVATE_CREDENTIAL_REFERENCE")],
                destinations=[dict(id="destination", budget_id="budget", system="Example_A",
                                   account_id="settings", allocation_project_id="allocation-example")])


@pytest.fixture
def profile():
    return dict(id="profile", enabled=True, status="approved", valid_from="", valid_until="",
                allocation_project_id="allocation-example", systems=["Example_A"],
                triggers=[dict(id="trigger", enabled=True, gitlab_target="example")])


def test_output_is_structural_and_omits_private_values(catalog, profile):
    result = compare_profiles(catalog, [profile])
    row = result["rows"][0]
    assert row["reasons"] == []
    assert row["candidates"][0]["reasons"] == []
    assert row["candidates"][0]["managed_system"] == "Managed"
    assert "no_changes_applied" in result["limitations"]
    output = json.dumps(result)
    for value in ("allocation-example", "PRIVATE_CREDENTIAL_REFERENCE", "https://gitlab.example.org"):
        assert value not in output


def test_each_system_and_trigger_retains_own_candidates(catalog, profile):
    profile["systems"].append("Example_B")
    profile["triggers"].append(dict(id="other", enabled=True, gitlab_target="missing"))
    rows = compare_profiles(catalog, [profile])["rows"]
    assert len(rows) == 4
    assert all(row["candidates"] for row in rows if row["system"] == "Example_A")
    assert all("no_registered_destination" in row["reasons"] for row in rows if row["system"] == "Example_B")
    assert all("existing_target_unavailable" in row["reasons"] for row in rows if row["trigger_id"] == "other")


@pytest.mark.parametrize("systems", [[], ["*"], ["Example_*"]])
def test_unbounded_scope_is_not_inferred_from_registry(catalog, profile, systems):
    profile["systems"] = systems
    row = compare_profiles(catalog, [profile])["rows"][0]
    assert "system_scope_unresolved" in row["reasons"]
    assert not row["candidates"]


def test_missing_trigger_does_not_inherit_default_target(catalog, profile):
    profile["triggers"] = []
    row = compare_profiles(catalog, [profile], default_target="example")["rows"][0]
    assert "existing_target_unknown" in row["reasons"]
    profile["triggers"] = [dict(id="default", enabled=True, gitlab_target="")]
    row = compare_profiles(catalog, [profile], default_target="example")["rows"][0]
    assert not row["reasons"]


@pytest.mark.parametrize("registered_allocation", ["", "allocation-example"])
def test_empty_profile_allocation_is_always_unspecified(catalog, profile, registered_allocation):
    profile["allocation_project_id"] = ""
    catalog["destinations"][0]["allocation_project_id"] = registered_allocation
    row = compare_profiles(catalog, [profile])["rows"][0]
    assert "existing_allocation_unspecified" in row["candidates"][0]["reasons"]


def test_mismatches_and_disabled_states_are_retained(catalog, profile):
    profile.update(enabled=False, status="draft", valid_from="2030-02-01")
    profile["triggers"][0]["enabled"] = False
    catalog["budgets"][0].update(enabled=False, valid_until="2029-12-31")
    catalog["execution_accounts"][0]["system"] = "Other"
    catalog["destinations"][0]["allocation_project_id"] = "different"
    row = compare_profiles(catalog, [profile], today="2030-01-01")["rows"][0]
    assert set(row["reasons"]) >= {"profile_disabled", "profile_not_approved", "profile_not_yet_valid", "trigger_disabled"}
    assert set(row["candidates"][0]["reasons"]) >= {
        "budget_disabled", "budget_expired", "allocation_mismatch", "managed_system_mismatch"}


def test_target_comparison_uses_endpoint_binding(catalog, profile):
    connection = deepcopy(catalog["connections"][0])
    connection.update(id="legacy", target_id="", project_path="group/different")
    catalog["connections"].append(connection)
    catalog["execution_accounts"][0]["connection_id"] = "legacy"
    row = compare_profiles(catalog, [profile])["rows"][0]
    assert "target_mismatch" in row["candidates"][0]["reasons"]
    connection["project_path"] = "group/project"
    assert not compare_profiles(catalog, [profile])["rows"][0]["candidates"][0]["reasons"]
    connection["available"] = False
    row = compare_profiles(catalog, [profile])["rows"][0]
    assert "connection_unavailable" in row["candidates"][0]["reasons"]


def test_multiple_candidates_are_not_selected(catalog, profile):
    catalog["destinations"].append(dict(catalog["destinations"][0], id="other-destination"))
    row = compare_profiles(catalog, [profile])["rows"][0]
    assert len(row["candidates"]) == 2
    assert "multiple_destinations_require_review" in row["reasons"]
    assert "selected_destination" not in row


@pytest.fixture
def profile_db(tmp_path):
    path = tmp_path / "profiles.sqlite3"
    store = ExecutionProfileStore(str(path))
    profile, errors = normalize_profile(dict(id="profile", display_name="Example profile", status="approved",
                                            system=["Example_A"], code=["example"], exp=["case"],
                                            metadata_json={"private": "DO_NOT_EXPORT"}))
    assert not errors
    store.upsert_profile(profile, actor="admin@example.org")
    trigger, errors = normalize_trigger_definition(dict(id="trigger", profile_id="profile", name="Example",
                                                        trigger_type="manual_button", gitlab_target=""))
    assert not errors
    store.upsert_trigger_definition(trigger, actor="admin@example.org")
    return path


def test_profile_reader_does_not_migrate_or_write(profile_db, monkeypatch):
    before = profile_db.read_bytes()
    def reject_migration(*args, **kwargs):
        pytest.fail("A preview must not migrate a database")
    monkeypatch.setattr(ExecutionProfileStore, "migrate", reject_migration)
    profiles = read_profiles(profile_db)
    assert profiles[0]["systems"] == ["Example_A"]
    assert profiles[0]["triggers"][0]["id"] == "trigger"
    assert "DO_NOT_EXPORT" not in json.dumps(profiles)
    assert profile_db.read_bytes() == before


def test_missing_or_old_database_is_not_created_or_migrated(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(RegistryError):
        read_profiles(path)
    assert not path.exists()
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT)")
    before = path.read_bytes()
    with pytest.raises(RegistryError):
        read_profiles(path)
    assert path.read_bytes() == before


def test_encrypted_preview_is_authorized_and_read_only(tmp_path, profile_db, monkeypatch):
    pytest.importorskip("sqlcipher3")
    for name in ("RESULT_SERVER_GITLAB_TARGETS", "RESULT_SERVER_GITLAB_REPO", "GITLAB_REPO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", "example=gitlab.example.org/group/project")
    for name in ("db", "keys"):
        (tmp_path / name).mkdir(mode=0o700)
    key = tmp_path / "keys" / "budget.key"
    generate_key(key)
    registry = BudgetRegistry(tmp_path / "db" / "budget.sqlite3", key)
    registry.initialize()
    revision = registry.save_budget(ADMIN, 0, id="budget", label="Example", system="Managed", enabled=True)
    revision = registry.save_account(ADMIN, revision, id="settings", label="Settings", system="Managed",
                                     connection_id="gitlab:example", build_tag="build", run_tag="run")
    registry.save_destination(ADMIN, revision, id="destination", budget_id="budget", system="Example_A",
                              account_id="settings", allocation_project_id="")
    before = registry.catalog(ADMIN)
    profile_before = profile_db.read_bytes()
    with pytest.raises(RegistryPermissionError):
        preview_profiles(registry, RegistryActor("manager@example.org"), tmp_path / "missing")
    result = preview_profiles(registry, ADMIN, profile_db)
    assert result["rows"][0]["candidates"][0]["destination_id"] == "destination"
    assert "existing_target_unavailable" not in result["rows"][0]["reasons"]
    command = [sys.executable, "-m", "result_server.budget_profile_preview", "--database", str(registry.storage.path),
               "--key-file", str(key), "--profile-database", str(profile_db)]
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == result
    failed = subprocess.run(command[:-1] + [str(tmp_path / "DO_NOT_EXPORT")],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert failed.returncode == 1
    assert "DO_NOT_EXPORT" not in failed.stdout + failed.stderr
    assert registry.catalog(ADMIN) == before
    assert profile_db.read_bytes() == profile_before
