import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.performance_telemetry import build_performance_telemetry


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_performance_telemetry_summarizes_timing_and_build_cache(tmp_path):
    estimated_dir = tmp_path / "estimated"
    estimated_dir.mkdir()
    _write_json(
        tmp_path / "result_20260902_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE1",
            "FOM": 1.0,
            "profile_data": {"tool": "ncu"},
            "pipeline_timing": {"build_time": 30, "queue_time": 60, "run_time": 120},
            "build_cache": {"status": "hit", "stored": False},
        },
    )
    _write_json(
        tmp_path / "result_20260901_010101_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE0",
            "FOM": 1.0,
            "pipeline_timing": {"build_time": 90, "queue_time": 60, "run_time": 300},
            "build_cache": {"status": "miss", "stored": True},
        },
    )
    _write_json(
        tmp_path / "result_20260901_020202_cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "genesis",
            "system": "RIKYU",
            "Exp": "p8",
            "FOM": 1.0,
        },
    )
    _write_json(
        tmp_path / "result_20260901_030303_dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "mtls-docker-runner",
            "system": None,
        },
    )
    _write_json(
        tmp_path / "result_20260901_040404_eeeeeeee-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "diagnostic-tool",
            "system": "Fugaku",
            "pipeline_timing": {"build_time": 1},
        },
    )
    _write_json(
        tmp_path / "result_20260901_050505_ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "../qws",
            "system": "Fugaku",
            "pipeline_timing": {"build_time": 1},
        },
    )
    _write_json(
        estimated_dir / "estimate_20260903_010101_11111111-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "qws",
            "exp": "CASE1",
            "estimate_metadata": {
                "source_result": {
                    "system": "Fugaku",
                },
            },
            "estimation_timing": {
                "elapsed_time": 42,
                "unit": "s",
            },
        },
    )
    _write_json(
        estimated_dir / "estimate_20260903_020202_22222222-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "diagnostic-tool",
            "exp": "CASE0",
            "estimate_metadata": {
                "source_result": {
                    "system": "Fugaku",
                },
            },
            "estimation_timing": {
                "elapsed_time": 999,
                "unit": "s",
            },
        },
    )

    telemetry = build_performance_telemetry(str(tmp_path), str(estimated_dir))

    assert telemetry["summary"]["result_count"] == 2
    assert telemetry["summary"]["ignored_result_count"] == 4
    assert telemetry["summary"]["timing_record_count"] == 2
    assert telemetry["summary"]["profiled_result_count"] == 1
    assert telemetry["summary"]["regular_run_timing_count"] == 1
    assert telemetry["summary"]["profiled_run_timing_count"] == 1
    assert telemetry["summary"]["estimate_record_count"] == 1
    assert telemetry["summary"]["estimate_timing_record_count"] == 1
    assert telemetry["summary"]["build_cache_record_count"] == 2
    assert telemetry["summary"]["build_cache_hit_count"] == 1
    assert telemetry["summary"]["build_cache_miss_count"] == 1
    assert telemetry["summary"]["build_cache_store_count"] == 1
    assert telemetry["summary"]["avg_build_time"] == "1m"
    assert telemetry["summary"]["avg_queue_time"] == "1m"
    assert telemetry["summary"]["avg_run_time"] == "3.5m"
    assert telemetry["summary"]["avg_regular_run_time"] == "5m"
    assert telemetry["summary"]["avg_profiled_run_time"] == "2m"
    assert telemetry["summary"]["avg_estimate_time"] == "42s"

    rows = {(row["code"], row["system"]): row for row in telemetry["rows"]}
    assert set(rows) == {("qws", "Fugaku")}
    qws = rows[("qws", "Fugaku")]
    assert qws["result_count"] == 2
    assert qws["timing_count"] == 2
    assert qws["profiled_count"] == 1
    assert qws["avg_build_time"] == "1m"
    assert qws["avg_run_time"] == "3.5m"
    assert qws["avg_regular_run_time"] == "5m"
    assert qws["avg_profiled_run_time"] == "2m"
    assert qws["latest_exp"] == "CASE1"
    assert qws["latest_build_time"] == "30s"
    assert qws["latest_queue_time"] == "1m"
    assert qws["latest_run_time"] == "2m"
    assert qws["latest_run_kind"] == "profiled"
    assert qws["estimate_count"] == 1
    assert qws["estimate_timing_count"] == 1
    assert qws["avg_estimate_time"] == "42s"
    assert qws["latest_estimate_elapsed_time"] == "42s"
    assert qws["latest_estimate_exp"] == "CASE1"
    assert qws["latest_build_cache_status"] == "hit"
    assert qws["build_cache_hit_count"] == 1
    assert qws["build_cache_miss_count"] == 1
    assert qws["build_cache_store_count"] == 1


def test_performance_telemetry_handles_missing_directory(tmp_path):
    telemetry = build_performance_telemetry(str(tmp_path / "missing"))

    assert telemetry["summary"]["result_count"] == 0
    assert telemetry["summary"]["ignored_result_count"] == 0
    assert telemetry["summary"]["timing_record_count"] == 0
    assert telemetry["summary"]["estimate_record_count"] == 0
    assert telemetry["summary"]["estimate_timing_record_count"] == 0
    assert telemetry["summary"]["avg_build_time"] == "-"
    assert telemetry["summary"]["avg_estimate_time"] == "-"
    assert telemetry["rows"] == []
