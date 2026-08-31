"""Public portal route tests for result detail and compare views."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import (  # noqa: E402
    StaticAffiliationUserStore,
    build_results_route_app,
    install_portal_test_stubs,
)

install_portal_test_stubs()


def _add_navigation_routes(app):
    app.add_url_rule("/", "home", lambda: "home")
    app.add_url_rule("/changes", "changes", lambda: "changes")
    app.add_url_rule("/systems", "systemlist", lambda: "systems")
    app.add_url_rule("/login", "auth.login", lambda: "login")
    app.add_url_rule("/logout", "auth.logout", lambda: "logout")


def _write_result(received_dir, filename, payload):
    with open(received_dir / filename, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _build_public_app(tmp_path):
    received_dir = tmp_path / "received"
    received_dir.mkdir()
    app = build_results_route_app(received_dir=str(received_dir))
    _add_navigation_routes(app)
    app.config["PUBLIC_PORTAL_MODE"] = True
    app.config["USER_STORE"] = StaticAffiliationUserStore({"dev@example.test": ["dev"]})
    return app, received_dir


def _authenticate_dev(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "dev@example.test"


def test_public_portal_detail_hides_confidential_result_for_authorized_session(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    _write_result(
        received_dir,
        filename,
        {
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE1",
            "FOM": 1.0,
            "confidential": ["dev"],
        },
    )

    with app.test_client() as client:
        _authenticate_dev(client)
        response = client.get(f"/results/detail/{filename}")

    assert response.status_code == 404


def test_public_portal_compare_hides_confidential_result_for_authorized_session(tmp_path):
    app, received_dir = _build_public_app(tmp_path)
    public_filename = "result_20260824_090000_11111111-2222-3333-4444-555555555555.json"
    confidential_filename = "result_20260824_091000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    _write_result(
        received_dir,
        public_filename,
        {
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE1",
            "FOM": 1.0,
        },
    )
    _write_result(
        received_dir,
        confidential_filename,
        {
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE2",
            "FOM": 1.1,
            "confidential": ["dev"],
        },
    )

    with app.test_client() as client:
        _authenticate_dev(client)
        response = client.get(
            f"/results/compare?files={public_filename},{confidential_filename}"
        )

    assert response.status_code == 404
