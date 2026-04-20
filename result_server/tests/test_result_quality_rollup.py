import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.result_quality_rollup import build_result_quality_rollup


def _write_result(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def test_build_result_quality_rollup(tmp_path):
    _write_result(
        tmp_path / "result_20260401_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 1.0,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.com/repo.git",
                "branch": "main",
                "commit_hash": "abcdef1234567890",
            },
            "fom_breakdown": {
                "sections": [
                    {
                        "name": "solver",
                        "time": 0.8,
                        "estimation_package": "weakscaling",
                        "artifacts": [{"type": "file_reference", "path": "a.json"}],
                    },
                ],
                "overlaps": [],
            },
        },
    )
    _write_result(
        tmp_path / "result_20260402_010101_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 2.0,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.com/repo.git",
                "branch": "main",
            },
        },
    )
    _write_result(
        tmp_path / "result_20260403_010101_cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee.json",
        {
            "code": "genesis",
            "system": "RC_GENOA",
            "FOM": 3.0,
        },
    )

    rollup = build_result_quality_rollup(str(tmp_path))

    assert rollup["entry_count"] == 2

    genesis = next(row for row in rollup["rows"] if row["app"] == "genesis")
    assert genesis["system"] == "RC_GENOA"
    assert genesis["source_tracked"] is False
    assert genesis["source_status"] == "not tracked"
    assert genesis["source_type"] == "-"
    assert genesis["source_reference"] == "-"
    assert genesis["source_missing_fields"] == ["source_info"]
    assert genesis["breakdown_present"] is False
    assert genesis["estimation_ready"] is False
    assert genesis["rich"] is False
    assert genesis["quality_label"] == "Basic"
    assert genesis["warning_count"] >= 2
    assert genesis["next_action"] == "populate top-level source_info for provenance tracking"
    assert "source_info present" in genesis["validator_candidates"]

    qws = next(row for row in rollup["rows"] if row["app"] == "qws")
    assert qws["system"] == "Fugaku"
    assert qws["timestamp"] == "2026-04-02 01:01:01"
    assert qws["source_tracked"] is False
    assert qws["source_status"] == "not tracked"
    assert qws["source_type"] == "git"
    assert qws["source_reference"] == "main"
    assert qws["source_missing_fields"] == ["commit_hash"]
    assert qws["breakdown_present"] is False
    assert qws["estimation_ready"] is False
    assert qws["rich"] is False
    assert qws["next_action"] == "fill the missing top-level source_info fields"
    assert "complete source_info fields" in qws["validator_candidates"]
