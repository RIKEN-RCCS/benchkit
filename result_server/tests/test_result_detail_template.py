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
    "pipeline_id": 3208,
    "parent_pipeline_id": 3207,
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
    "environment_snapshot": {
        "schema_version": 1,
        "hash": "sha256:abcdef",
        "summary": {
            "system": "RC_GH200",
            "allocation_project_id": "rccs-cloud",
            "scheduler": "slurm",
            "runner": "gh200-runner",
            "benchkit_commit": "1234567",
        },
        "payload": {
            "schema_version": 1,
            "ci": {"job_name": "qws_RC_GH200_run"},
            "toolchain": {
                "modules": ["gcc/11.5.0", "openmpi/4.1.7"],
                "commands": {
                    "gcc": {
                        "path": "/usr/bin/gcc",
                        "real_path": "/usr/bin/gcc",
                        "version": "gcc (GCC) 11.5.0",
                    }
                },
            },
        },
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


def _render_result_detail(result, quality, padata_filenames=None, *, public_surface=False):
    from flask import render_template

    detail_context = build_result_detail_context(
        result,
        quality,
        padata_filenames=padata_filenames,
        public_surface=public_surface,
    )
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
        assert "Pipeline ID" in html
        assert "3208" in html
        assert "Parent Pipeline ID" in html
        assert "3207" in html
        assert "Environment Snapshot" in html
        assert "sha256:abcdef" in html
        assert "rccs-cloud" in html
        assert "slurm" in html
        assert "Build Tools" in html
        assert "gcc (GCC) 11.5.0" in html
        assert "Back to Results" in html
        assert "Results" in html

    def test_public_surface_meta_omits_operator_fields(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY, public_surface=True)

        assert "benchpark-osu-micro-benchmarks" in html
        assert "RC_GH200" in html
        assert "6.470" in html
        assert "Pipeline ID" not in html
        assert "Parent Pipeline ID" not in html
        assert "Run Cause" not in html
        assert "<h2>Quality</h2>" not in html
        assert "Suggested Actions" not in html
        assert "Improvement Candidates" not in html
        assert "Environment Snapshot" not in html
        assert "Allocation Project ID" not in html
        assert "Runner" not in html
        assert "rccs-cloud" not in html
        assert "gh200-runner" not in html

    def test_vector_chart_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "vectorChart" in html
        assert "vendor/chartjs/chart.umd.min.js" in html
        assert "cdn.jsdelivr.net/npm/chart.js" not in html
        assert "logarithmic" in html
        assert "message_size" in html
        assert "Failed to load chart library" in html

    def test_pa_data_summary_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "PA Data Summary" in html
        assert "fapp" in html
        assert "single" in html
        assert "Tool-Specific Detail" in html
        assert "fapp event set: pa1" in html
        assert "summary_text" in html
        assert "pa1" in html

    def test_ncu_pa_data_summary_shows_ncu_options_without_generic_events(self, app):
        result = {
            **FULL_RESULT,
            "profile_data": {
                "tool": "ncu",
                "level": "single",
                "report_format": "text",
                "run_count": 1,
                "events": [],
                "ncu_options": ["--target-processes", "all", "--set", "basic", "--launch-count", "1"],
                "report_kinds": ["ncu_report", "summary_text"],
            },
        }
        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY)

        assert "Tool-Specific Detail" in html
        assert "ncu options: --target-processes all --set basic --launch-count 1" in html
        assert "NCU Options" in html
        assert "ncu_report" in html
        assert ">Events<" not in html

    def test_section_padata_archives_are_linked(self, app):
        result = {
            **FULL_RESULT,
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20260819_161329",
            "fom_breakdown": {
                "sections": [
                    {
                        "name": "pairlist",
                        "time": 1.0,
                        "artifacts": [
                            {
                                "type": "file_reference",
                                "path": "results/padata_k003_void_kern_build_pairlist.tgz",
                            }
                        ],
                    }
                ],
                "overlaps": [],
            },
        }
        filename = (
            "padata_20260819_161329_12345678-1234-1234-1234-123456789abc_"
            "padata_k003_void_kern_build_pairlist.tgz"
        )

        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY, [filename])

        assert "PA Data Archives" in html
        assert "pairlist" in html
        assert "results/padata_k003_void_kern_build_pairlist.tgz" in html
        assert f'href="/results/{filename}"' in html

    def test_public_surface_keeps_padata_archive_links(self, app):
        result = {
            **FULL_RESULT,
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20260819_161329",
            "fom_breakdown": {
                "sections": [
                    {
                        "name": "pairlist",
                        "time": 1.0,
                        "artifacts": [
                            {
                                "type": "file_reference",
                                "path": "results/padata_k003_void_kern_build_pairlist.tgz",
                            }
                        ],
                    }
                ],
                "overlaps": [],
            },
        }
        filename = (
            "padata_20260819_161329_12345678-1234-1234-1234-123456789abc_"
            "padata_k003_void_kern_build_pairlist.tgz"
        )

        with app.test_request_context():
            html = _render_result_detail(
                result,
                FULL_QUALITY,
                [filename],
                public_surface=True,
            )

        assert "PA Data Archives" in html
        assert f'href="/results/{filename}"' in html

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
        assert "not specified" in html

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
        assert "Suggested Actions" in html
        assert "Improvement Candidates" in html
