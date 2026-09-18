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
    "system": "GpuSystem",
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
            "system": "GpuSystem",
            "allocation_project_id": "rccs-cloud",
            "scheduler": "slurm",
            "runner": "gh200-runner",
            "benchkit_commit": "1234567",
        },
        "payload": {
            "schema_version": 1,
            "ci": {"job_name": "demoapp_GpuSystem_run"},
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
    "build_cache": {
        "schema_version": 1,
        "status": "hit",
        "stored": False,
        "reason": "restored cached build artifacts",
        "entry": {
            "created_at": "2026-09-04T10:20:30Z",
            "digests": {
                "build_inputs": "sha256:111111",
                "source_info": "sha256:222222",
                "artifacts": "sha256:333333",
            },
            "source": {
                "type": "git",
                "ref_kind": "branch",
                "ref_name": "develop",
                "resolved_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
            "container_image": {
                "sha256sum": "sha256:444444",
            },
            "host_environment_fingerprint": "sha256:555555",
        },
        "hit_basis": [
            "build inputs hash matched",
            "source_info.env digest matched",
            "artifact tree digest matched before and after restore",
            "git source ref resolved to cached commit",
            "container image SHA-256 matched",
        ],
    },
    "timing_observations": {
        "schema_version": 1,
        "observations": [
            {
                "id": "qws-case0-timers",
                "kind": "detailed-timing",
                "producer": "qws",
                "format": "qws_timing_observation/v1",
                "result_exp": "CASE0",
                "artifact": {
                    "type": "file_reference",
                    "path": "results/qws_timing_CASE0.json",
                },
                "summary": {
                    "timer_count": 14,
                    "schema_record_count": 3,
                    "has_overlap_probe_schema": True,
                },
                "note": "not projected to fom_breakdown",
            }
        ],
    },
    "node_status_snapshot": {
        "schema_version": 1,
        "kind": "node_status_snapshot",
        "collection_status": "ok",
        "collection_warnings": [],
        "scheduler_kind": "slurm",
        "summary": {
            "scheduler_host_count": 2,
            "observed_host_count": 2,
            "cpu_logical_counts": [64],
            "memory_total_mib_min": 262144,
            "memory_total_mib_max": 262144,
            "memory_available_mib_min": 131072,
            "load_average_1m_max": 0.5,
            "load_average_5m_max": 0.8,
            "observed_gpu_count": 4,
            "gpu_memory_used_total_mib": 0,
            "gpu_compute_process_count": 0,
            "gpu_compute_memory_used_mib": 0,
        },
        "artifact": {
            "type": "file_reference",
            "path": "results/node_status_snapshot_run.json",
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
        measurement_artifact_filenames=padata_filenames,
        public_surface=public_surface,
    )
    return render_template("result_detail.html", result=result, quality=quality, **detail_context)


class TestResultDetailTemplate:
    def test_meta_info_section(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY)

        assert "benchpark-osu-micro-benchmarks" in html
        assert "GpuSystem" in html
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
        assert "Build Cache" in html
        assert "Cached Binary Created At" in html
        assert "2026-09-04T10:20:30Z" in html
        assert "Host Environment Fingerprint" in html
        assert "Matched current host build environment" in html
        assert "Git-tracked files under programs/&lt;code&gt;/" in html
        assert "Matched current source metadata" in html
        assert "Cached Artifacts Digest" in html
        assert "Matched restored build outputs" in html
        assert "Hit Basis" in html
        assert "build inputs hash matched" in html
        assert "rccs-cloud" in html
        assert "slurm" in html
        assert "Node Status Snapshot" in html
        assert "Hosts Observed" in html
        assert "2/2" in html
        assert "CPU Counts Observed" in html
        assert "64" in html
        assert "Host Memory Total" in html
        assert "262144.000 MiB" in html
        assert "Min Memory Available Before Run" in html
        assert "131072.000 MiB" in html
        assert "Max Load Average Before Run" in html
        assert "1m=0.500; 5m=0.800" in html
        assert "Compute Processes Before Run" in html
        assert "0 process(es); 0.000 MiB" in html
        assert "results/node_status_snapshot_run.json" in html
        assert "Timing Observations" in html
        assert "qws-case0-timers" in html
        assert "producer=qws" in html
        assert "artifact=results/qws_timing_CASE0.json" in html
        assert "timers=14" in html
        assert "overlap probe schema=yes" in html
        assert "Build Tools" in html
        assert "gcc (GCC) 11.5.0" in html
        assert "Back to Results" in html
        assert "Results" in html

    def test_public_surface_meta_omits_operator_fields(self, app):
        with app.test_request_context():
            html = _render_result_detail(FULL_RESULT, FULL_QUALITY, public_surface=True)

        assert "benchpark-osu-micro-benchmarks" in html
        assert "GpuSystem" in html
        assert "6.470" in html
        assert "Pipeline ID" not in html
        assert "Parent Pipeline ID" not in html
        assert "Run Cause" not in html
        assert "<h2>Quality</h2>" not in html
        assert "Suggested Actions" not in html
        assert "Improvement Candidates" not in html
        assert "Environment Snapshot" not in html
        assert "Build Cache" not in html
        assert "Cached Binary Created At" not in html
        assert "Allocation Project ID" not in html
        assert "Runner" not in html
        assert "Node Status Snapshot" not in html
        assert "node_status_snapshot_run" not in html
        assert "Timing Observations" not in html
        assert "qws_timing_CASE0" not in html
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

        assert "Measurement Artifacts" in html
        assert "Profile archive" in html
        assert "Section: pairlist" in html
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

        assert "Measurement Artifacts" in html
        assert f'href="/results/{filename}"' in html

    @pytest.mark.parametrize("collection", ["sections", "overlaps"])
    @pytest.mark.parametrize("uploaded", [True, False])
    @pytest.mark.parametrize("public_surface", [True, False])
    def test_profile_metadata_links_respect_surface_and_upload_state(
        self, app, collection, uploaded, public_surface,
    ):
        basenames = ["kernel_discovery.json", "ncu_plan.json", "padata_kernel.metadata.json"]
        filenames = [
            "measurement_artifact_20250101_120000_"
            f"12345678-1234-1234-1234-123456789abc_{name}"
            for name in basenames
        ]
        result = {
            "code": "demoapp",
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20250101_120000",
            "fom_breakdown": {
                collection: [{
                    "name": "kernel",
                    "artifacts": [
                        {"type": "file_reference", "path": f"results/{name}"}
                        for name in basenames
                    ],
                }],
            },
        }

        with app.test_request_context():
            html = _render_result_detail(
                result, {}, filenames if uploaded else [], public_surface=public_surface,
            )

        for basename, filename in zip(basenames, filenames):
            if public_surface:
                assert basename not in html
            else:
                assert "Profile metadata" in html
                assert f"results/{basename}" in html
                if uploaded:
                    assert f'href="/results/{filename}"' in html
                else:
                    assert f"{filename} not uploaded" in html
                    assert f'href="/results/{filename}"' not in html

    @pytest.mark.parametrize("artifact_path", [
        "../metadata.json",
        "results/../metadata.json",
        "/results/metadata.json",
        "artifacts/metadata.json",
        "results/bad name.json",
        "results/metadata.txt",
    ])
    def test_invalid_profile_metadata_paths_are_omitted(self, app, artifact_path):
        result = {
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20250101_120000",
            "fom_breakdown": {
                "sections": [{
                    "name": "kernel",
                    "artifacts": [{"type": "file_reference", "path": artifact_path}],
                }],
            },
        }
        with app.test_request_context():
            context = build_result_detail_context(result, {})

        assert context["measurement_artifact_rows"] == []

    def test_timing_observation_artifact_is_linked_on_console_surface(self, app):
        result = {
            **FULL_RESULT,
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20260819_161329",
        }
        filename = (
            "measurement_artifact_20260819_161329_"
            "12345678-1234-1234-1234-123456789abc_qws_timing_CASE0.json"
        )

        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY, [filename])

        assert "Measurement Artifacts" in html
        assert "Timing observation" in html
        assert "qws-case0-timers" in html
        assert "results/qws_timing_CASE0.json" in html
        assert f'href="/results/{filename}"' in html

    def test_timing_observation_artifact_is_hidden_on_public_surface(self, app):
        result = {
            **FULL_RESULT,
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20260819_161329",
        }
        filename = (
            "measurement_artifact_20260819_161329_"
            "12345678-1234-1234-1234-123456789abc_qws_timing_CASE0.json"
        )

        with app.test_request_context():
            html = _render_result_detail(
                result,
                FULL_QUALITY,
                [filename],
                public_surface=True,
            )

        assert "Timing observation" not in html
        assert filename not in html

    def test_node_status_snapshot_artifact_is_linked_on_console_surface(self, app):
        result = {
            **FULL_RESULT,
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20260819_161329",
        }
        filename = (
            "measurement_artifact_20260819_161329_"
            "12345678-1234-1234-1234-123456789abc_node_status_snapshot_run.json"
        )

        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY, [filename])

        assert "Measurement Artifacts" in html
        assert "Node status snapshot" in html
        assert "Run placement" in html
        assert "results/node_status_snapshot_run.json" in html
        assert f'href="/results/{filename}"' in html

    def test_node_status_snapshot_artifact_is_hidden_on_public_surface(self, app):
        result = {
            **FULL_RESULT,
            "_server_uuid": "12345678-1234-1234-1234-123456789abc",
            "_server_timestamp": "20260819_161329",
        }
        filename = (
            "measurement_artifact_20260819_161329_"
            "12345678-1234-1234-1234-123456789abc_node_status_snapshot_run.json"
        )

        with app.test_request_context():
            html = _render_result_detail(
                result,
                FULL_QUALITY,
                [filename],
                public_surface=True,
            )

        assert "Node status snapshot" not in html
        assert filename not in html

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

    def test_build_cache_miss_shows_rejected_reason(self, app):
        result = {
            **FULL_RESULT,
            "build_cache": {
                "schema_version": 1,
                "status": "miss",
                "stored": True,
                "reason": "stored cache after build",
                "entry": {
                    "created_at": "2026-09-05T01:02:03Z",
                    "host_environment_fingerprint": "sha256:host-new",
                    "digests": {
                        "build_inputs": "sha256:new",
                        "source_info": "sha256:source-new",
                        "artifacts": "sha256:artifacts-new",
                    },
                },
                "store_basis": ["build inputs hash recorded"],
                "restore": {
                    "status": "miss",
                    "reason": "build inputs changed: cached old, current new",
                    "rejected_entry": {
                        "created_at": "2026-09-04T01:02:03Z",
                        "host_environment_fingerprint": "sha256:host-old",
                        "digests": {
                            "build_inputs": "sha256:old",
                            "source_info": "sha256:source-old",
                            "artifacts": "sha256:artifacts-old",
                        },
                    },
                },
            },
        }
        with app.test_request_context():
            html = _render_result_detail(result, FULL_QUALITY)

        assert "miss (stored fresh entry)" in html
        assert "Stored Entry Basis" in html
        assert "build inputs hash recorded" in html
        assert "Rejected Cache Reason" in html
        assert "build inputs changed: cached old, current new" in html
        assert "Rejected Cached Binary Created At" in html
        assert "2026-09-04T01:02:03Z" in html
        assert "Recorded the host build environment" in html
        assert "Recorded build recipe inputs" in html
        assert "Recorded source_info.env" in html
        assert "Recorded cached artifacts" in html
        assert "Rejected Host Environment Fingerprint" in html
        assert "Rejected Build Inputs Hash" in html
        assert "Rejected candidate build inputs" in html
        assert "Rejected candidate source metadata" in html
        assert "Rejected candidate artifact digest" in html

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
