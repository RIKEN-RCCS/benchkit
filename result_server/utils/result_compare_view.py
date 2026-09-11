from flask import abort

from utils.result_file import check_file_permission, load_public_result_json
from utils.result_records import (
    build_axis_label,
    build_compare_headline,
    format_numeric_value,
    format_result_timestamp,
    input_info_items_for_result,
    load_result_json_batch,
    short_identifier,
    summarize_result_quality,
)


def build_result_compare_context(results, *, include_evidence=True):
    rows = [row.get("data") or {} for row in results]
    has_vector_metrics = any(row.get("metrics", {}).get("vector") for row in rows)

    headline = ""
    mixed = False
    if rows:
        first_system = rows[0].get("system")
        first_code = rows[0].get("code")
        mixed = any(
            row.get("system") != first_system or row.get("code") != first_code
            for row in rows[1:]
        )
        headline = build_compare_headline(first_system, first_code, len(results))

    first_result = rows[0] if rows else {}
    vector_axis = {}
    if has_vector_metrics:
        for row in rows:
            vector = (row.get("metrics") or {}).get("vector") or {}
            x_axis = vector.get("x_axis") or {}
            if x_axis.get("name") or x_axis.get("unit"):
                vector_axis = x_axis
                break

    return {
        "results": results,
        "headline": headline,
        "has_vector_metrics": has_vector_metrics,
        "mixed": mixed,
        "comparison_summary": build_comparison_summary(
            results,
            include_evidence=include_evidence,
        ),
        "compare_chart": {
            "vector_axis_label": build_axis_label(vector_axis.get("name"), vector_axis.get("unit")),
            "fom_unit": first_result.get("FOM_unit") or "",
        },
    }


def build_comparison_summary(results, *, include_evidence=True):
    result_rows = [
        _summarize_compare_result(row, include_evidence=include_evidence)
        for row in results
    ]
    baseline = result_rows[0] if result_rows else {}
    latest = result_rows[-1] if result_rows else {}
    diff_rows = _build_diff_rows(baseline, latest) if len(result_rows) >= 2 else []
    return {
        "include_evidence": include_evidence,
        "baseline": baseline,
        "latest": latest,
        "fom_change": _build_fom_change(baseline, latest) if len(result_rows) >= 2 else {},
        "diff_rows": diff_rows,
        "result_rows": result_rows,
        "has_differences": any(row["status"] == "changed" for row in diff_rows),
    }


def load_result_compare_context(filenames, directory, *, public_surface=False):
    if public_surface:
        results = _load_public_result_json_batch(filenames, directory)
        return build_result_compare_context([
            _project_public_compare_result(row) for row in results
        ], include_evidence=False)

    for filename in filenames:
        check_file_permission(filename, directory)
    results = load_result_json_batch(filenames, directory)
    if len(results) != len(filenames):
        abort(404, "Result file not found")
    return build_result_compare_context(results)


def _load_public_result_json_batch(filenames, directory):
    results = []
    for filename in filenames:
        results.append({
            "filename": filename,
            "timestamp": format_result_timestamp(filename),
            "data": load_public_result_json(filename, directory),
        })

    results.sort(key=lambda item: item["timestamp"])
    return results


def _project_public_compare_result(row):
    data = row.get("data") or {}
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    public_metrics = {}
    if isinstance(metrics.get("vector"), dict):
        public_metrics["vector"] = metrics["vector"]

    public_data = {
        "code": data.get("code"),
        "system": data.get("system"),
        "Exp": data.get("Exp"),
        "FOM": data.get("FOM"),
        "FOM_unit": data.get("FOM_unit") or "",
    }
    if public_metrics:
        public_data["metrics"] = public_metrics

    return {
        "timestamp": row.get("timestamp"),
        "data": public_data,
    }


def _summarize_compare_result(row, *, include_evidence=True):
    data = row.get("data") or {}
    summary = {
        "timestamp": row.get("timestamp") or "-",
        "code": _display_value(data.get("code")),
        "system": _display_value(data.get("system")),
        "exp": _display_value(data.get("Exp") or data.get("exp")),
        "fom": data.get("FOM"),
        "fom_display": _display_value(format_numeric_value(data.get("FOM"))),
        "fom_unit": data.get("FOM_unit") or "",
    }
    if not include_evidence:
        return summary

    quality = summarize_result_quality(data)
    input_summary = _input_summary(data, quality["stats"])
    source_summary = _source_summary(data.get("source_info"))
    build_cache_summary = _build_cache_summary(data.get("build_cache"))
    profile_summary = _profile_summary(data.get("profile_data"))
    summary.update({
        "quality": quality["label"],
        "source_display": source_summary["display"],
        "source_key": source_summary["key"],
        "input_display": input_summary["display"],
        "input_key": input_summary["key"],
        "build_cache_display": build_cache_summary["display"],
        "build_cache_key": build_cache_summary["key"],
        "profile_display": profile_summary["display"],
        "profile_key": profile_summary["key"],
    })
    return summary


def _build_fom_change(baseline, latest):
    baseline_fom = _as_float(baseline.get("fom"))
    latest_fom = _as_float(latest.get("fom"))
    if baseline_fom is None or latest_fom is None:
        return {
            "available": False,
            "ratio_display": "-",
            "delta_display": "-",
            "percent_display": "-",
            "note": "FOM change is unavailable because one selected result has no numeric FOM.",
        }
    if baseline_fom == 0:
        return {
            "available": False,
            "ratio_display": "-",
            "delta_display": format_numeric_value(latest_fom - baseline_fom),
            "percent_display": "-",
            "note": "FOM ratio is unavailable because the baseline FOM is zero.",
        }

    ratio = latest_fom / baseline_fom
    delta = latest_fom - baseline_fom
    percent = (ratio - 1.0) * 100.0
    return {
        "available": True,
        "ratio_display": format_numeric_value(ratio),
        "delta_display": _format_signed(delta),
        "percent_display": _format_signed(percent, suffix="%"),
        "note": "Ratio is latest FOM divided by baseline FOM; no pass/fail judgement is applied.",
    }


def _build_diff_rows(baseline, latest):
    specs = [
        ("System", "system"),
        ("Code", "code"),
        ("Exp", "exp"),
    ]
    if "source_display" in baseline or "source_display" in latest:
        specs.extend([
            ("Source", "source"),
            ("Input", "input"),
            ("Build Cache", "build_cache"),
            ("Profile", "profile"),
            ("Quality", "quality"),
        ])
    rows = []
    display_keys = {"source", "input", "build_cache", "profile"}
    for label, key in specs:
        baseline_display = (
            baseline.get(f"{key}_display") if key in display_keys else baseline.get(key)
        )
        latest_display = (
            latest.get(f"{key}_display") if key in display_keys else latest.get(key)
        )
        baseline_key = baseline.get(f"{key}_key", baseline_display)
        latest_key = latest.get(f"{key}_key", latest_display)
        rows.append(
            {
                "label": label,
                "baseline": baseline_display or "-",
                "latest": latest_display or "-",
                "status": "same" if baseline_key == latest_key else "changed",
            }
        )
    return rows


def _source_summary(source_info):
    if not isinstance(source_info, dict) or not source_info:
        return {"display": "not tracked", "key": ("none",)}

    source_type = str(source_info.get("source_type") or "unknown").strip() or "unknown"
    if source_type == "git":
        ref_name = source_info.get("ref_name") or source_info.get("branch") or "-"
        commit = source_info.get("resolved_commit") or source_info.get("commit_hash") or ""
        display = f"git {ref_name}"
        if commit:
            display = f"{display}@{short_identifier(str(commit), 8)}"
        return {"display": display, "key": ("git", ref_name, commit)}

    if source_type == "file":
        digest = source_info.get("sha256sum") or source_info.get("md5sum") or ""
        display = "file source"
        if digest:
            display = f"{display} {short_identifier(str(digest), 12)}"
        return {"display": display, "key": ("file", digest)}

    return {"display": source_type, "key": (source_type,)}


def _input_summary(data, stats):
    status = stats.get("input_info_status") or "none"
    label = stats.get("input_info_label") or "None"
    descriptors = _input_descriptors(data)
    display = label if not descriptors else f"{label}: {'; '.join(descriptors[:2])}"
    if len(descriptors) > 2:
        display = f"{display}; +{len(descriptors) - 2} more"
    return {"display": display, "key": (status, tuple(descriptors))}


def _input_descriptors(data):
    items = input_info_items_for_result(data)
    descriptors = []
    for item in items:
        if not isinstance(item, dict):
            continue
        parts = []
        dataset_id = str(item.get("dataset_id") or item.get("name") or "").strip()
        version = str(item.get("dataset_version") or item.get("version") or "").strip()
        digest = _first_present(
            item,
            ("manifest_digest", "content_digest", "sha256", "sha256sum", "digest"),
        )
        if dataset_id:
            parts.append(dataset_id)
        if version:
            parts.append(version)
        if digest:
            parts.append(short_identifier(str(digest), 12))
        if parts:
            descriptors.append("@".join(parts))
    return descriptors


def _build_cache_summary(build_cache):
    if not isinstance(build_cache, dict) or not build_cache:
        return {"display": "not recorded", "key": ("none",)}
    status = str(build_cache.get("status") or "unknown").strip() or "unknown"
    stored = build_cache.get("stored") is True
    display = f"{status} stored" if stored else status
    entry = build_cache.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    digests = entry.get("digests")
    digests = digests if isinstance(digests, dict) else {}
    key = (
        status,
        stored,
        entry.get("host_environment_fingerprint")
        or build_cache.get("host_environment_fingerprint")
        or "",
        digests.get("build_inputs") or build_cache.get("build_inputs_hash") or "",
        digests.get("source_info") or build_cache.get("source_info_digest") or "",
        digests.get("artifacts")
        or build_cache.get("artifact_tree_digest")
        or build_cache.get("cached_artifacts_digest")
        or "",
    )
    return {"display": display, "key": key}


def _profile_summary(profile_data):
    if not isinstance(profile_data, dict) or not profile_data:
        return {"display": "none", "key": ("none",)}
    tool = str(profile_data.get("tool") or profile_data.get("profiler") or "recorded").strip()
    level = str(profile_data.get("level") or profile_data.get("profile_level") or "").strip()
    display = f"{tool} / {level}" if level else tool
    return {"display": display, "key": (tool, level)}


def _first_present(data, keys):
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return ""


def _display_value(value):
    return str(value) if value not in (None, "") else "-"


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_signed(value, suffix=""):
    formatted = format_numeric_value(value)
    if value > 0:
        return f"+{formatted}{suffix}"
    return f"{formatted}{suffix}"
