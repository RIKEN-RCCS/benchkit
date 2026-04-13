import os
import sys
import types


def _setup_stubs():
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")


_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, Blueprint


def test_systemlist_page_renders_summary_and_table():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    @app.route("/")
    def home():
        return ""

    @app.route("/systemlist")
    def systemlist():
        return ""

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

    with app.test_request_context("/systemlist"):
        from flask import render_template

        html = render_template(
            "systemlist.html",
            systems_summary={
                "total_count": 2,
                "gpu_enabled_count": 1,
                "cpu_only_count": 1,
            },
            systems_info={
                "Fugaku": {
                    "name": "Fugaku",
                    "cpu_name": "A64FX",
                    "cpu_per_node": "1",
                    "cpu_cores": "48",
                    "gpu_name": "-",
                    "gpu_per_node": "-",
                    "memory": "32GB",
                },
                "MiyabiG": {
                    "name": "MiyabiG",
                    "cpu_name": "NVIDIA Grace CPU",
                    "cpu_per_node": "1",
                    "cpu_cores": "72",
                    "gpu_name": "NVIDIA Hopper H100 GPU",
                    "gpu_per_node": "1",
                    "memory": "120GB",
                },
            },
        )

    assert "Available Systems" in html
    assert "Connected systems registered in the portal." in html
    assert "Systems with GPU accelerators listed in" in html
    assert "systems-table" in html
    assert "systems-table-wrap" in html
    assert "Filter systems by name, CPU, GPU, or memory" in html
    assert "GPU-enabled" in html
    assert "CPU-only" in html
    assert "Hardware summaries are sourced from" in html
    assert "Fugaku" in html
    assert "MiyabiG" in html
