import os
import sys
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_results_route_app, install_portal_test_stubs

install_portal_test_stubs()

from utils.result_table_rows import build_result_table_row
from utils.execution_profiles import ExecutionProfileStore
from utils.trigger_display import (
    build_trigger_result_links,
    build_trigger_run_lookup,
    load_trigger_run_lookup,
    summarize_execution_trigger,
    summarize_trigger_run,
)


@pytest.fixture
def flask_app(tmp_path):
    return build_results_route_app(
        received_dir=str(tmp_path),
        estimated_dir=str(tmp_path),
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )


def test_summarize_execution_trigger_formats_portal_metadata(flask_app):
    result = {
        "code": "demoapp",
        "system": "DemoSystem",
        "Exp": "case0",
        "FOM": 1.0,
        "execution_trigger": {
            "id": "demoapp-demosystem-watch",
            "type": "watch_event",
            "reason": "repo_ref:https://example.test/demoapp.git@master",
        },
    }

    summary = summarize_execution_trigger(result)

    assert summary["has_trigger"] is True
    assert summary["headline"] == "Watch event / demoapp-demosystem-watch"
    assert summary["subline"] == "repo/ref changed: https://example.test/demoapp.git@master"
    with flask_app.test_request_context("/results/"):
        row = build_result_table_row("20260807_030000_aaaaaaaa.json", result, [])
    assert row["execution_trigger_summary"]["headline"] == summary["headline"]


def test_summarize_execution_trigger_handles_older_results():
    summary = summarize_execution_trigger({"code": "demoapp"})

    assert summary == {
        "has_trigger": False,
        "headline": "-",
        "subline": "",
        "title": "No Portal trigger metadata was recorded for this result.",
    }


def test_summarize_execution_trigger_falls_back_to_pipeline_lookup():
    runs = [
        {
            "trigger_id": "demoapp-demosystem-watch",
            "trigger_type": "watch_event",
            "status": "submitted",
            "reason": "repo_ref:https://example.test/demoapp.git@master",
            "payload_json": {
                "submit": {"response": {"id": 3186}},
            },
        }
    ]

    summary = summarize_execution_trigger(
        {"pipeline_id": 3186},
        build_trigger_run_lookup(runs),
    )

    assert summary["headline"] == "Watch event / demoapp-demosystem-watch"
    assert summary["subline"] == "repo/ref changed: https://example.test/demoapp.git@master"


def test_summarize_execution_trigger_falls_back_to_parent_pipeline_lookup():
    runs = [
        {
            "trigger_id": "demoapp-demosystem-1400",
            "trigger_type": "scheduled",
            "status": "submitted",
            "reason": "cron:0 14 * * *@2026-08-07T14:00+09:00",
            "payload_json": {
                "submit": {"response": {"id": 3189}},
            },
        }
    ]

    summary = summarize_execution_trigger(
        {"pipeline_id": 3190, "parent_pipeline_id": 3189},
        build_trigger_run_lookup(runs),
    )

    assert summary["headline"] == "Scheduled / demoapp-demosystem-1400"
    assert summary["subline"] == "cron 0 14 * * * / 2026-08-07T14:00+09:00"


def test_load_trigger_run_lookup_ignores_newer_routine_runs(tmp_path):
    db_path = tmp_path / "cx_portal.sqlite3"
    store = ExecutionProfileStore(str(db_path))
    store.create_trigger_run(
        trigger_id="demoapp-demosystem-watch",
        trigger_type="watch_event",
        status="submitted",
        dry_run=False,
        reason="repo_ref:https://example.test/demoapp.git@master",
        payload={"submit": {"response": {"id": 3186}}},
    )
    for index in range(20):
        store.create_trigger_run(
            trigger_id="demoapp-demosystem-watch",
            trigger_type="watch_event",
            status="unchanged",
            dry_run=False,
            reason=f"repo_ref:{index}",
            payload={},
        )

    lookup = load_trigger_run_lookup(str(db_path), limit=1)

    assert lookup["3186"]["status"] == "submitted"


def test_summarize_execution_trigger_falls_back_to_child_pipeline_lookup():
    runs = [
        {
            "trigger_id": "demoapp-demosystem-watch",
            "trigger_type": "watch_event",
            "status": "submitted",
            "reason": "repo_ref:https://example.test/demoapp.git@master",
            "payload_json": {
                "submit": {"response": {"id": 3187, "child_pipeline_ids": [3188]}},
            },
        }
    ]

    summary = summarize_execution_trigger(
        {"pipeline_id": 3188},
        build_trigger_run_lookup(runs),
    )

    assert summary["headline"] == "Watch event / demoapp-demosystem-watch"


def test_summarize_trigger_run_extracts_payload_context():
    run = {
        "id": 3,
        "trigger_id": "demoapp-demosystem-1400",
        "trigger_type": "scheduled",
        "status": "submitted",
        "dry_run": False,
        "reason": "cron:0 14 * * *@2026-08-07T14:00+09:00",
        "payload_json": {
            "gitlab_target": "site_ci",
            "gitlab_project": "gitlab.example.org/group/project",
            "submit": {"response": {"id": 3186}},
            "payload": {
                "ref": "develop",
                "variables": {
                    "code": "demoapp",
                    "system": "DemoSystem",
                    "BK_ALLOCATION_PROJECT_ID": "project00010",
                    "RESULT_SERVER": "https://portal.example.org/dev",
                },
            },
        },
        "errors": [],
        "actor": "trigger_runner",
        "created_at": "2026-08-07T05:00:00Z",
    }

    summary = summarize_trigger_run(run)

    assert summary["target_ref"] == "develop"
    assert summary["code"] == "demoapp"
    assert summary["system"] == "DemoSystem"
    assert summary["allocation_project_id"] == "project00010"
    assert summary["pipeline_id"] == "3186"
    assert summary["reason_label"] == "cron 0 14 * * * / 2026-08-07T14:00+09:00"


def test_build_trigger_result_links_matches_direct_trigger_metadata(tmp_path):
    result_file = tmp_path / "result_20260807_140000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    result_file.write_text(
        json.dumps(
            {
                "code": "demoapp",
                "Exp": "CASE0",
                "execution_trigger": {
                    "id": "demoapp-demosystem-watch",
                    "type": "watch_event",
                    "reason": "repo_ref:https://example.test/demoapp.git@master",
                },
            }
        ),
        encoding="utf-8",
    )
    runs = [
        {
            "id": 7,
            "trigger_id": "demoapp-demosystem-watch",
            "trigger_type": "watch_event",
            "reason": "repo_ref:https://example.test/demoapp.git@master",
            "payload_json": {},
        }
    ]

    links = build_trigger_result_links(str(tmp_path), runs)

    assert links[7][0]["filename"] == result_file.name
    assert links[7][0]["label"] == "2026-08-07 14:00:00 / CASE0"


def test_build_trigger_result_links_matches_child_pipeline_fallback(tmp_path):
    result_file = tmp_path / "result_20260807_140611_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    result_file.write_text(
        json.dumps({"code": "demoapp", "Exp": "CASE1", "pipeline_id": 3190}),
        encoding="utf-8",
    )
    runs = [
        {
            "id": 8,
            "trigger_id": "demoapp-demosystem-1400",
            "trigger_type": "scheduled",
            "reason": "cron:0 14 * * *@2026-08-07T14:00+09:00",
            "payload_json": {
                "submit": {"response": {"id": 3189, "child_pipeline_ids": [3190]}},
            },
        }
    ]

    links = build_trigger_result_links(str(tmp_path), runs)

    assert links[8][0]["filename"] == result_file.name
    assert links[8][0]["pipeline_id"] == "3190"


def test_build_trigger_result_links_matches_parent_pipeline_fallback(tmp_path):
    result_file = tmp_path / "result_20260807_140611_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    result_file.write_text(
        json.dumps({"code": "demoapp", "Exp": "CASE1", "pipeline_id": 3190, "parent_pipeline_id": 3189}),
        encoding="utf-8",
    )
    runs = [
        {
            "id": 9,
            "trigger_id": "demoapp-demosystem-1400",
            "trigger_type": "scheduled",
            "reason": "cron:0 14 * * *@2026-08-07T14:00+09:00",
            "payload_json": {
                "submit": {"response": {"id": 3189}},
            },
        }
    ]

    links = build_trigger_result_links(str(tmp_path), runs)

    assert links[9][0]["filename"] == result_file.name
    assert links[9][0]["pipeline_id"] == "3190"
