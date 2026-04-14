"""Rendering tests for result_detail.html."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs()

import pytest
from utils.result_detail_view import build_result_detail_context


@pytest.fixture
def app():
    return build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )


FULL_RESULT = {
    "code": "benchpark-osu-micro-benchmarks",
    "system": "RC_GH200",
    "Exp": "osu_bibw",
    "FOM": 6.47,
    "FOM_unit": "MB/s",
    "FOM_version": "osu-micro-benchmarks.osu_bibw.test_mpi_2",
    "node_count": 1,
    "cpus_per_node": 2,
    "metrics": {
        "scalar": {"FOM": 6.47, "other_metric": 1.23},
        "vector": {
            "x_axis": {"name": "message_size", "unit": "bytes"},
            "table": {
                "columns": ["message_size", "Bandwidth", "P50 Tail Bandwidth"],
                "rows": [
                    [1, 6.47, 6.54],
                    [2, 12.64, 12.68],
                    [4194304, 25089.47, 25100.12],
                ],
            },
        },
    },
    "build": {
        "tool": "spack",
        "spack": {
            "compiler": {"name": "gcc", "version": "11.5.0"},
            "mpi": {"name": "openmpi", "version": "4.1.7"},
            "packages": [
                {"name": "gcc", "version": "11.5.0"},
                {"name": "openmpi", "version": "4.1.7"},
            ],
        },
    },
    "profile_data": {
        "tool": "fapp",
        "level": "single",
        "report_format": "text",
        "run_count": 1,
        "events": ["pa1"],
        "report_kinds": ["summary_text"],
    },
}

FULL_QUALITY = {
    "level": "rich",
    "label": "Rich",
    "summary": "Breakdown, estimation bindings, source provenance, and artifacts are present.",
    "warnings": [],
    "stats": {
        "has_fom": True,
        "has_source_info": True,
        "source_info_complete": True,
        "has_breakdown": True,
        "section_count": 2,
        "overlap_count": 1,
        "section_package_count": 2,
        "overlap_package_count": 1,
        "artifact_count": 3,
    },
}


def _render_result_detail(result, quality, filename="test.json"):
    from flask import render_template

    detail_context = build_result_detail_context(result, quality, filename)
    return render_template("result_detail.html", result=result, quality=quality, **detail_context)


class TestResultDetailTemplate:
    def test_meta_info_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "benchpark-osu-micro-benchmarks" in html
        assert "RC_GH200" in html
        assert "osu_bibw" in html
        assert "6.470" in html
        assert "MB/s" in html
        assert "CPUs per Node" in html
        assert "Back to Results" in html
        assert "Results" in html

    def test_vector_chart_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "vectorChart" in html
        assert "cdn.jsdelivr.net/npm/chart.js" in html
        assert "logarithmic" in html
        assert "message_size" in html
        assert "Failed to load chart library" in html

    def test_pa_data_summary_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "PA Data Summary" in html
        assert "fapp" in html
        assert "single" in html
        assert "Tool-Specific Events" in html
        assert "fapp event set: pa1" in html
        assert "summary_text" in html
        assert "pa1" in html

    def test_vector_data_table(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "Bandwidth" in html
        assert "P50 Tail Bandwidth" in html
        assert ">1<" in html or ">1</td>" in html
        assert ">4194304<" in html or ">4194304</td>" in html
        assert "6.47" in html
        assert "25089.47" in html

    def test_scalar_metrics_shown_when_multiple_keys(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "Scalar Metrics" in html
        assert "other_metric" in html
        assert "1.23" in html

    def test_scalar_metrics_hidden_when_fom_only(self, app):
        result = {
            "code": "test",
            "system": "sys",
            "Exp": "exp",
            "FOM": 1.0,
            "metrics": {"scalar": {"FOM": 1.0}},
        }
        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY)

        assert "<h2>Scalar Metrics</h2>" not in html

    def test_build_info_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "Build Information" in html
        assert "spack" in html
        assert "gcc" in html
        assert "11.5.0" in html
        assert "openmpi" in html
        assert "4.1.7" in html

    def test_build_info_hidden_when_no_build(self, app):
        result = {"code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0}
        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY)

        assert "<h2>Build Information</h2>" not in html
        assert "implicit default (s)" in html

    def test_no_vector_section_when_no_metrics(self, app):
        result = {"code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0}
        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY)

        assert "vectorChart" not in html
        assert "cdn.jsdelivr.net/npm/chart.js" not in html

    def test_build_tool_only_no_spack(self, app):
        result = {
            "code": "test",
            "system": "sys",
            "Exp": "exp",
            "FOM": 1.0,
            "build": {"tool": "cmake"},
        }
        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY)

        assert "Build Information" in html
        assert "cmake" in html
        assert "Compiler" not in html

    def test_quality_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "<h2>Quality</h2>" in html
        assert "Rich" in html
        assert "Breakdown" in html
        assert "Estimation Inputs" in html
        assert "top-level source tracked" in html
