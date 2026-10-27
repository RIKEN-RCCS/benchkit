"""Version overview tests use only temporary JSON and local Git fixtures."""

import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest
from flask import session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_support import StaticAffiliationUserStore, build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs()
from utils import estimate_version_list as listing


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE, text=True).strip()


@pytest.fixture
def app(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    declaration = repo / "programs/demo/estimate.metadata.json"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(json.dumps({"version": "2"}))
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
    received, estimated = tmp_path / "received", tmp_path / "estimated"
    received.mkdir()
    estimated.mkdir()
    app = build_portal_route_app(
        templates_dir=str(Path(__file__).resolve().parents[1] / "templates"),
        received_dir=str(received), estimated_dir=str(estimated),
        user_store=StaticAffiliationUserStore({"reader@example.com": ["dev"]}),
    )
    app.config.update(ESTIMATION_VERSION_REPO=str(repo), ESTIMATION_VERSION_REF="HEAD")
    app.config["ESTIMATION_VERSION_REF"] = git(repo, "symbolic-ref", "HEAD")
    return app


def write(app, number, version="1", **extra):
    payload = {
        "code": "demo", "exp": "CASE0",
        "estimate_metadata": {"estimation_result_uuid": str(UUID(int=number)),
                              "source_result_uuid": str(UUID(int=10000)),
                              "app_estimation_method": {"version": version},
                              "estimation_result_timestamp": "2026-01-01 00:00:00"},
        "current_system": {"system": "Current", "target_nodes": 1},
        "future_system": {"system": "Future", "target_nodes": 2},
        **extra,
    }
    name = f"estimate_20260101_000000_{UUID(int=number)}.json"
    path = Path(app.config["ESTIMATED_DIR"]) / name
    path.write_text(json.dumps(payload))
    return path


def client(app):
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(authenticated=True, user_email="reader@example.com")
    return client


def test_default_differences_unknowns_and_matching(app):
    write(app, 1)
    write(app, 2, version="2")
    write(app, 3, version=None)
    with app.test_request_context():
        session.update(authenticated=True, user_email="reader@example.com")
        context = listing.build_version_check_list(app.config["ESTIMATED_DIR"], app.config)
    assert context["counts"] == {"different": 1, "unknown": 1, "same": 1}
    assert len(context["rows"]) == 1 and context["rows"][0]["differences"] == 1
    c = client(app)
    assert "Version differences" in c.get("/estimated/version-checks").text
    assert "0 differences" in c.get("/estimated/version-checks?status=same").text
    assert "1 unknown" in c.get("/estimated/version-checks?status=unknown").text
    assert "3 Estimates" in c.get("/estimated/version-checks?status=all").text
    assert 'href="/estimated/version-checks"' in c.get("/estimated/").text


def test_known_differences_can_also_be_unknown(app):
    path = write(app, 1)
    data = json.loads(path.read_text())
    data["future_system"]["model"] = {"name": "external", "version": "weights"}
    path.write_text(json.dumps(data))
    response = client(app).get("/estimated/version-checks")
    assert response.status_code == 200
    assert "1 difference" in response.text and "1 unknown" in response.text


def test_auth_public_and_disabled_do_not_read_git(app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected Git read")
    monkeypatch.setattr(listing, "read_estimation_version_reference", forbidden)
    assert app.test_client().get("/estimated/version-checks").status_code == 403
    c = client(app)
    app.config["PUBLIC_PORTAL_MODE"] = True
    assert c.get("/estimated/version-checks").status_code == 404
    assert 'href="/estimated/version-checks"' not in c.get("/estimated/").text
    app.config["PUBLIC_PORTAL_MODE"] = False
    app.config["ESTIMATION_VERSION_REF"] = ""
    assert "Version Check is not configured" in c.get("/estimated/version-checks").text


def test_visibility_and_html_escape(app):
    hidden = write(app, 1, confidential=["other"], code="hidden-app")
    visible = write(app, 2, exp="<script>bad()</script>")
    before = {p: p.read_bytes() for p in (hidden, visible)}
    response = client(app).get("/estimated/version-checks?status=all")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert "hidden-app" not in response.text and hidden.name not in response.text
    assert "&lt;script&gt;bad()&lt;/script&gt;" in response.text
    assert "<script>bad()</script>" not in response.text
    assert before == {p: p.read_bytes() for p in before}


def test_pagination_after_classification_and_filtering(app, monkeypatch):
    for i in range(1, 57):
        write(app, i, code="other" if i > 53 else "demo")
    calls = []
    def check(payload, config):
        calls.append(config["ESTIMATION_VERSION_REF"])
        return {"status": "different", "changed_count": 1, "unknown_count": 0}
    monkeypatch.setattr(listing, "build_estimate_version_check", check)
    c = client(app)
    first = c.get("/estimated/version-checks?code=demo&per_page=50")
    second = c.get("/estimated/version-checks?code=demo&per_page=50&page=2")
    assert "53 Estimates" in first.text and "53 Estimates" in second.text
    assert 'rel="next"' in first.text and 'rel="prev"' in second.text
    assert "status=different" in first.text and "code=demo" in first.text
    assert len(calls) == 106 and len(set(calls)) == 1
    assert len(calls[0]) == 40 and not calls[0].startswith("refs/")


def test_unavailable_ref_does_not_fall_back_or_leak_path(app):
    write(app, 1)
    app.config["ESTIMATION_VERSION_REF"] = "refs/heads/missing"
    response = client(app).get("/estimated/version-checks?status=unknown")
    assert "Reference unavailable" in response.text and "1 unknown" in response.text
    assert app.config["ESTIMATION_VERSION_REPO"] not in response.text


def test_ref_is_pinned_even_when_configured_ref_moves(app, monkeypatch):
    write(app, 1)
    write(app, 2)
    original = listing.read_estimation_version_reference
    commit = git(app.config["ESTIMATION_VERSION_REPO"], "rev-parse", "HEAD")
    calls = []
    def resolve(repository, ref):
        calls.append(ref)
        resolved = original(repository, ref)
        declaration = Path(repository) / "programs/demo/estimate.metadata.json"
        declaration.write_text(json.dumps({"version": "1"}))
        git(repository, "add", ".")
        git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "next fixture")
        return resolved
    monkeypatch.setattr(listing, "read_estimation_version_reference", resolve)
    with app.test_request_context():
        session.update(authenticated=True, user_email="reader@example.com")
        context = listing.build_version_check_list(app.config["ESTIMATED_DIR"], app.config)
    assert len(calls) == 1 and context["reference"]["commit"] == commit
    assert len(context["rows"]) == 2 and context["counts"]["different"] == 2


@pytest.mark.parametrize("query", ["status=newest", "page=bad", "page=0", "per_page=1", "per_page=bad"])
def test_invalid_query_is_rejected(app, query):
    assert client(app).get("/estimated/version-checks?" + query).status_code == 400


def test_malformed_and_symlink_records_do_not_claim_complete_list(app):
    path = write(app, 1)
    (path.parent / "broken.json").write_text("{")
    (path.parent / "linked.json").symlink_to(path)
    response = client(app).get("/estimated/version-checks?status=all")
    assert "this list may be incomplete" in response.text and "1 Estimates" in response.text


def test_query_cannot_override_repository_or_ref(app):
    write(app, 1)
    response = client(app).get("/estimated/version-checks?ref=refs/heads/other&repository=ignored")
    assert response.status_code == 200 and "1 difference" in response.text
    assert "refs/heads/other" not in response.text
