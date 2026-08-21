import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_route_app, build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)

from utils.portal_access import (
    ACCESS_AUTHENTICATED_CONSOLE,
    ACCESS_OPERATOR,
    ACCESS_PUBLIC,
    ACCESS_PUBLIC_CONDITIONAL,
    ACCESS_RESTRICTED_VIEWER,
    ACCESS_RUNNER_API,
    classify_endpoint,
    register_public_portal_guard,
)


def _portal_app(tmp_path):
    received_dir = tmp_path / "received"
    estimated_dir = tmp_path / "estimated"
    padata_dir = tmp_path / "received_padata"
    for path in (received_dir, estimated_dir, padata_dir):
        path.mkdir()

    app = build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=str(received_dir),
        estimated_dir=str(estimated_dir),
    )
    app.config["RECEIVED_PADATA_DIR"] = str(padata_dir)

    from routes.api import api_bp
    from routes.security_metadata import register_security_metadata_routes

    register_security_metadata_routes(app)
    app.register_blueprint(api_bp)
    return app


def test_every_registered_route_has_access_class(tmp_path):
    app = _portal_app(tmp_path)

    unclassified = sorted(
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if classify_endpoint(rule.endpoint) is None
    )

    assert unclassified == []


def test_representative_route_access_classes():
    assert classify_endpoint("home") == ACCESS_PUBLIC
    assert classify_endpoint("systemlist") == ACCESS_PUBLIC
    assert classify_endpoint("results.results") == ACCESS_PUBLIC
    assert classify_endpoint("results.result_detail") == ACCESS_PUBLIC_CONDITIONAL
    assert classify_endpoint("results.show_result") == ACCESS_RESTRICTED_VIEWER
    assert classify_endpoint("results.results_confidential") == ACCESS_RESTRICTED_VIEWER
    assert classify_endpoint("estimated.estimated_results") == ACCESS_RESTRICTED_VIEWER
    assert classify_endpoint("auth.login") == ACCESS_RESTRICTED_VIEWER
    assert classify_endpoint("profile_requests.my_profile_requests") == ACCESS_AUTHENTICATED_CONSOLE
    assert classify_endpoint("results.usage_report") == ACCESS_OPERATOR
    assert classify_endpoint("admin.users") == ACCESS_OPERATOR
    assert classify_endpoint("api.ingest_result") == ACCESS_RUNNER_API


def test_public_portal_mode_blocks_restricted_browser_routes_but_allows_api_auth(tmp_path):
    app = _portal_app(tmp_path)
    app.config["PUBLIC_PORTAL_MODE"] = True
    register_public_portal_guard(app)

    with app.test_client() as client:
        assert client.get("/").status_code == 200
        assert client.get("/auth/login").status_code == 404
        assert client.get("/estimated/").status_code == 404
        assert client.get("/results/confidential").status_code == 404
        assert client.get("/admin/users").status_code == 404
        assert client.get("/execution-profile-requests/").status_code == 404

        response = client.get("/api/query/result")

    assert response.status_code == 401


def test_public_portal_mode_hides_anonymous_restricted_navigation():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.config["PUBLIC_PORTAL_MODE"] = True

    with app.test_request_context("/"):
        from flask import render_template

        html = render_template("_navigation.html")

    assert "Home" in html
    assert "Systems" in html
    assert "Results" in html
    assert "Login" not in html
    assert "Admin" not in html
    assert "Estimated" not in html
    assert "Confidential" not in html
    assert "Profile" not in html


def test_public_portal_mode_hides_authenticated_restricted_navigation():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.config["PUBLIC_PORTAL_MODE"] = True

    with app.test_request_context("/"):
        from flask import render_template, session

        session["authenticated"] = True
        session["user_email"] = "admin@example.test"
        session["user_affiliations"] = ["admin"]
        html = render_template("_navigation.html")

    assert "Home" in html
    assert "Systems" in html
    assert "Results" in html
    assert "admin@example.test" not in html
    assert "Login" not in html
    assert "Admin" not in html
    assert "Estimated" not in html
    assert "Confidential" not in html
    assert "Profile" not in html


def test_public_portal_mode_hides_home_restricted_entry_points(monkeypatch):
    monkeypatch.delenv("CX_DISCORD_INVITE_URL", raising=False)
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        include_home_route=False,
    )
    app.config["PUBLIC_PORTAL_MODE"] = True

    from routes.home import register_home_routes

    register_home_routes(app)

    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Browse Results" in html
    assert "View All Systems" in html
    assert "Estimated Results (login required)" not in html
    assert "Open Estimated Results" not in html
    assert "Login required" not in html


def test_public_portal_mode_hides_home_restricted_entry_points_when_authenticated(monkeypatch):
    monkeypatch.delenv("CX_DISCORD_INVITE_URL", raising=False)
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        include_home_route=False,
    )
    app.config["PUBLIC_PORTAL_MODE"] = True

    from routes.home import register_home_routes

    register_home_routes(app)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user_email"] = "admin@example.test"
            sess["user_affiliations"] = ["admin"]
        response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Browse Results" in html
    assert "View All Systems" in html
    assert "Open Estimated Results" not in html
    assert "Operations Views" not in html
    assert "Profile Request Review" not in html
