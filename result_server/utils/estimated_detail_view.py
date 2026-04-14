from utils.result_records import format_numeric_value


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
    return [
        {"label": "Code", "value": result.get("code", "N/A")},
        {"label": "Exp", "value": result.get("exp", "N/A")},
        {"label": "Applicability", "value": result.get("applicability", {}).get("status", "N/A")},
        {"label": "Requested Package", "value": estimate_meta.get("requested_estimation_package", "N/A")},
        {"label": "Applied Package", "value": estimate_meta.get("estimation_package", "N/A")},
        {"label": "Method Class", "value": estimate_meta.get("method_class", "N/A")},
        {"label": "Detail Level", "value": estimate_meta.get("detail_level", "N/A")},
        {
            "label": "Estimate UUID",
            "value": estimate_meta.get("estimation_result_uuid", "N/A"),
            "value_class": "detail-code",
        },
        {"label": "Estimate Timestamp", "value": estimate_meta.get("estimation_result_timestamp", "N/A")},
        {"label": "Performance Ratio", "value": format_numeric_value(result.get("performance_ratio", "N/A"))},
    ]


def _build_package_rows(estimate_meta):
    current_package = estimate_meta.get("current_package", {})
    future_package = estimate_meta.get("future_package", {})
    return [
        {"label": "Current Requested", "value": current_package.get("requested_estimation_package", "N/A")},
        {"label": "Current Applied", "value": current_package.get("estimation_package", "N/A")},
        {"label": "Future Requested", "value": future_package.get("requested_estimation_package", "N/A")},
        {"label": "Future Applied", "value": future_package.get("estimation_package", "N/A")},
    ]


def _build_system_rows(system_data):
    benchmark = system_data.get("benchmark", {})
    breakdown = system_data.get("fom_breakdown", {})
    model = system_data.get("model", {})
    return [
        {"label": "System", "value": system_data.get("system", "N/A")},
        {"label": "FOM", "value": format_numeric_value(system_data.get("fom", "N/A"))},
        {"label": "Target Nodes", "value": system_data.get("target_nodes", "N/A")},
        {"label": "Scaling Method", "value": system_data.get("scaling_method", "N/A")},
        {"label": "Benchmark System", "value": benchmark.get("system", "N/A")},
        {"label": "Benchmark FOM", "value": format_numeric_value(benchmark.get("fom", "N/A"))},
        {"label": "Benchmark Nodes", "value": benchmark.get("nodes", "N/A")},
        {"label": "Sections", "value": len(breakdown.get("sections", []))},
        {"label": "Overlaps", "value": len(breakdown.get("overlaps", []))},
        {"label": "Model", "value": model.get("name", "N/A")},
        {"label": "Model Type", "value": model.get("type", "N/A")},
    ]
