import os
from urllib.parse import urlsplit

from flask import url_for

from utils.result_records import (
    extract_result_uuid,
    format_result_timestamp,
    summarize_result_quality,
)
from utils.trigger_display import summarize_execution_trigger


def build_result_table_row(
    json_filename,
    result_data,
    padata_filenames,
    trigger_runs_by_pipeline=None,
    *,
    public_surface=False,
):
    """Build a single row for the public/confidential results index table."""
    timestamp = format_result_timestamp(json_filename)
    matched_padata = _find_matching_padata_archive(json_filename, result_data, padata_filenames)
    pipeline_timing = result_data.get("pipeline_timing", {})
    source_info = result_data.get("source_info")
    source_link = None if public_surface else _build_source_link(source_info)
    profile_data = result_data.get("profile_data")

    ci_trigger = result_data.get("ci_trigger", "-") or "-"
    pipeline_id = result_data.get("pipeline_id", "-")
    if pipeline_id is None:
        pipeline_id = "-"
    else:
        pipeline_id = str(pipeline_id)
    pipeline_label = f"#{pipeline_id}" if pipeline_id != "-" else "-"
    parent_pipeline_id = result_data.get("parent_pipeline_id", "")
    parent_pipeline_id = str(parent_pipeline_id) if parent_pipeline_id not in (None, "") else ""
    ci_title = f"{ci_trigger} / {pipeline_label}"
    ci_subline = ""
    if parent_pipeline_id and parent_pipeline_id != pipeline_id:
        ci_title = f"{ci_trigger} / child #{pipeline_id} / parent #{parent_pipeline_id}"
        ci_subline = f"parent #{parent_pipeline_id}"

    return {
        "timestamp": timestamp,
        "code": result_data.get("code", "N/A"),
        "exp": result_data.get("Exp", "N/A"),
        "fom": result_data.get("FOM", "N/A"),
        "fom_unit": result_data.get("FOM_unit") or "",
        "fom_version": result_data.get("FOM_version", "N/A"),
        "system": result_data.get("system", "N/A"),
        "activity_context": _build_activity_context(
            result_data,
            trigger_runs_by_pipeline,
        ),
        "nodes": result_data.get("node_count", "N/A"),
        "numproc_node": _normalize_optional_field(result_data.get("numproc_node")),
        "nthreads": _normalize_optional_field(result_data.get("nthreads")),
        "json_link": None if public_surface else url_for("results.show_result", filename=json_filename),
        "data_link": url_for("results.show_result", filename=matched_padata) if matched_padata else None,
        "has_vector": _has_vector_metrics(result_data),
        "detail_link": url_for("results.result_detail", filename=json_filename),
        "filename": json_filename,
        "build_time": _normalize_pipeline_timing(pipeline_timing, "build_time"),
        "queue_time": _normalize_pipeline_timing(pipeline_timing, "queue_time"),
        "run_time": _normalize_pipeline_timing(pipeline_timing, "run_time"),
        "execution_mode": result_data.get("execution_mode", "-") or "-",
        "ci_trigger": ci_trigger,
        "ci_summary": f"{ci_trigger} / {pipeline_id}",
        "ci_title": ci_title,
        "ci_subline": ci_subline,
        "pipeline_label": pipeline_label,
        "execution_trigger_summary": summarize_execution_trigger(
            result_data,
            trigger_runs_by_pipeline,
        ),
        "build_job": result_data.get("build_job", "-") or "-",
        "run_job": result_data.get("run_job", "-") or "-",
        "pipeline_id": pipeline_id,
        "parent_pipeline_id": parent_pipeline_id,
        "source_info": source_info,
        "source_link": source_link,
        "source_hash": _format_source_hash(source_info),
        "quality": summarize_result_quality(result_data),
        "profile_data": profile_data,
        "profile_summary": _format_profile_summary(profile_data),
        "profile_summary_meta": _build_profile_summary_meta(profile_data),
    }


def _normalize_optional_field(value):
    if value is None or value == "":
        return "N/A"
    return value


def _normalize_pipeline_timing(pipeline_timing, key):
    if not isinstance(pipeline_timing, dict):
        return "-"
    if key not in pipeline_timing:
        return "-"
    return str(pipeline_timing.get(key, "-"))


def _has_vector_metrics(result_data):
    metrics = result_data.get("metrics", {})
    return isinstance(metrics, dict) and "vector" in metrics


def _build_activity_context(result_data, trigger_runs_by_pipeline=None):
    """Return public activity/allocation context for the result table."""
    trigger_runs_by_pipeline = trigger_runs_by_pipeline or {}
    activity = _extract_result_activity(result_data)
    allocation_project_id = _extract_result_allocation_project_id(result_data)

    if (not activity or not allocation_project_id) and trigger_runs_by_pipeline:
        for pipeline_id in _result_pipeline_ids(result_data):
            run = trigger_runs_by_pipeline.get(pipeline_id)
            variables = _trigger_run_activity_context(run)
            if not activity:
                activity = variables.get("activity", "")
            if not allocation_project_id:
                allocation_project_id = variables.get("allocation_project_id", "")
            if activity and allocation_project_id:
                break

    headline = activity or allocation_project_id or "-"
    subline = ""
    if activity and allocation_project_id:
        subline = f"allocation {allocation_project_id}"
    elif allocation_project_id:
        subline = "allocation"

    title_parts = []
    if activity:
        title_parts.append(f"activity={activity}")
    if allocation_project_id:
        title_parts.append(f"allocation_project_id={allocation_project_id}")
    return {
        "headline": headline,
        "subline": subline,
        "title": "; ".join(title_parts) if title_parts else "No activity or allocation metadata was recorded for this result.",
        "activity": activity,
        "allocation_project_id": allocation_project_id,
    }


def _extract_result_activity(result_data):
    snapshot = result_data.get("environment_snapshot")
    if not isinstance(snapshot, dict):
        return ""
    summary = snapshot.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    payload = snapshot.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    execution = payload.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    return _first_text(
        summary.get("activity"),
        execution.get("activity"),
    )


def _extract_result_allocation_project_id(result_data):
    snapshot = result_data.get("environment_snapshot")
    if not isinstance(snapshot, dict):
        return ""
    summary = snapshot.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    payload = snapshot.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    system = payload.get("system")
    system = system if isinstance(system, dict) else {}
    return _first_text(
        summary.get("allocation_project_id"),
        system.get("allocation_project_id"),
    )


def _trigger_run_activity_context(run):
    if not isinstance(run, dict):
        return {}
    payload = run.get("payload_json") if isinstance(run.get("payload_json"), dict) else {}
    plan_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    variables = plan_payload.get("variables") if isinstance(plan_payload.get("variables"), dict) else {}
    return {
        "activity": _first_text(
            variables.get("BK_EXECUTION_ACTIVITY"),
            payload.get("activity"),
        ),
        "allocation_project_id": _first_text(
            variables.get("BK_ALLOCATION_PROJECT_ID"),
            payload.get("allocation_project_id"),
        ),
    }


def _result_pipeline_ids(result_data):
    values = []
    for value in (result_data.get("pipeline_id"), result_data.get("parent_pipeline_id")):
        text = str(value).strip() if value not in (None, "") else ""
        if text and text not in values:
            values.append(text)
    return values


def _first_text(*values):
    for value in values:
        if value is None or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _find_matching_padata_archive(json_filename, result_data, padata_filenames):
    result_uuid = extract_result_uuid(json_filename) or result_data.get("_server_uuid")
    if not result_uuid:
        return None
    matches = sorted(filename for filename in padata_filenames if result_uuid in filename)
    legacy_name = next(
        (
            filename for filename in matches
            if filename.endswith(f"_{result_uuid}.tgz")
        ),
        None,
    )
    return legacy_name or (matches[0] if matches else None)


def _format_source_hash(source_info):
    if not isinstance(source_info, dict):
        return "-"

    source_type = source_info.get("source_type")
    if source_type == "git":
        branch = source_info.get("ref_name") or source_info.get("branch", "")
        commit_hash = source_info.get("resolved_commit") or source_info.get("commit_hash", "")
        short_hash = commit_hash[:7] if commit_hash else ""
        return f"{branch}@{short_hash}" if branch and short_hash else short_hash or branch or "-"

    if source_type == "file":
        sha256sum = source_info.get("sha256sum", "")
        if sha256sum:
            return sha256sum[:12]
        md5sum = source_info.get("md5sum", "")
        return md5sum[:8] if md5sum else "-"

    return "-"


def _build_source_link(source_info):
    if not isinstance(source_info, dict):
        return None

    source_type = source_info.get("source_type")
    if source_type == "git":
        repo_url = str(source_info.get("repo_url") or "").strip()
        parsed = urlsplit(repo_url)
        has_unsafe_chars = any(ch.isspace() for ch in repo_url) or "\\" in repo_url
        if parsed.scheme in {"http", "https"} and parsed.netloc and not has_unsafe_chars:
            return {
                "href": repo_url,
                "title": repo_url,
            }
        return {
            "href": None,
            "title": "Repository URL is not linkable",
        }

    if source_type == "file":
        file_path = str(source_info.get("file_path") or "").strip()
        filename = os.path.basename(file_path) if file_path else "source archive"
        return {
            "href": None,
            "title": filename or "source archive",
        }

    return None


def _format_profile_summary(profile_data):
    if not isinstance(profile_data, dict) or not profile_data:
        return "-"

    headline_parts = [part for part in (profile_data.get("tool"), profile_data.get("level")) if part]
    return " / ".join(headline_parts) if headline_parts else "profile data"


# The template expects a stable, display-ready shape even when older result JSON
# files do not have profile_data or when only one profiler family is present.
def _build_profile_summary_meta(profile_data):
    if not isinstance(profile_data, dict) or not profile_data:
        return {
            "has_profile_data": False,
            "headline": "",
            "subline": "",
            "events": [],
            "ncu_options": [],
            "report_kinds": [],
        }

    report_format = profile_data.get("report_format") or ""
    run_count = profile_data.get("run_count")
    subline_parts = []
    if report_format:
        subline_parts.append(report_format)
    if isinstance(run_count, int):
        subline_parts.append(f"{run_count} run" if run_count == 1 else f"{run_count} runs")

    return {
        "has_profile_data": True,
        "headline": _format_profile_summary(profile_data),
        "subline": ", ".join(subline_parts),
        "archive_count": profile_data.get("archive_count") if isinstance(profile_data.get("archive_count"), int) else None,
        "events": profile_data.get("events") if isinstance(profile_data.get("events"), list) else [],
        "ncu_options": profile_data.get("ncu_options") if isinstance(profile_data.get("ncu_options"), list) else [],
        "report_kinds": profile_data.get("report_kinds") if isinstance(profile_data.get("report_kinds"), list) else [],
    }
