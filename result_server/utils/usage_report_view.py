from utils.app_support_matrix import load_app_system_support_matrix
from utils.node_hours import aggregate_node_hours
from utils.result_quality_rollup import build_result_quality_rollup
from utils.site_diagnostics import build_site_diagnostics
from utils.system_info import get_all_systems_info
from utils.usage_query_params import parse_usage_query_params, select_usage_periods


def build_usage_report_context(received_dir, args, current_fiscal_year):
    """Build the Usage report view-model from request args and collected results."""
    params = parse_usage_query_params(args, current_fiscal_year)
    period_type = params["period_type"]
    fiscal_year = params["fiscal_year"]
    period_filter = params["period_filter"]

    result = aggregate_node_hours(received_dir, fiscal_year, period_type)
    period_filter, filtered_periods = select_usage_periods(result["periods"], period_filter)

    systems_info = get_all_systems_info()
    coverage_systems, app_support_rows = load_app_system_support_matrix()
    coverage_headers = [
        {"system": system, "name": systems_info.get(system, {}).get("name", system)}
        for system in coverage_systems
    ]

    return {
        "result": result,
        "period_type": period_type,
        "fiscal_year": fiscal_year,
        "period_filter": period_filter,
        "filtered_periods": filtered_periods,
        "coverage_systems": coverage_headers,
        "app_support_rows": app_support_rows,
        "site_diagnostics": build_site_diagnostics(),
        "result_quality_rollup": build_result_quality_rollup(received_dir),
    }
