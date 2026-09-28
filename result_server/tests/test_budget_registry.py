"""Real encrypted storage, concurrency, authorization and recovery contracts."""

from __future__ import annotations

from datetime import date
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
import sys
from threading import Barrier

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("sqlcipher3")

from utils import encrypted_sqlite  # noqa: E402
from utils.budget_registry import (  # noqa: E402
    BudgetRegistry, RegistryActor, RegistryConflict, RegistryError, RegistryPermissionError,
)
from utils.encrypted_sqlite import EncryptedDatabaseError, EncryptedSQLite, generate_key  # noqa: E402
from budget_db import main  # noqa: E402


ADMIN = RegistryActor("admin@example.org", is_admin=True)
MANAGER = RegistryActor("manager@example.org")
APPLICANT = RegistryActor("applicant@example.org")
STRANGER = RegistryActor("other@example.org")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    for name in ("RESULT_SERVER_GITLAB_TARGETS", "RESULT_SERVER_GITLAB_REPO", "GITLAB_REPO"):
        monkeypatch.delenv(name, raising=False)
    for name in ("db", "keys", "backup"):
        (tmp_path / name).mkdir(mode=0o700)
    key = tmp_path / "keys" / "registry.key"
    generate_key(key)
    store = BudgetRegistry(tmp_path / "db" / "registry.db", key)
    store.initialize()
    return store


@pytest.fixture
def configured_target(registry, monkeypatch):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", "example=gitlab.example.org/group/project")
    return "gitlab:example"


def seed(store):
    revision = store.save_budget(ADMIN, 0, id="research", label="Research budget", system="ExampleSystem", enabled=True)
    revision = store.set_manager(ADMIN, revision, budget_id="research", principal=MANAGER.principal, assigned=True)
    revision = store.save_connection(ADMIN, revision, id="compute", label="Compute project",
                                    server_url="https://gitlab.example.org", project_path="group/benchmark",
                                    token_env="RESULT_SERVER_GITLAB_TRIGGER_TOKEN_COMPUTE")
    revision = store.save_account(ADMIN, revision, id="research-account", label="Research account",
                                 system="ExampleSystem", connection_id="compute",
                                 build_tag="example-build", run_tag="example-run")
    return store.save_destination(ADMIN, revision, id="research-system", budget_id="research",
                                  system="ExampleSystem", account_id="research-account",
                                  allocation_project_id="budget-example")


def test_encrypted_at_rest_and_wrong_key(registry, tmp_path, capfd):
    seed(registry)
    path = registry.storage.path
    content = path.read_bytes()
    assert not content.startswith(b"SQLite format 3")
    assert b"Research budget" not in content
    assert b"budget-example" not in content
    with sqlite3.connect(path) as plain:
        with pytest.raises(sqlite3.DatabaseError):
            plain.execute("SELECT * FROM sqlite_master").fetchall()
    wrong = tmp_path / "keys" / "wrong.key"
    generate_key(wrong)
    with pytest.raises(EncryptedDatabaseError):
        BudgetRegistry(path, wrong).check()
    assert path.read_bytes() == content
    assert str(path) not in capfd.readouterr().err
    registry.check()


def test_missing_key_driver_and_plaintext_never_fall_back(registry, tmp_path, monkeypatch):
    with pytest.raises(EncryptedDatabaseError):
        BudgetRegistry(registry.storage.path, tmp_path / "keys" / "missing").check()
    monkeypatch.setattr(encrypted_sqlite, "_driver", lambda: sqlite3)
    with pytest.raises(EncryptedDatabaseError, match="SQLCipher 4"):
        registry.check()
    assert registry.storage.path.read_bytes()[:16] != b"SQLite format 3\x00"


def test_driver_import_failure_is_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "sqlcipher3", None)
    with pytest.raises(EncryptedDatabaseError, match="driver is required"):
        encrypted_sqlite._driver()


def test_plaintext_is_rejected_unchanged(registry):
    path = registry.storage.path.parent / "plain.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE example (id INTEGER)")
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(EncryptedDatabaseError, match="Plaintext"):
        BudgetRegistry(path, registry.storage.key_file).check()
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["key-permissions", "key-symlink", "key-short", "key-fifo", "db-permissions", "db-symlink", "parent-permissions", "sidecar-symlink"])
def test_unsafe_storage_is_rejected(registry, kind, tmp_path):
    key, path = registry.storage.key_file, registry.storage.path
    if kind == "key-permissions":
        key.chmod(0o644)
    elif kind == "key-symlink":
        moved = key.with_suffix(".original")
        key.rename(moved)
        key.symlink_to(moved)
    elif kind == "key-short":
        key.write_bytes(b"short")
    elif kind == "key-fifo":
        key.unlink()
        os.mkfifo(key, mode=0o600)
    elif kind == "db-permissions":
        path.chmod(0o644)
    elif kind == "db-symlink":
        moved = path.with_suffix(".original")
        path.rename(moved)
        path.symlink_to(moved)
    elif kind == "sidecar-symlink":
        Path(str(path) + "-wal").symlink_to(tmp_path / "missing")
    else:
        path.parent.chmod(0o755)
    with pytest.raises(EncryptedDatabaseError):
        registry.check()


def test_no_implicit_creation_or_reinitialization(registry):
    missing = registry.storage.path.with_name("missing.db")
    with pytest.raises(EncryptedDatabaseError):
        BudgetRegistry(missing, registry.storage.key_file).check()
    assert not missing.exists()
    before = registry.storage.path.read_bytes()
    with pytest.raises(EncryptedDatabaseError):
        registry.initialize()
    assert registry.storage.path.read_bytes() == before
    key = registry.storage.key_file.read_bytes()
    with pytest.raises(EncryptedDatabaseError):
        generate_key(registry.storage.key_file)
    assert registry.storage.key_file.read_bytes() == key
    with pytest.raises(EncryptedDatabaseError, match="outside"):
        EncryptedSQLite(registry.storage.path, registry.storage.path.with_suffix(".key"))


def test_wal_backup_and_restore(registry, tmp_path):
    seed(registry)
    with registry.storage.connect() as writer:
        assert writer.execute("PRAGMA temp_store").fetchone()[0] == 2
        with writer:
            writer.execute("CREATE TABLE backup_probe (payload TEXT)")
            writer.execute("INSERT INTO backup_probe VALUES (?)", ("encrypted-canary-" * 2000,))
        wal = Path(str(registry.storage.path) + "-wal")
        assert wal.exists() and wal.stat().st_size > 0
        assert b"encrypted-canary" not in wal.read_bytes()
        backup = tmp_path / "backup" / "registry.db"
        registry.storage.backup(backup)
        restored = BudgetRegistry(backup, registry.storage.key_file)
        assert restored.check() == registry.check()
        assert restored.resolve(MANAGER, "research-system") == registry.resolve(MANAGER, "research-system")
        with restored.storage.connect(readonly=True) as conn:
            assert conn.execute("SELECT payload FROM backup_probe").fetchone()[0] == "encrypted-canary-" * 2000
        assert b"encrypted-canary" not in backup.read_bytes()
        with pytest.raises(EncryptedDatabaseError):
            registry.storage.backup(backup)
        restored.check()
    assert not list((tmp_path / "backup").glob("*.key"))


def test_corruption_is_detected(registry):
    seed(registry)
    content = bytearray(registry.storage.path.read_bytes())
    content[-100] ^= 1
    registry.storage.path.write_bytes(content)
    with pytest.raises(EncryptedDatabaseError):
        registry.check()


def test_shared_connections_and_conflicting_edits(registry):
    revision = seed(registry)
    second = BudgetRegistry(registry.storage.path, registry.storage.key_file)
    assert second.catalog(ADMIN)["revision"] == revision
    revision = second.save_budget(MANAGER, revision, id="research", label="Changed", system="ExampleSystem", enabled=True)
    with pytest.raises(RegistryConflict):
        registry.save_budget(MANAGER, revision - 1, id="research", label="Stale", system="ExampleSystem", enabled=True)
    assert registry.catalog(ADMIN)["budgets"][0]["label"] == "Changed"
    with registry.storage.connect(readonly=True) as conn:
        event = conn.execute("SELECT * FROM registry_history ORDER BY revision DESC LIMIT 1").fetchone()
        assert event["actor"] == MANAGER.principal
        assert '"label": "Research budget"' in event["before_json"]
        assert '"label": "Changed"' in event["after_json"]


def test_simultaneous_writers_do_not_lose_updates(registry):
    revision = seed(registry)
    barrier = Barrier(3)

    def edit(number):
        client = BudgetRegistry(registry.storage.path, registry.storage.key_file)
        barrier.wait(timeout=5)
        try:
            return client.save_budget(ADMIN, revision, id="research", label=f"Writer {number}", system="ExampleSystem", enabled=True)
        except RegistryConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(edit, range(3)))
    assert results.count("conflict") == 2
    assert results.count(revision + 1) == 1
    assert registry.check() == revision + 1


def test_roles_and_revocation(registry):
    revision = seed(registry)
    assert registry.resolve(MANAGER, "research-system")["budget_id"] == "research"
    for actor in (APPLICANT, STRANGER, RegistryActor("")):
        with pytest.raises(RegistryPermissionError):
            registry.resolve(actor, "research-system")
    with pytest.raises(RegistryPermissionError):
        registry.save_budget(APPLICANT, revision, id="research", label="Changed", system="ExampleSystem")
    with pytest.raises(RegistryPermissionError):
        registry.save_budget(MANAGER, revision, id="another", label="Other", system="ExampleSystem")
    with pytest.raises(RegistryPermissionError):
        registry.catalog(MANAGER)
    with pytest.raises(RegistryPermissionError):
        registry.save_connection(MANAGER, revision, id="new", label="New", server_url="https://example.org",
                                 project_path="group/project", token_env="RESULT_SERVER_GITLAB_TRIGGER_TOKEN")
    with pytest.raises(RegistryPermissionError):
        registry.set_manager(MANAGER, revision, budget_id="research", principal=APPLICANT.principal, assigned=True)
    registry.set_manager(ADMIN, revision, budget_id="research", principal=MANAGER.principal, assigned=False)
    with pytest.raises(RegistryPermissionError):
        registry.resolve(MANAGER, "research-system")


def test_disabled_and_expired_destinations(registry):
    revision = seed(registry)
    revision = registry.save_budget(MANAGER, revision, id="research", label="Research", system="ExampleSystem", enabled=True,
                                    valid_from="2026-01-01", valid_until="2026-12-31")
    assert registry.resolve(MANAGER, "research-system", today=date(2026, 12, 31))
    for today in (date(2025, 12, 31), date(2027, 1, 1)):
        with pytest.raises(RegistryError):
            registry.resolve(MANAGER, "research-system", today=today)
    registry.save_budget(MANAGER, revision, id="research", label="Research", system="ExampleSystem", enabled=False)
    with pytest.raises(RegistryError):
        registry.resolve(ADMIN, "research-system")


def test_multiple_budgets_share_system_and_connection(registry):
    revision = seed(registry)
    snapshot = registry.resolve(MANAGER, "research-system")
    revision = registry.save_budget(ADMIN, revision, id="second", label="Second", system="ExampleSystem", enabled=True)
    registry.save_destination(ADMIN, revision, id="second-system", budget_id="second", system="ExampleSystem",
                              account_id="research-account", allocation_project_id="second-budget")
    second = registry.resolve(ADMIN, "second-system")
    assert snapshot["system"] == second["system"]
    assert snapshot["connection_id"] == second["connection_id"]
    assert snapshot["route"]["allocation_project_id"] != second["route"]["allocation_project_id"]
    assert snapshot["registry_revision"] < second["registry_revision"]
    with pytest.raises(RegistryPermissionError):
        registry.resolve(MANAGER, "second-system")
    choices = registry.list_destinations(MANAGER)
    assert [row["id"] for row in choices["destinations"]] == ["research-system"]
    assert "account_name" not in choices["destinations"][0]
    assert "allocation_project_id" not in choices["destinations"][0]
    assert len(registry.list_destinations(ADMIN)["destinations"]) == 2
    assert registry.list_destinations(STRANGER)["destinations"] == []


def test_snapshot_is_not_rewritten_when_account_changes(registry):
    revision = seed(registry)
    original = registry.resolve(MANAGER, "research-system")
    registry.save_account(ADMIN, revision, id="research-account", label="Replacement", system="ExampleSystem",
                          connection_id="compute", build_tag="new-build", run_tag="new-run")
    current = registry.resolve(MANAGER, "research-system")
    assert current["route"]["run_tag"] == "new-run"
    assert original["route"]["run_tag"] == "example-run"
    assert current["registry_revision"] > original["registry_revision"]


@pytest.mark.parametrize("legacy_name", ["", "legacy-user"])
def test_retired_account_name_is_preserved_but_not_exposed(registry, legacy_name):
    revision = seed(registry)
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("UPDATE execution_accounts SET account_name=? WHERE id=?",
                         (legacy_name, "research-account"))
    registry.save_account(ADMIN, revision, id="research-account", label="Execution settings",
                          system="ExampleSystem", connection_id="compute", build_tag="", run_tag="new-run")
    with registry.storage.connect(readonly=True) as conn:
        assert conn.execute("SELECT account_name FROM execution_accounts WHERE id=?",
                            ("research-account",)).fetchone()[0] == legacy_name
    for catalog in (registry.catalog(ADMIN), registry.management_catalog(ADMIN)):
        assert "account_name" not in catalog["execution_accounts"][0]
    assert "account_name" not in registry.resolve(ADMIN, "research-system")


def test_identity_and_references_cannot_drift(registry):
    revision = seed(registry)
    with pytest.raises(RegistryError):
        registry.save_destination(ADMIN, revision, id="research-system", budget_id="other", system="ExampleSystem",
                                  account_id="research-account", allocation_project_id="example")
    with pytest.raises(RegistryError):
        registry.save_account(ADMIN, revision, id="research-account", label="Account", system="OtherSystem",
                              connection_id="compute", build_tag="build", run_tag="run")
    with pytest.raises(RegistryError):
        registry.save_destination(ADMIN, revision, id="new", budget_id="research", system="OtherSystem",
                                  account_id="research-account", allocation_project_id="example")
    with pytest.raises(RegistryError):
        registry.save_destination(ADMIN, revision, id="duplicate", budget_id="research", system="ExampleSystem",
                                  account_id="research-account", allocation_project_id="example")
    assert registry.check() == revision


def budget_system_values():
    return dict(budget_id="new-budget", destination_id="new-destination", label="New budget",
                valid_from="", valid_until="", system="ExampleSystem",
                account_id="research-account", allocation_project_id="example-allocation", enabled=True)


def test_budget_system_atomic_preview_and_apply(registry):
    revision = seed(registry)
    before = registry.management_catalog(ADMIN)
    values = budget_system_values()
    registry.save_budget_system(ADMIN, revision, **values, preview=True)
    assert registry.management_catalog(ADMIN) == before
    updated = registry.save_budget_system(ADMIN, revision, **values)
    assert updated > revision
    snapshot = registry.resolve(ADMIN, values["destination_id"])
    assert snapshot["budget_id"] == values["budget_id"]
    assert snapshot["registry_revision"] == updated
    assert snapshot["route"]["allocation_project_id"] == values["allocation_project_id"]
    assert registry.resolve(ADMIN, "research-system")["budget_id"] == "research"
    history = registry.management_catalog(ADMIN)["history"]
    assert {entry["entity_type"] for entry in history if entry["revision"] > revision} == {"budgets", "destinations"}


@pytest.mark.parametrize("budget_id", ["research", "new-budget"])
def test_budget_system_failed_destination_rolls_back_budget_and_history(registry, budget_id):
    revision = seed(registry)
    before = registry.management_catalog(ADMIN)
    values = budget_system_values()
    values.update(budget_id=budget_id, system="WrongSystem", label="Must not persist")
    with pytest.raises(RegistryError):
        registry.save_budget_system(ADMIN, revision, **values)
    assert registry.management_catalog(ADMIN) == before


def test_budget_system_authorization_identity_and_revision(registry):
    revision = seed(registry)
    values = budget_system_values()
    before = registry.management_catalog(ADMIN)
    for actor in (MANAGER, APPLICANT, STRANGER):
        with pytest.raises(RegistryPermissionError):
            registry.save_budget_system(actor, revision, **values)
    with pytest.raises(RegistryConflict):
        registry.save_budget_system(ADMIN, revision - 1, **values)
    values["destination_id"] = "research-system"
    with pytest.raises(RegistryError):
        registry.save_budget_system(ADMIN, revision, **values)
    assert registry.management_catalog(ADMIN) == before


def test_single_system_budget_and_single_enabled_state(registry):
    revision = seed(registry)
    revision = registry.save_account(ADMIN, revision, id="other-account", label="Other account", system="OtherSystem",
                                     connection_id="compute", build_tag="", run_tag="other-run")
    before = registry.management_catalog(ADMIN)
    with pytest.raises(RegistryError):
        registry.save_destination(ADMIN, revision, id="another-system", budget_id="research", system="OtherSystem",
                                  account_id="other-account", allocation_project_id="example-allocation")
    for actor in (ADMIN, MANAGER):
        with pytest.raises(RegistryError):
            registry.save_budget(actor, revision, id="research", label="Research", system="OtherSystem")
    assert registry.management_catalog(ADMIN) == before
    assert "enabled" not in before["destinations"][0]
    assert "role" not in before["budget_managers"][0]
    revision = registry.save_budget(MANAGER, revision, id="research", label="Research", system="ExampleSystem", enabled=False)
    with pytest.raises(RegistryError):
        registry.resolve(ADMIN, "research-system")
    registry.save_budget(MANAGER, revision, id="research", label="Research", system="ExampleSystem", enabled=True)
    assert registry.resolve(MANAGER, "research-system")


def setup_values():
    return dict(budget_id="new-budget", destination_id="new-destination", label="New budget", enabled=True,
                valid_from="", valid_until="", system="ExampleSystem", allocation_project_id="example-allocation",
                account_id="new-account", build_tag="example-build", run_tag="example-run",
                connection_id="gitlab:example", new_account=True)


def test_complete_budget_setup_is_atomic_and_reuses_shared_records(registry, configured_target):
    values = setup_values()
    registry.save_budget_setup(ADMIN, 0, **values, preview=True)
    assert registry.check() == 0
    with registry.storage.connect(readonly=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 0
    revision = registry.save_budget_setup(ADMIN, 0, **values)
    snapshot = registry.resolve(ADMIN, values["destination_id"])
    assert snapshot["target"]["project_path"] == "group/project"
    assert snapshot["route"]["run_tag"] == values["run_tag"]
    before = registry.catalog(ADMIN)
    values.update(new_account=False, budget_id="another-budget", destination_id="another-destination")
    registry.save_budget_setup(ADMIN, revision, **values)
    after = registry.management_catalog(ADMIN)
    assert after["connections"] == before["connections"]
    assert after["execution_accounts"] == before["execution_accounts"]
    assert len(after["budgets"]) == len(before["budgets"]) + 1
    assert {item["entity_type"] for item in after["history"] if item["revision"] > revision} == {"budgets", "destinations"}


@pytest.mark.parametrize("field,value", [("run_tag", "invalid tag"), ("allocation_project_id", "invalid allocation"),
                                         ("connection_id", "missing")])
def test_setup_failure_never_leaves_partial_connection_account_or_budget(registry, configured_target, field, value):
    values = setup_values()
    values[field] = value
    with pytest.raises(RegistryError):
        registry.save_budget_setup(ADMIN, 0, **values)
    catalog = registry.management_catalog(ADMIN)
    assert catalog["revision"] == 0
    assert all(not catalog[key] for key in ("budgets", "destinations", "execution_accounts", "history"))
    with registry.storage.connect(readonly=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 0


def test_setup_cannot_bypass_scope_modes_or_revision(registry, configured_target):
    revision = seed(registry)
    values = setup_values()
    before = registry.management_catalog(ADMIN)
    for actor in (MANAGER, APPLICANT):
        with pytest.raises(RegistryPermissionError):
            registry.save_budget_setup(actor, revision, **values)
    with pytest.raises(RegistryConflict):
        registry.save_budget_setup(ADMIN, revision - 1, **values)
    for changes in ({"new_account": False}, {"new_account": "false"},
                    {"connection_id": "missing"}, {"account_id": "research-account"}):
        with pytest.raises(RegistryError):
            registry.save_budget_setup(ADMIN, revision, **{**values, **changes})
    assert registry.management_catalog(ADMIN) == before


def test_invalid_budget_edit_rolls_back_changes_to_shared_records(registry):
    revision = seed(registry)
    values = setup_values()
    values.update(new_account=False, account_id="research-account", connection_id="compute",
                  budget_id="research", destination_id="new-destination", run_tag="changed-run")
    before = registry.management_catalog(ADMIN)
    with pytest.raises(RegistryError):
        registry.save_budget_setup(ADMIN, revision, **values)
    assert registry.management_catalog(ADMIN) == before


def test_configured_target_is_a_reference_not_a_configuration_copy(registry, configured_target, monkeypatch):
    registry.save_budget_setup(ADMIN, 0, **setup_values())
    with registry.storage.connect(readonly=True) as conn:
        stored = dict(conn.execute("SELECT * FROM connections").fetchone())
    assert stored["target_id"] == "example"
    assert stored["server_url"] == stored["project_path"] == stored["token_env"] == ""
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", "example=other.example.org/group/replacement")
    snapshot = registry.resolve(ADMIN, "new-destination")
    assert snapshot["target"] == {"server_url": "https://other.example.org", "project_path": "group/replacement"}
    assert snapshot["route"]["id_token_audience"] == "https://other.example.org"
    monkeypatch.delenv("RESULT_SERVER_GITLAB_TARGETS")
    assert not registry.catalog(ADMIN)["connections"][0]["available"]
    with pytest.raises(RegistryError, match="unavailable"):
        registry.resolve(ADMIN, "new-destination")


def test_budget_edit_preserves_custom_audience(registry, configured_target):
    revision = seed(registry)
    revision = registry.save_account(ADMIN, revision, id="research-account", label="Runner settings",
                                     system="ExampleSystem", connection_id="compute", build_tag="", run_tag="run",
                                     id_token_audience="https://runner.example.org")
    values = {**setup_values(), "new_account": False, "account_id": "research-account", "connection_id": "compute"}
    revision = registry.save_budget_setup(ADMIN, revision, **values)
    assert registry.resolve(ADMIN, "new-destination")["route"]["id_token_audience"] == "https://runner.example.org"
    before = registry.management_catalog(ADMIN)
    with pytest.raises(RegistryError, match="custom audience"):
        registry.save_budget_setup(ADMIN, revision, **{**values, "connection_id": configured_target})
    assert registry.management_catalog(ADMIN) == before


@pytest.mark.parametrize("target", ["bad target", "example=example.org/group/repo?token=value",
                                  "example=example.org/group/repo#fragment", "example=user:password@example.org/group/repo"])
def test_invalid_target_configuration_is_sanitized(registry, monkeypatch, target):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", target)
    with pytest.raises(RegistryError, match="^GitLab target configuration is invalid$"):
        registry.catalog(ADMIN)


def legacy_empty_registry(registry):
    """Recreate the version-1 prototype schema in an encrypted fixture only."""
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("ALTER TABLE connections DROP COLUMN target_id")
            conn.execute("ALTER TABLE budgets DROP COLUMN system")
            conn.execute("ALTER TABLE budget_managers RENAME TO budget_members")
            conn.execute("ALTER TABLE budget_members ADD COLUMN role TEXT NOT NULL DEFAULT 'manager' CHECK(role IN ('manager','operator'))")
            conn.execute("DROP TABLE destinations")
            conn.execute("""CREATE TABLE destinations (
                id TEXT PRIMARY KEY, budget_id TEXT NOT NULL REFERENCES budgets(id), system TEXT NOT NULL,
                account_id TEXT NOT NULL REFERENCES execution_accounts(id), allocation_project_id TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), UNIQUE(budget_id, system))""")
            conn.execute("UPDATE registry_meta SET schema_version=1")


def test_empty_prototype_migration_is_explicit_and_backed_up(registry, tmp_path):
    legacy_empty_registry(registry)
    with pytest.raises(RegistryError, match="migration required"):
        registry.check()
    backup = tmp_path / "backup" / "prototype.db"
    assert main(["migrate-empty", "--database", str(registry.storage.path), "--key-file", str(registry.storage.key_file),
                 "--destination", str(backup)]) == 0
    assert registry.check() == 0
    old = BudgetRegistry(backup, registry.storage.key_file)
    with old.storage.connect(readonly=True) as conn:
        assert conn.execute("SELECT schema_version FROM registry_meta").fetchone()[0] == 1
    assert not backup.read_bytes().startswith(b"SQLite format 3")
    seed(registry)
    assert registry.resolve(MANAGER, "research-system")


def test_empty_version_two_migration(registry, tmp_path):
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("ALTER TABLE connections DROP COLUMN target_id")
            conn.execute("UPDATE registry_meta SET schema_version=2")
    backup = tmp_path / "backup" / "version-two.db"
    assert main(["migrate-empty", "--database", str(registry.storage.path), "--key-file", str(registry.storage.key_file),
                 "--destination", str(backup)]) == 0
    seed(registry)
    assert registry.resolve(MANAGER, "research-system")


@pytest.mark.parametrize("state", ["data", "revision", "current-schema"])
def test_migration_never_discards_existing_data(registry, state):
    if state != "current-schema":
        legacy_empty_registry(registry)
        with registry.storage.connect() as conn:
            with conn:
                if state == "data":
                    conn.execute("INSERT INTO budgets VALUES ('existing','Existing',0,'','')")
                else:
                    conn.execute("UPDATE registry_meta SET revision=1")
    with registry.storage.connect(readonly=True) as conn:
        schema = [tuple(row) for row in conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name")]
        data = [tuple(row) for row in conn.execute("SELECT * FROM budgets")]
    with pytest.raises(RegistryError):
        registry.migrate_empty()
    with registry.storage.connect(readonly=True) as conn:
        assert [tuple(row) for row in conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name")] == schema
        assert [tuple(row) for row in conn.execute("SELECT * FROM budgets")] == data


@pytest.mark.parametrize("start,end", [("invalid", ""), ("2026-12-31", "2026-01-01"), (None, "")])
def test_invalid_dates(registry, start, end):
    with pytest.raises(RegistryError):
        registry.save_budget(ADMIN, 0, id="research", label="Research", system="ExampleSystem", valid_from=start, valid_until=end)


@pytest.mark.parametrize("field,value", [("server_url", "http://example.org"), ("server_url", "https://user:pass@example.org"),
                                         ("token_env", "arbitrary_env"), ("project_path", "not-a-project")])
def test_invalid_connections(registry, field, value):
    args = dict(id="compute", label="Compute", server_url="https://example.org", project_path="group/project",
                token_env="RESULT_SERVER_GITLAB_TRIGGER_TOKEN")
    args[field] = value
    with pytest.raises(RegistryError):
        registry.save_connection(ADMIN, 0, **args)
    assert registry.check() == 0


def test_schema_mismatch_is_not_auto_migrated(registry):
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("UPDATE registry_meta SET schema_version=999")
    with pytest.raises(RegistryError, match="migration required"):
        registry.check()
    with registry.storage.connect(readonly=True) as conn:
        assert conn.execute("SELECT schema_version FROM registry_meta").fetchone()[0] == 999


def test_cli_reports_no_keys_or_data(registry, capsys):
    key = str(registry.storage.key_file)
    path = str(registry.storage.path)
    assert main(["check", "--database", path, "--key-file", key]) == 0
    assert main(["init", "--database", path, "--key-file", key]) == 1
    output = capsys.readouterr().out
    assert key not in output and path not in output
    assert registry.storage.key_file.read_bytes().hex() not in output


@pytest.mark.parametrize("actor", [RegistryActor(""), RegistryActor("user", is_admin="false"), RegistryActor(None)])
def test_invalid_identity_is_rejected(registry, actor):
    with pytest.raises(RegistryPermissionError):
        registry.catalog(actor)
    with pytest.raises(RegistryPermissionError):
        registry.list_destinations(actor)


def test_readonly_connections_cannot_write(registry):
    with pytest.raises(EncryptedDatabaseError):
        with registry.storage.connect(readonly=True) as conn:
            conn.execute("DELETE FROM registry_meta")
    assert registry.check() == 0
