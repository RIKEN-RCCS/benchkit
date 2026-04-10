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
        tmp_path / "qws_1.json",
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
                    {"name": "solver", "time": 0.8, "estimation_package": "weakscaling", "artifacts": [{"type": "file_reference", "path": "a.json"}]},
                ],
                "overlaps": [],
            },
        },
    )
    _write_result(
        tmp_path / "qws_2.json",
        {
            "code": "qws",
            "system": "MiyabiG",
            "FOM": 2.0,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.com/repo.git",
                "branch": "main",
            },
        },
    )
    _write_result(
        tmp_path / "genesis_1.json",
        {
            "code": "genesis",
            "system": "RC_GENOA",
            "FOM": 3.0,
        },
    )

    rollup = build_result_quality_rollup(str(tmp_path))

    assert rollup["total_results"] == 3
    assert rollup["app_count"] == 2

    genesis = next(row for row in rollup["rows"] if row["app"] == "genesis")
    assert genesis["results"] == 1
    assert genesis["source_tracked"] == 0
    assert genesis["breakdown"] == 0
    assert genesis["estimation_ready"] == 0
    assert genesis["rich"] == 0

    qws = next(row for row in rollup["rows"] if row["app"] == "qws")
    assert qws["results"] == 2
    assert qws["source_tracked"] == 1
    assert qws["breakdown"] == 1
    assert qws["estimation_ready"] == 1
    assert qws["rich"] == 1
    assert qws["source_tracked_pct"] == 50
