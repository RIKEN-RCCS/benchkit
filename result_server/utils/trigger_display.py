"""Display helpers for Portal-triggered benchmark execution metadata."""

from __future__ import annotations

import sqlite3
from typing import Any


def extract_execution_trigger(result: dict[str, Any] | None) -> dict[str, str]:
    """Return a stable trigger metadata shape from a result JSON object."""
    data = result if isinstance(result, dict) else {}
    raw = data.get("execution_trigger") if isinstance(data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": str(raw.get("id") or "").strip(),
        "type": str(raw.get("type") or "").strip(),
        "reason": str(raw.get("reason") or "").strip(),
    }


def load_trigger_run_lookup(db_path: str | None, *, limit: int = 500) -> dict[str, dict[str, Any]]:
    """Load trigger runs keyed by GitLab pipeline id, when the Portal DB is available."""
    if not db_path:
        return {}
    try:
        try:
            from utils.execution_profiles import ExecutionProfileStore
        except ModuleNotFoundError:  # pragma: no cover - package import fallback
            from result_server.utils.execution_profiles import ExecutionProfileStore

        runs = ExecutionProfileStore(db_path).list_trigger_runs(
            statuses=("submitted",),
            limit=limit,
        )
    except (sqlite3.Error, OSError):
        return {}
    return build_trigger_run_lookup(runs)


def build_trigger_run_lookup(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return latest trigger run by GitLab pipeline id."""
    lookup: dict[str, dict[str, Any]] = {}
    for run in runs:
        for pipeline_id in _trigger_run_pipeline_ids(run):
            if pipeline_id and pipeline_id not in lookup:
                lookup[pipeline_id] = run
    return lookup


def build_trigger_result_links(
    results_dir: str,
    runs: list[dict[str, Any]],
) -> dict[int, list[dict[str, str]]]:
    """Return result summaries keyed by trigger run id."""
    if not results_dir:
        return {}
    try:
        filenames = sorted(
            [name for name in _os_listdir(results_dir) if name.endswith(".json")],
            reverse=True,
        )
    except OSError:
        return {}

    by_run_id: dict[int, list[dict[str, str]]] = {}
    indexed_runs = [_index_trigger_run(run) for run in runs]
    for filename in filenames:
        result = _load_result_json(filename, results_dir)
        if not isinstance(result, dict):
            continue
        for indexed in indexed_runs:
            if _result_matches_trigger_run(result, indexed):
                by_run_id.setdefault(indexed["id"], []).append(
                    {
                        "filename": filename,
                        "label": _format_result_link_label(filename, result),
                        "pipeline_id": str(result.get("pipeline_id") or ""),
                    }
                )
    return by_run_id


def summarize_execution_trigger(
    result: dict[str, Any] | None,
    trigger_runs_by_pipeline: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str | bool]:
    """Build a compact display summary for why a benchmark run was launched."""
    trigger = extract_execution_trigger(result)
    if not any(trigger.values()):
        trigger = _execution_trigger_from_pipeline(result, trigger_runs_by_pipeline or {})
    trigger_id = trigger["id"]
    trigger_type = trigger["type"]
    reason = trigger["reason"]
    if not any((trigger_id, trigger_type, reason)):
        return {
            "has_trigger": False,
            "headline": "-",
            "subline": "",
            "title": "No Portal trigger metadata was recorded for this result.",
        }

    headline = _format_trigger_type(trigger_type)
    if trigger_id:
        headline = f"{headline} / {trigger_id}" if headline != "Portal trigger" else trigger_id

    subline = _format_trigger_reason(reason)
    title_parts = []
    if trigger_type:
        title_parts.append(f"type={trigger_type}")
    if trigger_id:
        title_parts.append(f"id={trigger_id}")
    if reason:
        title_parts.append(f"reason={reason}")
    return {
        "has_trigger": True,
        "headline": headline,
        "subline": subline,
        "title": "; ".join(title_parts),
    }


def summarize_trigger_run(run: dict[str, Any]) -> dict[str, Any]:
    """Return template-ready trigger-run context extracted from run payload."""
    payload = run.get("payload_json") if isinstance(run.get("payload_json"), dict) else {}
    plan_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    variables = plan_payload.get("variables") if isinstance(plan_payload.get("variables"), dict) else {}
    errors = run.get("errors") if isinstance(run.get("errors"), list) else []
    return {
        "id": run.get("id"),
        "trigger_id": run.get("trigger_id") or "-",
        "trigger_type": run.get("trigger_type") or "-",
        "status": run.get("status") or "-",
        "dry_run": bool(run.get("dry_run")),
        "reason": run.get("reason") or "-",
        "reason_label": _format_trigger_reason(run.get("reason") or ""),
        "created_at": run.get("created_at") or "-",
        "actor": run.get("actor") or "-",
        "gitlab_target": payload.get("gitlab_target") or "-",
        "gitlab_project": payload.get("gitlab_project") or "-",
        "target_ref": plan_payload.get("ref") or "-",
        "code": variables.get("code") or "-",
        "system": variables.get("system") or "-",
        "allocation_project_id": variables.get("BK_ALLOCATION_PROJECT_ID") or "-",
        "result_server": variables.get("RESULT_SERVER") or "-",
        "pipeline_id": _trigger_run_pipeline_ids(run)[0] if _trigger_run_pipeline_ids(run) else "-",
        "errors": errors,
        "error_summary": "; ".join(str(error) for error in errors) if errors else "",
    }


def _index_trigger_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(run.get("id") or 0),
        "trigger_id": str(run.get("trigger_id") or "").strip(),
        "trigger_type": str(run.get("trigger_type") or "").strip(),
        "reason": str(run.get("reason") or "").strip(),
        "pipeline_ids": set(_trigger_run_pipeline_ids(run)),
    }


def _result_matches_trigger_run(result: dict[str, Any], run: dict[str, Any]) -> bool:
    result_pipeline_ids = _result_pipeline_ids(result)
    if set(result_pipeline_ids).intersection(run["pipeline_ids"]):
        return True
    trigger = extract_execution_trigger(result)
    if not trigger["id"]:
        return False
    if trigger["id"] != run["trigger_id"]:
        return False
    if trigger["type"] and trigger["type"] != run["trigger_type"]:
        return False
    return not trigger["reason"] or trigger["reason"] == run["reason"]


def _format_result_link_label(filename: str, result: dict[str, Any]) -> str:
    try:
        from utils.result_records import format_result_timestamp
    except ModuleNotFoundError:  # pragma: no cover - package import fallback
        from result_server.utils.result_records import format_result_timestamp

    parts = [
        format_result_timestamp(filename),
        str(result.get("Exp") or "").strip(),
    ]
    return " / ".join(part for part in parts if part)


def _load_result_json(filename: str, results_dir: str) -> dict[str, Any] | None:
    try:
        from utils.result_records import load_result_json
    except ModuleNotFoundError:  # pragma: no cover - package import fallback
        from result_server.utils.result_records import load_result_json

    return load_result_json(filename, results_dir)


def _os_listdir(path: str) -> list[str]:
    import os

    return os.listdir(path)


def _execution_trigger_from_pipeline(
    result: dict[str, Any] | None,
    trigger_runs_by_pipeline: dict[str, dict[str, Any]],
) -> dict[str, str]:
    data = result if isinstance(result, dict) else {}
    run = None
    for pipeline_id in _result_pipeline_ids(data):
        run = trigger_runs_by_pipeline.get(pipeline_id)
        if run:
            break
    if not run:
        return {"id": "", "type": "", "reason": ""}
    return {
        "id": str(run.get("trigger_id") or "").strip(),
        "type": str(run.get("trigger_type") or "").strip(),
        "reason": str(run.get("reason") or "").strip(),
    }


def _trigger_run_pipeline_ids(run: dict[str, Any]) -> list[str]:
    payload = run.get("payload_json") if isinstance(run.get("payload_json"), dict) else {}
    submit = payload.get("submit") if isinstance(payload.get("submit"), dict) else {}
    response = submit.get("response") if isinstance(submit.get("response"), dict) else {}
    values = [response.get("id")]
    child_ids = response.get("child_pipeline_ids")
    if isinstance(child_ids, list):
        values.extend(child_ids)
    return [
        str(value).strip()
        for value in values
        if value not in (None, "") and str(value).strip()
    ]


def _result_pipeline_ids(result: dict[str, Any]) -> list[str]:
    values = []
    for value in (result.get("pipeline_id"), result.get("parent_pipeline_id")):
        text = str(value).strip() if value not in (None, "") else ""
        if text and text not in values:
            values.append(text)
    return values


def _format_trigger_type(trigger_type: str) -> str:
    mapping = {
        "manual_button": "Manual",
        "scheduled": "Scheduled",
        "watch_event": "Watch event",
    }
    return mapping.get(trigger_type, "Portal trigger")


def _format_trigger_reason(reason: str) -> str:
    if not reason:
        return ""
    if reason.startswith("cron:"):
        expr, _, due_minute = reason.removeprefix("cron:").partition("@")
        return f"cron {expr} / {due_minute}" if due_minute else f"cron {expr}"
    if reason.startswith("repo_ref:"):
        target = reason.removeprefix("repo_ref:")
        return f"repo/ref changed: {target}" if target else "repo/ref watch"
    if reason.startswith("lock:"):
        return f"runner lock: {reason.removeprefix('lock:')}"
    return reason
