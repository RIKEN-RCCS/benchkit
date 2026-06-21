from utils.result_records import build_labeled_value_rows, format_numeric_value


def build_estimated_detail_context(result):
    estimate_meta = result.get("estimate_metadata", {})
    current = result.get("current_system", {})
    future = result.get("future_system", {})
    reestimation = result.get("reestimation", {})
    applicability = result.get("applicability", {})
    breakdown_fallback_count = _count_breakdown_fallbacks(current) + _count_breakdown_fallbacks(future)

    return {
        "meta_rows": _build_meta_rows(result, estimate_meta),
        "package_rows": _build_package_rows(estimate_meta, applicability),
        "applicability_summary": _build_applicability_summary(
            estimate_meta,
            applicability,
            breakdown_fallback_count,
        ),
        "reestimation_rows": _build_reestimation_rows(reestimation),
        "current_rows": _build_system_rows(current),
        "future_rows": _build_system_rows(future),
        "system_comparison_rows": _build_system_comparison_rows(current, future),
        "measurement_json": result.get("measurement", {}),
        "confidence_json": result.get("confidence", {}),
        "assumptions_json": result.get("assumptions", {}),
        "current_breakdown": _build_display_breakdown(current.get("fom_breakdown", {})),
        "future_breakdown": _build_display_breakdown(future.get("fom_breakdown", {})),
    }


def _build_meta_rows(result, estimate_meta):
    source_result = estimate_meta.get("source_result", {})
    current_source_result = estimate_meta.get("current_source_result", {})
    future_source_result = estimate_meta.get("future_source_result", {})
    return build_labeled_value_rows([
        ("Code", result.get("code", "N/A")),
        ("Exp", result.get("exp", "N/A")),
        ("Applicability", result.get("applicability", {}).get("status", "N/A")),
        ("Requested Package", estimate_meta.get("requested_estimation_package", "N/A")),
        ("Applied Package", estimate_meta.get("estimation_package", "N/A")),
        ("Method Class", estimate_meta.get("method_class", "N/A")),
        ("Detail Level", estimate_meta.get("detail_level", "N/A")),
        ("Estimate UUID", estimate_meta.get("estimation_result_uuid", "N/A"), "detail-code"),
        ("Estimate Timestamp", estimate_meta.get("estimation_result_timestamp", "N/A")),
        ("Source Result UUID", estimate_meta.get("source_result_uuid", "N/A"), "detail-code"),
        ("Source Result Timestamp", estimate_meta.get("source_result_timestamp", source_result.get("timestamp", "N/A"))),
        ("Source Result System", source_result.get("system", "N/A")),
        ("Source Result Exp", source_result.get("exp", "N/A")),
        ("Source Result Nodes", source_result.get("node_count", "N/A")),
        ("Current Source UUID", current_source_result.get("uuid", "N/A"), "detail-code"),
        ("Current Source Timestamp", current_source_result.get("timestamp", "N/A")),
        ("Future Source UUID", future_source_result.get("uuid", "N/A"), "detail-code"),
        ("Future Source Timestamp", future_source_result.get("timestamp", "N/A")),
        ("Execution Mode", result.get("execution_mode", "N/A")),
        ("CI Trigger", result.get("ci_trigger", "N/A")),
        ("Pipeline ID", result.get("pipeline_id", "N/A"), "detail-code"),
        ("Estimate Job", result.get("estimate_job", "N/A")),
        ("Performance Ratio", format_numeric_value(result.get("performance_ratio", "N/A"))),
    ])


def _build_package_rows(estimate_meta, applicability):
    current_package = estimate_meta.get("current_package", {})
    future_package = estimate_meta.get("future_package", {})
    rows = build_labeled_value_rows([
        ("Top-Level Package", _format_package_resolution(
            estimate_meta.get("requested_estimation_package", "N/A"),
            estimate_meta.get("estimation_package", "N/A"),
        )),
        ("Top-Level Fallback", applicability.get("fallback_used", "none")),
        ("Current Package", _format_package_resolution(
            current_package.get("requested_estimation_package", "N/A"),
            current_package.get("estimation_package", "N/A"),
        )),
        ("Future Package", _format_package_resolution(
            future_package.get("requested_estimation_package", "N/A"),
            future_package.get("estimation_package", "N/A"),
        )),
    ])

    _append_list_row(rows, "Missing Inputs", applicability.get("missing_inputs", []))
    _append_list_row(rows, "Required Actions", applicability.get("required_actions", []))
    _append_list_row(rows, "Incompatibilities", applicability.get("incompatibilities", []))
    return rows


def _format_package_resolution(requested, applied):
    if requested == applied:
        return applied
    return f"{applied} (requested: {requested})"


def _build_system_rows(system_data):
    benchmark = system_data.get("benchmark", {})
    breakdown = system_data.get("fom_breakdown", {})
    model = system_data.get("model", {})
    return build_labeled_value_rows([
        ("System", system_data.get("system", "N/A")),
        ("FOM", format_numeric_value(system_data.get("fom", "N/A"))),
        ("Target Nodes", system_data.get("target_nodes", "N/A")),
        ("Scaling Method", system_data.get("scaling_method", "N/A")),
        ("Benchmark System", benchmark.get("system", "N/A")),
        ("Benchmark FOM", format_numeric_value(benchmark.get("fom", "N/A"))),
        ("Benchmark Nodes", benchmark.get("nodes", "N/A")),
        ("Sections", len(breakdown.get("sections", []))),
        ("Overlaps", len(breakdown.get("overlaps", []))),
        ("Model", model.get("name", "N/A")),
        ("Model Type", model.get("type", "N/A")),
    ])


def _build_system_comparison_rows(current, future):
    current_rows = _build_comparison_system_rows(current)
    future_rows = _build_comparison_system_rows(future)
    future_by_label = {row["label"]: row for row in future_rows}
    rows = []
    for current_row in current_rows:
        label = current_row["label"]
        future_row = future_by_label.get(label, {})
        rows.append({
            "label": label,
            "current": current_row.get("value", "N/A"),
            "future": future_row.get("value", "N/A"),
            "current_class": current_row.get("value_class", ""),
            "future_class": future_row.get("value_class", ""),
        })
    return rows


def _build_comparison_system_rows(system_data):
    benchmark = system_data.get("benchmark", {})
    breakdown = system_data.get("fom_breakdown", {})
    return build_labeled_value_rows([
        ("System", system_data.get("system", "N/A")),
        ("FOM", format_numeric_value(system_data.get("fom", "N/A"))),
        ("Target Nodes", system_data.get("target_nodes", "N/A")),
        ("Benchmark System", benchmark.get("system", "N/A")),
        ("Benchmark FOM", format_numeric_value(benchmark.get("fom", "N/A"))),
        ("Benchmark Nodes", benchmark.get("nodes", "N/A")),
        ("Benchmark Processes/Node", benchmark.get("numproc_node", "N/A")),
        ("Sections", len(breakdown.get("sections", []))),
        ("Overlaps", len(breakdown.get("overlaps", []))),
    ])


def _build_reestimation_rows(reestimation):
    if not reestimation:
        return []

    request = reestimation.get("request", {})
    source_result = reestimation.get("source_result", {})
    source_estimate = reestimation.get("source_estimate", {})

    return build_labeled_value_rows([
        ("Reason", request.get("reason", reestimation.get("reason", "N/A"))),
        ("Trigger", request.get("trigger", reestimation.get("trigger", "N/A"))),
        ("Scope", request.get("scope", reestimation.get("scope", "N/A"))),
        ("Baseline Policy", request.get("baseline_policy", reestimation.get("baseline_policy", "N/A"))),
        ("Source Result UUID", source_result.get("uuid", reestimation.get("source_result_uuid", "N/A")), "detail-code"),
        ("Source Result Timestamp", source_result.get("timestamp", reestimation.get("source_result_timestamp", "N/A"))),
        ("Source Estimate UUID", source_estimate.get("uuid", reestimation.get("source_estimate_result_uuid", "N/A")), "detail-code"),
        ("Source Estimate Timestamp", source_estimate.get("timestamp", reestimation.get("source_estimate_result_timestamp", "N/A"))),
        ("Source Requested Package", source_estimate.get("requested_estimation_package", "N/A")),
        ("Source Applied Package", source_estimate.get("estimation_package", "N/A")),
        ("Source Method Class", source_estimate.get("method_class", "N/A")),
        ("Source Detail Level", source_estimate.get("detail_level", "N/A")),
        ("Source CI Trigger", source_estimate.get("ci_trigger", "N/A")),
        ("Source Pipeline ID", source_estimate.get("pipeline_id", "N/A"), "detail-code"),
        ("Source Estimate Job", source_estimate.get("estimate_job", "N/A")),
    ])


def _append_list_row(rows, label, values):
    if not values:
        return
    rows.append({"label": label, "list": values})


def _build_display_breakdown(breakdown):
    if not isinstance(breakdown, dict):
        return {}

    return {
        **breakdown,
        "sections": [
            _build_display_breakdown_item(item)
            for item in breakdown.get("sections", [])
            if isinstance(item, dict)
        ],
        "overlaps": [
            _build_display_breakdown_item(item)
            for item in breakdown.get("overlaps", [])
            if isinstance(item, dict)
        ],
    }


def _build_display_breakdown_item(item):
    before = item.get("bench_time", item.get("time", "N/A"))
    after = item.get("time", "N/A")
    ratio = _get_nested(item, ("metrics", "time_ratio_predicted_over_source"))
    if ratio in (None, "", "N/A", "null", "nan"):
        ratio = _safe_ratio(after, before)

    display_item = {
        **item,
        "before_scaling_display": _format_display_numeric(before),
        "after_scaling_display": _format_display_numeric(after),
        "time_ratio_display": _format_display_numeric(ratio),
    }
    if "candidate_estimates" in item:
        display_item["candidate_estimates"] = [
            _build_display_candidate_estimate(candidate)
            for candidate in item.get("candidate_estimates", [])
            if isinstance(candidate, dict)
        ]
    metrics = item.get("metrics", {})
    if isinstance(metrics, dict) and metrics.get("kernel_summaries"):
        display_item["metrics"] = {
            **metrics,
            "kernel_summaries": [
                _build_display_kernel_summary(kernel)
                for kernel in metrics.get("kernel_summaries", [])
                if isinstance(kernel, dict)
            ],
        }
    return display_item


def _build_display_candidate_estimate(candidate):
    ratio = _get_nested(candidate, ("metrics", "time_ratio_predicted_over_source"))
    return {
        **candidate,
        "time_display": _format_display_numeric(candidate.get("time", "N/A")),
        "time_ratio_display": _format_display_numeric(ratio),
    }


def _build_display_kernel_summary(kernel):
    return {
        **kernel,
        "package_summaries": [
            _build_display_kernel_package(package)
            for package in kernel.get("package_summaries", [])
            if isinstance(package, dict)
        ],
    }


def _build_display_kernel_package(package):
    return {
        **package,
        "source_time_ns_mean_display": _format_display_numeric(package.get("source_time_ns_mean", "N/A")),
        "predicted_time_ns_mean_display": _format_display_numeric(package.get("predicted_time_ns_mean", "N/A")),
        "mean_time_ratio_display": _format_display_numeric(package.get("mean_time_ratio_predicted_over_source", "N/A")),
        "metric_comparisons": [
            _build_display_metric_comparison(metric)
            for metric in package.get("metric_comparisons", [])
            if isinstance(metric, dict)
        ],
    }


def _build_display_metric_comparison(metric):
    return {
        **metric,
        "source_value_mean_display": _format_display_numeric(metric.get("source_value_mean", "N/A")),
        "predicted_value_mean_display": _format_display_numeric(metric.get("predicted_value_mean", "N/A")),
        "ratio_display": _format_display_numeric(metric.get("ratio_predicted_over_source_mean", "N/A")),
    }


def _get_nested(data, keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_ratio(numerator, denominator):
    try:
        numerator_value = float(numerator)
        denominator_value = float(denominator)
    except (TypeError, ValueError):
        return "N/A"
    if denominator_value == 0:
        return "N/A"
    return numerator_value / denominator_value


def _format_display_numeric(value):
    if value in (None, "", "N/A", "null", "nan"):
        return "N/A"
    return format_numeric_value(value)


def _count_breakdown_fallbacks(system_data):
    breakdown = system_data.get("fom_breakdown", {})
    section_count = sum(1 for item in breakdown.get("sections", []) if item.get("fallback_used"))
    overlap_count = sum(1 for item in breakdown.get("overlaps", []) if item.get("fallback_used"))
    return section_count + overlap_count


def _build_applicability_summary(estimate_meta, applicability, breakdown_fallback_count):
    status = applicability.get("status", "N/A")
    requested = estimate_meta.get("requested_estimation_package", "")
    applied = estimate_meta.get("estimation_package", "")
    fallback_used = applicability.get("fallback_used", "")
    missing_inputs = applicability.get("missing_inputs", [])
    required_actions = applicability.get("required_actions", [])
    incompatibilities = applicability.get("incompatibilities", [])
    highlights = []

    if requested:
        highlights.append(f"requested package: {requested}")
    if applied:
        highlights.append(f"applied package: {applied}")
    if fallback_used:
        highlights.append(f"fallback used: {fallback_used}")
    if breakdown_fallback_count:
        highlights.append(f"section/overlap fallback entries: {breakdown_fallback_count}")
    highlights.extend(f"missing input: {item}" for item in missing_inputs)
    highlights.extend(f"required action: {item}" for item in required_actions)
    highlights.extend(f"incompatibility: {item}" for item in incompatibilities)

    if status == "applicable":
        return {
            "status": status,
            "tone": "ok",
            "headline": "Requested package was applied without a top-level fallback.",
            "body": (
                "This estimate succeeded as requested. Section- or overlap-level fallback entries can still appear below "
                "when only part of the breakdown needed a substitute package."
            ),
            "highlights": highlights,
        }
    if status == "partially_applicable":
        return {
            "status": status,
            "tone": "warn",
            "headline": "Estimate succeeded, but part of the breakdown used fallback handling.",
            "body": (
                "The overall estimate was stored successfully, but at least one section or overlap could not use its "
                "requested package as-is. Review the breakdown cards for the exact fallback points."
            ),
            "highlights": highlights,
        }
    if status == "fallback":
        return {
            "status": status,
            "tone": "warn",
            "headline": "Estimate succeeded after switching the top-level package.",
            "body": (
                "The originally requested package did not apply cleanly, so BenchKit stored a successful estimate with "
                "a different top-level package. Compare requested versus applied packages before reusing this result."
            ),
            "highlights": highlights,
        }
    if status == "not_applicable":
        return {
            "status": status,
            "tone": "danger",
            "headline": "Estimate attempt was recorded, but it did not finish as a valid estimate result.",
            "body": (
                "This does not necessarily mean the pipeline failed. It means the stored estimate record is mainly a "
                "diagnostic artifact showing why the requested estimation path could not be completed."
            ),
            "highlights": highlights,
        }
    if status == "needs_remeasurement":
        return {
            "status": status,
            "tone": "danger",
            "headline": "Estimate needs additional measurement data before it can be completed.",
            "body": (
                "BenchKit stored the attempt, but more input data is required before the requested estimate can be "
                "considered usable."
            ),
            "highlights": highlights,
        }

    return {
        "status": status,
        "tone": "info",
        "headline": "Applicability state is recorded, but it does not match a standard summary path.",
        "body": "Use the package resolution and breakdown tables below to interpret the stored estimate context.",
        "highlights": highlights,
    }
