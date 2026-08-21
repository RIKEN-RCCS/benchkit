import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)

from routes.home import register_home_routes


def test_home_page_renders_landing_content(monkeypatch):
    monkeypatch.delenv("CX_DISCORD_INVITE_URL", raising=False)
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        include_home_route=False,
    )
    register_home_routes(app)

    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "CX Portal" in html
    assert "Main Entry Points" in html
    assert "User Guide" in html
    assert "GPU Performance Estimation" not in html
    assert "Available Systems" not in html
    assert "At a Glance" not in html
    assert "Start Here" not in html
    assert "Add a New Site" in html
    assert "PerfTools" not in html
    assert "RIKEN-RCCS BenchPark FN_apps branch" in html
    assert "Upstream BenchPark" in html
    assert "https://github.com/masaaki-kondo/PerfTools" not in html
    assert "https://github.com/RIKEN-RCCS/benchpark/blob/FN_apps/User_Guide.md" in html
    assert "https://github.com/llnl/benchpark" in html
    assert "Browse Results" in html
    assert "Estimated Results" in html
    assert "Login required" in html
    assert "Questions and Discussion" not in html


def test_home_page_renders_discord_link_when_configured(monkeypatch):
    monkeypatch.setenv("CX_DISCORD_INVITE_URL", "https://discord.gg/example")
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        include_home_route=False,
    )
    register_home_routes(app)

    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Questions and Discussion" in html
    assert "invitation-only Discord" in html
    assert "https://discord.gg/example" in html
