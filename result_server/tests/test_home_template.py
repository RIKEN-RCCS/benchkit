import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import install_portal_test_stubs

install_portal_test_stubs(include_otp=False)

from flask import Flask, Blueprint

from routes.home import register_home_routes


def _register_dummy_routes(app):
    results_bp = Blueprint("results", __name__)
    estimated_bp = Blueprint("estimated", __name__)
    auth_bp = Blueprint("auth", __name__)

    @results_bp.route("/")
    def results():
        return ""

    @estimated_bp.route("/")
    def estimated_results():
        return ""

    @auth_bp.route("/login")
    def login():
        return ""

    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp, url_prefix="/auth")

    @app.route("/systemlist")
    def systemlist():
        return ""


def test_home_page_renders_landing_content():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    _register_dummy_routes(app)
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
