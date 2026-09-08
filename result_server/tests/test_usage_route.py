"""Route tests for /results/usage and related usage navigation."""

import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import (
    StaticAffiliationUserStore,
    build_portal_route_app,
    install_portal_test_stubs,
)

install_portal_test_stubs()


@pytest.fixture
def tmp_dirs():
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    yield received, estimated
    shutil.rmtree(received)
    shutil.rmtree(estimated)


@pytest.fixture
def app(tmp_dirs):
    received, estimated = tmp_dirs
    yield build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=received,
        estimated_dir=estimated,
        user_store=StaticAffiliationUserStore(
            {
                "admin@example.com": ["admin"],
                "user@example.com": ["dev"],
            }
        ),
        totp_issuer="Benchkit-Test",
    )


@pytest.fixture
def client(app):
    return app.test_client()


def _login_session(client, email, affiliations):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = email
        sess["user_affiliations"] = affiliations


def _write_result(directory, filename, data):
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestUsageRoute:
    def test_confidential_results_hides_table_when_unauthenticated(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {"code": "demoapp", "system": "DemoSystem", "Exp": "CASE0", "FOM": 1.0},
        )
        resp = client.get("/results/confidential")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Authentication required to view confidential data." in text
        assert '<table id="resultsTable"' not in text
        assert "no-store" in resp.headers.get("Cache-Control", "")

    def test_unauthenticated_user_is_redirected_to_login(self, client):
        resp = client.get("/results/usage")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
        assert "no-store" in resp.headers.get("Cache-Control", "")

    def test_non_admin_user_gets_403(self, client):
        _login_session(client, "user@example.com", ["dev"])
        resp = client.get("/results/usage")
        assert resp.status_code == 403

    def test_admin_user_can_access_usage_page(self, client):
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        assert resp.status_code == 200
        assert "Usage Report" in resp.get_data(as_text=True)
        assert "no-store" in resp.headers.get("Cache-Control", "")

    def test_usage_page_shows_consolidated_evidence_snapshot(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {"code": "demoapp", "system": "DemoSystem", "Exp": "CASE0", "FOM": 1.0},
        )
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        assert resp.status_code == 200
        text = resp.get_data(as_text=True)
        assert "Configuration Checks" in text
        assert "Evidence Snapshot" in text
        assert "Result / Quality" in text
        assert "Application/System Coverage" not in text
        assert "Latest Result Quality Details" not in text
        assert "Maturity Gaps" in text
        assert "demoapp" in text

    def test_usage_page_shows_source_tracking_columns_when_rollup_exists(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {
                "code": "demoapp",
                "system": "DemoSystem",
                "Exp": "CASE0",
                "FOM": 1.0,
                "source_info": {
                    "source_type": "git",
                    "repo_url": "https://example.com/repo.git",
                    "branch": "main",
                    "commit_hash": "abcdef1234567890",
                },
            },
        )

        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Source Status" in text
        assert "tracked" in text
        assert "Input Status" in text

    def test_usage_route_uses_default_parameters(self, app, client, monkeypatch):
        _login_session(client, "admin@example.com", ["admin"])

        captured = {}

        def fake_build_usage_report_context(
            directory,
            args,
            current_fiscal_year,
            db_path=None,
            estimated_dir=None,
            benchkit_commit="",
        ):
            captured["directory"] = directory
            captured["args"] = args
            captured["current_fiscal_year"] = current_fiscal_year
            captured["db_path"] = db_path
            captured["estimated_dir"] = estimated_dir
            captured["benchkit_commit"] = benchkit_commit
            return {
                "result": {
                    "apps": [],
                    "systems": [],
                    "periods": ["FY2025"],
                    "table": {},
                    "row_totals": {},
                    "col_totals": {},
                    "grand_totals": {},
                    "available_fiscal_years": [2025],
                },
                "period_type": "fiscal_year",
                "fiscal_year": 2025,
                "period_filter": "",
                "filtered_periods": ["FY2025"],
                "site_diagnostics": {
                    "registered_system_count": 0,
                    "unused_systems": [],
                    "missing_system_info": [],
                    "missing_queue_definitions": [],
                    "application_count": 0,
                    "partial_support": [],
                },
                "profile_usage_overview": {"available": False, "rows": []},
                "performance_telemetry": {"summary": {"result_count": 0}, "rows": []},
                "evidence_snapshot": {
                    "summary": {
                        "row_count": 0,
                        "result_count": 0,
                        "profiled_count": 0,
                        "estimated_count": 0,
                    },
                    "rows": [],
                },
            }

        import routes.results_usage_routes as usage_routes_mod

        monkeypatch.setattr(usage_routes_mod, "build_usage_report_context", fake_build_usage_report_context)
        monkeypatch.setattr(usage_routes_mod, "get_fiscal_year", lambda dt: 2025)

        resp = client.get("/results/usage")
        assert resp.status_code == 200
        assert captured["directory"] == app.config["RECEIVED_DIR"]
        assert captured["db_path"] == app.config.get("EXECUTION_PROFILE_DB_PATH")
        assert captured["estimated_dir"] == app.config.get("ESTIMATED_DIR")
        assert captured["benchkit_commit"] == ""
        assert captured["current_fiscal_year"] == 2025
        assert captured["args"].get("period_type") is None

    def test_usage_page_shows_evidence_snapshot_and_csv_link(self, client, tmp_dirs):
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Evidence Snapshot" in text
        assert "Maturity Gaps" in text
        assert "Execution Timing Overview" in text
        assert "Evidence Snapshot:</strong> the roll-up and CSV export source" in text
        assert "reported queue values may not include scheduler-side wait" in text
        assert "Input Status:</strong> None = no input_info" in text
        assert "/results/usage/evidence-snapshot.csv" in text

    def test_usage_evidence_snapshot_csv_requires_admin(self, client):
        resp = client.get("/results/usage/evidence-snapshot.csv")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

        _login_session(client, "user@example.com", ["dev"])
        resp = client.get("/results/usage/evidence-snapshot.csv")
        assert resp.status_code == 403

    def test_usage_evidence_snapshot_csv_exports_flat_rows(self, client, tmp_dirs):
        received, estimated = tmp_dirs
        _write_result(
            received,
            "result_20260901_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
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
                "build_cache": {"status": "hit", "stored": False},
            },
        )
        _write_result(
            estimated,
            "estimate_20260902_020202_bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {
                "code": "demoapp",
                "exp": "CASE0",
                "current_system": {"system": "DemoSystem"},
                "future_system": {"system": "FutureSystem"},
                "applicability": {"status": "applicable"},
            },
        )

        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage/evidence-snapshot.csv")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert "attachment; filename=evidence_snapshot_" in resp.headers["Content-Disposition"]
        assert "snapshot_time,benchkit_commit,code,system,configured" in text
        assert "demoapp,DemoSystem" in text
        assert "hit" in text
        assert "example.com/demoapp.git" not in text

    def test_usage_page_shows_no_data_message(self, client):
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/usage")
        assert resp.status_code == 200
        assert "No usage data is available for the selected periods." in resp.get_data(as_text=True)

    def test_admin_navigation_shows_usage_link(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {"code": "demoapp", "system": "DemoSystem", "Exp": "CASE0", "FOM": 1.0},
        )
        _login_session(client, "admin@example.com", ["admin"])
        resp = client.get("/results/confidential")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "/results/usage" in text

    def test_non_admin_navigation_hides_usage_link(self, client, tmp_dirs):
        received, _ = tmp_dirs
        _write_result(
            received,
            "result_20260401_123456_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json",
            {"code": "demoapp", "system": "DemoSystem", "Exp": "CASE0", "FOM": 1.0},
        )
        _login_session(client, "user@example.com", ["dev"])
        resp = client.get("/results/confidential")
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "/results/usage" not in text
