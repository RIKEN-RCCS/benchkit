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
        "measurement_json": result.get("measurement", {}),
        "confidence_json": result.get("confidence", {}),
        "assumptions_json": result.get("assumptions", {}),
        "current_breakdown": current.get("fom_breakdown", {}),
        "future_breakdown": future.get("fom_breakdown", {}),
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
        ("Top-Level Requested", estimate_meta.get("requested_estimation_package", "N/A")),
        ("Top-Level Applied", estimate_meta.get("estimation_package", "N/A")),
        ("Top-Level Fallback", applicability.get("fallback_used", "none")),
        ("Current Requested", current_package.get("requested_estimation_package", "N/A")),
        ("Current Applied", current_package.get("estimation_package", "N/A")),
        ("Future Requested", future_package.get("requested_estimation_package", "N/A")),
        ("Future Applied", future_package.get("estimation_package", "N/A")),
    ])

    _append_list_row(rows, "Missing Inputs", applicability.get("missing_inputs", []))
    _append_list_row(rows, "Required Actions", applicability.get("required_actions", []))
    _append_list_row(rows, "Incompatibilities", applicability.get("incompatibilities", []))
    return rows


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
