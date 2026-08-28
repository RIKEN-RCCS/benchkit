"""Tests for the SQLite result metadata index."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.result_metadata_index import (  # noqa: E402
    extract_result_index_record,
    index_result_metadata,
    list_indexed_results,
)


def test_extract_result_index_record_from_benchmark_result():
    payload = {
        "code": "qws",
        "system": "RIKYU",
        "Exp": "case0",
        "FOM": 42.5,
        "_server_uuid": "11111111-2222-3333-4444-555555555555",
        "_server_timestamp": "20260806_010203",
        "ci_trigger": "pipeline",
        "pipeline_id": 3152,
        "source_info": {
            "source_type": "git",
            "repo_url": "https://example.org/repo.git",
            "branch": "develop",
            "commit_hash": "abcdef123456",
            "ref_name": "v1.0",
            "ref_kind": "tag",
            "resolved_commit": "0123456789abcdef0123456789abcdef01234567",
        },
    }

    record = extract_result_index_record(
        record_type="result",
        payload=payload,
        json_file="result_20260806_010203_11111111-2222-3333-4444-555555555555.json",
    )

    assert record["result_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert record["server_timestamp"] == "20260806_010203"
    assert record["code"] == "qws"
    assert record["system"] == "RIKYU"
    assert record["exp"] == "case0"
    assert record["pipeline_id"] == "3152"
    assert record["source_type"] == "git"
    assert record["source_ref"] == "0123456789abcdef0123456789abcdef01234567"
    metadata = json.loads(record["metadata_json"])
    assert metadata["fom"] == 42.5
    assert metadata["source_info"]["branch"] == "develop"
    assert metadata["source_info"]["ref_kind"] == "tag"
    assert metadata["source_info"]["resolved_commit"] == "0123456789abcdef0123456789abcdef01234567"


def test_index_result_metadata_upserts_rows(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    payload = {
        "code": "qws",
        "system": "RIKYU",
        "_server_uuid": "11111111-2222-3333-4444-555555555555",
        "_server_timestamp": "20260806_010203",
    }

    indexed = index_result_metadata(
        db_path=str(db_path),
        record_type="result",
        payload=payload,
        json_file="result.json",
    )
    payload["system"] = "FugakuNEXT"
    index_result_metadata(
        db_path=str(db_path),
        record_type="result",
        payload=payload,
        json_file="result-renamed.json",
    )

    rows = list_indexed_results(str(db_path), record_type="result")
    assert indexed is True
    assert len(rows) == 1
    assert rows[0]["json_file"] == "result-renamed.json"
    assert rows[0]["system"] == "FugakuNEXT"


def test_extract_result_index_record_from_estimate_result():
    payload = {
        "code": "qws",
        "exp": "case0",
        "performance_ratio": 2.5,
        "current_system": {"system": "RIKYU"},
        "future_system": {"system": "FugakuNEXT"},
        "estimate_metadata": {
            "estimation_result_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "estimation_result_timestamp": "2026-08-06 01:02:03",
            "source_result_uuid": "11111111-2222-3333-4444-555555555555",
            "estimation_package": "weakscaling",
        },
        "applicability": {"status": "applicable"},
    }

    record = extract_result_index_record(
        record_type="estimate",
        payload=payload,
        json_file="estimate_20260806_010203_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
    )

    assert record["result_uuid"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert record["server_timestamp"] == "2026-08-06 01:02:03"
    assert record["code"] == "qws"
    assert record["system"] == "RIKYU"
    assert record["exp"] == "case0"
    metadata = json.loads(record["metadata_json"])
    assert metadata["source_result_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert metadata["future_system"] == "FugakuNEXT"
