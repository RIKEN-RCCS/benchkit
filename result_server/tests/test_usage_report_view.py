import os
import sys

from werkzeug.datastructures import MultiDict


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import utils.usage_report_view as usage_report_view


def test_build_usage_report_context_builds_named_coverage_headers(monkeypatch):
    monkeypatch.setattr(
        usage_report_view,
        "aggregate_node_hours",
        lambda directory, fiscal_year, period_type: {
            "apps": [],
            "systems": [],
            "periods": ["FY2025"],
            "table": {},
            "row_totals": {},
            "col_totals": {},
            "grand_totals": {},
            "available_fiscal_years": [2025],
        },
    )
    monkeypatch.setattr(
        usage_report_view,
        "load_app_system_support_matrix",
        lambda: (["Fugaku"], [{"app": "qws", "systems": {}}]),
    )
    monkeypatch.setattr(
        usage_report_view,
        "get_all_systems_info",
        lambda: {"Fugaku": {"name": "Fugaku Prime"}},
    )
    monkeypatch.setattr(
        usage_report_view,
        "build_site_diagnostics",
        lambda: {"registered_system_count": 1},
    )
    monkeypatch.setattr(
        usage_report_view,
        "build_result_quality_rollup",
        lambda directory: {"rows": []},
    )

    context = usage_report_view.build_usage_report_context(
        "received",
        MultiDict(),
        2025,
    )

    assert context["period_type"] == "fiscal_year"
    assert context["fiscal_year"] == 2025
    assert context["filtered_periods"] == ["FY2025"]
    assert context["coverage_systems"] == [{"system": "Fugaku", "name": "Fugaku Prime"}]
    assert context["app_support_rows"] == [{"app": "qws", "systems": {}}]
    assert context["site_diagnostics"] == {"registered_system_count": 1}
    assert context["result_quality_rollup"] == {"rows": []}
