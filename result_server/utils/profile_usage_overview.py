"""Profile-centered operational overview for Usage Report."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from utils.execution_profiles import ExecutionProfileStore, load_execution_profiles
from utils.node_hours import compute_node_hours, extract_timestamp_from_filename
from utils.result_records import format_result_timestamp, load_result_json
from utils.trigger_display import extract_execution_trigger, summarize_execution_trigger


def build_profile_usage_overview(received_dir: str, db_path: str | None) -> dict[str, Any]:
    """Summarize profiles with their trigger, result, and node-hour activity."""
    if not db_path or not os.path.exists(db_path):
        return {
            "available": False,
            "path": db_path or "",
            "rows": [],
            "summary": _empty_summary(),
            "errors": [],
        }

    profile_result = load_execution_profiles(db_path or "")
    if not profile_result.exists:
        return {
            "available": False,
            "path": profile_result.path,
            "rows": [],
            "summary": _empty_summary(),
            "errors": profile_result.errors,
        }

    store = ExecutionProfileStore(db_path or "")
    triggers = store.list_trigger_definitions()
    trigger_runs = store.list_trigger_runs(limit=500)
    result_records = _load_result_records(received_dir)

    triggers_by_profile = _group_by(triggers, "profile_id")
    runs_by_trigger = _latest_runs_by_trigger(trigger_runs)

    rows = []
    for profile in profile_result.profiles:
        profile_triggers = triggers_by_profile.get(profile["id"], [])
        trigger_ids = {trigger["id"] for trigger in profile_triggers}
        matched_results = [
            record
            for record in result_records
            if _result_matches_profile(record["data"], profile, trigger_ids)
        ]
        latest_result = matched_results[0] if matched_results else None
        latest_run = _latest_profile_run(profile_triggers, runs_by_trigger)
        node_hours = round(sum(record["node_hours"] for record in matched_results), 2)
        rows.append(
            {
                "profile_id": profile["id"],
                "status": profile.get("status") or "-",
                "enabled": bool(profile.get("enabled")),
                "code": _scope_label(profile.get("code", [])),
                "system": _scope_label(profile.get("system", [])),
                "exp": _scope_label(profile.get("exp", [])),
                "allocation_project_id": profile.get("allocation_project_id") or "-",
                "trigger_count": len(profile_triggers),
                "enabled_trigger_count": sum(1 for trigger in profile_triggers if trigger.get("enabled")),
                "trigger_labels": [_trigger_label(trigger) for trigger in profile_triggers[:3]],
                "result_count": len(matched_results),
                "node_hours": node_hours,
                "latest_result": _latest_result_context(latest_result),
                "latest_trigger_run": _latest_run_context(latest_run),
            }
        )

    return {
        "available": True,
        "path": profile_result.path,
        "rows": rows,
        "summary": {
            "profile_count": len(rows),
            "profile_with_results_count": sum(1 for row in rows if row["result_count"]),
            "trigger_count": len(triggers),
            "result_count": len(result_records),
            "node_hours": round(sum(record["node_hours"] for record in result_records), 2),
        },
        "errors": profile_result.errors,
    }


def _empty_summary() -> dict[str, int | float]:
    return {
        "profile_count": 0,
        "profile_with_results_count": 0,
        "trigger_count": 0,
        "result_count": 0,
        "node_hours": 0.0,
    }


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or ""), []).append(row)
    return grouped


def _latest_runs_by_trigger(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        trigger_id = str(run.get("trigger_id") or "")
        if trigger_id and trigger_id not in latest:
            latest[trigger_id] = run
    return latest


def _latest_profile_run(
    triggers: list[dict[str, Any]],
    runs_by_trigger: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    runs = [
        runs_by_trigger[trigger["id"]]
        for trigger in triggers
        if trigger.get("id") in runs_by_trigger
    ]
    return runs[0] if runs else None


def _load_result_records(received_dir: str) -> list[dict[str, Any]]:
    try:
        filenames = [name for name in os.listdir(received_dir) if name.endswith(".json")]
    except OSError:
        filenames = []

    records = []
    for filename in filenames:
        data = load_result_json(filename, received_dir)
        if not isinstance(data, dict):
            continue
        records.append(
            {
                "filename": filename,
                "timestamp": extract_timestamp_from_filename(filename),
                "timestamp_label": format_result_timestamp(filename),
                "data": data,
                "node_hours": compute_node_hours(data),
            }
        )
    records.sort(key=lambda record: record["timestamp"] or datetime.min, reverse=True)
    return records


def _result_matches_profile(
    result: dict[str, Any],
    profile: dict[str, Any],
    trigger_ids: set[str],
) -> bool:
    trigger_id = extract_execution_trigger(result)["id"]
    if trigger_id and trigger_id in trigger_ids:
        return True
    return (
        _scope_matches(profile.get("code", []), result.get("code"))
        and _scope_matches(profile.get("system", []), result.get("system"))
        and _scope_matches(profile.get("exp", []), result.get("Exp"))
    )

def _scope_matches(scope: list[str], value: Any) -> bool:
    if not scope:
        return True
    text = str(value or "").strip()
    return text in {str(item).strip() for item in scope}


def _scope_label(scope: list[str]) -> str:
    values = [str(value).strip() for value in scope if str(value).strip()]
    return ", ".join(values) if values else "*"


def _trigger_label(trigger: dict[str, Any]) -> str:
    state = "on" if trigger.get("enabled") else "paused"
    return f"{trigger.get('trigger_type') or '-'} / {trigger.get('id') or '-'} / {state}"


def _latest_result_context(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    trigger_summary = summarize_execution_trigger(record["data"])
    return {
        "filename": record["filename"],
        "timestamp": record["timestamp_label"],
        "code": record["data"].get("code") or "-",
        "system": record["data"].get("system") or "-",
        "exp": record["data"].get("Exp") or "-",
        "pipeline_id": record["data"].get("pipeline_id") or "-",
        "trigger_headline": trigger_summary.get("headline") or "-",
    }


def _latest_run_context(run: dict[str, Any] | None) -> dict[str, str] | None:
    if not run:
        return None
    return {
        "status": str(run.get("status") or "-"),
        "created_at": str(run.get("created_at") or "-"),
        "reason": str(run.get("reason") or "-"),
    }
