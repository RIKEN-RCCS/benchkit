import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)


def test_results_template_renders_table_note():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results"):
        from flask import render_template

        html = render_template(
            "results.html",
                columns=[
                    {"label": "Timestamp", "key": "timestamp", "tooltip": "Date and time when benchmark execution completed and results were automatically submitted to server", "tooltip_class": "tooltip-left"},
                    {"label": "SYSTEM", "key": "system", "tooltip": "Computing system name"},
                    {"label": "CODE", "key": "code"},
                    {"label": "FOM", "key": "fom", "tooltip": "Figure of Merit - Benchmark performance metric value, typically elapsed time in seconds for main section"},
                    {"label": "Exp", "key": "exp", "tooltip": "Experimental conditions (filtered by CODE)"},
                    {"label": "Profiler / PA", "key": "profile_summary", "tooltip": "Profiler tool, level, report summary, and PA data download access"},
                    {"label": "CI", "key": "ci_summary", "tooltip": "CI trigger source and pipeline ID"},
                    {"label": "JSON", "key": "json_link", "tooltip": "Detailed benchmark results in JSON format", "tooltip_class": "tooltip-right"},
                ],
            rows=[
                {
                    "timestamp": "2026-04-13 12:00:00",
                    "system": "Fugaku",
                    "code": "qws",
                    "fom": 1.234,
                    "exp": "CASE0",
                    "json_link": "/results/result0.json",
                    "data_link": "/results/padata0.tgz",
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
                    "profile_summary": "fapp / detailed",
                    "profile_summary_meta": {
                        "has_profile_data": True,
                        "headline": "fapp / detailed",
                        "subline": "both, 17 runs",
                        "events": ["pa1", "pa2"],
                        "report_kinds": ["summary_text", "cpu_pa_csv"],
                    },
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

    assert "check the profiler and PA summary when available" in html
    assert "results-table-wrap" in html
    assert "Compare" in html
    assert "fapp / detailed" in html
    assert "Profiler / PA" in html
    assert "CI" in html
    assert "padata" in html
    assert "#10" in html


def test_estimated_results_template_renders_table_note():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/estimated"):
        from flask import render_template

        html = render_template(
            "estimated_results.html",
            authenticated=True,
            columns=[
                {"label": "Timestamp", "key": "timestamp", "section": "leading"},
                {"label": "CODE", "key": "code", "section": "leading"},
                {"label": "Exp", "key": "exp", "section": "leading"},
                {"label": "System", "key": "systemA_system", "group": "System A"},
                {"label": "FOM", "key": "systemA_fom_display", "group": "System A", "title_key": "systemA_fom", "align": "right"},
                {"label": "Target Nodes", "key": "systemA_target_nodes", "group": "System A"},
                {"label": "Scaling Method", "key": "systemA_scaling_short", "group": "System A", "title_key": "systemA_scaling_title"},
                {"label": "Bench System", "key": "systemA_bench_system", "group": "System A"},
                {"label": "Bench FOM", "key": "systemA_bench_fom_display", "group": "System A", "title_key": "systemA_bench_fom", "align": "right"},
                {"label": "Bench Nodes", "key": "systemA_bench_nodes", "group": "System A"},
                {"label": "System", "key": "systemB_system", "group": "System B"},
                {"label": "FOM", "key": "systemB_fom_display", "group": "System B", "title_key": "systemB_fom", "align": "right"},
                {"label": "Target Nodes", "key": "systemB_target_nodes", "group": "System B"},
                {"label": "Scaling Method", "key": "systemB_scaling_short", "group": "System B", "title_key": "systemB_scaling_title"},
                {"label": "Bench System", "key": "systemB_bench_system", "group": "System B"},
                {"label": "Bench FOM", "key": "systemB_bench_fom_display", "group": "System B", "title_key": "systemB_bench_fom", "align": "right"},
                {"label": "Bench Nodes", "key": "systemB_bench_nodes", "group": "System B"},
                {"label": "Applicability", "key": "applicability_status", "section": "trailing"},
                {"label": "Requested Package", "key": "requested_package_short", "section": "trailing", "title_key": "requested_package_title"},
                {"label": "Applied Package", "key": "applied_package_short", "section": "trailing", "title_key": "applied_package_title", "meta_key": "applied_package_meta_line"},
                {"label": "Estimate UUID", "key": "estimate_uuid_short", "section": "trailing", "title_key": "estimate_uuid", "cell_class": "estimated-code-cell"},
                {"label": "Ratio", "key": "performance_ratio_display", "section": "trailing", "title_key": "performance_ratio", "align": "right"},
                {"label": "JSON", "key": "json_link", "section": "trailing", "cell_class": "estimated-link-cell"},
            ],
            rows=[
                {
                    "timestamp": "2026-04-13 12:00:00",
                    "timestamp_date": "2026-04-13",
                    "timestamp_time": "12:00:00",
                    "code": "qws",
                    "exp": "CASE0",
                    "systemA_system": "Fugaku",
                    "systemA_fom": 0.944,
                    "systemA_fom_display": "0.944",
                    "systemA_target_nodes": "1024",
                    "systemA_scaling_method": "weakscaling",
                    "systemA_scaling_short": "weakscaling",
                    "systemA_scaling_title": "weakscaling",
                    "systemA_bench_system": "Fugaku",
                    "systemA_bench_fom": 0.386,
                    "systemA_bench_fom_display": "0.386",
                    "systemA_bench_nodes": "1",
                    "systemB_system": "FugakuNEXT",
                    "systemB_fom": 9.054,
                    "systemB_fom_display": "9.054",
                    "systemB_target_nodes": "256",
                    "systemB_scaling_method": "instrumented-app-sections-dummy",
                    "systemB_scaling_short": "instr-app-sec",
                    "systemB_scaling_title": "instrumented-app-sections-dummy",
                    "systemB_bench_system": "MiyabiG",
                    "systemB_bench_fom": 5.712,
                    "systemB_bench_fom_display": "5.712",
                    "systemB_bench_nodes": "1",
                    "applicability_status": "applicable",
                    "requested_estimation_package": "instrumented_app_sections_dummy",
                    "estimation_package": "instrumented_app_sections_dummy",
                    "requested_package_short": "instr_app_sec",
                    "applied_package_short": "instr_app_sec",
                    "requested_current_estimation_package": "weakscaling",
                    "requested_future_estimation_package": "instrumented_app_sections_dummy",
                    "current_estimation_package": "weakscaling",
                    "future_estimation_package": "instrumented_app_sections_dummy",
                    "method_class": "detailed",
                    "detail_level": "intermediate",
                    "requested_package_title": "instrumented_app_sections_dummy\ncurrent-side: weakscaling\nfuture-side: instrumented_app_sections_dummy",
                    "applied_package_title": "instrumented_app_sections_dummy\nclass: detailed\ndetail: intermediate\ncurrent-side: weakscaling\nfuture-side: instrumented_app_sections_dummy",
                    "applied_package_meta_line": "detailed / intermediate",
                    "estimate_uuid": "11111111-2222-3333-4444-555555555555",
                    "estimate_uuid_short": "11111111",
                    "performance_ratio": 0.104,
                    "performance_ratio_display": "0.104",
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

    assert "Scan system pairs, applied packages, and ratio here" in html
    assert "estimated-table-wrap" in html
    assert "detail" in html


def test_usage_report_template_renders_search_box():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
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

    assert "Filter coverage and current-state tables" in html
    assert "applyUsageSearch" in html


def test_result_compare_template_renders_headline():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results/compare"):
        from flask import render_template

        html = render_template(
            "result_compare.html",
            results=[
                {
                    "filename": "result0.json",
                    "timestamp": "2026-04-13 12:00:00",
                    "data": {"system": "Fugaku", "code": "qws", "FOM": 1.2},
                },
                {
                    "filename": "result1.json",
                    "timestamp": "2026-04-13 13:00:00",
                    "data": {"system": "Fugaku", "code": "qws", "FOM": 1.1},
                },
            ],
            mixed=False,
            headline="Fugaku / qws - Comparing 2 results",
            has_vector_metrics=False,
        )

    assert "Fugaku / qws - Comparing 2 results" in html
    assert "FOM Timeline" in html
