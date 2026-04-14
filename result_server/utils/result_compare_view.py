def build_result_compare_context(results):
    has_vector_metrics = any(
        (row.get("data") or {}).get("metrics", {}).get("vector")
        for row in results
    )

    headline = ""
    if results:
        first = results[0].get("data", {})
        headline = f"{first.get('system', '')} / {first.get('code', '')} - Comparing {len(results)} results"

    return {
        "results": results,
        "headline": headline,
        "has_vector_metrics": has_vector_metrics,
    }
