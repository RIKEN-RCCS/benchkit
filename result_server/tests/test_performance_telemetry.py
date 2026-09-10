import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import utils.performance_telemetry as performance_telemetry
from utils.performance_telemetry import build_performance_telemetry


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_performance_telemetry_summarizes_timing_and_build_cache(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "programs" / "demoapp").mkdir(parents=True)
    monkeypatch.setattr(performance_telemetry, "REPO_ROOT", repo_root)

    estimated_dir = tmp_path / "estimated"
    estimated_dir.mkdir()
    _write_json(
        tmp_path / "result_20260902_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE1",
            "FOM": 1.0,
            "profile_data": {"tool": "ncu"},
            "pipeline_timing": {
                "build_time": 30,
                "queue_time": 60,
                "queue_time_source": "not_measured",
                "scheduler_queue_time": 240,
                "scheduler_queue_time_source": "runner_metadata",
                "run_time": 120,
            },
            "build_cache": {"status": "hit", "stored": False},
        },
    )
    _write_json(
        tmp_path / "result_20260901_010101_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE0",
            "FOM": 1.0,
            "pipeline_timing": {
                "build_time": 90,
                "queue_time": 60,
                "queue_time_source": "not_measured",
                "run_time": 300,
            },
            "build_cache": {"status": "miss", "stored": True},
        },
    )
    _write_json(
        tmp_path / "result_20260901_020202_cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "auxapp",
            "system": "SourceSystem",
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
            "system": "DemoSystem",
            "pipeline_timing": {"build_time": 1},
        },
    )
    _write_json(
        tmp_path / "result_20260901_050505_ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "../demoapp",
            "system": "DemoSystem",
            "pipeline_timing": {"build_time": 1},
        },
    )
    _write_json(
        estimated_dir / "estimate_20260903_010101_11111111-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "exp": "CASE1",
            "estimate_metadata": {
                "source_result": {
                    "system": "DemoSystem",
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
                    "system": "DemoSystem",
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
    assert telemetry["summary"]["scheduler_queue_timing_count"] == 1
    assert telemetry["summary"]["profiled_result_count"] == 1
    assert telemetry["summary"]["regular_run_timing_count"] == 1
    assert telemetry["summary"]["profiled_run_timing_count"] == 1
    assert telemetry["summary"]["profile_overhead_pair_count"] == 0
    assert telemetry["summary"]["estimate_record_count"] == 1
    assert telemetry["summary"]["estimate_timing_record_count"] == 1
    assert telemetry["summary"]["build_cache_record_count"] == 2
    assert telemetry["summary"]["build_cache_hit_count"] == 1
    assert telemetry["summary"]["build_cache_miss_count"] == 1
    assert telemetry["summary"]["build_cache_store_count"] == 1
    assert telemetry["summary"]["avg_build_time"] == "1m"
    assert telemetry["summary"]["avg_queue_time"] == "1m"
    assert telemetry["summary"]["avg_scheduler_queue_time"] == "4m"
    assert telemetry["summary"]["avg_run_time"] == "3.5m"
    assert telemetry["summary"]["avg_regular_run_time"] == "5m"
    assert telemetry["summary"]["avg_profiled_run_time"] == "2m"
    assert telemetry["summary"]["avg_profile_overhead_delta"] == "-"
    assert telemetry["summary"]["avg_profile_overhead_ratio"] == "-"
    assert telemetry["summary"]["avg_estimate_time"] == "42s"

    rows = {(row["code"], row["system"]): row for row in telemetry["rows"]}
    assert set(rows) == {("demoapp", "DemoSystem")}
    demoapp = rows[("demoapp", "DemoSystem")]
    assert demoapp["result_count"] == 2
    assert demoapp["timing_count"] == 2
    assert demoapp["scheduler_queue_timing_count"] == 1
    assert demoapp["profiled_count"] == 1
    assert demoapp["avg_build_time"] == "1m"
    assert demoapp["avg_scheduler_queue_time"] == "4m"
    assert demoapp["avg_run_time"] == "3.5m"
    assert demoapp["avg_regular_run_time"] == "5m"
    assert demoapp["avg_profiled_run_time"] == "2m"
    assert demoapp["profile_overhead_pair_count"] == 0
    assert demoapp["profile_overhead_status"] == "needs matching run dimensions"
    assert demoapp["avg_profile_overhead_delta"] == "-"
    assert demoapp["avg_profile_overhead_ratio"] == "-"
    conditions = {condition["exp"]: condition for condition in demoapp["run_conditions"]}
    assert set(conditions) == {"CASE0", "CASE1"}
    assert conditions["CASE0"]["label"] == "CASE0 / N- P- T- / -"
    assert conditions["CASE0"]["regular_result_count"] == 1
    assert conditions["CASE0"]["profiled_result_count"] == 0
    assert conditions["CASE0"]["regular_run_timing_count"] == 1
    assert conditions["CASE0"]["profiled_run_timing_count"] == 0
    assert conditions["CASE0"]["avg_regular_run_time"] == "5m"
    assert conditions["CASE0"]["avg_profiled_run_time"] == "-"
    assert conditions["CASE0"]["profile_overhead_status"] == "needs matching profiled run"
    assert conditions["CASE1"]["regular_result_count"] == 0
    assert conditions["CASE1"]["profiled_result_count"] == 1
    assert conditions["CASE1"]["regular_run_timing_count"] == 0
    assert conditions["CASE1"]["profiled_run_timing_count"] == 1
    assert conditions["CASE1"]["avg_regular_run_time"] == "-"
    assert conditions["CASE1"]["avg_profiled_run_time"] == "2m"
    assert conditions["CASE1"]["profile_overhead_status"] == "needs matching regular run"
    assert demoapp["latest_exp"] == "CASE1"
    assert demoapp["latest_build_time"] == "30s"
    assert demoapp["latest_queue_time"] == "1m"
    assert demoapp["latest_queue_time_source"] == "not measured"
    assert demoapp["latest_scheduler_queue_time"] == "4m"
    assert demoapp["latest_scheduler_queue_time_source"] == "runner metadata"
    assert demoapp["latest_run_time"] == "2m"
    assert demoapp["latest_run_kind"] == "profiled"
    assert demoapp["estimate_count"] == 1
    assert demoapp["estimate_timing_count"] == 1
    assert demoapp["avg_estimate_time"] == "42s"
    assert demoapp["latest_estimate_elapsed_time"] == "42s"
    assert demoapp["latest_estimate_exp"] == "CASE1"
    assert demoapp["latest_build_cache_status"] == "hit"
    assert demoapp["build_cache_hit_count"] == 1
    assert demoapp["build_cache_miss_count"] == 1
    assert demoapp["build_cache_store_count"] == 1


def test_performance_telemetry_counts_profile_overhead_pairs(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "programs" / "demoapp").mkdir(parents=True)
    monkeypatch.setattr(performance_telemetry, "REPO_ROOT", repo_root)

    common = {
        "code": "demoapp",
        "system": "DemoSystem",
        "Exp": "CASE0",
        "node_count": 1,
        "numproc_node": 4,
        "nthreads": 8,
        "FOM_version": "region-v1",
    }
    _write_json(
        tmp_path / "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            **common,
            "FOM": 1.0,
            "pipeline_timing": {"run_time": 300},
        },
    )
    _write_json(
        tmp_path / "result_20260902_010101_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            **common,
            "FOM": 1.0,
            "profile_data": {"tool": "ncu"},
            "pipeline_timing": {"run_time": 360},
        },
    )

    telemetry = build_performance_telemetry(str(tmp_path))

    assert telemetry["summary"]["profile_overhead_pair_count"] == 1
    assert telemetry["summary"]["avg_profile_overhead_delta"] == "1m"
    assert telemetry["summary"]["avg_profile_overhead_ratio"] == "1.2x"
    assert telemetry["rows"][0]["profile_overhead_pair_count"] == 1
    assert telemetry["rows"][0]["profile_overhead_status"] == "observed from matching dimensions"
    assert telemetry["rows"][0]["avg_profile_overhead_delta"] == "1m"
    assert telemetry["rows"][0]["avg_profile_overhead_ratio"] == "1.2x"
    assert telemetry["rows"][0]["run_conditions"] == [
        {
            "label": "CASE0 / N1 P4 T8 / region-v1",
            "exp": "CASE0",
            "node_count": "1",
            "numproc_node": "4",
            "nthreads": "8",
            "fom_version": "region-v1",
            "regular_result_count": 1,
            "profiled_result_count": 1,
            "regular_run_timing_count": 1,
            "profiled_run_timing_count": 1,
            "avg_regular_run_time": "5m",
            "avg_profiled_run_time": "6m",
            "avg_profile_overhead_delta": "1m",
            "avg_profile_overhead_ratio": "1.2x",
            "profile_overhead_status": "observed from matching dimensions",
        }
    ]


def test_performance_telemetry_keeps_benchmark_conditions_without_timing(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "programs" / "demoapp").mkdir(parents=True)
    monkeypatch.setattr(performance_telemetry, "REPO_ROOT", repo_root)

    _write_json(
        tmp_path / "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE1",
            "node_count": 1,
            "numproc_node": 2,
            "nthreads": 12,
            "FOM_version": "solver-v1",
            "FOM": 0.425,
        },
    )

    telemetry = build_performance_telemetry(str(tmp_path))

    assert telemetry["summary"]["result_count"] == 1
    assert telemetry["summary"]["timing_record_count"] == 0
    assert telemetry["summary"]["regular_run_timing_count"] == 0
    assert telemetry["summary"]["profiled_run_timing_count"] == 0
    row = telemetry["rows"][0]
    assert row["profile_overhead_status"] == "-"
    assert row["run_conditions"] == [
        {
            "label": "CASE1 / N1 P2 T12 / solver-v1",
            "exp": "CASE1",
            "node_count": "1",
            "numproc_node": "2",
            "nthreads": "12",
            "fom_version": "solver-v1",
            "regular_result_count": 1,
            "profiled_result_count": 0,
            "regular_run_timing_count": 0,
            "profiled_run_timing_count": 0,
            "avg_regular_run_time": "-",
            "avg_profiled_run_time": "-",
            "avg_profile_overhead_delta": "-",
            "avg_profile_overhead_ratio": "-",
            "profile_overhead_status": "regular run timing not recorded",
        }
    ]


def test_performance_telemetry_handles_missing_directory(tmp_path):
    telemetry = build_performance_telemetry(str(tmp_path / "missing"))

    assert telemetry["summary"]["result_count"] == 0
    assert telemetry["summary"]["ignored_result_count"] == 0
    assert telemetry["summary"]["timing_record_count"] == 0
    assert telemetry["summary"]["scheduler_queue_timing_count"] == 0
    assert telemetry["summary"]["profile_overhead_pair_count"] == 0
    assert telemetry["summary"]["estimate_record_count"] == 0
    assert telemetry["summary"]["estimate_timing_record_count"] == 0
    assert telemetry["summary"]["avg_build_time"] == "-"
    assert telemetry["summary"]["avg_scheduler_queue_time"] == "-"
    assert telemetry["summary"]["avg_profile_overhead_delta"] == "-"
    assert telemetry["summary"]["avg_profile_overhead_ratio"] == "-"
    assert telemetry["summary"]["avg_estimate_time"] == "-"
    assert telemetry["rows"] == []
