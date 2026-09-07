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
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE0",
            "FOM": 1.0,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.com/qws.git",
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
            "code": "qws",
            "exp": "CASE0",
            "current_system": {"system": "Fugaku"},
            "future_system": {"system": "FugakuNEXT"},
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
                "app": "qws",
                "systems": {
                    "Fugaku": {"status": "enabled"},
                    "FugakuNEXT": {"status": "enabled_partial"},
                },
            }
        ],
    )

    assert snapshot["generated_at"] == "2026-09-07T00:00:00Z"
    assert snapshot["summary"]["row_count"] == 2
    assert snapshot["summary"]["result_count"] == 1
    assert snapshot["summary"]["profiled_count"] == 1
    assert snapshot["summary"]["estimated_count"] == 2

    fugaku = next(row for row in snapshot["rows"] if row["system"] == "Fugaku")
    assert fugaku["configured"] == "yes"
    assert fugaku["latest_result_time"] == "2026-09-01 01:01:01"
    assert fugaku["latest_result_exp"] == "CASE0"
    assert fugaku["latest_result_status"] == "basic"
    assert fugaku["profiled"] == "yes"
    assert fugaku["estimated"] == "yes"
    assert fugaku["estimate_applicability"] == "applicable"
    assert fugaku["source_status"] == "tracked"
    assert fugaku["input_status"] == "Covered"
    assert fugaku["build_cache_status"] == "hit"
    assert fugaku["public_result_available"] == "yes"
    assert fugaku["missing_reason"] == "none"

    future = next(row for row in snapshot["rows"] if row["system"] == "FugakuNEXT")
    assert future["configured"] == "partial"
    assert future["estimated"] == "yes"
    assert "script support incomplete" in future["missing_reason"]
    assert "no result" in future["missing_reason"]


def test_evidence_snapshot_redacts_confidential_result_availability(tmp_path):
    received_dir = tmp_path / "received"
    estimated_dir = tmp_path / "estimated"
    received_dir.mkdir()
    estimated_dir.mkdir()

    _write_json(
        received_dir / "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "salmon",
            "system": "Fugaku",
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
