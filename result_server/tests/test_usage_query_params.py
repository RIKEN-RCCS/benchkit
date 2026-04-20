import os
import sys

from werkzeug.datastructures import MultiDict


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.usage_query_params import parse_usage_query_params, select_usage_periods


def test_parse_usage_query_params_reads_usage_filters():
    args = MultiDict([
        ("period_type", "semi_annual"),
        ("fiscal_year", "2026"),
        ("period_filter", "H1"),
    ])

    params = parse_usage_query_params(args, 2025)

    assert params == {
        "period_type": "semi_annual",
        "fiscal_year": 2026,
        "period_filter": "H1",
    }


def test_parse_usage_query_params_falls_back_for_invalid_values():
    args = MultiDict([
        ("period_type", "weird"),
        ("fiscal_year", "oops"),
        ("period_filter", "FY2025"),
    ])

    params = parse_usage_query_params(args, 2025)

    assert params == {
        "period_type": "fiscal_year",
        "fiscal_year": 2025,
        "period_filter": "FY2025",
    }


def test_select_usage_periods_returns_single_period_when_present():
    period_filter, filtered_periods = select_usage_periods(["H1", "H2"], "H2")

    assert period_filter == "H2"
    assert filtered_periods == ["H2"]


def test_select_usage_periods_resets_unknown_filter():
    period_filter, filtered_periods = select_usage_periods(["FY2025"], "H2")

    assert period_filter == ""
    assert filtered_periods == ["FY2025"]
