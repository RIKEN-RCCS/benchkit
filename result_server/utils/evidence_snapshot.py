"""Flat evidence snapshot rows for operator review and CSV export."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from utils.app_support_matrix import load_app_system_support_matrix
from utils.node_hours import extract_timestamp_from_filename
from utils.result_file import get_file_confidential_tags
from utils.result_records import (
    format_result_timestamp,
    load_result_json,
    summarize_result_quality,
)


EVIDENCE_SNAPSHOT_CSV_COLUMNS = [
    "snapshot_time",
    "benchkit_commit",
    "code",
    "system",
    "configured",
    "configured_status",
    "latest_result_time",
    "latest_result_exp",
    "latest_result_status",
    "profiled",
    "latest_profile_time",
    "estimated",
    "latest_estimate_time",
    "estimate_applicability",
    "source_status",
    "input_status",
    "build_cache_status",
    "public_result_available",
    "next_action",
    "missing_reason",
]


def build_evidence_snapshot(
    received_dir: str,
    estimated_dir: str,
    *,
    benchkit_commit: str = "",
    generated_at: datetime | str | None = None,
    app_support_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build release-review evidence rows without exposing site-local values."""
    snapshot_time = _format_snapshot_time(generated_at)
    if app_support_rows is None:
        _, app_support_rows = load_app_system_support_matrix()

    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    _merge_configured_rows(rows_by_key, app_support_rows, snapshot_time, benchkit_commit)
    _merge_latest_results(rows_by_key, received_dir, snapshot_time, benchkit_commit)
    _merge_latest_estimates(rows_by_key, estimated_dir, snapshot_time, benchkit_commit)

    rows = [
        _finalize_missing_reason(row)
        for _key, row in sorted(rows_by_key.items(), key=lambda item: (item[0][0].lower(), item[0][1].lower()))
    ]
    return {
        "generated_at": snapshot_time,
        "benchkit_commit": benchkit_commit,
        "columns": EVIDENCE_SNAPSHOT_CSV_COLUMNS,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "configured_count": sum(1 for row in rows if row["configured"] == "yes"),
            "partial_count": sum(1 for row in rows if row["configured"] == "partial"),
            "result_count": sum(1 for row in rows if row["latest_result_status"] != "missing"),
            "profiled_count": sum(1 for row in rows if row["profiled"] == "yes"),
            "estimated_count": sum(1 for row in rows if row["estimated"] == "yes"),
            "public_result_count": sum(1 for row in rows if row["public_result_available"] == "yes"),
        },
    }


def _merge_configured_rows(
    rows_by_key: dict[tuple[str, str], dict[str, Any]],
    app_support_rows: list[dict[str, Any]],
    snapshot_time: str,
    benchkit_commit: str,
) -> None:
    for app_row in app_support_rows:
        code = _clean(app_row.get("app"))
        if not code:
            continue
        systems = app_row.get("systems")
        if not isinstance(systems, dict):
            continue
        for system, item in systems.items():
            if not isinstance(item, dict):
                continue
            status = _clean(item.get("status"))
            if status == "not_listed":
                continue
            row = _ensure_row(rows_by_key, code, _clean(system), snapshot_time, benchkit_commit)
            if status == "enabled":
                row["configured"] = "yes"
                row["configured_status"] = "enabled and implemented"
            elif status == "enabled_partial":
                row["configured"] = "partial"
                row["configured_status"] = "enabled but script support incomplete"
            elif status == "configured_off":
                row["configured"] = "off"
                row["configured_status"] = "configured off"


def _merge_latest_results(
    rows_by_key: dict[tuple[str, str], dict[str, Any]],
    received_dir: str,
    snapshot_time: str,
    benchkit_commit: str,
) -> None:
    for record in _load_json_records(received_dir, prefix="result_"):
        data = record["data"]
        if "FOM" not in data or "system" not in data:
            continue
        code = _clean(data.get("code")) or "unknown"
        system = _clean(data.get("system")) or "unknown"
        row = _ensure_row(rows_by_key, code, system, snapshot_time, benchkit_commit)

        current_sort_key = row.get("_result_sort_key")
        if current_sort_key is not None and current_sort_key >= record["sort_key"]:
            continue

        quality = summarize_result_quality(data)
        stats = quality["stats"]
        row.update(
            {
                "_result_sort_key": record["sort_key"],
                "latest_result_file": record["filename"],
                "latest_result_time": record["timestamp"],
                "latest_result_exp": _clean(data.get("Exp")) or "-",
                "latest_result_status": quality["level"],
                "profiled": "yes" if _has_profile_data(data) else "no",
                "latest_profile_time": record["timestamp"] if _has_profile_data(data) else "-",
                "source_status": "tracked" if stats.get("source_info_complete") else "incomplete",
                "input_status": stats.get("input_info_label") or "None",
                "build_cache_status": _build_cache_status(data.get("build_cache")),
                "public_result_available": (
                    "no"
                    if get_file_confidential_tags(record["filename"], received_dir)
                    else "yes"
                ),
            }
        )


def _merge_latest_estimates(
    rows_by_key: dict[tuple[str, str], dict[str, Any]],
    estimated_dir: str,
    snapshot_time: str,
    benchkit_commit: str,
) -> None:
    for record in _load_json_records(estimated_dir, prefix="estimate_"):
        data = record["data"]
        code = _clean(data.get("code")) or "unknown"
        exp = _clean(data.get("exp")) or "-"
        estimate_metadata = data.get("estimate_metadata")
        estimate_metadata = estimate_metadata if isinstance(estimate_metadata, dict) else {}
        estimate_time = _clean(estimate_metadata.get("estimation_result_timestamp")) or record["timestamp"]
        applicability = data.get("applicability")
        applicability = applicability if isinstance(applicability, dict) else {}
        applicability_status = _clean(applicability.get("status")) or "unknown"

        for system in _estimate_evidence_systems(data):
            row = rows_by_key.get((code, system))
            if row is None:
                continue
            current_sort_key = row.get("_estimate_sort_key")
            if current_sort_key is not None and current_sort_key >= record["sort_key"]:
                continue
            row.update(
                {
                    "_estimate_sort_key": record["sort_key"],
                    "latest_estimate_file": record["filename"],
                    "latest_estimate_time": estimate_time,
                    "estimated": "yes",
                    "estimate_applicability": applicability_status,
                }
            )
            if row["latest_result_exp"] == "-":
                row["latest_result_exp"] = exp


def _load_json_records(directory: str, *, prefix: str) -> list[dict[str, Any]]:
    try:
        filenames = [
            filename
            for filename in os.listdir(directory)
            if filename.startswith(prefix) and filename.endswith(".json")
        ]
    except OSError:
        filenames = []

    records = []
    for filename in filenames:
        data = load_result_json(filename, directory)
        if not isinstance(data, dict):
            continue
        sort_key = extract_timestamp_from_filename(filename) or datetime.min
        records.append(
            {
                "filename": filename,
                "data": data,
                "sort_key": sort_key,
                "timestamp": format_result_timestamp(filename),
            }
        )
    records.sort(key=lambda record: record["sort_key"], reverse=True)
    return records


def _ensure_row(
    rows_by_key: dict[tuple[str, str], dict[str, Any]],
    code: str,
    system: str,
    snapshot_time: str,
    benchkit_commit: str,
) -> dict[str, Any]:
    key = (code, system)
    if key not in rows_by_key:
        rows_by_key[key] = {
            "snapshot_time": snapshot_time,
            "benchkit_commit": benchkit_commit or "-",
            "code": code,
            "system": system,
            "configured": "no",
            "configured_status": "not listed",
            "latest_result_file": "",
            "latest_result_time": "-",
            "latest_result_exp": "-",
            "latest_result_status": "missing",
            "profiled": "no",
            "latest_profile_time": "-",
            "latest_estimate_file": "",
            "estimated": "no",
            "latest_estimate_time": "-",
            "estimate_applicability": "-",
            "source_status": "not tracked",
            "input_status": "None",
            "build_cache_status": "not recorded",
            "public_result_available": "no",
            "next_action": "",
            "missing_reason": "",
        }
    return rows_by_key[key]


def _finalize_missing_reason(row: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    if row["configured"] == "no":
        reasons.append("not configured")
    elif row["configured"] == "partial":
        reasons.append("script support incomplete")
    elif row["configured"] == "off":
        reasons.append("configured off")
    if row["latest_result_status"] == "missing":
        reasons.append("no result")
    if row["profiled"] == "no":
        reasons.append("no profile")
    if row["estimated"] == "no":
        reasons.append("no estimate")
    if row["source_status"] != "tracked":
        reasons.append("source incomplete")
    if row["input_status"] == "None":
        reasons.append("input not declared")

    cleaned = {
        key: value
        for key, value in row.items()
        if not key.startswith("_")
    }
    cleaned["missing_reason"] = "; ".join(reasons) if reasons else "none"
    cleaned["next_action"] = _next_action(cleaned)
    return cleaned


def _next_action(row: dict[str, Any]) -> str:
    if row["configured"] == "no":
        return "Decide whether to add this app/system condition"
    if row["configured"] == "partial":
        return "Complete app adapter scripts"
    if row["configured"] == "off":
        return "Confirm whether this condition should stay disabled"
    if row["latest_result_status"] == "missing":
        return "Trigger a benchmark run"
    if row["source_status"] != "tracked":
        return "Record source provenance"
    if row["input_status"] == "None":
        return "Declare input metadata"
    if row["profiled"] == "no":
        return "Collect profile data if needed"
    if row["estimated"] == "no":
        return "Run estimation if applicable"
    if row["public_result_available"] == "no":
        return "Review publication eligibility"
    return "Ready for review"


def _has_profile_data(data: dict[str, Any]) -> bool:
    profile_data = data.get("profile_data")
    return isinstance(profile_data, dict) and bool(profile_data)


def _build_cache_status(build_cache: Any) -> str:
    if not isinstance(build_cache, dict) or not build_cache:
        return "not recorded"
    status = _clean(build_cache.get("status")) or "unknown"
    if build_cache.get("stored") is True:
        return f"{status} stored"
    return status


def _estimate_evidence_systems(data: dict[str, Any]) -> list[str]:
    """Return systems that can own Evidence Snapshot rows for an estimate."""
    systems = []

    def add_system(value: Any) -> None:
        system = _clean(value)
        if system and system not in systems:
            systems.append(system)

    current = data.get("current_system")
    if isinstance(current, dict):
        add_system(current.get("system"))
        benchmark = current.get("benchmark")
        if isinstance(benchmark, dict):
            add_system(benchmark.get("system"))

    future = data.get("future_system")
    if isinstance(future, dict):
        # future_system.system may be an abstract target, so use its measured baseline.
        benchmark = future.get("benchmark")
        if isinstance(benchmark, dict):
            add_system(benchmark.get("system"))

    return systems


def _format_snapshot_time(value: datetime | str | None) -> str:
    if isinstance(value, str):
        return value
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean(value: Any) -> str:
    return str(value or "").strip()
