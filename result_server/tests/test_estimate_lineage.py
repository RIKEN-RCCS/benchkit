"""Synthetic stored-record and route checks; no live DB or services."""

import json
from pathlib import Path
import sys
from uuid import UUID

import pytest
from flask import session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_support import StaticAffiliationUserStore, build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs()

from utils.estimate_lineage import build_estimate_lineage


SOURCE = str(UUID(int=1))
E0, E1, E2 = (str(UUID(int=n)) for n in (2, 3, 4))


@pytest.fixture
def app(tmp_path):
    received, estimated = tmp_path / "received", tmp_path / "estimated"
    received.mkdir()
    estimated.mkdir()
    return build_portal_route_app(
        templates_dir=str(Path(__file__).resolve().parents[1] / "templates"),
        received_dir=str(received), estimated_dir=str(estimated),
        user_store=StaticAffiliationUserStore({"reader@example.com": ["dev"]}),
    )


def write(app, payload, uid, *, estimate=True, name=None):
    filename = name or f"{'estimate' if estimate else 'result'}_20260101_000000_{uid}.json"
    directory = app.config["ESTIMATED_DIR" if estimate else "RECEIVED_DIR"]
    (Path(directory) / filename).write_text(json.dumps(payload))
    return filename


def estimate(uid, parent=None, source=SOURCE):
    payload = {
        "code": "demoapp", "exp": "CASE0", "applicability": {"status": "applicable"},
        "estimate_metadata": {
            "estimation_result_uuid": uid, "source_result_uuid": source,
            "estimation_result_timestamp": "2026-01-01 00:00:00",
            "app_estimation_method": {"version": "1"},
            "estimation_package": "demo", "estimation_package_version": "2",
        },
        "current_system": {"system": "Current", "target_nodes": 1},
        "future_system": {"system": "Future", "target_nodes": 2},
    }
    if parent:
        payload["reestimation"] = {"previous_estimation_result_uuid": parent}
    return payload


def authenticate():
    session.update(authenticated=True, user_email="reader@example.com")


def lineage(app, payload=None, filename="result.json", *, is_estimate=False):
    with app.test_request_context():
        authenticate()
        return build_estimate_lineage(payload or {"_server_uuid": SOURCE}, filename, estimate=is_estimate)


def test_branching_history_and_current_record(app):
    result_name = write(app, {"_server_uuid": SOURCE}, SOURCE, estimate=False)
    names = [write(app, estimate(uid, parent), uid) for uid, parent in ((E0, None), (E1, E0), (E2, E0))]
    history = lineage(app, estimate(E1, E0), names[1], is_estimate=True)
    assert len(history["rows"]) == 3
    assert history["source_link"].endswith(result_name)
    assert [r["selected"] for r in history["rows"]] == [False, True, False]
    assert history["rows"][0]["parent_note"] == "No parent recorded"
    assert all(r["parent_link"].endswith(names[0]) for r in history["rows"][1:])
    assert history["rows"][1]["method_version"] == "1"


def test_authentication_and_public_surface_precede_scanning(app, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Record scan should not run")
    monkeypatch.setattr("utils.estimate_lineage._records", forbidden)
    with app.test_request_context():
        assert build_estimate_lineage({}, "result.json") is None
        authenticate()
        app.config["PUBLIC_PORTAL_MODE"] = True
        assert build_estimate_lineage({}, "result.json") is None


def test_confidential_records_and_parent_not_exposed(app):
    hidden = estimate(E0)
    hidden["confidential"] = ["other"]
    write(app, hidden, E0)
    write(app, estimate(E1, E0), E1)
    history = lineage(app)
    assert len(history["rows"]) == 1
    row = history["rows"][0]
    assert not row["parent_link"] and not row["parent_uuid"]
    assert E0 not in json.dumps(history)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "cycle", "cross-source", "conflict"])
def test_invalid_parent_never_creates_link(app, kind):
    child = estimate(E1, E0)
    if kind == "duplicate":
        write(app, estimate(E0), E0)
        write(app, estimate(E0), E0, name="duplicate.json")
    elif kind == "cycle":
        write(app, estimate(E0, E1), E0)
    elif kind == "cross-source":
        write(app, estimate(E0, source=str(UUID(int=99))), E0)
    elif kind == "conflict":
        child["reestimation"]["source_estimate_result_uuid"] = E2
    name = write(app, child, E1)
    row = next(r for r in lineage(app)["rows"] if r["uuid"] == E1)
    assert row["parent_note"] and not row["parent_link"]
    if kind == "duplicate":
        assert all(not r["link"] for r in lineage(app)["rows"] if r["uuid"] == E0)
    assert lineage(app, child, name, is_estimate=True)


def test_source_reference_conflicts_and_legacy_unknowns(app):
    payload = estimate(E0)
    payload["estimate_metadata"]["source_result"] = {"uuid": str(UUID(int=98))}
    name = write(app, payload, E0)
    history = lineage(app, payload, name, is_estimate=True)
    assert not history["rows"] and history["notice"]
    legacy = {"estimate_metadata": {"source_result_uuid": SOURCE}, "current_system": None}
    write(app, legacy, E2)
    row = lineage(app)["rows"][0]
    assert row["uuid"] == E2 and row["method_version"] == "Unknown"
    assert row["parent_note"] == "No parent recorded"


def test_malformed_files_symlinks_and_missing_directory(app):
    directory = Path(app.config["ESTIMATED_DIR"])
    (directory / "bad.json").write_text("{")
    (directory / "array.json").write_text("[]")
    write(app, estimate(E0), E0)
    (directory / "link.json").symlink_to(directory / f"estimate_20260101_000000_{E0}.json")
    history = lineage(app)
    assert len(history["rows"]) == 1 and history["notice"]
    app.config["ESTIMATED_DIR"] = str(directory / "missing")
    assert lineage(app)["notice"]


def test_real_detail_routes_link_both_directions_and_escape(app):
    source = {"_server_uuid": SOURCE, "code": "demoapp", "system": "Current", "Exp": "CASE0", "FOM": 1}
    source_name = write(app, source, SOURCE, estimate=False)
    first_name = write(app, estimate(E0), E0)
    child = estimate(E1, E0)
    child["estimate_metadata"]["estimation_package"] = "<script>bad()</script>"
    child_name = write(app, child, E1)
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(authenticated=True, user_email="reader@example.com")
    result_html = client.get(f"/results/detail/{source_name}")
    assert result_html.status_code == 200
    assert f'href="/estimated/detail/{first_name}"' in result_html.text
    assert f'href="/estimated/detail/{child_name}"' in result_html.text
    assert "<script>bad()</script>" not in result_html.text
    assert "&lt;script&gt;bad()&lt;/script&gt;" in result_html.text
    estimate_html = client.get(f"/estimated/detail/{child_name}")
    assert estimate_html.status_code == 200
    assert f'href="/results/detail/{source_name}"' in estimate_html.text
    assert 'aria-current="true"' in estimate_html.text
    app.config["PUBLIC_PORTAL_MODE"] = True
    public_html = client.get(f"/results/detail/{source_name}")
    assert public_html.status_code == 200
    assert "Estimation History" not in public_html.text and E1 not in public_html.text


def test_prefix_and_explicit_changes(app):
    child = estimate(E1, E0)
    child["reestimation"]["resolved_request"] = {"explicit_changes": {"nodes": {"recorded": 1, "requested": 2}}}
    write(app, child, E1)
    with app.test_request_context(environ_overrides={"SCRIPT_NAME": "/preview/console"}):
        authenticate()
        row = build_estimate_lineage({"_server_uuid": SOURCE}, "result.json")["rows"][0]
        assert row["link"].startswith("/preview/console/")
        assert row["changes"] == "Recorded explicit overrides"


def test_source_link_requires_unique_accessible_result(app):
    payload = estimate(E0)
    filename = write(app, payload, E0)
    source = {"_server_uuid": SOURCE, "confidential": ["other"]}
    write(app, source, SOURCE, estimate=False)
    history = lineage(app, payload, filename, is_estimate=True)
    assert not history["source_link"] and history["source_unavailable"]
    source.pop("confidential")
    write(app, source, SOURCE, estimate=False)
    assert lineage(app, payload, filename, is_estimate=True)["source_link"]
    write(app, source, SOURCE, estimate=False, name="duplicate.json")
    assert not lineage(app, payload, filename, is_estimate=True)["source_link"]


def test_reference_aliases_and_partial_metadata(app):
    write(app, estimate(E0), E0)
    child = estimate(E1)
    child["reestimation"] = {"source_estimate": {"uuid": E0}}
    child["estimate_metadata"]["app_estimation_method"] = None
    child["future_system"] = None
    write(app, child, E1)
    row = next(r for r in lineage(app)["rows"] if r["uuid"] == E1)
    assert row["parent_uuid"] == E0 and row["method_version"] == "Unknown"


def test_unauthenticated_result_does_not_disclose_estimates(app):
    name = write(app, {"_server_uuid": SOURCE, "FOM": 1}, SOURCE, estimate=False)
    write(app, estimate(E0), E0)
    client = app.test_client()
    response = client.get(f"/results/detail/{name}")
    assert response.status_code == 200
    assert "Estimation History" not in response.text and E0 not in response.text
    estimate_name = f"estimate_20260101_000000_{E0}.json"
    assert client.get(f"/estimated/detail/{estimate_name}").status_code == 403
