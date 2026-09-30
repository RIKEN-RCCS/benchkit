"""Compact, read-only presentation of the authorized registry catalog."""

from datetime import UTC, datetime
import json


def decorate_catalog(catalog, *, today=None):
    today = (today or datetime.now(UTC).date()).isoformat()
    configured = {row["budget_id"] for row in catalog["destinations"]}
    for budget in catalog["budgets"]:
        if not budget["enabled"]:
            status = "Disabled"
        elif budget["valid_from"] and today < budget["valid_from"]:
            status = "Not started"
        elif budget["valid_until"] and today > budget["valid_until"]:
            status = "Expired"
        elif budget["id"] not in configured:
            status = "Not configured"
        else:
            status = "Within validity"
        budget["status_label"] = status

    budgets = {row["id"]: row["label"] for row in catalog["budgets"]}
    labels = {
        "label": "Name", "system": "System", "enabled": "Enabled",
        "valid_from": "Valid from", "valid_until": "Valid until",
        "allocation_project_id": "Scheduler allocation ID", "account_id": "Execution settings",
        "connection_id": "GitLab connection", "build_tag": "Build tag", "run_tag": "Run tag",
        "principal": "Manager", "id_token_audience": "ID token audience",
        "server_url": "GitLab URL", "project_path": "Project", "token_env": "Credential reference",
    }
    kinds = {"budgets": "Budget", "budget_managers": "Budget managers",
             "budget_defaults": "Budget defaults", "destinations": "Execution target",
             "execution_accounts": "Execution settings", "connections": "Connection"}
    for row in catalog["history"]:
        before, after = (json.loads(row[key]) or {} for key in ("before_json", "after_json"))
        record = after or before
        kind = row["entity_type"]
        if kind in ("budget_managers", "budget_defaults"):
            name = budgets.get(record.get("budget_id", record.get("id")), "Budget")
        elif kind == "destinations":
            name = record.get("system", "Execution target")
        elif kind == "execution_accounts":
            name = record.get("system", "Execution settings")
        else:
            name = record.get("label", kinds.get(kind, "Record"))
        row["display_name"] = name
        row["display_kind"] = kinds.get(kind, "Record")
        row["operation"] = "Added" if not before else "Removed" if not after else "Updated"
        row["changed_fields"] = [label for key, label in labels.items()
                                 if before.get(key) != after.get(key)]
