from utils.result_records import build_labeled_value_rows, format_numeric_value


def build_estimated_detail_context(result):
    estimate_meta = result.get("estimate_metadata", {})
    current = result.get("current_system", {})
    future = result.get("future_system", {})

    return {
        "meta_rows": _build_meta_rows(result, estimate_meta),
        "package_rows": _build_package_rows(estimate_meta),
        "current_rows": _build_system_rows(current),
        "future_rows": _build_system_rows(future),
        "measurement_json": result.get("measurement", {}),
        "confidence_json": result.get("confidence", {}),
        "assumptions_json": result.get("assumptions", {}),
        "current_breakdown": current.get("fom_breakdown", {}),
        "future_breakdown": future.get("fom_breakdown", {}),
    }


def _build_meta_rows(result, estimate_meta):
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
        ("Performance Ratio", format_numeric_value(result.get("performance_ratio", "N/A"))),
    ])


def _build_package_rows(estimate_meta):
    current_package = estimate_meta.get("current_package", {})
    future_package = estimate_meta.get("future_package", {})
    return build_labeled_value_rows([
        ("Current Requested", current_package.get("requested_estimation_package", "N/A")),
        ("Current Applied", current_package.get("estimation_package", "N/A")),
        ("Future Requested", future_package.get("requested_estimation_package", "N/A")),
        ("Future Applied", future_package.get("estimation_package", "N/A")),
    ])


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
