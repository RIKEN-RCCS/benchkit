import os
import sys
import types


def _setup_stubs():
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")


_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, Blueprint


def _make_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    results_bp = Blueprint("results", __name__)
    estimated_bp = Blueprint("estimated", __name__)
    auth_bp = Blueprint("auth", __name__)
    admin_bp = Blueprint("admin", __name__)

    @results_bp.route("/")
    def results():
        return ""

    @results_bp.route("/compare")
    def result_compare():
        return ""

    @results_bp.route("/detail/<filename>")
    def result_detail(filename):
        return filename

    @results_bp.route("/usage")
    def usage_report():
        return ""

    @estimated_bp.route("/")
    def estimated_results():
        return ""

    @estimated_bp.route("/detail/<filename>")
    def estimated_detail(filename):
        return filename

    @estimated_bp.route("/show/<filename>")
    def show_estimated_result(filename):
        return filename

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

    @app.route("/")
    def home():
        return ""

    @app.route("/systemlist")
    def systemlist():
        return ""

    return app


def test_results_template_renders_table_note():
    app = _make_app()
    with app.test_request_context("/results"):
        from flask import render_template

        html = render_template(
            "results.html",
            columns=[
                ("Timestamp", "timestamp"),
                ("SYSTEM", "system"),
                ("CODE", "code"),
                ("FOM", "fom"),
                ("Exp", "exp"),
                ("JSON", "json_link"),
            ],
            rows=[
                {
                    "timestamp": "2026-04-13 12:00:00",
                    "system": "Fugaku",
                    "code": "qws",
                    "fom": 1.234,
                    "exp": "CASE0",
                    "json_link": "/results/result0.json",
                    "data_link": None,
                    "filename": "result0.json",
                    "detail_link": "/results/detail/result0.json",
                    "source_info": None,
                    "quality": {
                        "level": "ready",
                        "label": "Ready",
                        "summary": "Breakdown is present.",
                    },
                    "fom_version": "DDSolverJacobi",
                    "nodes": "1",
                    "numproc_node": "1",
                    "nthreads": "12",
                    "ci_trigger": "push",
                    "pipeline_id": "10",
                    "source_hash": "main@abcdef12",
                }
            ],
            pagination={"total": 1, "page": 1, "total_pages": 1},
            current_per_page=50,
            current_system="",
            current_code="",
            current_exp="",
            filter_options={"systems": ["Fugaku"], "codes": ["qws"], "exps": ["CASE0"]},
            systems_info={
                "Fugaku": {
                    "name": "Fugaku",
                    "cpu_name": "A64FX",
                    "cpu_per_node": "1",
                    "cpu_cores": "48",
                    "gpu_name": "-",
                    "gpu_per_node": "-",
                    "memory": "32GB",
                }
            },
        )

    assert "Use the server-side filters to narrow the table first" in html
    assert "results-table-wrap" in html
    assert "Compare" in html


def test_estimated_results_template_renders_table_note():
    app = _make_app()
    with app.test_request_context("/estimated"):
        from flask import render_template

        html = render_template(
            "estimated_results.html",
            authenticated=True,
            rows=[
                {
                    "timestamp": "2026-04-13 12:00:00",
                    "code": "qws",
                    "exp": "CASE0",
                    "systemA_system": "Fugaku",
                    "systemA_fom": 0.944,
                    "systemA_target_nodes": "1024",
                    "systemA_scaling_method": "weakscaling",
                    "systemA_bench_system": "Fugaku",
                    "systemA_bench_fom": 0.386,
                    "systemA_bench_nodes": "1",
                    "systemB_system": "FugakuNEXT",
                    "systemB_fom": 9.054,
                    "systemB_target_nodes": "256",
                    "systemB_scaling_method": "instrumented-app-sections-dummy",
                    "systemB_bench_system": "MiyabiG",
                    "systemB_bench_fom": 5.712,
                    "systemB_bench_nodes": "1",
                    "applicability_status": "applicable",
                    "requested_estimation_package": "instrumented_app_sections_dummy",
                    "estimation_package": "instrumented_app_sections_dummy",
                    "requested_current_estimation_package": "weakscaling",
                    "requested_future_estimation_package": "instrumented_app_sections_dummy",
                    "current_estimation_package": "weakscaling",
                    "future_estimation_package": "instrumented_app_sections_dummy",
                    "method_class": "detailed",
                    "detail_level": "intermediate",
                    "estimate_uuid": "11111111-2222-3333-4444-555555555555",
                    "performance_ratio": 0.104,
                    "json_link": "estimate0.json",
                }
            ],
            pagination={"total": 1, "page": 1, "total_pages": 1},
            current_per_page=50,
            current_system="",
            current_code="",
            current_exp="",
            filter_options={"systems": ["Fugaku"], "codes": ["qws"], "exps": ["CASE0"]},
        )

    assert "Focus on system pairs, applied packages, and ratio" in html
    assert "estimated-table-wrap" in html
    assert "detail" in html


def test_usage_report_template_renders_search_box():
    app = _make_app()
    with app.test_request_context("/results/usage"):
        from flask import render_template

        html = render_template(
            "usage_report.html",
            result={
                "apps": [],
                "systems": [],
                "periods": [],
                "available_fiscal_years": [2025],
            },
            filtered_periods=[],
            period_type="fiscal_year",
            fiscal_year=2025,
            period_filter="",
            site_diagnostics={
                "registered_system_count": 1,
                "unused_systems": [],
                "missing_system_info": [],
                "missing_queue_definitions": [],
                "application_count": 0,
                "partial_support": [],
            },
            coverage_systems=[],
            app_support_rows=[],
            result_quality_rollup={"rows": []},
        )

    assert "Filter application/system coverage and current-state tables" in html
    assert "applyUsageSearch" in html
