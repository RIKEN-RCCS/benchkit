import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import install_portal_test_stubs

install_portal_test_stubs()

from utils.result_compare_view import build_result_compare_context, load_result_compare_context


def test_build_result_compare_context_marks_same_system_code_as_not_mixed():
    context = build_result_compare_context(
        [
            {"data": {"system": "Fugaku", "code": "qws", "FOM": 1.0}},
            {"data": {"system": "Fugaku", "code": "qws", "FOM": 0.9}},
        ]
    )

    assert context["headline"] == "Fugaku / qws - Comparing 2 results"
    assert context["mixed"] is False
    assert context["has_vector_metrics"] is False
    assert context["comparison_summary"]["fom_change"]["ratio_display"] == "0.900"


def test_build_result_compare_context_summarizes_evidence_differences():
    context = build_result_compare_context(
        [
            {
                "timestamp": "2026-09-01 00:00:00",
                "data": {
                    "system": "Fugaku",
                    "code": "qws",
                    "Exp": "CASE0",
                    "FOM": 10.0,
                    "source_info": {
                        "source_type": "git",
                        "repo_url": "https://example.test/qws.git",
                        "ref_name": "main",
                        "resolved_commit": "aaaaaaaa11111111",
                    },
                    "input_info": {
                        "inputs": [
                            {
                                "dataset_id": "case0",
                                "dataset_version": "v1",
                                "local_path": "/site/input/case0",
                                "manifest_digest": "sha256:1111111122222222",
                                "verification_status": "verified",
                            }
                        ],
                    },
                    "build_cache": {
                        "status": "hit",
                        "host_environment_fingerprint": "sha256:env-a",
                        "build_inputs_hash": "sha256:input-a",
                    },
                    "profile_data": {"tool": "ncu", "level": "kernel"},
                },
            },
            {
                "timestamp": "2026-09-02 00:00:00",
                "data": {
                    "system": "Fugaku",
                    "code": "qws",
                    "Exp": "CASE0",
                    "FOM": 12.0,
                    "source_info": {
                        "source_type": "git",
                        "repo_url": "https://example.test/qws.git",
                        "ref_name": "main",
                        "resolved_commit": "bbbbbbbb22222222",
                    },
                    "input_info": {
                        "inputs": [
                            {
                                "dataset_id": "case0",
                                "dataset_version": "v1",
                                "local_path": "/site/input/case0",
                                "manifest_digest": "sha256:1111111122222222",
                                "verification_status": "verified",
                            }
                        ],
                    },
                    "build_cache": {
                        "status": "miss",
                        "host_environment_fingerprint": "sha256:env-b",
                        "build_inputs_hash": "sha256:input-a",
                    },
                    "profile_data": {"tool": "ncu", "level": "kernel"},
                },
            },
        ]
    )

    summary = context["comparison_summary"]
    assert summary["baseline"]["timestamp"] == "2026-09-01 00:00:00"
    assert summary["latest"]["timestamp"] == "2026-09-02 00:00:00"
    assert summary["fom_change"]["ratio_display"] == "1.200"
    assert summary["fom_change"]["delta_display"] == "+2.000"
    assert summary["fom_change"]["percent_display"] == "+20.000%"

    diff_rows = {row["label"]: row for row in summary["diff_rows"]}
    assert diff_rows["Source"]["status"] == "changed"
    assert diff_rows["Build Cache"]["status"] == "changed"
    assert diff_rows["Input"]["status"] == "same"
    assert diff_rows["Profile"]["status"] == "same"

    summary_text = repr(summary)
    assert "example.test/qws.git" not in summary_text
    assert "/site/input" not in summary_text


def test_build_result_compare_context_marks_mixed_rows():
    context = build_result_compare_context(
        [
            {"data": {"system": "Fugaku", "code": "qws"}},
            {"data": {"system": "Other", "code": "qws"}},
        ]
    )

    assert context["mixed"] is True


def test_build_result_compare_context_uses_vector_axis_metadata():
    context = build_result_compare_context(
        [
            {
                "data": {
                    "system": "Fugaku",
                    "code": "qws",
                    "FOM_unit": "s",
                    "metrics": {
                        "vector": {
                            "x_axis": {"name": "message_size", "unit": "bytes"},
                            "table": {"columns": ["message_size", "Bandwidth"], "rows": [[1, 2.0]]},
                        }
                    },
                }
            }
        ]
    )

    assert context["has_vector_metrics"] is True
    assert context["compare_chart"]["vector_axis_label"] == "message_size (bytes)"
    assert context["compare_chart"]["fom_unit"] == "s"


def test_public_surface_compare_context_projects_raw_result_data(tmp_path):
    filename = "result_20250101_120000_11111111-2222-3333-4444-555555555555.json"
    payload = {
        "code": "qws",
        "system": "Fugaku",
        "Exp": "CASE0",
        "FOM": 1.0,
        "FOM_unit": "s",
        "pipeline_id": 1234,
        "runner": "internal-runner",
        "environment_snapshot": {
            "summary": {
                "allocation_project_id": "allocation-id",
                "runner": "internal-runner",
            },
        },
        "metrics": {
            "scalar": {"internal_metric": 2.0},
            "vector": {
                "x_axis": {"name": "message_size", "unit": "bytes"},
                "table": {"columns": ["message_size", "Bandwidth"], "rows": [[1, 2.0]]},
            },
        },
    }
    with open(tmp_path / filename, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    context = load_result_compare_context(
        [filename],
        str(tmp_path),
        public_surface=True,
    )

    projected = context["results"][0]["data"]
    assert projected["code"] == "qws"
    assert projected["FOM"] == 1.0
    assert "pipeline_id" not in projected
    assert "runner" not in projected
    assert "environment_snapshot" not in projected
    assert "scalar" not in projected["metrics"]
    assert projected["metrics"]["vector"]["x_axis"]["name"] == "message_size"


def test_public_surface_compare_summary_omits_operator_evidence(tmp_path):
    first = "result_20250101_120000_11111111-2222-3333-4444-555555555555.json"
    second = "result_20250101_130000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
    for filename, fom, commit in [
        (first, 1.0, "aaaaaaaa11111111"),
        (second, 2.0, "bbbbbbbb22222222"),
    ]:
        payload = {
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE0",
            "FOM": fom,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.test/qws.git",
                "ref_name": "main",
                "resolved_commit": commit,
            },
            "build_cache": {"status": "hit"},
            "profile_data": {"tool": "ncu", "level": "kernel"},
        }
        with open(tmp_path / filename, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    context = load_result_compare_context(
        [first, second],
        str(tmp_path),
        public_surface=True,
    )

    summary = context["comparison_summary"]
    assert summary["fom_change"]["ratio_display"] == "2.000"
    assert [row["label"] for row in summary["diff_rows"]] == ["System", "Code", "Exp"]
