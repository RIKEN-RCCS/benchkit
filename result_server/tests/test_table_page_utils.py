import os
import sys

from flask import Blueprint, Flask


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.table_page_utils import build_filtered_redirect_args, render_no_store_template


def test_build_filtered_redirect_args_omits_missing_filters():
    args = build_filtered_redirect_args(2, 50, "Fugaku", None, "CASE0")

    assert args == {
        "page": 2,
        "per_page": 50,
        "system": "Fugaku",
        "exp": "CASE0",
    }


def test_render_no_store_template_sets_cache_headers():
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"))
    app.config["SECRET_KEY"] = "test-secret"

    results_bp = Blueprint("results", __name__)
    estimated_bp = Blueprint("estimated", __name__)
    auth_bp = Blueprint("auth", __name__)
    admin_bp = Blueprint("admin", __name__)

    @app.route("/")
    def home():
        return ""

    @app.route("/systemlist")
    def systemlist():
        return ""

    @results_bp.route("/")
    def results():
        return ""

    @results_bp.route("/compare")
    def result_compare():
        return ""

    @results_bp.route("/usage")
    def usage_report():
        return ""

    @estimated_bp.route("/")
    def estimated_results():
        return ""

    @auth_bp.route("/login")
    def login():
        return ""

    @admin_bp.route("/users")
    def users():
        return ""

    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    with app.test_request_context("/estimated"):
        response = render_no_store_template("estimated_results.html", authenticated=False, rows=[], columns=[], systems_info={}, pagination={"page": 1, "per_page": 100, "total": 0, "total_pages": 1}, filter_options={"systems": [], "codes": [], "exps": []}, current_system=None, current_code=None, current_exp=None, current_per_page=100)

    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"
