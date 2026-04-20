import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)

from routes.home import register_home_routes


def test_home_page_renders_landing_content():
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
    assert "For Application Developers" in html
    assert "Available Systems" in html
    assert "Add a New Site" in html
    assert "Browse Results" in html
    assert "Estimated Results (login required)" in html
    assert "Login required" in html
