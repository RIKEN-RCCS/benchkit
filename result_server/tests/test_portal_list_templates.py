import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)

from utils.estimated_table_rows import APPLICABILITY_STATUS_LEGEND


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
                    {"label": "FOM", "key": "fom", "tooltip": "Figure of Merit - Benchmark performance metric value with its unit when available"},
                    {"label": "Exp", "key": "exp", "tooltip": "Experimental conditions (filtered by CODE)"},
                    {"label": "Profiler / PA", "key": "profile_summary", "tooltip": "Profiler tool/level and PA data download access when archive is available"},
                    {"label": "CI", "key": "ci_summary", "tooltip": "CI trigger source and pipeline ID"},
                    {"label": "JSON", "key": "json_link", "tooltip": "Detailed benchmark results in JSON format", "tooltip_class": "tooltip-right"},
                ],
            rows=[
                {
                    "timestamp": "2026-04-13 12:00:00",
                    "system": "DemoSystem",
                    "code": "demoapp",
                    "fom": 1.234,
                    "fom_unit": "s",
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
            filter_options={"systems": ["DemoSystem"], "codes": ["demoapp"], "exps": ["CASE0"]},
            systems_info={
                "DemoSystem": {
                    "name": "DemoSystem",
                    "cpu_name": "A64FX",
                    "cpu_per_node": "1",
                    "cpu_cores": "48",
                    "gpu_name": "-",
                    "gpu_per_node": "-",
                    "memory": "32GB",
                }
            },
        )

    assert "inspect profiler context when a PA archive is available" in html
    assert "results-table-wrap" in html
    assert "Compare" in html
    assert "fapp / detailed" in html
    assert "Profiler / PA" in html
    assert "CI" in html
    assert "padata" in html
    assert "#10" in html
    assert "1.234 s" in html


def test_results_template_renders_profile_summary_when_padata_link_is_available():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results"):
        from flask import render_template

        html = render_template(
            "results.html",
            columns=[
                {"label": "Timestamp", "key": "timestamp"},
                {"label": "Profiler / PA", "key": "profile_summary"},
                {"label": "JSON", "key": "json_link"},
            ],
            rows=[
                {
                    "timestamp": "2026-04-13 12:00:00",
                    "profile_summary": "ncu / single",
                    "profile_summary_meta": {
                        "has_profile_data": True,
                        "headline": "ncu / single",
                        "subline": "text, 1 run",
                        "archive_count": 3,
                        "events": [],
                        "ncu_options": ["--target-processes", "all", "--set", "basic", "--launch-count", "1"],
                        "report_kinds": ["ncu_report", "summary_text"],
                    },
                    "data_link": "/results/padata0.tgz",
                    "json_link": "/results/result0.json",
                    "detail_link": "/results/detail/result0.json",
                    "filename": "result0.json",
                    "source_info": None,
                    "quality": {"level": "ready", "label": "Ready", "summary": "Breakdown is present."},
                    "system": "GpuSystem",
                    "code": "auxapp",
                    "fom": 1.0,
                    "exp": "CASE0",
                    "fom_version": "test",
                    "nodes": "1",
                    "numproc_node": "8",
                    "nthreads": "9",
                    "ci_trigger": "push",
                    "pipeline_id": "10",
                    "source_hash": "-",
                }
            ],
            pagination={"total": 1, "page": 1, "total_pages": 1},
            current_per_page=50,
            current_system="",
            current_code="",
            current_exp="",
            filter_options={"systems": ["GpuSystem"], "codes": ["auxapp"], "exps": ["CASE0"]},
            systems_info={},
        )

    assert "ncu / single" in html
    assert "padata x3" in html
    assert "archive: available (3)" in html
    assert "ncu options: --target-processes all --set basic --launch-count 1" in html
    assert "ncu_report" in html


def test_results_template_hides_profile_summary_without_padata_link():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results"):
        from flask import render_template

        html = render_template(
            "results.html",
            columns=[
                {"label": "Timestamp", "key": "timestamp"},
                {"label": "Profiler / PA", "key": "profile_summary"},
            ],
            rows=[
                {
                    "timestamp": "2026-04-13 12:00:00",
                    "profile_summary": "ncu / single",
                    "profile_summary_meta": {
                        "has_profile_data": True,
                        "headline": "ncu / single",
                        "subline": "text, 1 run",
                        "archive_count": None,
                        "events": [],
                        "ncu_options": ["--set", "basic"],
                        "report_kinds": ["ncu_report"],
                    },
                    "data_link": None,
                    "detail_link": "/results/detail/result0.json",
                    "filename": "result0.json",
                    "source_info": None,
                    "quality": {"level": "ready", "label": "Ready", "summary": "Breakdown is present."},
                    "system": "GpuSystem",
                    "code": "auxapp",
                    "fom": 1.0,
                    "exp": "CASE0",
                    "fom_version": "test",
                    "nodes": "1",
                    "numproc_node": "8",
                    "nthreads": "9",
                    "ci_trigger": "push",
                    "pipeline_id": "10",
                    "source_hash": "-",
                }
            ],
            pagination={"total": 1, "page": 1, "total_pages": 1},
            current_per_page=50,
            current_system="",
            current_code="",
            current_exp="",
            filter_options={"systems": ["GpuSystem"], "codes": ["auxapp"], "exps": ["CASE0"]},
            systems_info={},
        )

    assert "ncu / single" not in html
    assert "padata" not in html
    assert "ncu_report" not in html


def test_pagination_template_urlencodes_filters_without_inline_javascript():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results"):
        from flask import render_template

        html = render_template(
            "_pagination.html",
            pagination={"total": 120, "page": 1, "total_pages": 3},
            current_per_page=50,
            current_system="Sys');alert(1)//",
            current_code='code" onclick="alert(1)',
            current_exp="<CASE0>",
        )

    assert "onchange=" not in html
    assert "window.location.href" not in html
    assert "system=Sys%27%29%3Balert%281%29" in html
    assert "code=code%22%20onclick%3D%22alert%281%29" in html
    assert "exp=%3CCASE0%3E" in html
    assert "Sys');alert(1)//" not in html
    assert 'code" onclick="alert(1)' not in html


def test_code_cell_adds_noopener_to_source_links():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results"):
        from flask import render_template

        html = render_template(
            "_results_table_cell_code.html",
            row={
                "code": "demoapp",
                "source_link": {
                    "href": "https://example.invalid/repo.git",
                    "title": "https://example.invalid/repo.git",
                },
                "quality": {"level": "ready", "label": "Ready", "summary": "ok"},
            },
        )

    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert 'href="https://example.invalid/repo.git"' in html


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
                {"label": "Applicability", "key": "applicability_status", "section": "trailing", "title_key": "applicability_title", "meta_key": "applicability_meta_line", "tooltip": APPLICABILITY_STATUS_LEGEND},
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
                    "code": "demoapp",
                    "exp": "CASE0",
                    "systemA_system": "DemoSystem",
                    "systemA_fom": 0.944,
                    "systemA_fom_display": "0.944",
                    "systemA_target_nodes": "1024",
                    "systemA_scaling_method": "weakscaling",
                    "systemA_scaling_short": "weakscaling",
                    "systemA_scaling_title": "weakscaling",
                    "systemA_bench_system": "DemoSystem",
                    "systemA_bench_fom": 0.386,
                    "systemA_bench_fom_display": "0.386",
                    "systemA_bench_nodes": "1",
                    "systemB_system": "FutureSystem",
                    "systemB_fom": 9.054,
                    "systemB_fom_display": "9.054",
                    "systemB_target_nodes": "256",
                    "systemB_scaling_method": "instrumented-app-sections-dummy",
                    "systemB_scaling_short": "instr-app-sec",
                    "systemB_scaling_title": "instrumented-app-sections-dummy",
                    "systemB_bench_system": "PeerSystem",
                    "systemB_bench_fom": 5.712,
                    "systemB_bench_fom_display": "5.712",
                    "systemB_bench_nodes": "1",
                    "applicability_status": "applicable",
                    "applicability_title": "applicable",
                    "applicability_tooltip": "applicable: requested package applied",
                    "applicability_meta_line": "fallback -> weakscaling",
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
            filter_options={"systems": ["DemoSystem"], "codes": ["demoapp"], "exps": ["CASE0"]},
            estimation_links={"perftools": "https://github.com/masaaki-kondo/PerfTools"},
        )

    assert "Scan system pairs, applied packages, and ratio here" in html
    assert "Applicability" in html
    assert "estimated-status-legend" not in html
    assert "estimated-applicability-cell" in html
    assert "estimated-status-chip" in html
    assert "tooltip-wide" in html
    assert "tooltiptext" in html
    assert "<br>" in html
    assert 'data-status="applicable"' in html
    assert "applicable" in html
    assert "requested package applied" in html
    assert "partially_applicable" in html
    assert "stored with section/overlap fallback" in html
    assert "fallback" in html
    assert "stored with top-level fallback" in html
    assert "not_applicable" in html
    assert "attempt stored without a valid estimate" in html
    assert "needs_remeasurement" in html
    assert "more benchmark data required" in html
    assert "PerfTools" in html
    assert "https://github.com/masaaki-kondo/PerfTools" in html
    assert "estimated-table-wrap" in html
    assert "detail" in html
    assert "fallback -&gt; weakscaling" in html


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
                "application_directory_count": 1,
                "apps_missing_files": [{"app": "auxapp", "missing_files": ["run.sh"]}],
                "apps_without_estimate": ["ffb"],
                "apps_with_estimate_count": 1,
                "unknown_listed_systems": [{"app": "auxapp", "system": "UNKNOWN_SYSTEM", "enabled_rows": 1, "disabled_rows": 0}],
            },
            profile_usage_overview={"available": False, "rows": []},
        )

    assert "Profile Operations Overview" in html
    assert "Execution Timing Overview" in html
    assert "Filter evidence and profile tables" in html
    assert "applyUsageSearch" in html
    assert "Application Entry Points" in html
    assert "auxapp is missing run.sh." in html
    assert "ffb does not define" in html
    assert "UNKNOWN_SYSTEM" in html


def test_profile_usage_overview_template_shows_snapshot_count_and_link():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results/usage"):
        from flask import render_template

        html = render_template(
            "_usage_report_profile_overview_section.html",
            profile_usage_overview={
                "available": True,
                "summary": {
                    "profile_count": 1,
                    "profile_with_results_count": 1,
                    "trigger_count": 1,
                    "result_count": 2,
                    "node_hours": 0.5,
                },
                "rows": [
                    {
                        "profile_id": "demoapp-demosystem",
                        "status": "approved",
                        "enabled": True,
                        "code": "demoapp",
                        "system": "DemoSystem",
                        "exp": "*",
                        "allocation_project_id": "project00010",
                        "enabled_trigger_count": 1,
                        "trigger_count": 1,
                        "trigger_labels": ["scheduled / demoapp-demosystem-time / on"],
                        "latest_trigger_run": None,
                        "result_count": 2,
                        "node_hours": 0.5,
                        "snapshot_count": 2,
                        "attribution_counts": {
                            "trigger_id_match": 1,
                            "manual_profile_match": 0,
                            "legacy_scope_fallback": 1,
                        },
                        "latest_result": {
                            "filename": "result_20260810_160604_uuid.json",
                            "timestamp": "2026-08-10 16:06:04",
                            "code": "demoapp",
                            "system": "DemoSystem",
                            "exp": "CASE0",
                            "trigger_headline": "Scheduled / demoapp-demosystem-time",
                            "pipeline_id": 3301,
                            "attribution": {
                                "label": "trigger id match",
                                "reason": "trigger_id_match",
                            },
                            "environment_snapshot": {
                                "hash": "sha256:abcdef",
                                "short_hash": "sha256:abcdef",
                                "allocation_project_id": "project00010",
                                "scheduler": "pbs",
                            },
                        },
                    }
                ],
            },
        )

    assert "2 snapshots" in html
    assert "attribution trigger/manual/legacy:" in html
    assert "1/0/1" in html
    assert "attributed by trigger id match" in html
    assert "/results/environment-snapshots/sha256:abcdef" in html
    assert "snapshot sha256:abcdef" in html


def test_usage_report_node_hours_table_uses_explicit_column_widths():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results/usage"):
        from flask import render_template

        html = render_template(
            "usage_report.html",
            result={
                "apps": ["auxapp"],
                "systems": ["SourceSystem", "DemoSystem"],
                "periods": ["2026-04", "2026-05"],
                "available_fiscal_years": [2026],
                "table": {
                    "auxapp": {
                        "SourceSystem": {"2026-04": 0.0, "2026-05": 0.0},
                        "DemoSystem": {"2026-04": 1.23, "2026-05": 0.0},
                    }
                },
                "row_totals": {"auxapp": {"2026-04": 1.23, "2026-05": 0.0}},
                "col_totals": {
                    "SourceSystem": {"2026-04": 0.0, "2026-05": 0.0},
                    "DemoSystem": {"2026-04": 1.23, "2026-05": 0.0},
                },
                "grand_totals": {"2026-04": 1.23, "2026-05": 0.0},
            },
            filtered_periods=["2026-04", "2026-05"],
            period_type="monthly",
            fiscal_year=2026,
            period_filter="",
            site_diagnostics={
                "registered_system_count": 0,
                "unused_systems": [],
                "missing_system_info": [],
                "missing_queue_definitions": [],
                "application_count": 0,
                "partial_support": [],
                "application_directory_count": 0,
                "apps_missing_files": [],
                "apps_without_estimate": [],
                "apps_with_estimate_count": 0,
                "unknown_listed_systems": [],
            },
            profile_usage_overview={"available": False, "rows": []},
        )

    assert 'class="usage-node-hours-app-col"' in html
    assert html.count('class="usage-node-hours-period-col"') == 6
    assert "table-layout: fixed" in html


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
                    "data": {"system": "DemoSystem", "code": "demoapp", "FOM": 1.2},
                },
                {
                    "filename": "result1.json",
                    "timestamp": "2026-04-13 13:00:00",
                    "data": {"system": "DemoSystem", "code": "demoapp", "FOM": 1.1},
                },
            ],
            mixed=False,
            headline="DemoSystem / demoapp - Comparing 2 results",
            has_vector_metrics=False,
            comparison_summary={
                "include_evidence": True,
                "baseline": {
                    "timestamp": "2026-04-13 12:00:00",
                    "system": "DemoSystem",
                    "code": "demoapp",
                    "exp": "CASE0",
                },
                "latest": {
                    "timestamp": "2026-04-13 13:00:00",
                    "system": "DemoSystem",
                    "code": "demoapp",
                    "exp": "CASE0",
                },
                "fom_change": {
                    "ratio_display": "0.917",
                    "delta_display": "-0.100",
                    "percent_display": "-8.333%",
                    "note": "Ratio is latest FOM divided by baseline FOM; no pass/fail judgement is applied.",
                },
                "diff_rows": [
                    {
                        "label": "Source",
                        "baseline": "git main@abcdef12",
                        "latest": "git main@fedcba98",
                        "status": "changed",
                    }
                ],
            },
            compare_chart={"vector_axis_label": "", "fom_unit": "s"},
        )

    assert "DemoSystem / demoapp - Comparing 2 results" in html
    assert "Run Comparison Summary" in html
    assert "highlights FOM and evidence differences for review" in html
    assert "does not classify regressions" in html
    assert "latest / baseline" in html
    assert "git main@abcdef12" in html
    assert "changed" in html
    assert "FOM Timeline" in html
    assert "compareConfigData" in html
    assert "vendor/chartjs/chart.umd.min.js" in html
    assert "cdn.jsdelivr.net/npm/chart.js" not in html
    assert "Failed to load chart library" in html


def test_vendored_chartjs_static_asset_is_available():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )

    response = app.test_client().get("/static/vendor/chartjs/chart.umd.min.js")

    assert response.status_code == 200
    assert b"Chart.js" in response.data[:512]


def test_usage_report_evidence_snapshot_consolidates_coverage_and_quality():
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
                "application_directory_count": 1,
                "apps_missing_files": [],
                "apps_without_estimate": [],
                "apps_with_estimate_count": 1,
                "unknown_listed_systems": [],
            },
            profile_usage_overview={"available": False, "rows": []},
            performance_telemetry={
                "summary": {
                    "result_count": 1,
                    "timing_record_count": 1,
                    "profiled_result_count": 0,
                    "regular_run_timing_count": 1,
                    "profiled_run_timing_count": 0,
                    "profile_overhead_pair_count": 0,
                    "scheduler_queue_timing_count": 0,
                    "estimate_record_count": 1,
                    "estimate_timing_record_count": 1,
                    "build_cache_record_count": 1,
                    "build_cache_hit_count": 1,
                    "build_cache_miss_count": 0,
                    "build_cache_store_count": 0,
                    "avg_build_time": "30s",
                    "avg_queue_time": "1m",
                    "avg_scheduler_queue_time": "-",
                    "avg_run_time": "2m",
                    "avg_regular_run_time": "2m",
                    "avg_profiled_run_time": "-",
                    "avg_profile_overhead_delta": "-",
                    "avg_profile_overhead_ratio": "-",
                    "avg_estimate_time": "42s",
                },
                "rows": [
                    {
                        "code": "demoapp",
                        "system": "DemoSystem",
                        "result_count": 1,
                        "timing_count": 1,
                        "profiled_count": 0,
                        "regular_run_timing_count": 1,
                        "profiled_run_timing_count": 0,
                        "profile_overhead_pair_count": 0,
                        "profile_overhead_status": "needs matching profiled run",
                        "avg_profile_overhead_delta": "-",
                        "avg_profile_overhead_ratio": "-",
                        "run_conditions": [
                            {
                                "label": "CASE0 / N1 P1 T12 / DemoFOM",
                                "regular_result_count": 1,
                                "profiled_result_count": 0,
                                "regular_run_timing_count": 1,
                                "profiled_run_timing_count": 0,
                                "avg_regular_run_time": "2m",
                                "avg_profiled_run_time": "-",
                                "avg_profile_overhead_delta": "-",
                                "avg_profile_overhead_ratio": "-",
                                "profile_overhead_status": "needs matching profiled run",
                            }
                        ],
                        "scheduler_queue_timing_count": 0,
                        "estimate_count": 1,
                        "estimate_timing_count": 1,
                        "avg_build_time": "30s",
                        "avg_queue_time": "1m",
                        "avg_scheduler_queue_time": "-",
                        "avg_run_time": "2m",
                        "avg_regular_run_time": "2m",
                        "avg_profiled_run_time": "-",
                        "avg_estimate_time": "42s",
                        "latest_build_time": "30s",
                        "latest_queue_time": "1m",
                        "latest_queue_time_source": "not measured",
                        "latest_scheduler_queue_time": "-",
                        "latest_scheduler_queue_time_source": "-",
                        "latest_run_time": "2m",
                        "latest_run_kind": "regular",
                        "latest_estimate_elapsed_time": "42s",
                        "latest_estimate_exp": "CASE0",
                        "build_cache_hit_count": 1,
                        "build_cache_miss_count": 0,
                        "build_cache_store_count": 0,
                        "latest_build_cache_status": "hit",
                        "latest_result_file": "result0.json",
                        "latest_result_time": "2026-04-13 12:00:00",
                        "latest_exp": "CASE0",
                    }
                ],
            },
            evidence_snapshot={
                "summary": {
                    "row_count": 1,
                    "result_count": 1,
                    "profiled_count": 0,
                    "estimated_count": 0,
                    "public_packet_available_count": 0,
                    "public_packet_eligible_count": 0,
                    "reuse_package_complete_count": 0,
                },
                "rows": [
                    {
                        "code": "demoapp",
                        "system": "DemoSystem",
                        "configured": "yes",
                        "configured_status": "enabled and implemented",
                        "latest_result_file": "result0.json",
                        "latest_result_time": "2026-04-13 12:00:00",
                        "latest_result_exp": "CASE0",
                        "latest_result_status": "basic",
                        "profiled": "no",
                        "latest_profile_time": "-",
                        "latest_estimate_file": "",
                        "estimated": "no",
                        "latest_estimate_time": "-",
                        "estimate_applicability": "-",
                        "source_status": "not tracked",
                        "input_status": "None",
                        "build_cache_status": "not recorded",
                        "public_result_available": "yes",
                        "latest_public_packet_file": "",
                        "latest_public_packet_time": "-",
                        "reuse_package_status": "needs evidence",
                        "public_packet_status": "needs public source",
                        "public_packet_next_action": "Record public source provenance",
                        "next_action": "Record source provenance",
                        "missing_reason": "no profile; no estimate; source incomplete; input not declared",
                    }
                ]
            },
        )

    assert "Evidence Snapshot" in html
    assert "Execution Timing Overview" in html
    assert "Operator view for choosing trigger scope/frequency and improving CI and build-cache flow" in html
    assert "reported queue values may not include scheduler-side wait" in html
    assert "may be read as job queue time" in html
    assert "build 30s / reported queue 1m / run 2m" in html
    assert "scheduler/job queue - / 0 explicit records" in html
    assert "reported queue 1m" in html
    assert "not measured" in html
    assert "regular 2m / profiled -" in html
    assert "observed overhead - / - across 0 pairs" in html
    assert "overhead pairs 0" in html
    assert "observed overhead - / -" in html
    assert "CASE0 / N1 P1 T12 / DemoFOM" in html
    assert "regular 2m (1/1 timed) /" in html
    assert "profiled - (0/0 timed)" in html
    assert "needs matching profiled run" in html
    assert "1 with timing / 1 estimates; avg 42s" in html
    assert "1 hit / 0 miss" in html
    assert "Result Evidence" in html
    assert "Profile / Estimate" in html
    assert "Provenance" in html
    assert "Application/System Coverage" not in html
    assert "Latest Result Quality Details" not in html
    assert "Evidence Snapshot:</strong> the roll-up and CSV export source" in html
    assert "Configured:</strong> yes = enabled and implemented" in html
    assert "Result Quality:</strong> missing = no result" in html
    assert "Reuse Package:</strong> complete = public packet eligible" in html
    assert "Public Packet:</strong> current latest result status" in html
    assert "Next Action" in html
    assert "Reuse / Next Action" in html
    assert "needs public source" in html
    assert "Record source provenance" in html
    assert "Maturity Gaps" in html
    assert "Input Status" in html
    assert "None = no input_info" in html
    assert "Covered = input fixed by a recorded source commit" in html
    assert "no profile; no estimate; source incomplete; input not declared" in html


def test_usage_report_links_public_reuse_packet_for_eligible_rows():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results/usage"):
        from flask import render_template

        html = render_template(
            "_usage_report_evidence_snapshot_section.html",
            evidence_snapshot={
                "summary": {
                    "row_count": 1,
                    "result_count": 1,
                    "profiled_count": 1,
                    "estimated_count": 1,
                    "public_packet_available_count": 1,
                    "public_packet_eligible_count": 1,
                    "reuse_package_complete_count": 1,
                },
                "rows": [
                    {
                        "code": "demoapp",
                        "system": "DemoSystem",
                        "configured": "yes",
                        "configured_status": "enabled and implemented",
                        "latest_result_file": "result0.json",
                        "latest_result_time": "2026-04-13 12:00:00",
                        "latest_result_exp": "CASE0",
                        "latest_result_status": "rich",
                        "profiled": "yes",
                        "latest_profile_time": "2026-04-13 12:00:00",
                        "latest_estimate_file": "estimate0.json",
                        "estimated": "yes",
                        "latest_estimate_time": "2026-04-14 12:00:00",
                        "estimate_applicability": "applicable",
                        "source_status": "tracked",
                        "input_status": "Covered",
                        "build_cache_status": "hit",
                        "public_result_available": "yes",
                        "latest_public_packet_file": "result0.json",
                        "latest_public_packet_time": "2026-04-13 12:00:00",
                        "reuse_package_status": "complete",
                        "public_packet_status": "eligible",
                        "public_packet_next_action": "Review public reuse packet",
                        "next_action": "Ready for review",
                        "missing_reason": "none",
                    }
                ],
            },
        )

    assert "/results/detail/result0.json/reuse-packet.md" in html
    assert "/results/detail/result0.json/reuse-manifest.json" in html
    assert "Latest packet" in html
    assert "Markdown packet" in html
    assert "Manifest" in html


def test_usage_report_links_latest_available_public_reuse_packet():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/results/usage"):
        from flask import render_template

        html = render_template(
            "_usage_report_evidence_snapshot_section.html",
            evidence_snapshot={
                "summary": {
                    "row_count": 1,
                    "result_count": 1,
                    "profiled_count": 0,
                    "estimated_count": 0,
                    "public_packet_available_count": 1,
                    "public_packet_eligible_count": 0,
                    "reuse_package_complete_count": 0,
                },
                "rows": [
                    {
                        "code": "demoapp",
                        "system": "DemoSystem",
                        "configured": "yes",
                        "configured_status": "enabled and implemented",
                        "latest_result_file": "latest.json",
                        "latest_result_time": "2026-04-14 12:00:00",
                        "latest_result_exp": "CASE0",
                        "latest_result_status": "basic",
                        "profiled": "no",
                        "latest_profile_time": "-",
                        "latest_estimate_file": "",
                        "estimated": "no",
                        "latest_estimate_time": "-",
                        "estimate_applicability": "-",
                        "source_status": "tracked",
                        "input_status": "None",
                        "build_cache_status": "hit",
                        "public_result_available": "yes",
                        "latest_public_packet_file": "eligible.json",
                        "latest_public_packet_time": "2026-04-13 12:00:00",
                        "reuse_package_status": "needs evidence",
                        "public_packet_status": "needs public input",
                        "public_packet_next_action": "Declare public input binding",
                        "next_action": "Declare input metadata",
                        "missing_reason": "no profile; no estimate; input not declared",
                    }
                ],
            },
        )

    assert "1 packet available / 0 complete" in html
    assert "Public packet: needs public input" in html
    assert "/results/detail/eligible.json/reuse-packet.md" in html
    assert "/results/detail/eligible.json/reuse-manifest.json" in html
    assert "/results/detail/latest.json/reuse-packet.md" not in html
    assert "2026-04-13 12:00:00" in html
