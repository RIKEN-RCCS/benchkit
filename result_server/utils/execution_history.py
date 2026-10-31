"""Display adapters for persisted manual and scheduled execution history."""

import json

from utils.gitlab_pipeline import GITLAB_REPO_RE
from utils.trigger_display import build_trigger_result_links, summarize_trigger_run


def list_execution_history(store, *, limit=80, offset=0, **filters):
    runs = []
    for record in store.list_execution_history_records(limit=limit, offset=offset, **filters):
        payload = _json_value(record["payload_json"], dict)
        plan = payload.get("payload")
        plan = dict(plan) if isinstance(plan, dict) else {}
        plan.setdefault("ref", record["target_ref"])
        payload["payload"] = plan
        manual = record["history_source"] == "manual"
        if record["status"] != "submitted" or record["dry_run"]:
            payload.pop("submit", None)
        runs.append({
            # Keep the two independent integer ID sequences disjoint for link lookup.
            "id": -record["id"] if manual else record["id"],
            "manual_request_id": record["id"] if manual else None,
            "profile_id": record["profile_id"],
            # Manual results match recorded pipeline IDs, never the reusable profile ID.
            "trigger_id": record["trigger_id"],
            "trigger_type": record["trigger_type"],
            "status": record["status"],
            "dry_run": bool(record["dry_run"]),
            "reason": "manual_button:" + record["profile_id"] if manual else record["reason"],
            "payload_json": payload,
            "errors": _json_value(record["errors_json"], list),
            "actor": record["actor"],
            "created_at": record["created_at"],
        })
    return runs


def _json_value(value, kind):
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return kind()
    return parsed if isinstance(parsed, kind) else kind()


def execution_result_links(results_dir, runs, *, pipeline_projects=None):
    """Only actual submissions with a recorded pipeline may claim Results."""
    eligible = [run for run in runs if run["status"] == "submitted"
                and not run["dry_run"]
                and summarize_trigger_run(run)["pipeline_id"] != "-"]
    return build_trigger_result_links(
        results_dir, eligible, strict=True, pipeline_only=True,
        pipeline_projects=pipeline_projects,
    )


def summarize_execution_history(run):
    summary = summarize_trigger_run(run)
    request_id = run.get("manual_request_id")
    summary["history_source"] = "Manual" if request_id else "Runner"
    summary["record_id"] = request_id or run["id"]
    summary["profile_id"] = run.get("profile_id") or ""
    summary["source"] = "manual" if request_id else "runner"
    summary["decision_label"] = {
        "submitted": "Submitted", "submit_failed": "Submission failed",
        "submitting": "Submission in progress; do not resubmit",
        "submission_unknown": "Acceptance unknown; confirmation required",
        "submission_held": "Automatic resubmission held",
        "submit_blocked": "Submission blocked", "not_due": "Not due",
        "unchanged": "Unchanged",
    }.get(summary["status"], summary["status"])
    summary["ci_status"] = "Not checked" if summary["pipeline_id"] != "-" else "-"
    if request_id:
        summary["trigger_id"] = run["profile_id"] or "-"
        summary["reason_label"] = "Manual submission"
    project = str(summary["gitlab_project"]).removesuffix(".git")
    pipeline = str(summary["pipeline_id"])
    summary["pipeline_url"] = ""
    if (GITLAB_REPO_RE.fullmatch(project) and pipeline.isascii() and pipeline.isdecimal()
            and int(pipeline) > 0 and all(part not in (".", "..") for part in project.split("/"))):
        summary["pipeline_url"] = "https://" + project + "/-/pipelines/" + pipeline
    return summary
