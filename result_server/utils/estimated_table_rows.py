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

    return {
        "timestamp": timestamp,
        "timestamp_date": _get_timestamp_date(timestamp),
        "timestamp_time": _get_timestamp_time(timestamp),
        "code": result_data.get("code", ""),
        "exp": result_data.get("exp", ""),
        "systemA_system": current.get("system", ""),
        "systemA_fom": current.get("fom", ""),
        "systemA_fom_display": _format_numeric_display(current.get("fom", "")),
        "systemA_target_nodes": current.get("target_nodes", ""),
        "systemA_scaling_method": current.get("scaling_method", ""),
        "systemA_scaling_title": current.get("scaling_method", ""),
        "systemA_bench_system": current.get("benchmark", {}).get("system", ""),
        "systemA_bench_fom": current.get("benchmark", {}).get("fom", ""),
        "systemA_bench_fom_display": _format_numeric_display(current.get("benchmark", {}).get("fom", "")),
        "systemA_bench_nodes": current.get("benchmark", {}).get("nodes", ""),
        "systemB_system": future.get("system", ""),
        "systemB_fom": future.get("fom", ""),
        "systemB_fom_display": _format_numeric_display(future.get("fom", "")),
        "systemB_target_nodes": future.get("target_nodes", ""),
        "systemB_scaling_method": future.get("scaling_method", ""),
        "systemB_scaling_title": future.get("scaling_method", ""),
        "systemB_bench_system": future.get("benchmark", {}).get("system", ""),
        "systemB_bench_fom": future.get("benchmark", {}).get("fom", ""),
        "systemB_bench_fom_display": _format_numeric_display(future.get("benchmark", {}).get("fom", "")),
        "systemB_bench_nodes": future.get("benchmark", {}).get("nodes", ""),
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
        "estimate_uuid_short": estimate_uuid[:8] if estimate_uuid else "",
        "performance_ratio": result_data.get("performance_ratio", ""),
        "performance_ratio_display": _format_numeric_display(result_data.get("performance_ratio", "")),
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
        "applied_package_title": _build_applied_package_title(
            applied_package,
            method_class,
            detail_level,
            current_package,
            future_package,
        ),
        "applied_package_meta_line": _build_applied_package_meta_line(method_class, detail_level),
    }


def build_estimated_table_columns():
    return [
        {"label": "Timestamp", "key": "timestamp", "section": "leading"},
        {"label": "CODE", "key": "code", "section": "leading"},
        {"label": "Exp", "key": "exp", "section": "leading"},
        {"label": "System", "key": "systemA_system", "group": "System A"},
        {"label": "FOM", "key": "systemA_fom_display", "group": "System A", "title_key": "systemA_fom", "align": "right"},
        {"label": "Target Nodes", "key": "systemA_target_nodes", "group": "System A"},
        {"label": "Scaling Method", "key": "systemA_scaling_short", "group": "System A", "title_key": "systemA_scaling_title"},
        {"label": "Bench System", "key": "systemA_bench_system", "group": "System A"},
        {"label": "Bench FOM", "key": "systemA_bench_fom_display", "group": "System A", "title_key": "systemA_bench_fom", "align": "right"},
        {"label": "Bench Nodes", "key": "systemA_bench_nodes", "group": "System A"},
        {"label": "System", "key": "systemB_system", "group": "System B"},
        {"label": "FOM", "key": "systemB_fom_display", "group": "System B", "title_key": "systemB_fom", "align": "right"},
        {"label": "Target Nodes", "key": "systemB_target_nodes", "group": "System B"},
        {"label": "Scaling Method", "key": "systemB_scaling_short", "group": "System B", "title_key": "systemB_scaling_title"},
        {"label": "Bench System", "key": "systemB_bench_system", "group": "System B"},
        {"label": "Bench FOM", "key": "systemB_bench_fom_display", "group": "System B", "title_key": "systemB_bench_fom", "align": "right"},
        {"label": "Bench Nodes", "key": "systemB_bench_nodes", "group": "System B"},
        {"label": "Applicability", "key": "applicability_status", "section": "trailing"},
        {"label": "Requested Package", "key": "requested_package_short", "section": "trailing", "title_key": "requested_package_title"},
        {"label": "Applied Package", "key": "applied_package_short", "section": "trailing", "title_key": "applied_package_title", "meta_key": "applied_package_meta_line"},
        {"label": "Estimate UUID", "key": "estimate_uuid_short", "section": "trailing", "title_key": "estimate_uuid", "cell_class": "estimated-code-cell"},
        {"label": "Ratio", "key": "performance_ratio_display", "section": "trailing", "title_key": "performance_ratio", "align": "right"},
        {"label": "JSON", "key": "json_link", "section": "trailing", "cell_class": "estimated-link-cell"},
    ]


def _format_scaling_short_name(value):
    if value == "instrumented-app-sections-dummy":
        return "instr-app-sec"
    if value == "scale-mock":
        return "scale-mock"
    return value


def _format_package_short_name(value):
    if value == "instrumented_app_sections_dummy":
        return "instr_app_sec"
    if value in ("lightweight_fom_scaling", "weakscaling"):
        return "weakscaling"
    return value


def _build_requested_package_title(requested_package, requested_current, requested_future):
    title = requested_package or ""
    if requested_current:
        title += "\ncurrent-side: " + requested_current
    if requested_future:
        title += "\nfuture-side: " + requested_future
    return title


def _build_applied_package_title(applied_package, method_class, detail_level, current_package, future_package):
    title = applied_package or ""
    if method_class:
        title += "\nclass: " + method_class
    if detail_level:
        title += "\ndetail: " + detail_level
    if current_package:
        title += "\ncurrent-side: " + current_package
    if future_package:
        title += "\nfuture-side: " + future_package
    return title


def _build_applied_package_meta_line(method_class, detail_level):
    meta_parts = [part for part in (method_class, detail_level) if part]
    return " / ".join(meta_parts)


def _format_numeric_display(value):
    if value in (None, "", "N/A", "null", "nan"):
        return value

    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return value


def _get_timestamp_date(value):
    if not value:
        return ""
    return value.split(" ")[0]


def _get_timestamp_time(value):
    if not value or " " not in value:
        return ""
    return value.split(" ", 1)[1]
