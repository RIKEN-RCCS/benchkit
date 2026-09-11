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
                "repo_url": "https://github.com/example-owner/demoapp.git",
                "ref_name": "main",
                "resolved_commit": "abcdef1234567890",
                "public_access_check": {
                    "confirmed": True,
                    "method": "github_rest_api_anonymous",
                    "host": "github.com",
                },
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
    assert snapshot["summary"]["public_packet_available_count"] == 1
    assert snapshot["summary"]["public_packet_eligible_count"] == 1
    assert snapshot["summary"]["reuse_package_complete_count"] == 1

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
    assert (
        demosystem["latest_public_packet_file"]
        == "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    )
    assert demosystem["latest_public_packet_time"] == "2026-09-01 01:01:01"
    assert demosystem["reuse_package_status"] == "complete"
    assert demosystem["public_packet_status"] == "eligible"
    assert demosystem["public_packet_next_action"] == "Review public reuse packet"
    assert demosystem["next_action"] == "Ready for review"
    assert demosystem["missing_reason"] == "none"
    assert all(row["system"] != "FutureSystem" for row in snapshot["rows"])


def test_evidence_snapshot_requires_public_source_for_public_packet(tmp_path):
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
                "repo_url": "git@example.com:demoapp.git",
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

    row = snapshot["rows"][0]
    assert row["source_status"] == "tracked"
    assert row["input_status"] == "Covered"
    assert row["public_packet_status"] == "needs public source"
    assert row["public_packet_next_action"] == "Record public source provenance"
    assert row["reuse_package_status"] == "needs public evidence"


def test_evidence_snapshot_accepts_public_input_commit_for_public_packet(tmp_path):
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
                "repo_url": "https://github.com/example-owner/demoapp.git",
                "ref_name": "main",
                "resolved_commit": "abcdef1234567890",
                "public_access_check": {
                    "confirmed": True,
                    "method": "github_rest_api_anonymous",
                    "host": "github.com",
                },
            },
            "input_info": {
                "inputs": [
                    {
                        "dataset_id": "apoa1-p8",
                        "kind": "public-git",
                        "source": "public_url",
                        "public_url": "https://github.com/example-owner/input.git",
                        "source_ref": "main",
                        "resolved_commit": "1234567890abcdef",
                        "repo_relative_path": "npt/apoa1",
                        "verification_status": "public_source_commit",
                        "public_access_check": {
                            "confirmed": True,
                            "method": "github_rest_api_anonymous",
                            "host": "github.com",
                        },
                    }
                ],
            },
        },
    )

    snapshot = build_evidence_snapshot(
        str(received_dir),
        str(estimated_dir),
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

    row = snapshot["rows"][0]
    assert row["input_status"] == "Covered"
    assert (
        row["latest_public_packet_file"]
        == "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    )
    assert row["public_packet_status"] == "eligible"
    assert row["reuse_package_status"] == "public packet eligible"


def test_evidence_snapshot_keeps_latest_available_public_packet(tmp_path):
    received_dir = tmp_path / "received"
    estimated_dir = tmp_path / "estimated"
    received_dir.mkdir()
    estimated_dir.mkdir()

    public_source_info = {
        "source_type": "git",
        "repo_url": "https://github.com/example-owner/demoapp.git",
        "ref_name": "main",
        "resolved_commit": "abcdef1234567890",
        "public_access_check": {
            "confirmed": True,
            "method": "github_rest_api_anonymous",
            "host": "github.com",
        },
    }
    _write_json(
        received_dir / "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE0",
            "FOM": 1.0,
            "source_info": public_source_info,
            "input_info": {
                "inputs": [
                    {
                        "dataset_id": "case0",
                        "kind": "public-git",
                        "source": "public_url",
                        "public_url": "https://github.com/example-owner/input.git",
                        "source_ref": "main",
                        "resolved_commit": "1234567890abcdef",
                        "repo_relative_path": "benchmarks/case0",
                        "verification_status": "public_source_commit",
                        "public_access_check": {
                            "confirmed": True,
                            "method": "github_rest_api_anonymous",
                            "host": "github.com",
                        },
                    }
                ],
            },
        },
    )
    _write_json(
        received_dir / "result_20260902_020202_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE0",
            "FOM": 1.1,
            "source_info": public_source_info,
        },
    )

    snapshot = build_evidence_snapshot(
        str(received_dir),
        str(estimated_dir),
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

    row = snapshot["rows"][0]
    assert row["latest_result_time"] == "2026-09-02 02:02:02"
    assert row["input_status"] == "None"
    assert row["public_packet_status"] == "needs public input"
    assert row["public_packet_next_action"] == "Declare public input binding"
    assert snapshot["summary"]["public_packet_available_count"] == 1
    assert snapshot["summary"]["public_packet_eligible_count"] == 0
    assert (
        row["latest_public_packet_file"]
        == "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    )
    assert row["latest_public_packet_time"] == "2026-09-01 01:01:01"


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
    assert row["next_action"] == "Decide whether to add this app/system condition"
    assert "not configured" in row["missing_reason"]


def test_evidence_snapshot_next_action_prioritizes_practical_followup(tmp_path):
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
            "input_info": {"inputs": [{"dataset_id": "case0", "verification_status": "declared"}]},
        },
    )

    snapshot = build_evidence_snapshot(
        str(received_dir),
        str(estimated_dir),
        generated_at="2026-09-07T00:00:00Z",
        app_support_rows=[
            {
                "app": "demoapp",
                "systems": {
                    "DemoSystem": {"status": "enabled"},
                    "PeerSystem": {"status": "enabled"},
                    "PartialSystem": {"status": "enabled_partial"},
                },
            }
        ],
    )

    rows = {(row["code"], row["system"]): row for row in snapshot["rows"]}
    assert rows[("demoapp", "DemoSystem")]["next_action"] == "Record source provenance"
    assert rows[("demoapp", "PeerSystem")]["next_action"] == "Trigger a benchmark run"
    assert rows[("demoapp", "PartialSystem")]["next_action"] == "Complete app adapter scripts"
