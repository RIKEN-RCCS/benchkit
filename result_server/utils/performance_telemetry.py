"""Execution timing and build-cache telemetry for Usage Report."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from utils.node_hours import extract_timestamp_from_filename
from utils.result_records import format_result_timestamp, load_result_json


TIMING_FIELDS = ("build_time", "queue_time", "run_time")


def build_performance_telemetry(received_dir: str) -> dict[str, Any]:
    """Summarize available timing records without adding new result contracts."""
    records = _load_result_records(received_dir)
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    totals = _empty_timing_totals()
    summary = {
        "result_count": len(records),
        "timing_record_count": 0,
        "profiled_result_count": 0,
        "build_cache_record_count": 0,
        "build_cache_hit_count": 0,
        "build_cache_miss_count": 0,
        "build_cache_store_count": 0,
    }

    for record in records:
        data = record["data"]
        code = _clean(data.get("code")) or "unknown"
        system = _clean(data.get("system")) or "unknown"
        key = (code, system)
        row = rows_by_key.setdefault(
            key,
            {
                "code": code,
                "system": system,
                "result_count": 0,
                "timing_count": 0,
                "profiled_count": 0,
                "build_cache_hit_count": 0,
                "build_cache_miss_count": 0,
                "build_cache_store_count": 0,
                "latest_result_file": record["filename"],
                "latest_result_time": record["timestamp_label"],
                "latest_exp": _clean(data.get("Exp")) or "-",
                "latest_build_time": "-",
                "latest_queue_time": "-",
                "latest_run_time": "-",
                "latest_build_cache_status": "-",
                "_timing_totals": _empty_timing_totals(),
            },
        )
        row["result_count"] += 1

        timing = _timing_values(data.get("pipeline_timing"))
        if timing:
            row["timing_count"] += 1
            summary["timing_record_count"] += 1
            _add_timing_totals(row["_timing_totals"], timing)
            _add_timing_totals(totals, timing)

            if row["latest_result_file"] == record["filename"]:
                row["latest_build_time"] = _format_seconds(timing.get("build_time"))
                row["latest_queue_time"] = _format_seconds(timing.get("queue_time"))
                row["latest_run_time"] = _format_seconds(timing.get("run_time"))

        if _has_profile_data(data):
            row["profiled_count"] += 1
            summary["profiled_result_count"] += 1

        build_cache = data.get("build_cache")
        if isinstance(build_cache, dict) and build_cache:
            summary["build_cache_record_count"] += 1
            status = _clean(build_cache.get("status")).lower() or "unknown"
            if row["latest_result_file"] == record["filename"]:
                row["latest_build_cache_status"] = status
            if status == "hit":
                row["build_cache_hit_count"] += 1
                summary["build_cache_hit_count"] += 1
            elif status == "miss":
                row["build_cache_miss_count"] += 1
                summary["build_cache_miss_count"] += 1
            if build_cache.get("stored") is True:
                row["build_cache_store_count"] += 1
                summary["build_cache_store_count"] += 1

    rows = [_finalize_row(row) for row in rows_by_key.values()]
    rows.sort(key=lambda row: (row["code"].lower(), row["system"].lower()))

    summary.update(
        {
            "total_build_time": _format_seconds(totals["build_time"]["sum"]),
            "total_queue_time": _format_seconds(totals["queue_time"]["sum"]),
            "total_run_time": _format_seconds(totals["run_time"]["sum"]),
            "avg_build_time": _format_average(totals, "build_time"),
            "avg_queue_time": _format_average(totals, "queue_time"),
            "avg_run_time": _format_average(totals, "run_time"),
        }
    )

    return {
        "summary": summary,
        "rows": rows,
    }


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
            }
        )
    records.sort(key=lambda record: record["timestamp"] or datetime.min, reverse=True)
    return records


def _timing_values(raw_timing: Any) -> dict[str, float]:
    if not isinstance(raw_timing, dict):
        return {}
    timing = {}
    for field in TIMING_FIELDS:
        value = _as_float(raw_timing.get(field))
        if value is not None:
            timing[field] = value
    return timing


def _empty_timing_totals() -> dict[str, dict[str, float | int]]:
    return {field: {"sum": 0.0, "count": 0} for field in TIMING_FIELDS}


def _add_timing_totals(totals: dict[str, dict[str, float | int]], timing: dict[str, float]) -> None:
    for field, value in timing.items():
        totals[field]["sum"] = float(totals[field]["sum"]) + value
        totals[field]["count"] = int(totals[field]["count"]) + 1


def _finalize_row(row: dict[str, Any]) -> dict[str, Any]:
    totals = row.pop("_timing_totals")
    row.update(
        {
            "avg_build_time": _format_average(totals, "build_time"),
            "avg_queue_time": _format_average(totals, "queue_time"),
            "avg_run_time": _format_average(totals, "run_time"),
        }
    )
    return row


def _format_average(totals: dict[str, dict[str, float | int]], field: str) -> str:
    item = totals[field]
    count = int(item["count"])
    if count == 0:
        return "-"
    return _format_seconds(float(item["sum"]) / count)


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 60:
        return f"{_trim_decimal(value)}s"
    minutes = value / 60
    if minutes < 60:
        return f"{_trim_decimal(minutes)}m"
    hours = minutes / 60
    return f"{_trim_decimal(hours, digits=2)}h"


def _trim_decimal(value: float, *, digits: int = 1) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_profile_data(data: dict[str, Any]) -> bool:
    profile_data = data.get("profile_data")
    return isinstance(profile_data, dict) and bool(profile_data)


def _clean(value: Any) -> str:
    return str(value or "").strip()
