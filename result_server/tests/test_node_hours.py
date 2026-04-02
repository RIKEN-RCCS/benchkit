"""
node_hours.py のユニットテスト
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.node_hours import (
    compute_node_hours,
    extract_timestamp_from_filename,
    get_fiscal_year,
    get_fiscal_month_index,
    get_half,
)


class TestComputeNodeHours:
    def test_cross_mode_uses_run_time_only(self):
        data = {
            "node_count": 4,
            "execution_mode": "cross",
            "pipeline_timing": {"build_time": 100, "run_time": 1800},
        }
        assert compute_node_hours(data) == 2.0

    def test_native_mode_uses_build_and_run_time(self):
        data = {
            "node_count": 2,
            "execution_mode": "native",
            "pipeline_timing": {"build_time": 600, "run_time": 1200},
        }
        assert compute_node_hours(data) == 1.0

    def test_native_mode_missing_build_time_falls_back_to_zero(self):
        data = {
            "node_count": 3,
            "execution_mode": "native",
            "pipeline_timing": {"run_time": 600},
        }
        assert compute_node_hours(data) == 0.5

    def test_missing_node_count_returns_zero(self):
        data = {"execution_mode": "cross", "pipeline_timing": {"run_time": 100}}
        assert compute_node_hours(data) == 0.0

    def test_invalid_run_time_returns_zero(self):
        data = {
            "node_count": 2,
            "execution_mode": "cross",
            "pipeline_timing": {"run_time": "bad"},
        }
        assert compute_node_hours(data) == 0.0

    def test_rounds_to_two_decimal_places(self):
        data = {
            "node_count": 1,
            "execution_mode": "cross",
            "pipeline_timing": {"run_time": 1000},
        }
        assert compute_node_hours(data) == 0.28


class TestTimestampHelpers:
    def test_extract_timestamp_from_filename(self):
        ts = extract_timestamp_from_filename(
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
        )
        assert ts == datetime(2026, 4, 1, 12, 34, 56)

    def test_extract_timestamp_from_filename_without_pattern(self):
        assert extract_timestamp_from_filename("result.json") is None


class TestFiscalHelpers:
    def test_get_fiscal_year_january_is_previous_year(self):
        assert get_fiscal_year(datetime(2026, 1, 15)) == 2025

    def test_get_fiscal_year_april_is_current_year(self):
        assert get_fiscal_year(datetime(2026, 4, 1)) == 2026

    def test_get_fiscal_month_index(self):
        assert get_fiscal_month_index(datetime(2026, 4, 1)) == 0
        assert get_fiscal_month_index(datetime(2027, 3, 1)) == 11

    def test_get_half(self):
        assert get_half(datetime(2026, 4, 1)) == "first"
        assert get_half(datetime(2026, 9, 30)) == "first"
        assert get_half(datetime(2026, 10, 1)) == "second"
        assert get_half(datetime(2027, 3, 31)) == "second"
