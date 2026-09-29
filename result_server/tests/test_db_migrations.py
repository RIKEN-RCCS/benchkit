"""One-instance encrypted migrations, rollback and explicit CLI selection."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from threading import Event

import pytest

pytest.importorskip("sqlcipher3")

from test_budget_registry import registry, seed, ADMIN, MANAGER, legacy_empty_registry  # noqa: E402,F401
from test_budget_groups import version_three  # noqa: E402
from utils.budget_registry import BudgetRegistry  # noqa: E402
from utils.budget_migrations import BudgetMigrationBackend  # noqa: E402
from utils.db_migrations import EncryptedSQLiteMigrator, MigrationError  # noqa: E402
from utils.encrypted_sqlite import EncryptedDatabaseError  # noqa: E402
from db import main  # noqa: E402


def runner_for(registry):
    return EncryptedSQLiteMigrator(BudgetMigrationBackend(registry.storage.path, registry.storage.key_file))


def migrate(runner, backup, **overrides):
    state = runner.status()
    options = dict(backup=backup, expected_version=state["schema_version"], expected_revision=state["revision"],
                   expected_instance=state["instance_id"])
    options.update(overrides)
    return runner.migrate(**options)


def test_plan_is_read_only_and_migration_preserves_data(registry, tmp_path):
    revision = seed(registry)
    version_three(registry)
    before = registry.management_catalog(ADMIN)
    runner = runner_for(registry)
    state = runner.status()
    plan = runner.plan()
    assert plan["instance_id"] == state["instance_id"]
    assert plan["steps"] == [dict(id="budget-0003-execution-targets", source=3, target=4)]
    assert plan["exclusive_writes"] and plan["backup_required"]
    assert registry.management_catalog(ADMIN) == before
    with registry.storage.connect(readonly=True) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='db_migration_history'").fetchone()
    backup = tmp_path / "backup" / "original.db"
    result = migrate(runner, backup)
    assert result["verified"] and result["schema_version"] == 4 and result["revision"] == revision
    assert len(result["migrations"]) == 1
    assert registry.management_catalog(ADMIN) == {**before, "schema_version": 4}
    restored = BudgetRegistry(backup, registry.storage.key_file)
    assert restored.management_catalog(ADMIN) == before
    assert not backup.read_bytes().startswith(b"SQLite format 3")
    assert registry.resolve(MANAGER, "research-system")["route"] == restored.resolve(MANAGER, "research-system")["route"]
    assert not runner.plan()["steps"]
    assert not migrate(runner, tmp_path / "backup" / "unused.db")["applied"]
    assert not (tmp_path / "backup" / "unused.db").exists()


def test_rehearsal_changes_only_the_copy(registry, tmp_path):
    seed(registry)
    version_three(registry)
    runner = runner_for(registry)
    before = registry.management_catalog(ADMIN)
    copy = tmp_path / "backup" / "rehearsal.db"
    result = runner.rehearse(destination=copy)
    assert result["rehearsal"] and result["source_version"] == 3 and result["schema_version"] == 4
    assert result["instance_id"] != runner.status()["instance_id"]
    assert registry.management_catalog(ADMIN) == before
    assert BudgetRegistry(copy, registry.storage.key_file).catalog(ADMIN)["schema_version"] == 4
    assert not copy.read_bytes().startswith(b"SQLite format 3")
    assert copy.stat().st_mode & 0o777 == 0o600
    with pytest.raises(EncryptedDatabaseError):
        runner.rehearse(destination=copy)


@pytest.mark.parametrize("override", [dict(expected_version=99), dict(expected_revision=-1), dict(expected_instance="other")])
def test_stale_or_wrong_instance_plan_cannot_write(registry, tmp_path, override):
    seed(registry)
    version_three(registry)
    before = registry.management_catalog(ADMIN)
    backup = tmp_path / "backup" / "must-not-exist.db"
    with pytest.raises(MigrationError, match="plan again"):
        migrate(runner_for(registry), backup, **override)
    assert not backup.exists()
    assert registry.management_catalog(ADMIN) == before


def test_another_database_with_same_schema_and_revision_is_not_the_same_target(registry, tmp_path):
    seed(registry)
    version_three(registry)
    other_path = tmp_path / "backup" / "independent.db"
    registry.storage.backup(other_path)
    other = BudgetRegistry(other_path, registry.storage.key_file)
    source = runner_for(registry).status()
    with pytest.raises(MigrationError):
        migrate(runner_for(other), tmp_path / "backup" / "wrong-target-backup.db", expected_instance=source["instance_id"])
    assert other.catalog(ADMIN)["schema_version"] == 3
    assert registry.catalog(ADMIN)["schema_version"] == 3


def test_failed_migration_rolls_back_schema_data_and_history(registry, tmp_path):
    seed(registry)
    version_three(registry)
    runner = runner_for(registry)
    before = registry.management_catalog(ADMIN)
    original = runner.backend.migrations[-1]

    def fail(conn):
        original.apply(conn)
        conn.execute("UPDATE budgets SET label='must rollback'")
        raise MigrationError("Injected failure")

    runner.backend.migrations = (*runner.backend.migrations[:-1], replace(original, apply=fail))
    backup = tmp_path / "backup" / "before-failure.db"
    with pytest.raises(MigrationError):
        migrate(runner, backup)
    assert registry.management_catalog(ADMIN) == before
    assert BudgetRegistry(backup, registry.storage.key_file).management_catalog(ADMIN) == before
    assert runner.status()["migrations"] == []


def test_verification_failure_rolls_back_successful_step(registry, tmp_path, monkeypatch):
    seed(registry)
    version_three(registry)
    before = registry.management_catalog(ADMIN)
    runner = runner_for(registry)

    def fail(conn):
        raise MigrationError("Verification failed")

    monkeypatch.setattr(runner.backend, "verify", fail)
    with pytest.raises(MigrationError):
        migrate(runner, tmp_path / "backup" / "verify-failure.db")
    assert registry.management_catalog(ADMIN) == before
    assert runner.status()["migrations"] == []


def test_backup_is_under_write_lock_and_second_migrator_is_rejected(registry, tmp_path, monkeypatch):
    seed(registry)
    version_three(registry)
    runner = runner_for(registry)
    state = runner.status()
    started, release = Event(), Event()
    original_backup = runner.backend.storage.backup

    def paused_backup(path):
        started.set()
        assert release.wait(4)
        original_backup(path)

    monkeypatch.setattr(runner.backend.storage, "backup", paused_backup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(migrate, runner, tmp_path / "backup" / "first.db")
        assert started.wait(4)
        try:
            with pytest.raises(EncryptedDatabaseError):
                with registry.storage.connect() as conn:
                    conn.execute("PRAGMA busy_timeout=0")
                    conn.execute("BEGIN IMMEDIATE")
            second = pool.submit(migrate, runner_for(registry), tmp_path / "backup" / "second.db",
                                 expected_version=state["schema_version"], expected_revision=state["revision"])
        finally:
            release.set()
        assert first.result(timeout=8)["schema_version"] == 4
        with pytest.raises(MigrationError):
            second.result(timeout=8)
    assert not (tmp_path / "backup" / "second.db").exists()


def test_migration_never_overwrites_backup_or_source(registry, tmp_path):
    seed(registry)
    version_three(registry)
    runner = runner_for(registry)
    before = registry.catalog(ADMIN)
    for path in (registry.storage.path, registry.storage.key_file):
        with pytest.raises(EncryptedDatabaseError):
            migrate(runner, path)
    assert registry.catalog(ADMIN) == before


def test_numbered_chain_upgrades_only_empty_prototype(registry, tmp_path):
    legacy_empty_registry(registry)
    runner = runner_for(registry)
    assert len(runner.plan()["steps"]) == 2
    assert not runner.status()["readable"]
    result = migrate(runner, tmp_path / "backup" / "prototype.db")
    assert result["schema_version"] == 4 and len(result["migrations"]) == 2
    seed(registry)
    assert runner.verify()["verified"]


def test_wrong_database_kind_is_refused(registry):
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("DROP TABLE registry_history")
    with pytest.raises(MigrationError, match="not a recognized"):
        runner_for(registry).status()


def cli_args(registry, command):
    return [command, "--kind", "budget", "--database", str(registry.storage.path),
            "--key-file", str(registry.storage.key_file)]


def test_cli_status_plan_verify_and_explicit_migrate(registry, tmp_path, capsys):
    seed(registry)
    version_three(registry)
    for command in ("status", "plan", "verify"):
        assert main(cli_args(registry, command)) == 0
        output = capsys.readouterr().out
        state = json.loads(output)
        assert str(registry.storage.path) not in output
        assert str(registry.storage.key_file) not in output
        assert "budget-example" not in output and ADMIN.principal not in output
    args = cli_args(registry, "migrate") + ["--backup", str(tmp_path / "backup" / "cli.db"),
             "--expect-version", str(state["schema_version"]), "--expect-revision", str(state["revision"]),
             "--expect-instance", state["instance_id"], "--confirm"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["verified"]
    assert main(args) == 1
    assert "Database changed" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["status"], ["status", "--kind", "all"], ["migrate"], ["rehearse"]])
def test_cli_requires_explicit_target_and_migration_arguments(registry, args):
    with pytest.raises(SystemExit) as exc:
        if len(args) == 1 and args[0] != "status":
            main(cli_args(registry, args[0]))
        else:
            main(args)
    assert exc.value.code == 2


def test_bad_key_error_contains_no_paths_or_secrets(registry, tmp_path, capsys):
    args = cli_args(registry, "status")
    args[-1] = str(tmp_path / "keys" / "absent-secret.key")
    assert main(args) == 1
    output = capsys.readouterr().out
    assert "absent-secret" not in output and str(tmp_path) not in output


def test_backup_failure_leaves_source_and_history_unchanged(registry, tmp_path, monkeypatch):
    seed(registry)
    version_three(registry)
    runner = runner_for(registry)
    before = registry.management_catalog(ADMIN)

    def fail(path):
        raise EncryptedDatabaseError("Backup unavailable")

    monkeypatch.setattr(runner.backend.storage, "backup", fail)
    with pytest.raises(EncryptedDatabaseError):
        migrate(runner, tmp_path / "backup" / "failed.db")
    assert registry.management_catalog(ADMIN) == before
    assert not runner.status()["migrations"]


def test_unsupported_schema_is_reported_but_not_copied_or_migrated(registry, tmp_path):
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("UPDATE registry_meta SET schema_version=999")
    runner = runner_for(registry)
    assert not runner.status()["readable"] and not runner.status()["writable"]
    copy = tmp_path / "backup" / "must-not-exist.db"
    with pytest.raises(MigrationError):
        runner.rehearse(destination=copy)
    assert not copy.exists()
    with pytest.raises(MigrationError):
        runner.verify()


def test_explicit_database_ignores_other_environment_database(registry, tmp_path, monkeypatch, capsys):
    seed(registry)
    version_three(registry)
    isolated_path = tmp_path / "backup" / "isolated.db"
    registry.storage.backup(isolated_path)
    isolated = BudgetRegistry(isolated_path, registry.storage.key_file)
    before = isolated.management_catalog(ADMIN)
    monkeypatch.setenv("RESULT_SERVER_BUDGET_DB_PATH", str(isolated_path))
    assert main(cli_args(registry, "rehearse") + ["--destination", str(tmp_path / "backup" / "selected-copy.db")]) == 0
    assert json.loads(capsys.readouterr().out)["rehearsal"]
    assert isolated.management_catalog(ADMIN) == before
    assert registry.catalog(ADMIN)["schema_version"] == 3
