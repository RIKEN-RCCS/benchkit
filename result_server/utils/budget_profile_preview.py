"""Read-only structural comparison; never authorizes or binds a profile."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .budget_registry import RegistryError
from .gitlab_pipeline import configured_gitlab_targets


def read_profiles(database):
    """Avoid ExecutionProfileStore readers, which may migrate their database."""
    try:
        uri = Path(database).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            profiles = [dict(row) for row in conn.execute(
                "SELECT id, enabled, status, allocation_project_id, valid_from, valid_until "
                "FROM execution_profiles ORDER BY id")]
            scopes = list(conn.execute(
                "SELECT profile_id, value FROM execution_profile_scopes "
                "WHERE scope_type='system' ORDER BY value"))
            triggers = [dict(row) for row in conn.execute(
                "SELECT id, profile_id, enabled, gitlab_target FROM trigger_definitions ORDER BY id")]
    except (OSError, ValueError, sqlite3.Error):
        raise RegistryError("Cannot read the profile database; check its path, permissions and schema") from None
    for profile in profiles:
        profile["systems"] = [row["value"] for row in scopes if row["profile_id"] == profile["id"]]
        profile["triggers"] = [row for row in triggers if row["profile_id"] == profile["id"]]
    return profiles


def _state_reasons(record, prefix, today):
    reasons = []
    if not record["enabled"]:
        reasons.append(prefix + "_disabled")
    if record["valid_from"] and today < record["valid_from"]:
        reasons.append(prefix + "_not_yet_valid")
    if record["valid_until"] and today > record["valid_until"]:
        reasons.append(prefix + "_expired")
    return reasons


def compare_profiles(catalog, profiles, *, default_target="", today=None):
    today = today or datetime.now(timezone.utc).date().isoformat()
    budgets = {row["id"]: row for row in catalog["budgets"]}
    accounts = {row["id"]: row for row in catalog["execution_accounts"]}
    connections = {row["id"]: row for row in catalog["connections"]}
    targets = {row["target_id"]: row for row in catalog["connections"]
               if row["target_id"] and row["available"]}
    rows = []
    for profile in profiles:
        for system in profile["systems"] or [""]:
            for trigger in profile["triggers"] or [None]:
                reasons = _state_reasons(profile, "profile", today)
                if profile["status"] != "approved":
                    reasons.append("profile_not_approved")
                target_id = (trigger["gitlab_target"] or default_target) if trigger else ""
                target = targets.get(target_id)
                if trigger and not trigger["enabled"]:
                    reasons.append("trigger_disabled")
                if trigger is None:
                    reasons.append("existing_target_unknown")
                elif target is None:
                    reasons.append("existing_target_unavailable")
                explicit_system = bool(system) and not any(char in system for char in "*?[")
                if not explicit_system:
                    reasons.append("system_scope_unresolved")
                candidates = []
                for destination in sorted(catalog["destinations"], key=lambda item: item["id"]):
                    if not explicit_system or destination["system"] != system:
                        continue
                    budget = budgets[destination["budget_id"]]
                    account = accounts[destination["account_id"]]
                    connection = connections.get(account["connection_id"])
                    issues = _state_reasons(budget, "budget", today)
                    if account["system"] != budget["system"]:
                        issues.append("managed_system_mismatch")
                    if catalog["schema_version"] == 3 and system != budget["system"]:
                        issues.append("legacy_system_mismatch")
                    if not connection or not connection["available"]:
                        issues.append("connection_unavailable")
                    elif target is not None and any(connection[key] != target[key]
                                                    for key in ("server_url", "project_path")):
                        issues.append("target_mismatch")
                    allocation = profile["allocation_project_id"]
                    if not allocation:
                        issues.append("existing_allocation_unspecified")
                    elif allocation != destination["allocation_project_id"]:
                        issues.append("allocation_mismatch")
                    candidates.append(dict(destination_id=destination["id"], budget_id=budget["id"],
                                           managed_system=budget["system"], reasons=issues))
                if explicit_system and not candidates:
                    reasons.append("no_registered_destination")
                if len(candidates) > 1:
                    reasons.append("multiple_destinations_require_review")
                rows.append(dict(profile_id=profile["id"], system=system,
                                 trigger_id=trigger["id"] if trigger else None,
                                 reasons=reasons, candidates=candidates))
    return dict(registry_revision=catalog["revision"], rows=rows,
                limitations=["structural_comparison_only", "separate_database_snapshots",
                             "runner_tags_not_compared", "execution_authorization_not_checked",
                             "credentials_and_runner_health_not_checked", "no_changes_applied"])


def preview_profiles(registry, actor, profile_database):
    # Authorize before opening the separate profile database.
    catalog = registry.catalog(actor)
    targets, errors = configured_gitlab_targets()
    if errors:
        raise RegistryError("GitLab target configuration is invalid")
    return compare_profiles(catalog, read_profiles(profile_database),
                            default_target=targets[0].id if targets else "")
