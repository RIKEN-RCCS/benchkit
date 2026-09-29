"""Managed-system scopes, canonical execution targets and populated migration."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

pytest.importorskip("sqlcipher3")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_budget_registry import registry, configured_target, seed, ADMIN, MANAGER, STRANGER  # noqa: E402,F401
from utils.budget_registry import BudgetRegistry, RegistryError, RegistryPermissionError, RegistryConflict  # noqa: E402
from budget_db import main  # noqa: E402
from test_execution_routes import routes  # noqa: E402


def group_values():
    return dict(budget_id="group-budget", label="Research resources", system="Example Computing Center",
                enabled=True, valid_from="", valid_until="", allocation_project_id="",
                account_id="common-settings", connection_id="gitlab:example", build_tag="", run_tag="shared-run",
                new_account=True, targets=[dict(id="target-a", system="Example_A", account_id=""),
                                           dict(id="target-b", system="Example_B", account_id="")])


def version_three(registry):
    """Downgrade only fixture storage to the exact legacy destination constraint."""
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("DROP TABLE budget_defaults")
            conn.execute("ALTER TABLE destinations RENAME TO destinations_old")
            conn.execute("""CREATE TABLE destinations (
                id TEXT PRIMARY KEY, budget_id TEXT NOT NULL UNIQUE REFERENCES budgets(id),
                system TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES execution_accounts(id),
                allocation_project_id TEXT NOT NULL)""")
            conn.execute("INSERT INTO destinations SELECT * FROM destinations_old")
            conn.execute("DROP TABLE destinations_old")
            conn.execute("UPDATE registry_meta SET schema_version=3")


def test_group_preview_and_canonical_resolution(registry, configured_target):
    values = group_values()
    before = registry.catalog(ADMIN)
    registry.save_budget_group(ADMIN, 0, **values, preview=True)
    assert registry.catalog(ADMIN) == before
    revision = registry.save_budget_group(ADMIN, 0, **values)
    catalog = registry.catalog(ADMIN)
    assert len(catalog["budgets"]) == 1
    assert len(catalog["execution_accounts"]) == 1
    assert len(catalog["destinations"]) == 2
    revision = registry.set_manager(ADMIN, revision, budget_id=values["budget_id"], principal=MANAGER.principal, assigned=True)
    for target in values["targets"]:
        resolved = registry.resolve(MANAGER, target["id"])
        assert resolved["system"] == target["system"]
        assert resolved["managed_system"] == values["system"]
        assert resolved["route"]["systems"] == [target["system"]]
        assert resolved["route"]["run_tag"] == "shared-run"
        assert resolved["route"]["allocation_project_id"] == ""
        ci_routes = routes.resolve_routes(
            {"version": 1, "target": resolved["target"], "routes": [resolved["route"]]},
            {"Example_A": "native", "Example_B": "native"},
            {"CI_SERVER_URL": resolved["target"]["server_url"], "CI_PROJECT_PATH": resolved["target"]["project_path"]},
        )
        assert set(ci_routes) == {target["system"]}
        with pytest.raises(RegistryPermissionError):
            registry.resolve(STRANGER, target["id"])
    assert len(registry.list_destinations(MANAGER)["destinations"]) == 2
    registry.save_budget(MANAGER, revision, id=values["budget_id"], label="Paused", system=values["system"], enabled=False)
    for target in values["targets"]:
        with pytest.raises(RegistryError):
            registry.resolve(ADMIN, target["id"])


def test_target_override_can_use_another_connection_and_tags(registry, configured_target):
    values = group_values()
    revision = registry.save_budget_group(ADMIN, 0, **values)
    revision = registry.save_connection(ADMIN, revision, id="alternate", label="Alternate",
                                       server_url="https://other.example.org", project_path="group/compute",
                                       token_env="RESULT_SERVER_GITLAB_TRIGGER_TOKEN_OTHER")
    revision = registry.save_account(ADMIN, revision, id="other-settings", label="Other target settings",
                                    system=values["system"], connection_id="alternate", build_tag="other-build", run_tag="other-run")
    values["new_account"] = False
    values["targets"][0]["account_id"] = "other-settings"
    registry.save_budget_group(ADMIN, revision, **values)
    first = registry.resolve(ADMIN, "target-a")
    second = registry.resolve(ADMIN, "target-b")
    assert first["target"]["server_url"] == "https://other.example.org"
    assert first["route"]["run_tag"] == "other-run"
    assert second["route"]["run_tag"] == "shared-run"
    assert registry.catalog(ADMIN)["budget_defaults"][0]["account_id"] == "common-settings"


def test_removal_preserves_other_ids_managers_and_audits_revocation(registry, configured_target):
    values = group_values()
    revision = registry.save_budget_group(ADMIN, 0, **values)
    revision = registry.set_manager(ADMIN, revision, budget_id=values["budget_id"], principal=MANAGER.principal, assigned=True)
    original = registry.resolve(MANAGER, "target-b")
    values.update(new_account=False, allocation_project_id="new-allocation", targets=values["targets"][:1])
    registry.save_budget_group(ADMIN, revision, **values)
    assert registry.resolve(MANAGER, "target-a")["route"]["allocation_project_id"] == "new-allocation"
    with pytest.raises(RegistryPermissionError):
        registry.resolve(MANAGER, "target-b")
    assert original["route"]["allocation_project_id"] == ""
    history = registry.management_catalog(ADMIN)["history"]
    assert any(row["entity_id"] == "target-b" and row["after_json"] == "null" for row in history)


@pytest.mark.parametrize("change", ["duplicate", "bad-system", "bad-settings", "wrong-scope", "empty", "rebind"])
def test_group_failures_roll_back_all_changes(registry, configured_target, change):
    revision = seed(registry)
    values = group_values()
    if change == "duplicate":
        values["targets"].append(deepcopy(values["targets"][0]))
    elif change == "bad-system":
        values["targets"][1]["system"] = "Invalid target"
    elif change == "bad-settings":
        values["targets"][1]["account_id"] = "missing"
    elif change == "wrong-scope":
        values["targets"][1]["account_id"] = "research-account"
    elif change == "empty":
        values["targets"] = []
    else:
        values["targets"][1]["id"] = "research-system"
    before = registry.management_catalog(ADMIN)
    with pytest.raises(RegistryError):
        registry.save_budget_group(ADMIN, revision, **values)
    assert registry.management_catalog(ADMIN) == before


def test_group_permission_revision_and_shared_allocation(registry, configured_target):
    values = group_values()
    revision = registry.save_budget_group(ADMIN, 0, **values)
    values["new_account"] = False
    with pytest.raises(RegistryPermissionError):
        registry.save_budget_group(MANAGER, revision, **values)
    with pytest.raises(RegistryConflict):
        registry.save_budget_group(ADMIN, revision - 1, **values)
    with pytest.raises(RegistryError, match="allocation"):
        registry.save_destination(ADMIN, revision, id="target-a", budget_id=values["budget_id"],
                                  system="Example_A", account_id="common-settings", allocation_project_id="different")
    values["allocation_project_id"] = "common-allocation"
    registry.save_budget_group(ADMIN, revision, **values)
    assert {row["allocation_project_id"] for row in registry.catalog(ADMIN)["destinations"]} == {"common-allocation"}


def test_populated_migration_preserves_records_and_encrypted_backup(registry, tmp_path):
    seed(registry)
    version_three(registry)
    before = registry.management_catalog(ADMIN)
    old_snapshot = registry.resolve(MANAGER, "research-system")
    backup = tmp_path / "backup" / "before-targets.db"
    assert main(["migrate-targets", "--database", str(registry.storage.path),
                 "--key-file", str(registry.storage.key_file), "--destination", str(backup)]) == 0
    after = registry.management_catalog(ADMIN)
    assert after == {**before, "schema_version": 4}
    assert registry.resolve(MANAGER, "research-system") == old_snapshot
    assert not backup.read_bytes().startswith(b"SQLite format 3")
    restored = BudgetRegistry(backup, registry.storage.key_file)
    assert restored.management_catalog(ADMIN) == before
    with pytest.raises(RegistryError):
        registry.migrate_targets()


def test_version_three_reads_edits_and_rejects_groups_without_migration(registry, configured_target):
    revision = seed(registry)
    version_three(registry)
    before = registry.catalog(ADMIN)
    with pytest.raises(RegistryError, match="explicit database migration"):
        registry.save_budget_group(ADMIN, revision, **group_values())
    assert registry.catalog(ADMIN) == before
    registry.save_budget(MANAGER, revision, id="research", label="Updated", system="ExampleSystem", enabled=True)
    assert registry.resolve(MANAGER, "research-system")["system"] == "ExampleSystem"
    assert registry.catalog(ADMIN)["schema_version"] == 3


def test_migration_refuses_inconsistent_legacy_records_without_changes(registry):
    seed(registry)
    version_three(registry)
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("UPDATE destinations SET system='WrongSystem'")
    before = registry.catalog(ADMIN)
    with pytest.raises(RegistryError, match="inconsistent"):
        registry.migrate_targets()
    assert registry.catalog(ADMIN) == before
