import os
import sys

import pytest
from flask import Flask, Blueprint, render_template


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


ESTIMATE_RESULT = {
    "code": "qws",
    "exp": "CASE0",
    "performance_ratio": 0.104,
    "applicability": {"status": "applicable"},
    "estimate_metadata": {
        "requested_estimation_package": "instrumented_app_sections_dummy",
        "estimation_package": "instrumented_app_sections_dummy",
        "method_class": "detailed",
        "detail_level": "intermediate",
        "estimation_result_uuid": "11111111-2222-3333-4444-555555555555",
        "estimation_result_timestamp": "2026-04-10 12:34:56",
        "current_package": {
            "requested_estimation_package": "weakscaling",
            "estimation_package": "weakscaling",
        },
        "future_package": {
            "requested_estimation_package": "instrumented_app_sections_dummy",
            "estimation_package": "instrumented_app_sections_dummy",
        },
    },
    "current_system": {
        "system": "Fugaku",
        "fom": 0.944,
        "target_nodes": "1024",
        "scaling_method": "weakscaling",
        "benchmark": {"system": "Fugaku", "fom": 0.386, "nodes": "1"},
        "model": {"name": "weakscaling-current", "type": "intra_system_scaling_model"},
        "fom_breakdown": {
            "sections": [
                {
                    "name": "prepare_rhs",
                    "time": 0.062,
                    "estimation_package": "identity",
                    "scaling_method": "identity",
                    "fallback_used": "identity",
                    "package_applicability": {
                        "status": "fallback",
                        "missing_inputs": ["section_package_unsupported:half"],
                    },
                }
            ],
            "overlaps": [
                {
                    "sections": ["compute_hopping", "halo_exchange"],
                    "time": 0.015,
                    "estimation_package": "identity",
                    "scaling_method": "identity",
                    "fallback_used": "identity",
                    "package_applicability": {
                        "status": "fallback",
                        "missing_inputs": ["overlap_package_unsupported:half"],
                    },
                }
            ],
        },
    },
    "future_system": {
        "system": "FugakuNEXT",
        "fom": 9.054,
        "target_nodes": "256",
        "scaling_method": "instrumented-app-sections-dummy",
        "benchmark": {"system": "MiyabiG", "fom": 5.712, "nodes": "1"},
        "model": {"name": "instrumented-app-sections-future-projection", "type": "cross_system_projection_model"},
        "fom_breakdown": {
            "sections": [
                {
                    "name": "allreduce",
                    "time": 7.312,
                    "estimation_package": "logp",
                    "scaling_method": "logP",
                }
            ],
            "overlaps": [],
        },
    },
    "measurement": {"tool": "application-section-timer", "method": "section-timing"},
    "confidence": {"level": "experimental", "score": 0.2},
    "assumptions": {"scaling_assumption": "weak-scaling"},
}


@pytest.fixture
def app():
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    app = Flask(__name__, template_folder=template_dir)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    @app.route("/estimated/")
    def estimated_results():
        return "estimated"

    @app.route("/")
    def home():
        return "home"

    @app.route("/systemlist")
    def systemlist():
        return "systems"

    results_bp = Blueprint("results", __name__)
    estimated_bp = Blueprint("estimated", __name__)
    admin_bp = Blueprint("admin", __name__)
    auth_bp = Blueprint("auth", __name__)

    @results_bp.route("/")
    def results():
        return "results"

    @results_bp.route("/confidential")
    def results_confidential():
        return "results confidential"

    @results_bp.route("/usage")
    def usage_report():
        return "usage"

    @estimated_bp.route("/", endpoint="estimated_results")
    def estimated_results_bp():
        return "estimated"

    @admin_bp.route("/")
    def admin_users():
        return "admin"

    @auth_bp.route("/login")
    def login():
        return "login"

    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(auth_bp, url_prefix="/auth")

    yield app


def test_estimated_detail_template_renders_sections(app):
    with app.test_request_context("/estimated/detail/estimate.json"):
        html = render_template("estimated_detail.html", result=ESTIMATE_RESULT, filename="estimate.json")

    assert "Estimate Detail" in html
    assert "Package Resolution" in html
    assert "Current System" in html
    assert "Future System" in html
    assert "weakscaling" in html
    assert "instrumented_app_sections_dummy" in html
    assert "fallback" in html
    assert "section_package_unsupported:half" in html
    assert "overlap_package_unsupported:half" in html
