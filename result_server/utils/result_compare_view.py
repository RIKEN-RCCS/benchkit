from utils.result_file import check_file_permission
from utils.result_records import build_axis_label, build_compare_headline, load_result_json_batch


def build_result_compare_context(results):
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

    compare_chart = _build_compare_chart_context(rows, has_vector_metrics)
    return {
        "results": results,
        "headline": headline,
        "has_vector_metrics": has_vector_metrics,
        "mixed": mixed,
        "compare_chart": compare_chart,
    }


def load_result_compare_context(filenames, directory):
    for filename in filenames:
        check_file_permission(filename, directory)
    results = load_result_json_batch(filenames, directory)
    return build_result_compare_context(results)


def _build_compare_chart_context(rows, has_vector_metrics):
    first_result = rows[0] if rows else {}
    vector_axis = _find_vector_axis(rows) if has_vector_metrics else {}
    vector_axis_label = build_axis_label(vector_axis.get("name"), vector_axis.get("unit"))
    fom_unit = first_result.get("FOM_unit") or ""
    return {
        "vector_axis_label": vector_axis_label,
        "fom_unit": fom_unit,
    }


def _find_vector_axis(rows):
    for row in rows:
        vector = (row.get("metrics") or {}).get("vector") or {}
        x_axis = vector.get("x_axis") or {}
        if x_axis.get("name") or x_axis.get("unit"):
            return x_axis
    return {}
