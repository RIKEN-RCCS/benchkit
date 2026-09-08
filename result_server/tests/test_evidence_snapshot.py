import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.evidence_snapshot import build_evidence_snapshot


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def test_evidence_snapshot_builds_flat_review_rows(tmp_path):
    received_dir = tmp_path / "received"
    estimated_dir = tmp_path / "estimated"
    received_dir.mkdir()
    estimated_dir.mkdir()

    _write_json(
        received_dir / "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE0",
            "FOM": 1.0,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.com/demoapp.git",
                "ref_name": "main",
                "resolved_commit": "abcdef1234567890",
            },
            "input_info": {
                "inputs": [
                    {
                        "repo_relative_path": "benchmarks/case0",
                        "source": "source_info",
                        "verification_status": "covered_by_source_commit",
                    }
                ],
            },
            "profile_data": {"tool": "ncu", "level": "kernel"},
            "build_cache": {"status": "hit", "stored": False},
        },
    )
    _write_json(
        estimated_dir / "estimate_20260902_020202_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "exp": "CASE0",
            "current_system": {"system": "DemoSystem"},
            "future_system": {"system": "FutureSystem"},
            "applicability": {"status": "applicable"},
        },
    )

    snapshot = build_evidence_snapshot(
        str(received_dir),
        str(estimated_dir),
        benchkit_commit="abc123",
        generated_at="2026-09-07T00:00:00Z",
        app_support_rows=[
            {
                "app": "demoapp",
                "systems": {
                    "DemoSystem": {"status": "enabled"},
                },
            }
        ],
    )

    assert snapshot["generated_at"] == "2026-09-07T00:00:00Z"
    assert snapshot["summary"]["row_count"] == 1
    assert snapshot["summary"]["result_count"] == 1
    assert snapshot["summary"]["profiled_count"] == 1
    assert snapshot["summary"]["estimated_count"] == 1

    demosystem = next(row for row in snapshot["rows"] if row["system"] == "DemoSystem")
    assert demosystem["configured"] == "yes"
    assert demosystem["latest_result_time"] == "2026-09-01 01:01:01"
    assert demosystem["latest_result_exp"] == "CASE0"
    assert demosystem["latest_result_status"] == "basic"
    assert demosystem["profiled"] == "yes"
    assert demosystem["estimated"] == "yes"
    assert demosystem["estimate_applicability"] == "applicable"
    assert demosystem["source_status"] == "tracked"
    assert demosystem["input_status"] == "Covered"
    assert demosystem["build_cache_status"] == "hit"
    assert demosystem["public_result_available"] == "yes"
    assert demosystem["missing_reason"] == "none"
    assert all(row["system"] != "FutureSystem" for row in snapshot["rows"])


def test_evidence_snapshot_uses_estimate_benchmark_systems_without_future_target_rows(tmp_path):
    received_dir = tmp_path / "received"
    estimated_dir = tmp_path / "estimated"
    received_dir.mkdir()
    estimated_dir.mkdir()

    _write_json(
        estimated_dir / "estimate_20260902_020202_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "auxapp",
            "exp": "p8",
            "current_system": {
                "system": "DemoSystem",
                "benchmark": {"system": "DemoSystem"},
            },
            "future_system": {
                "system": "FutureSystem",
                "benchmark": {"system": "PeerSystem"},
            },
            "applicability": {"status": "applicable"},
        },
    )

    snapshot = build_evidence_snapshot(
        str(received_dir),
        str(estimated_dir),
        benchkit_commit="abc123",
        generated_at="2026-09-07T00:00:00Z",
        app_support_rows=[
            {
                "app": "auxapp",
                "systems": {
                    "DemoSystem": {"status": "enabled"},
                    "PeerSystem": {"status": "enabled"},
                },
            }
        ],
    )

    systems = {row["system"]: row for row in snapshot["rows"]}
    assert set(systems) == {"DemoSystem", "PeerSystem"}
    assert systems["DemoSystem"]["estimated"] == "yes"
    assert systems["PeerSystem"]["estimated"] == "yes"
    assert "FutureSystem" not in systems


def test_evidence_snapshot_redacts_confidential_result_availability(tmp_path):
    received_dir = tmp_path / "received"
    estimated_dir = tmp_path / "estimated"
    received_dir.mkdir()
    estimated_dir.mkdir()

    _write_json(
        received_dir / "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "thirdapp",
            "system": "DemoSystem",
            "Exp": "CASE0",
            "FOM": 1.0,
            "confidential": ["internal"],
        },
    )

    snapshot = build_evidence_snapshot(
        str(received_dir),
        str(estimated_dir),
        generated_at="2026-09-07T00:00:00Z",
        app_support_rows=[],
    )

    row = snapshot["rows"][0]
    assert row["public_result_available"] == "no"
    assert row["configured"] == "no"
    assert "not configured" in row["missing_reason"]
