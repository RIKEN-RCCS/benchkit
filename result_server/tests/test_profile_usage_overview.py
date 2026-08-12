import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.execution_profiles import (  # noqa: E402
    ExecutionProfileStore,
    normalize_profile,
    normalize_trigger_definition,
)
from utils.profile_usage_overview import build_profile_usage_overview  # noqa: E402


def _profile(**overrides):
    data = {
        "id": "qws-fugaku",
        "enabled": True,
        "status": "approved",
        "code": "qws",
        "system": "Fugaku",
        "exp": [],
        "allocation_project_id": "rkp00010",
    }
    data.update(overrides)
    profile, errors = normalize_profile(data)
    assert errors == []
    assert profile is not None
    return profile


def _trigger(**overrides):
    data = {
        "id": "qws-fugaku-time",
        "trigger_type": "scheduled",
        "profile_id": "qws-fugaku",
        "enabled": True,
        "gitlab_target": "swc",
        "target_ref": "develop",
        "cron_expr": "0 14 * * *",
        "timezone": "Asia/Tokyo",
    }
    data.update(overrides)
    trigger, errors = normalize_trigger_definition(data)
    assert errors == []
    assert trigger is not None
    return trigger


def test_profile_usage_overview_links_profile_triggers_results_and_node_hours(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    received_dir = tmp_path / "received"
    received_dir.mkdir()

    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(), actor="admin@test.com")
    store.upsert_trigger_definition(_trigger(), actor="admin@test.com")
    store.create_trigger_run(
        trigger_id="qws-fugaku-time",
        trigger_type="scheduled",
        status="submitted",
        dry_run=False,
        reason="cron:0 14 * * *@2026-08-10T14:00+09:00",
        payload={"submit": {"response": {"id": 123}}},
    )
    result_file = "result_20260810_140500_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    (received_dir / result_file).write_text(
        json.dumps(
            {
                "code": "qws",
                "system": "Fugaku",
                "Exp": "CASE0",
                "node_count": "2",
                "execution_mode": "cross",
                "pipeline_timing": {"run_time": 3600},
                "pipeline_id": 123,
                "execution_trigger": {
                    "id": "qws-fugaku-time",
                    "type": "scheduled",
                    "reason": "cron:0 14 * * *@2026-08-10T14:00+09:00",
                },
                "environment_snapshot": {
                    "hash": "sha256:54d4b0024f2e58b62b80cc5ca2b86f522fa69fee381c5a15e4cf37168debe7fb",
                    "summary": {
                        "system": "Fugaku",
                        "allocation_project_id": "rkp00010",
                        "scheduler": "pbs",
                        "runner": "fugaku-runner",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    overview = build_profile_usage_overview(str(received_dir), str(db_path))

    assert overview["available"] is True
    assert overview["summary"]["profile_count"] == 1
    assert overview["summary"]["profile_with_results_count"] == 1
    assert overview["summary"]["trigger_count"] == 1
    assert overview["summary"]["result_count"] == 1
    assert overview["summary"]["node_hours"] == 2.0
    row = overview["rows"][0]
    assert row["profile_id"] == "qws-fugaku"
    assert row["allocation_project_id"] == "rkp00010"
    assert row["enabled_trigger_count"] == 1
    assert row["result_count"] == 1
    assert row["snapshot_count"] == 1
    assert row["node_hours"] == 2.0
    assert row["attribution_counts"] == {
        "trigger_id_match": 1,
        "manual_profile_match": 0,
        "legacy_scope_fallback": 0,
    }
    assert row["latest_trigger_run"]["status"] == "submitted"
    assert row["latest_result"]["filename"] == result_file
    assert row["latest_result"]["trigger_headline"] == "Scheduled / qws-fugaku-time"
    assert row["latest_result"]["attribution"]["reason"] == "trigger_id_match"
    assert row["latest_result"]["environment_snapshot"]["short_hash"] == "sha256:54d4b0024f..."
    assert row["latest_result"]["environment_snapshot"]["allocation_project_id"] == "rkp00010"


def test_profile_usage_overview_does_not_scope_match_triggered_results_to_other_profiles(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    received_dir = tmp_path / "received"
    received_dir.mkdir()

    store = ExecutionProfileStore(str(db_path))
    store.upsert_profile(_profile(id="qws-fugaku"), actor="admin@test.com")
    store.upsert_profile(
        _profile(
            id="qws-test",
            system=["Fugaku", "MiyabiG"],
            allocation_project_id="",
        ),
        actor="admin@test.com",
    )
    store.upsert_trigger_definition(_trigger(profile_id="qws-fugaku"), actor="admin@test.com")
    (received_dir / "result_20260810_170000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json").write_text(
        json.dumps(
            {
                "code": "qws",
                "system": "Fugaku",
                "Exp": "CASE0",
                "node_count": "1",
                "execution_mode": "cross",
                "pipeline_timing": {"run_time": 3600},
                "execution_trigger": {
                    "id": "qws-fugaku-time",
                    "type": "scheduled",
                    "reason": "cron:0 14 * * *",
                },
            }
        ),
        encoding="utf-8",
    )
    (received_dir / "result_20260810_180000_cccccccc-dddd-eeee-ffff-000000000000.json").write_text(
        json.dumps(
            {
                "code": "qws",
                "system": "Fugaku",
                "Exp": "CASE0",
                "node_count": "1",
                "execution_mode": "cross",
                "pipeline_timing": {"run_time": 900},
                "execution_trigger": {
                    "id": "qws-fugaku",
                    "type": "manual_button",
                    "reason": "manual_button:qws-fugaku",
                },
            }
        ),
        encoding="utf-8",
    )
    (received_dir / "result_20260809_170000_bbbbbbbb-cccc-dddd-eeee-ffffffffffff.json").write_text(
        json.dumps(
            {
                "code": "qws",
                "system": "Fugaku",
                "Exp": "CASE0",
                "node_count": "1",
                "execution_mode": "cross",
                "pipeline_timing": {"run_time": 1800},
            }
        ),
        encoding="utf-8",
    )

    overview = build_profile_usage_overview(str(received_dir), str(db_path))

    rows = {row["profile_id"]: row for row in overview["rows"]}
    assert rows["qws-fugaku"]["result_count"] == 3
    assert rows["qws-fugaku"]["node_hours"] == 1.75
    assert rows["qws-fugaku"]["attribution_counts"] == {
        "trigger_id_match": 1,
        "manual_profile_match": 1,
        "legacy_scope_fallback": 1,
    }
    assert rows["qws-fugaku"]["latest_result"]["attribution"]["reason"] == "manual_profile_match"
    assert rows["qws-test"]["result_count"] == 1
    assert rows["qws-test"]["node_hours"] == 0.5
    assert rows["qws-test"]["attribution_counts"] == {
        "trigger_id_match": 0,
        "manual_profile_match": 0,
        "legacy_scope_fallback": 1,
    }
    assert rows["qws-test"]["latest_result"]["timestamp"] == "2026-08-09 17:00:00"
    assert rows["qws-test"]["latest_result"]["attribution"]["reason"] == "legacy_scope_fallback"


def test_profile_usage_overview_handles_missing_db(tmp_path):
    overview = build_profile_usage_overview(str(tmp_path), None)

    assert overview["available"] is False
    assert overview["rows"] == []
