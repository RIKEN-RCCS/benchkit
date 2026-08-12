"""Tests for environment snapshot indexing."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.environment_snapshots import (  # noqa: E402
    extract_environment_snapshot_record,
    get_environment_snapshot,
    index_environment_snapshot,
    list_environment_snapshot_results,
    list_environment_snapshots,
)


def _payload(snapshot_hash="sha256:abc123"):
    return {
        "code": "qws",
        "system": "Fugaku",
        "Exp": "CASE1",
        "_server_uuid": "11111111-2222-3333-4444-555555555555",
        "pipeline_id": 3270,
        "environment_snapshot": {
            "schema_version": 1,
            "hash": snapshot_hash,
            "summary": {
                "system": "Fugaku",
                "allocation_project_id": "rkp00010",
                "scheduler": "pbs",
                "runner": "fugaku-runner",
                "benchkit_commit": "abcdef",
            },
            "payload": {
                "schema_version": 1,
                "system": {
                    "name": "Fugaku",
                    "allocation_project_id": "rkp00010",
                },
                "scheduler": {"kind": "pbs"},
            },
        },
    }


def test_extract_environment_snapshot_record():
    record = extract_environment_snapshot_record(_payload())

    assert record is not None
    assert record["snapshot_hash"] == "sha256:abc123"
    assert record["schema_version"] == 1
    assert record["result_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert record["pipeline_id"] == "3270"
    assert json.loads(record["summary_json"])["allocation_project_id"] == "rkp00010"


def test_index_environment_snapshot_deduplicates_payloads(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"

    assert index_environment_snapshot(
        db_path=str(db_path),
        payload=_payload(),
        json_file="result-a.json",
    )
    payload = _payload()
    payload["_server_uuid"] = "22222222-3333-4444-5555-666666666666"
    assert index_environment_snapshot(
        db_path=str(db_path),
        payload=payload,
        json_file="result-b.json",
    )

    rows = list_environment_snapshots(str(db_path))
    assert len(rows) == 1
    assert rows[0]["snapshot_hash"] == "sha256:abc123"
    assert rows[0]["result_count"] == 2
    snapshot = get_environment_snapshot(str(db_path), "sha256:abc123")
    assert snapshot is not None
    assert snapshot["summary"]["system"] == "Fugaku"
    assert snapshot["payload"]["scheduler"]["kind"] == "pbs"
    linked_results = list_environment_snapshot_results(str(db_path), "sha256:abc123")
    assert [row["json_file"] for row in linked_results] == ["result-b.json", "result-a.json"]

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        links = conn.execute(
            "SELECT result_uuid, snapshot_hash FROM environment_snapshot_results ORDER BY result_uuid"
        ).fetchall()
    assert links == [
        ("11111111-2222-3333-4444-555555555555", "sha256:abc123"),
        ("22222222-3333-4444-5555-666666666666", "sha256:abc123"),
    ]


def test_index_environment_snapshot_moves_existing_result_link(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"

    index_environment_snapshot(
        db_path=str(db_path),
        payload=_payload("sha256:old"),
        json_file="result-a.json",
    )
    index_environment_snapshot(
        db_path=str(db_path),
        payload=_payload("sha256:new"),
        json_file="result-a.json",
    )

    rows = {
        row["snapshot_hash"]: row["result_count"]
        for row in list_environment_snapshots(str(db_path))
    }
    assert rows["sha256:old"] == 0
    assert rows["sha256:new"] == 1
