"""Display adapters for persisted manual and scheduled execution history."""

from utils.gitlab_pipeline import GITLAB_REPO_RE
from utils.trigger_display import summarize_trigger_run


def list_execution_history(store, *, limit=80):
    runs = store.list_trigger_runs(limit=limit)
    for request in store.list_execution_requests(limit=limit):
        payload = dict(request["payload_json"])
        plan = payload.get("payload")
        plan = dict(plan) if isinstance(plan, dict) else {}
        plan.setdefault("ref", request["target_ref"])
        payload["payload"] = plan
        # Blocked/failed submissions must not acquire another attempt's results.
        if request["status"] != "submitted":
            payload.pop("submit", None)
        runs.append({
            # Keep the two independent integer ID sequences disjoint for link lookup.
            "id": -request["id"],
            "manual_request_id": request["id"],
            "profile_id": request["profile_id"],
            # Manual results match recorded pipeline IDs, never the reusable profile ID.
            "trigger_id": "",
            "trigger_type": "manual_button",
            "status": request["status"],
            "dry_run": False,
            "reason": "manual_button:" + request["profile_id"],
            "payload_json": payload,
            "errors": request["errors_json"],
            "actor": request["actor"],
            "created_at": request["created_at"],
        })
    return sorted(runs, key=lambda run: (run["created_at"], abs(run["id"])), reverse=True)[:limit]


def summarize_execution_history(run):
    summary = summarize_trigger_run(run)
    request_id = run.get("manual_request_id")
    summary["history_source"] = "Manual" if request_id else "Runner"
    summary["record_id"] = request_id or run["id"]
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
