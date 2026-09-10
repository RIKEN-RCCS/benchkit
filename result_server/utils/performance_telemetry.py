"""Execution timing and build-cache telemetry for Usage Report."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.node_hours import extract_timestamp_from_filename
from utils.result_records import format_result_timestamp, load_result_json


TIMING_FIELDS = ("build_time", "queue_time", "run_time")
CODE_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
REPO_ROOT = Path(__file__).resolve().parents[2]
TIMING_SOURCE_LABELS = {
    "not_measured": "not measured",
    "timestamp_files": "timestamp files",
    "runner_metadata": "runner metadata",
    "scheduler_metadata": "scheduler metadata",
    "scheduler_logs": "scheduler logs",
    "gitlab_job_started_at": "GitLab job queue",
    "gitlab_metadata": "GitLab metadata",
}


def build_performance_telemetry(received_dir: str, estimated_dir: str | None = None) -> dict[str, Any]:
    """Summarize available timing records for operator usage reports."""
    records = _load_result_records(received_dir)
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    totals = _empty_timing_totals()
    regular_run_totals = _empty_scalar_total()
    profiled_run_totals = _empty_scalar_total()
    estimate_totals = _empty_scalar_total()
    scheduler_queue_totals = _empty_scalar_total()
    profile_overhead_totals = _empty_overhead_total()
    summary = {
        "result_count": 0,
        "ignored_result_count": 0,
        "timing_record_count": 0,
        "scheduler_queue_timing_count": 0,
        "profiled_result_count": 0,
        "regular_run_timing_count": 0,
        "profiled_run_timing_count": 0,
        "profile_overhead_pair_count": 0,
        "estimate_record_count": 0,
        "estimate_timing_record_count": 0,
        "build_cache_record_count": 0,
        "build_cache_hit_count": 0,
        "build_cache_miss_count": 0,
        "build_cache_store_count": 0,
    }

    for record in records:
        data = record["data"]
        if not _is_performance_record(data):
            summary["ignored_result_count"] += 1
            continue

        code = _clean(data.get("code")) or "unknown"
        system = _clean(data.get("system")) or "unknown"
        key = (code, system)
        summary["result_count"] += 1
        row = rows_by_key.setdefault(
            key,
            {
                "code": code,
                "system": system,
                "result_count": 0,
                "timing_count": 0,
                "scheduler_queue_timing_count": 0,
                "profiled_count": 0,
                "regular_run_timing_count": 0,
                "profiled_run_timing_count": 0,
                "profile_overhead_pair_count": 0,
                "profile_overhead_status": "-",
                "avg_profile_overhead_delta": "-",
                "avg_profile_overhead_ratio": "-",
                "run_conditions": [],
                "estimate_count": 0,
                "estimate_timing_count": 0,
                "build_cache_hit_count": 0,
                "build_cache_miss_count": 0,
                "build_cache_store_count": 0,
                "latest_result_file": record["filename"],
                "latest_result_time": record["timestamp_label"],
                "latest_exp": _clean(data.get("Exp")) or "-",
                "latest_build_time": "-",
                "latest_queue_time": "-",
                "latest_queue_time_source": "-",
                "latest_scheduler_queue_time": "-",
                "latest_scheduler_queue_time_source": "-",
                "latest_run_time": "-",
                "latest_run_kind": "-",
                "latest_build_cache_status": "-",
                "latest_estimate_file": "",
                "latest_estimate_time": "-",
                "latest_estimate_elapsed_time": "-",
                "latest_estimate_exp": "-",
                "_timing_totals": _empty_timing_totals(),
                "_regular_run_totals": _empty_scalar_total(),
                "_profiled_run_totals": _empty_scalar_total(),
                "_estimate_totals": _empty_scalar_total(),
                "_scheduler_queue_totals": _empty_scalar_total(),
                "_run_conditions": {},
            },
        )
        row["result_count"] += 1
        is_profiled = _has_profile_data(data)
        run_kind = "profiled" if is_profiled else "regular"
        _add_run_condition_result(row["_run_conditions"], data, run_kind)

        raw_timing = data.get("pipeline_timing")
        timing = _timing_values(raw_timing)
        scheduler_queue_time = _scheduler_queue_time(raw_timing)
        if timing or scheduler_queue_time is not None:
            row["timing_count"] += 1
            summary["timing_record_count"] += 1
            _add_timing_totals(row["_timing_totals"], timing)
            _add_timing_totals(totals, timing)
            if scheduler_queue_time is not None:
                row["scheduler_queue_timing_count"] += 1
                summary["scheduler_queue_timing_count"] += 1
                _add_scalar_total(row["_scheduler_queue_totals"], scheduler_queue_time)
                _add_scalar_total(scheduler_queue_totals, scheduler_queue_time)
            run_time = timing.get("run_time")
            if run_time is not None:
                _add_run_condition_timing(row["_run_conditions"], data, run_kind, run_time)
                if is_profiled:
                    row["profiled_run_timing_count"] += 1
                    summary["profiled_run_timing_count"] += 1
                    _add_scalar_total(row["_profiled_run_totals"], run_time)
                    _add_scalar_total(profiled_run_totals, run_time)
                else:
                    row["regular_run_timing_count"] += 1
                    summary["regular_run_timing_count"] += 1
                    _add_scalar_total(row["_regular_run_totals"], run_time)
                    _add_scalar_total(regular_run_totals, run_time)

            if row["latest_result_file"] == record["filename"]:
                row["latest_build_time"] = _format_seconds(timing.get("build_time"))
                row["latest_queue_time"] = _format_seconds(timing.get("queue_time"))
                row["latest_queue_time_source"] = _timing_source_label(
                    _nested_value(raw_timing, "queue_time_source")
                )
                row["latest_scheduler_queue_time"] = _format_seconds(scheduler_queue_time)
                row["latest_scheduler_queue_time_source"] = _timing_source_label(
                    _nested_value(raw_timing, "scheduler_queue_time_source")
                )
                row["latest_run_time"] = _format_seconds(timing.get("run_time"))
                row["latest_run_kind"] = run_kind

        if is_profiled:
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

    if estimated_dir:
        _merge_estimate_timing(rows_by_key, estimated_dir, summary, estimate_totals)

    rows = []
    for row in rows_by_key.values():
        finalized_row = _finalize_row(row)
        _add_overhead_total(profile_overhead_totals, finalized_row)
        rows.append(_strip_temporary_fields(finalized_row))
    rows.sort(key=lambda row: (row["code"].lower(), row["system"].lower()))
    summary["profile_overhead_pair_count"] = sum(row["profile_overhead_pair_count"] for row in rows)

    summary.update(
        {
            "total_build_time": _format_seconds(totals["build_time"]["sum"]),
            "total_queue_time": _format_seconds(totals["queue_time"]["sum"]),
            "total_run_time": _format_seconds(totals["run_time"]["sum"]),
            "avg_build_time": _format_average(totals, "build_time"),
            "avg_queue_time": _format_average(totals, "queue_time"),
            "avg_scheduler_queue_time": _format_scalar_average(scheduler_queue_totals),
            "avg_run_time": _format_average(totals, "run_time"),
            "avg_regular_run_time": _format_scalar_average(regular_run_totals),
            "avg_profiled_run_time": _format_scalar_average(profiled_run_totals),
            "avg_profile_overhead_delta": _format_overhead_delta(profile_overhead_totals),
            "avg_profile_overhead_ratio": _format_overhead_ratio(profile_overhead_totals),
            "avg_estimate_time": _format_scalar_average(estimate_totals),
        }
    )

    return {
        "summary": summary,
        "rows": rows,
    }


def _load_result_records(received_dir: str) -> list[dict[str, Any]]:
    return _load_json_records(received_dir)


def _load_estimate_records(estimated_dir: str) -> list[dict[str, Any]]:
    return _load_json_records(estimated_dir, prefix="estimate_")


def _load_json_records(directory: str, *, prefix: str = "") -> list[dict[str, Any]]:
    try:
        filenames = [
            name
            for name in os.listdir(directory)
            if name.endswith(".json") and (not prefix or name.startswith(prefix))
        ]
    except OSError:
        filenames = []

    records = []
    for filename in filenames:
        data = load_result_json(filename, directory)
        if not isinstance(data, dict):
            continue
        timestamp = extract_timestamp_from_filename(filename)
        records.append(
            {
                "filename": filename,
                "timestamp": timestamp,
                "sort_key": timestamp or datetime.min,
                "timestamp_label": format_result_timestamp(filename),
                "data": data,
            }
        )
    records.sort(key=lambda record: record["sort_key"], reverse=True)
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


def _scheduler_queue_time(raw_timing: Any) -> float | None:
    if not isinstance(raw_timing, dict):
        return None
    for field in ("scheduler_queue_time", "scheduler_queue_seconds"):
        value = _as_float(raw_timing.get(field))
        if value is not None:
            return value
    return None


def _timing_source_label(value: Any) -> str:
    source = _clean(value).lower().replace("-", "_")
    if not source:
        return "-"
    return TIMING_SOURCE_LABELS.get(source, "provided")


def _empty_timing_totals() -> dict[str, dict[str, float | int]]:
    return {field: {"sum": 0.0, "count": 0} for field in TIMING_FIELDS}


def _add_timing_totals(totals: dict[str, dict[str, float | int]], timing: dict[str, float]) -> None:
    for field, value in timing.items():
        totals[field]["sum"] = float(totals[field]["sum"]) + value
        totals[field]["count"] = int(totals[field]["count"]) + 1


def _empty_scalar_total() -> dict[str, float | int]:
    return {"sum": 0.0, "count": 0}


def _add_scalar_total(total: dict[str, float | int], value: float) -> None:
    total["sum"] = float(total["sum"]) + value
    total["count"] = int(total["count"]) + 1


def _empty_overhead_total() -> dict[str, float | int]:
    return {"delta_sum": 0.0, "ratio_sum": 0.0, "count": 0}


def _add_overhead_total(total: dict[str, float | int], row: dict[str, Any]) -> None:
    count = int(row.get("_profile_overhead_metric_count") or 0)
    if count == 0:
        return
    total["delta_sum"] = float(total["delta_sum"]) + float(row["_profile_overhead_delta_sum"])
    total["ratio_sum"] = float(total["ratio_sum"]) + float(row["_profile_overhead_ratio_sum"])
    total["count"] = int(total["count"]) + count


def _merge_estimate_timing(
    rows_by_key: dict[tuple[str, str], dict[str, Any]],
    estimated_dir: str,
    summary: dict[str, Any],
    estimate_totals: dict[str, float | int],
) -> None:
    for record in _load_estimate_records(estimated_dir):
        data = record["data"]
        if not _is_estimate_record(data):
            continue
        summary["estimate_record_count"] += 1

        key = _estimate_row_key(data)
        if key is None:
            continue
        row = rows_by_key.get(key)
        if row is None:
            continue

        row["estimate_count"] += 1
        elapsed_time = _estimate_elapsed_time(data)
        if elapsed_time is not None:
            row["estimate_timing_count"] += 1
            summary["estimate_timing_record_count"] += 1
            _add_scalar_total(row["_estimate_totals"], elapsed_time)
            _add_scalar_total(estimate_totals, elapsed_time)

        current_sort_key = row.get("_estimate_sort_key")
        if current_sort_key is None or current_sort_key < record["sort_key"]:
            row["_estimate_sort_key"] = record["sort_key"]
            row["latest_estimate_file"] = record["filename"]
            row["latest_estimate_time"] = record["timestamp_label"]
            row["latest_estimate_elapsed_time"] = _format_seconds(elapsed_time)
            row["latest_estimate_exp"] = _clean(data.get("exp")) or "-"


def _finalize_row(row: dict[str, Any]) -> dict[str, Any]:
    totals = row.pop("_timing_totals")
    regular_run_totals = row.pop("_regular_run_totals")
    profiled_run_totals = row.pop("_profiled_run_totals")
    estimate_totals = row.pop("_estimate_totals")
    scheduler_queue_totals = row.pop("_scheduler_queue_totals")
    run_conditions = row.pop("_run_conditions")
    profile_overhead_pair_count = _profile_overhead_pair_count(run_conditions)
    profile_overhead = _profile_overhead_metrics(run_conditions)
    row.pop("_estimate_sort_key", None)
    row.update(
        {
            "avg_build_time": _format_average(totals, "build_time"),
            "avg_queue_time": _format_average(totals, "queue_time"),
            "avg_scheduler_queue_time": _format_scalar_average(scheduler_queue_totals),
            "avg_run_time": _format_average(totals, "run_time"),
            "avg_regular_run_time": _format_scalar_average(regular_run_totals),
            "avg_profiled_run_time": _format_scalar_average(profiled_run_totals),
            "avg_estimate_time": _format_scalar_average(estimate_totals),
            "profile_overhead_pair_count": profile_overhead_pair_count,
            "profile_overhead_status": _profile_overhead_status(row, profile_overhead_pair_count),
            "avg_profile_overhead_delta": _format_overhead_delta(profile_overhead),
            "avg_profile_overhead_ratio": _format_overhead_ratio(profile_overhead),
            "run_conditions": _run_condition_rows(run_conditions),
            "_profile_overhead_metric_count": profile_overhead["count"],
            "_profile_overhead_delta_sum": profile_overhead["delta_sum"],
            "_profile_overhead_ratio_sum": profile_overhead["ratio_sum"],
        }
    )
    return row


def _run_pair_key(data: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return tuple(
        _clean(data.get(field)) or "-"
        for field in ("Exp", "node_count", "numproc_node", "nthreads", "FOM_version")
    )


def _add_run_condition_result(
    run_conditions: dict[tuple[str, ...], dict[str, Any]],
    data: dict[str, Any],
    run_kind: str,
) -> None:
    condition = _ensure_run_condition(run_conditions, data)
    condition[f"{run_kind}_result_count"] += 1


def _add_run_condition_timing(
    run_conditions: dict[tuple[str, ...], dict[str, Any]],
    data: dict[str, Any],
    run_kind: str,
    run_time: float,
) -> None:
    condition = _ensure_run_condition(run_conditions, data)
    condition[f"{run_kind}_run_timing_count"] += 1
    _add_scalar_total(condition[f"_{run_kind}_run_totals"], run_time)


def _ensure_run_condition(
    run_conditions: dict[tuple[str, ...], dict[str, Any]],
    data: dict[str, Any],
) -> dict[str, Any]:
    key = _run_pair_key(data)
    if key not in run_conditions:
        exp, node_count, numproc_node, nthreads, fom_version = key
        run_conditions[key] = {
            "exp": exp,
            "node_count": node_count,
            "numproc_node": numproc_node,
            "nthreads": nthreads,
            "fom_version": fom_version,
            "regular_result_count": 0,
            "profiled_result_count": 0,
            "regular_run_timing_count": 0,
            "profiled_run_timing_count": 0,
            "_regular_run_totals": _empty_scalar_total(),
            "_profiled_run_totals": _empty_scalar_total(),
        }
    return run_conditions[key]


def _profile_overhead_pair_count(
    run_conditions: dict[tuple[str, ...], dict[str, Any]],
) -> int:
    return sum(
        1
        for condition in run_conditions.values()
        if int(condition["regular_run_timing_count"]) and int(condition["profiled_run_timing_count"])
    )


def _profile_overhead_metrics(
    run_conditions: dict[tuple[str, ...], dict[str, Any]],
) -> dict[str, float | int]:
    metrics = _empty_overhead_total()
    for condition in run_conditions.values():
        regular_avg = _scalar_average(condition["_regular_run_totals"])
        profiled_avg = _scalar_average(condition["_profiled_run_totals"])
        if regular_avg is None or profiled_avg is None or regular_avg <= 0:
            continue
        metrics["delta_sum"] = float(metrics["delta_sum"]) + (profiled_avg - regular_avg)
        metrics["ratio_sum"] = float(metrics["ratio_sum"]) + (profiled_avg / regular_avg)
        metrics["count"] = int(metrics["count"]) + 1
    return metrics


def _run_condition_rows(run_conditions: dict[tuple[str, ...], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for condition in run_conditions.values():
        regular_avg = _scalar_average(condition["_regular_run_totals"])
        profiled_avg = _scalar_average(condition["_profiled_run_totals"])
        overhead = _condition_overhead_metrics(regular_avg, profiled_avg)
        rows.append(
            {
                "label": _run_condition_label(condition),
                "exp": condition["exp"],
                "node_count": condition["node_count"],
                "numproc_node": condition["numproc_node"],
                "nthreads": condition["nthreads"],
                "fom_version": condition["fom_version"],
                "regular_result_count": condition["regular_result_count"],
                "profiled_result_count": condition["profiled_result_count"],
                "regular_run_timing_count": condition["regular_run_timing_count"],
                "profiled_run_timing_count": condition["profiled_run_timing_count"],
                "avg_regular_run_time": _format_seconds(regular_avg),
                "avg_profiled_run_time": _format_seconds(profiled_avg),
                "avg_profile_overhead_delta": _format_overhead_delta(overhead),
                "avg_profile_overhead_ratio": _format_overhead_ratio(overhead),
                "profile_overhead_status": _run_condition_status(
                    condition,
                    regular_avg,
                    profiled_avg,
                ),
            }
        )
    rows.sort(key=_run_condition_sort_key)
    return rows


def _condition_overhead_metrics(
    regular_avg: float | None,
    profiled_avg: float | None,
) -> dict[str, float | int]:
    metrics = _empty_overhead_total()
    if regular_avg is None or profiled_avg is None or regular_avg <= 0:
        return metrics
    metrics["delta_sum"] = profiled_avg - regular_avg
    metrics["ratio_sum"] = profiled_avg / regular_avg
    metrics["count"] = 1
    return metrics


def _run_condition_status(
    condition: dict[str, Any],
    regular_avg: float | None,
    profiled_avg: float | None,
) -> str:
    if regular_avg is not None and profiled_avg is not None:
        return "observed from matching dimensions"
    if condition["profiled_run_timing_count"] and condition["regular_result_count"]:
        return "needs regular run timing"
    if condition["regular_run_timing_count"] and condition["profiled_result_count"]:
        return "needs profiled run timing"
    if condition["profiled_run_timing_count"]:
        return "needs matching regular run"
    if condition["regular_run_timing_count"]:
        return "needs matching profiled run"
    if condition["regular_result_count"] and condition["profiled_result_count"]:
        return "needs run timing"
    if condition["regular_result_count"]:
        return "regular run timing not recorded"
    if condition["profiled_result_count"]:
        return "profiled run timing not recorded"
    return "-"


def _run_condition_label(condition: dict[str, Any]) -> str:
    return (
        f"{condition['exp']} / N{condition['node_count']} "
        f"P{condition['numproc_node']} T{condition['nthreads']} / {condition['fom_version']}"
    )


def _run_condition_sort_key(condition: dict[str, Any]) -> tuple[Any, ...]:
    return (
        condition["exp"].lower(),
        _numeric_sort_value(condition["node_count"]),
        _numeric_sort_value(condition["numproc_node"]),
        _numeric_sort_value(condition["nthreads"]),
        condition["fom_version"].lower(),
    )


def _numeric_sort_value(value: str) -> tuple[int, float | str]:
    try:
        return (0, float(value))
    except ValueError:
        return (1, value.lower())


def _profile_overhead_status(row: dict[str, Any], pair_count: int) -> str:
    if pair_count:
        return "observed from matching dimensions"
    if row["regular_run_timing_count"] and row["profiled_run_timing_count"]:
        return "needs matching run dimensions"
    if row["regular_run_timing_count"]:
        return "needs matching profiled run"
    if row["profiled_run_timing_count"]:
        return "needs matching regular run"
    return "-"


def _format_average(totals: dict[str, dict[str, float | int]], field: str) -> str:
    item = totals[field]
    count = int(item["count"])
    if count == 0:
        return "-"
    return _format_seconds(float(item["sum"]) / count)


def _format_scalar_average(total: dict[str, float | int]) -> str:
    value = _scalar_average(total)
    if value is None:
        return "-"
    return _format_seconds(value)


def _scalar_average(total: dict[str, float | int]) -> float | None:
    count = int(total["count"])
    if count == 0:
        return None
    return float(total["sum"]) / count


def _format_overhead_delta(total: dict[str, float | int]) -> str:
    count = int(total["count"])
    if count == 0:
        return "-"
    return _format_seconds(float(total["delta_sum"]) / count)


def _format_overhead_ratio(total: dict[str, float | int]) -> str:
    count = int(total["count"])
    if count == 0:
        return "-"
    return f"{_trim_decimal(float(total['ratio_sum']) / count, digits=2)}x"


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value < 60:
        return f"{sign}{_trim_decimal(value)}s"
    minutes = value / 60
    if minutes < 60:
        return f"{sign}{_trim_decimal(minutes)}m"
    hours = minutes / 60
    return f"{sign}{_trim_decimal(hours, digits=2)}h"


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


def _is_performance_record(data: dict[str, Any]) -> bool:
    code = _clean(data.get("code"))
    system = _clean(data.get("system"))
    if not code or not system:
        return False
    if not CODE_COMPONENT_RE.fullmatch(code):
        return False
    if not (REPO_ROOT / "programs" / code).is_dir():
        return False
    return bool(
        _timing_values(data.get("pipeline_timing"))
        or _scheduler_queue_time(data.get("pipeline_timing")) is not None
        or _has_profile_data(data)
        or _has_build_cache_data(data)
        or "FOM" in data
    )


def _is_estimate_record(data: dict[str, Any]) -> bool:
    code = _clean(data.get("code"))
    if not code or not CODE_COMPONENT_RE.fullmatch(code):
        return False
    return (REPO_ROOT / "programs" / code).is_dir()


def _estimate_row_key(data: dict[str, Any]) -> tuple[str, str] | None:
    code = _clean(data.get("code"))
    system = (
        _clean(_nested_value(data, "estimate_metadata", "source_result", "system"))
        or _clean(_nested_value(data, "estimate_metadata", "future_source_result", "system"))
        or _clean(_nested_value(data, "current_system", "benchmark", "system"))
        or _clean(_nested_value(data, "current_system", "system"))
    )
    if not code or not system:
        return None
    return (code, system)


def _estimate_elapsed_time(data: dict[str, Any]) -> float | None:
    timing = data.get("estimation_timing")
    if not isinstance(timing, dict):
        return None
    for field in ("elapsed_time", "elapsed_seconds", "duration_seconds", "duration"):
        value = _as_float(timing.get(field))
        if value is not None:
            return value
    return None


def _has_build_cache_data(data: dict[str, Any]) -> bool:
    build_cache = data.get("build_cache")
    return isinstance(build_cache, dict) and bool(build_cache)


def _strip_temporary_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _nested_value(data: dict[str, Any], *path: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _clean(value: Any) -> str:
    return str(value or "").strip()
