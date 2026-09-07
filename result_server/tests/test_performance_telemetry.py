import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.performance_telemetry import build_performance_telemetry


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_performance_telemetry_summarizes_timing_and_build_cache(tmp_path):
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

    telemetry = build_performance_telemetry(str(tmp_path))

    assert telemetry["summary"]["result_count"] == 3
    assert telemetry["summary"]["timing_record_count"] == 2
    assert telemetry["summary"]["profiled_result_count"] == 1
    assert telemetry["summary"]["build_cache_record_count"] == 2
    assert telemetry["summary"]["build_cache_hit_count"] == 1
    assert telemetry["summary"]["build_cache_miss_count"] == 1
    assert telemetry["summary"]["build_cache_store_count"] == 1
    assert telemetry["summary"]["avg_build_time"] == "1m"
    assert telemetry["summary"]["avg_queue_time"] == "1m"
    assert telemetry["summary"]["avg_run_time"] == "3.5m"

    rows = {(row["code"], row["system"]): row for row in telemetry["rows"]}
    qws = rows[("qws", "Fugaku")]
    assert qws["result_count"] == 2
    assert qws["timing_count"] == 2
    assert qws["profiled_count"] == 1
    assert qws["avg_build_time"] == "1m"
    assert qws["avg_run_time"] == "3.5m"
    assert qws["latest_exp"] == "CASE1"
    assert qws["latest_build_time"] == "30s"
    assert qws["latest_queue_time"] == "1m"
    assert qws["latest_run_time"] == "2m"
    assert qws["latest_build_cache_status"] == "hit"
    assert qws["build_cache_hit_count"] == 1
    assert qws["build_cache_miss_count"] == 1
    assert qws["build_cache_store_count"] == 1

    genesis = rows[("genesis", "RIKYU")]
    assert genesis["timing_count"] == 0
    assert genesis["avg_build_time"] == "-"
    assert genesis["latest_build_cache_status"] == "-"


def test_performance_telemetry_handles_missing_directory(tmp_path):
    telemetry = build_performance_telemetry(str(tmp_path / "missing"))

    assert telemetry["summary"]["result_count"] == 0
    assert telemetry["summary"]["timing_record_count"] == 0
    assert telemetry["summary"]["avg_build_time"] == "-"
    assert telemetry["rows"] == []
