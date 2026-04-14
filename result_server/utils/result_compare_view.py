from utils.result_file import check_file_permission
from utils.result_records import load_result_json_batch


def build_result_compare_context(results):
    has_vector_metrics = any(
        (row.get("data") or {}).get("metrics", {}).get("vector")
        for row in results
    )

    mixed = False
    if results:
        first = results[0].get("data", {})
        first_system = first.get("system")
        first_code = first.get("code")
        mixed = any(
            (row.get("data") or {}).get("system") != first_system
            or (row.get("data") or {}).get("code") != first_code
            for row in results[1:]
        )

    headline = ""
    if results:
        first = results[0].get("data", {})
        headline = f"{first.get('system', '')} / {first.get('code', '')} - Comparing {len(results)} results"

    return {
        "results": results,
        "headline": headline,
        "has_vector_metrics": has_vector_metrics,
        "mixed": mixed,
    }


def load_result_compare_context(filenames, directory):
    for filename in filenames:
        check_file_permission(filename, directory)
    results = load_result_json_batch(filenames, directory)
    return build_result_compare_context(results)
