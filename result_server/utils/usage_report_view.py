from utils.app_support_matrix import load_app_system_support_matrix
from utils.evidence_snapshot import build_evidence_snapshot
from utils.node_hours import aggregate_node_hours
from utils.performance_telemetry import build_performance_telemetry
from utils.profile_usage_overview import build_profile_usage_overview
from utils.site_diagnostics import build_site_diagnostics
from utils.usage_query_params import parse_usage_query_params, select_usage_periods


def build_usage_report_context(
    received_dir,
    args,
    current_fiscal_year,
    db_path=None,
    estimated_dir=None,
    benchkit_commit="",
):
    """Build the Usage report view-model from request args and collected results."""
    params = parse_usage_query_params(args, current_fiscal_year)
    period_type = params["period_type"]
    fiscal_year = params["fiscal_year"]
    period_filter = params["period_filter"]

    result = aggregate_node_hours(received_dir, fiscal_year, period_type)
    period_filter, filtered_periods = select_usage_periods(result["periods"], period_filter)

    _, app_support_rows = load_app_system_support_matrix()

    return {
        "result": result,
        "period_type": period_type,
        "fiscal_year": fiscal_year,
        "period_filter": period_filter,
        "filtered_periods": filtered_periods,
        "site_diagnostics": build_site_diagnostics(),
        "profile_usage_overview": build_profile_usage_overview(received_dir, db_path),
        "performance_telemetry": build_performance_telemetry(received_dir),
        "evidence_snapshot": build_evidence_snapshot(
            received_dir,
            estimated_dir or received_dir,
            benchkit_commit=benchkit_commit,
            app_support_rows=app_support_rows,
        ),
    }
