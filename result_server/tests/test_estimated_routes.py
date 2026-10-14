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
        user_store=StaticAffiliationUserStore({"user@example.com": ["dev"]}),
    )


@pytest.fixture
def client(app):
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "user@example.com"
        sess["user_affiliations"] = ["dev"]


def _write_estimate(directory, filename):
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "code": "demoapp",
                "exp": "CASE0",
                "performance_ratio": 0.104,
                "applicability": {"status": "applicable"},
                "estimate_metadata": {
                    "requested_estimation_package": "instrumented_app_sections_dummy",
                    "estimation_package": "instrumented_app_sections_dummy",
                    "method_class": "detailed",
                    "detail_level": "intermediate",
                    "current_package": {"estimation_package": "weakscaling"},
                    "future_package": {"estimation_package": "instrumented_app_sections_dummy"},
                },
                "current_system": {"system": "DemoSystem"},
                "future_system": {"system": "FutureSystem"},
            },
            f,
            ensure_ascii=False,
        )
    return path


def test_estimated_detail_requires_authentication(client, tmp_dirs):
    _, estimated = tmp_dirs
    _write_estimate(estimated, "estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")

    resp = client.get("/estimated/detail/estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")

    assert resp.status_code == 403


def test_estimated_detail_renders_for_authenticated_user(client, tmp_dirs):
    _, estimated = tmp_dirs
    _write_estimate(estimated, "estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")
    _login_session(client)

    resp = client.get("/estimated/detail/estimate_20260410_120000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Estimate Detail" in html
    assert "Package Resolution" in html
    assert "FutureSystem" in html


def test_version_check_is_hidden_by_default(client, tmp_dirs):
    _, estimated = tmp_dirs
    _write_estimate(estimated, "estimate_sample.json")
    _login_session(client)
    assert "Version Check" not in client.get("/estimated/detail/estimate_sample.json").get_data(as_text=True)


def test_authentication_precedes_version_read(client, app, tmp_dirs, monkeypatch):
    from utils import estimate_version_view
    app.config.update(ESTIMATION_VERSION_REPO="repository", ESTIMATION_VERSION_REF="refs/heads/test")

    def forbidden(*args, **kwargs):
        raise AssertionError("unauthenticated Git read")

    monkeypatch.setattr(estimate_version_view, "read_estimation_version_snapshot", forbidden)
    _write_estimate(tmp_dirs[1], "estimate_sample.json")
    assert client.get("/estimated/detail/estimate_sample.json").status_code == 403


def test_version_check_escapes_values_and_uses_only_configured_ref(client, app, tmp_dirs, monkeypatch):
    from utils import estimate_version_view
    app.config.update(ESTIMATION_VERSION_REPO="repository", ESTIMATION_VERSION_REF="refs/heads/test")
    path = _write_estimate(tmp_dirs[1], "estimate_sample.json")
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    payload["estimate_metadata"]["app_estimation_method"] = {"version": "<script>alert(1)</script>"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    calls = []

    def read(repository, ref, code, **kwargs):
        calls.append(ref)
        return {"app": {"version": "next"}, "ref": ref, "commit": "a" * 40,
                "packages": {}, "section_packages": {}, "unknowns": []}

    monkeypatch.setattr(estimate_version_view, "read_estimation_version_snapshot", read)
    _login_session(client)
    response = client.get("/estimated/detail/estimate_sample.json?ref=refs/heads/other&repository=other")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Version Check" in html and "Different" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert calls == ["refs/heads/test"]
