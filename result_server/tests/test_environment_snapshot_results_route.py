"""Route tests for environment snapshot result listings."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_results_route_app, install_portal_test_stubs  # noqa: E402

install_portal_test_stubs()

from utils.environment_snapshots import index_environment_snapshot  # noqa: E402


def _add_navigation_routes(app):
    app.add_url_rule("/", "home", lambda: "home")
    app.add_url_rule("/systems", "systemlist", lambda: "systems")
    app.add_url_rule("/login", "auth.login", lambda: "login")
    app.add_url_rule("/logout", "auth.logout", lambda: "logout")


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _payload(uuid, snapshot_hash="sha256:routeabc"):
    return {
        "_server_uuid": uuid,
        "code": "qws",
        "system": "Fugaku",
        "Exp": "CASE1",
        "FOM": "0.423",
        "FOM_unit": "s",
        "node_count": "1",
        "pipeline_id": 3270,
        "pipeline_timing": {"run_time": 120},
        "execution_trigger": {
            "id": "qws-fugaku-time",
            "type": "scheduled",
            "reason": "cron:0 14 * * *",
        },
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


def test_environment_snapshot_results_route_lists_linked_results(tmp_path):
    received_dir = tmp_path / "received"
    received_dir.mkdir()
    db_path = tmp_path / "cx_portal.sqlite3"
    filename = "result_20260810_160604_11111111-2222-3333-4444-555555555555.json"
    payload = _payload("11111111-2222-3333-4444-555555555555")
    _write_json(received_dir / filename, payload)
    assert index_environment_snapshot(
        db_path=str(db_path),
        payload=payload,
        json_file=filename,
    )

    app = build_results_route_app(received_dir=str(received_dir))
    _add_navigation_routes(app)
    app.config["EXECUTION_PROFILE_DB_PATH"] = str(db_path)
    response = app.test_client().get("/results/environment-snapshots/sha256:routeabc")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Environment Snapshot" in html
    assert "Visible Results" in html
    assert "1 / 1 linked" in html
    assert "Node-hours" in html
    assert "sha256:routeabc" in html
    assert "result_detail" not in html
    assert "2026-08-10 16:06:04" in html
    assert "qws" in html
    assert "Fugaku" in html
    assert "Scheduled / qws-fugaku-time" in html
    assert "0.03" in html


def test_result_detail_links_to_environment_snapshot_results(tmp_path):
    received_dir = tmp_path / "received"
    received_dir.mkdir()
    filename = "result_20260810_160604_11111111-2222-3333-4444-555555555555.json"
    _write_json(received_dir / filename, _payload("11111111-2222-3333-4444-555555555555"))

    app = build_results_route_app(received_dir=str(received_dir))
    _add_navigation_routes(app)
    app.config["EXECUTION_PROFILE_DB_PATH"] = str(tmp_path / "cx_portal.sqlite3")
    response = app.test_client().get(f"/results/detail/{filename}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "View results with this snapshot" in html
    assert "/results/environment-snapshots/sha256:routeabc" in html
