from flask import url_for

from utils.result_records import (
    extract_result_uuid,
    format_result_timestamp,
    summarize_result_quality,
)


def build_result_table_row(json_filename, result_data, padata_filenames):
    """Build a single row for the public/confidential results index table."""
    timestamp = format_result_timestamp(json_filename)
    matched_padata = _find_matching_padata_archive(json_filename, result_data, padata_filenames)
    pipeline_timing = result_data.get("pipeline_timing", {})
    source_info = result_data.get("source_info")
    profile_data = result_data.get("profile_data")

    ci_trigger = result_data.get("ci_trigger", "-") or "-"
    pipeline_id = result_data.get("pipeline_id", "-")
    if pipeline_id is None:
        pipeline_id = "-"
    else:
        pipeline_id = str(pipeline_id)

    return {
        "timestamp": timestamp,
        "code": result_data.get("code", "N/A"),
        "exp": result_data.get("Exp", "N/A"),
        "fom": result_data.get("FOM", "N/A"),
        "fom_version": result_data.get("FOM_version", "N/A"),
        "system": result_data.get("system", "N/A"),
        "nodes": result_data.get("node_count", "N/A"),
        "numproc_node": _normalize_optional_field(result_data.get("numproc_node")),
        "nthreads": _normalize_optional_field(result_data.get("nthreads")),
        "json_link": url_for("results.show_result", filename=json_filename),
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
        "build_job": result_data.get("build_job", "-") or "-",
        "run_job": result_data.get("run_job", "-") or "-",
        "pipeline_id": pipeline_id,
        "source_info": source_info,
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
def _find_matching_padata_archive(json_filename, result_data, padata_filenames):
    result_uuid = extract_result_uuid(json_filename) or result_data.get("_server_uuid")
    if not result_uuid:
        return None
    return next((filename for filename in padata_filenames if result_uuid in filename), None)


def _format_source_hash(source_info):
    if not isinstance(source_info, dict):
        return "-"

    source_type = source_info.get("source_type")
    if source_type == "git":
        branch = source_info.get("branch", "")
        commit_hash = source_info.get("commit_hash", "")
        short_hash = commit_hash[:7] if commit_hash else ""
        return f"{branch}@{short_hash}" if branch and short_hash else short_hash or branch or "-"

    if source_type == "file":
        md5sum = source_info.get("md5sum", "")
        return md5sum[:8] if md5sum else "-"

    return "-"


def _format_profile_summary(profile_data):
    if not isinstance(profile_data, dict) or not profile_data:
        return "-"

    headline_parts = [part for part in (profile_data.get("tool"), profile_data.get("level")) if part]
    return " / ".join(headline_parts) if headline_parts else "profile data"


def _build_profile_summary_meta(profile_data):
    if not isinstance(profile_data, dict) or not profile_data:
        return {
            "has_profile_data": False,
            "headline": "",
            "subline": "",
            "events": [],
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
        "events": profile_data.get("events") if isinstance(profile_data.get("events"), list) else [],
        "report_kinds": profile_data.get("report_kinds") if isinstance(profile_data.get("report_kinds"), list) else [],
    }
