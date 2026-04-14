from utils.result_file import check_file_permission
from utils.result_records import build_compare_headline, load_result_json_batch


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
