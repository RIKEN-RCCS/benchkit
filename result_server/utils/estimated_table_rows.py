from utils.result_records import (
    build_multiline_title,
    format_numeric_value,
    short_identifier,
    split_display_timestamp,
)

SCALING_SHORT_NAMES = {
    "instrumented-app-sections-dummy": "instr-app-sec",
    "scale-mock": "scale-mock",
}

PACKAGE_SHORT_NAMES = {
    "instrumented_app_sections_dummy": "instr_app_sec",
    "lightweight_fom_scaling": "weakscaling",
    "weakscaling": "weakscaling",
}


def build_estimated_table_row(filename, result_data, fallback_uuid=None, fallback_timestamp=None):
    current = result_data.get("current_system", {})
    future = result_data.get("future_system", {})
    estimate_meta = result_data.get("estimate_metadata", {})
    applicability = result_data.get("applicability", {})

    estimate_uuid = estimate_meta.get("estimation_result_uuid") or fallback_uuid or ""
    timestamp = estimate_meta.get("estimation_result_timestamp") or fallback_timestamp or ""

    requested_package = estimate_meta.get("requested_estimation_package", "")
    applied_package = estimate_meta.get("estimation_package", "")
    method_class = estimate_meta.get("method_class", "")
    detail_level = estimate_meta.get("detail_level", "")
    requested_current = estimate_meta.get("current_package", {}).get("requested_estimation_package", "")
    requested_future = estimate_meta.get("future_package", {}).get("requested_estimation_package", "")
    current_package = estimate_meta.get("current_package", {}).get("estimation_package", "")
    future_package = estimate_meta.get("future_package", {}).get("estimation_package", "")

    timestamp_date, timestamp_time = split_display_timestamp(timestamp)

    row = {
        "timestamp": timestamp,
        "timestamp_date": timestamp_date,
        "timestamp_time": timestamp_time,
        "code": result_data.get("code", ""),
        "exp": result_data.get("exp", ""),
        "applicability_status": applicability.get("status", ""),
        "requested_estimation_package": requested_package,
        "estimation_package": applied_package,
        "method_class": method_class,
        "detail_level": detail_level,
        "current_estimation_package": current_package,
        "future_estimation_package": future_package,
        "requested_current_estimation_package": requested_current,
        "requested_future_estimation_package": requested_future,
        "estimate_uuid": estimate_uuid,
        "estimate_uuid_short": short_identifier(estimate_uuid),
        "performance_ratio": result_data.get("performance_ratio", ""),
        "performance_ratio_display": format_numeric_value(result_data.get("performance_ratio", "")),
        "json_link": filename,
        "requested_package_short": _format_package_short_name(requested_package),
        "applied_package_short": _format_package_short_name(applied_package),
        "systemA_scaling_short": _format_scaling_short_name(current.get("scaling_method", "")),
        "systemB_scaling_short": _format_scaling_short_name(future.get("scaling_method", "")),
        "requested_package_title": _build_requested_package_title(
            requested_package,
            requested_current,
            requested_future,
        ),
        "applicability_title": _build_applicability_title(applicability),
        "applicability_meta_line": _build_applicability_meta_line(applicability),
        "applied_package_title": _build_applied_package_title(
            applied_package,
            method_class,
            detail_level,
            current_package,
            future_package,
        ),
        "applied_package_meta_line": _build_applied_package_meta_line(method_class, detail_level),
    }
    row.update(_build_estimated_system_fields("systemA", current))
    row.update(_build_estimated_system_fields("systemB", future))
    return row


def build_estimated_table_columns():
    return [
        {"label": "Timestamp", "key": "timestamp", "section": "leading"},
        {"label": "CODE", "key": "code", "section": "leading"},
        {"label": "Exp", "key": "exp", "section": "leading"},
        *_build_estimated_system_columns("System A", "systemA"),
        *_build_estimated_system_columns("System B", "systemB"),
        {"label": "Applicability", "key": "applicability_status", "section": "trailing", "title_key": "applicability_title", "meta_key": "applicability_meta_line"},
        {"label": "Req. Pkg", "key": "requested_package_short", "section": "trailing", "title_key": "requested_package_title"},
        {"label": "Applied Pkg", "key": "applied_package_short", "section": "trailing", "title_key": "applied_package_title", "meta_key": "applied_package_meta_line"},
        {"label": "UUID", "key": "estimate_uuid_short", "section": "trailing", "title_key": "estimate_uuid", "cell_class": "estimated-code-cell"},
        {"label": "Ratio", "key": "performance_ratio_display", "section": "trailing", "title_key": "performance_ratio", "align": "right"},
        {"label": "JSON", "key": "json_link", "section": "trailing", "cell_class": "estimated-link-cell"},
    ]


def _build_estimated_system_fields(prefix, system_data):
    benchmark = system_data.get("benchmark", {})
    fom = system_data.get("fom", "")
    benchmark_fom = benchmark.get("fom", "")
    scaling_method = system_data.get("scaling_method", "")
    return {
        f"{prefix}_system": system_data.get("system", ""),
        f"{prefix}_fom": fom,
        f"{prefix}_fom_display": format_numeric_value(fom),
        f"{prefix}_target_nodes": system_data.get("target_nodes", ""),
        f"{prefix}_scaling_method": scaling_method,
        f"{prefix}_scaling_title": scaling_method,
        f"{prefix}_bench_system": benchmark.get("system", ""),
        f"{prefix}_bench_fom": benchmark_fom,
        f"{prefix}_bench_fom_display": format_numeric_value(benchmark_fom),
        f"{prefix}_bench_nodes": benchmark.get("nodes", ""),
        f"{prefix}_scaling_short": _format_scaling_short_name(scaling_method),
    }


def _build_estimated_system_columns(group_label, key_prefix):
    return [
        {"label": "System", "key": f"{key_prefix}_system", "group": group_label},
        {"label": "FOM", "key": f"{key_prefix}_fom_display", "group": group_label, "title_key": f"{key_prefix}_fom", "align": "right"},
        {"label": "Nodes", "key": f"{key_prefix}_target_nodes", "group": group_label},
        {"label": "Scaling", "key": f"{key_prefix}_scaling_short", "group": group_label, "title_key": f"{key_prefix}_scaling_title"},
        {"label": "Bench", "key": f"{key_prefix}_bench_system", "group": group_label},
        {"label": "Bench FOM", "key": f"{key_prefix}_bench_fom_display", "group": group_label, "title_key": f"{key_prefix}_bench_fom", "align": "right"},
        {"label": "Bench Nodes", "key": f"{key_prefix}_bench_nodes", "group": group_label},
    ]


def _format_scaling_short_name(value):
    return SCALING_SHORT_NAMES.get(value, value)


def _format_package_short_name(value):
    return PACKAGE_SHORT_NAMES.get(value, value)


def _build_requested_package_title(requested_package, requested_current, requested_future):
    return build_multiline_title(
        requested_package,
        [
            ("current-side", requested_current),
            ("future-side", requested_future),
        ],
    )


def _build_applied_package_title(applied_package, method_class, detail_level, current_package, future_package):
    return build_multiline_title(
        applied_package,
        [
            ("class", method_class),
            ("detail", detail_level),
            ("current-side", current_package),
            ("future-side", future_package),
        ],
    )


def _build_applied_package_meta_line(method_class, detail_level):
    meta_parts = [part for part in (method_class, detail_level) if part]
    return " / ".join(meta_parts)


def _build_applicability_title(applicability):
    return build_multiline_title(
        applicability.get("status", ""),
        [
            ("fallback", applicability.get("fallback_used", "")),
            ("missing", ", ".join(applicability.get("missing_inputs", []))),
            ("actions", ", ".join(applicability.get("required_actions", []))),
        ],
    )


def _build_applicability_meta_line(applicability):
    if applicability.get("fallback_used"):
        return f"fallback -> {applicability['fallback_used']}"
    if applicability.get("required_actions"):
        return f"action: {applicability['required_actions'][0]}"
    if applicability.get("missing_inputs"):
        first = applicability["missing_inputs"][0]
        extra = len(applicability["missing_inputs"]) - 1
        if extra > 0:
            return f"missing: {first} (+{extra})"
        return f"missing: {first}"
    return ""
