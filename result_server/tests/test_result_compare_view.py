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
            {"data": {"system": "DemoSystem", "code": "demoapp", "FOM": 1.0}},
            {"data": {"system": "DemoSystem", "code": "demoapp", "FOM": 0.9}},
        ]
    )

    assert context["headline"] == "DemoSystem / demoapp - Comparing 2 results"
    assert context["mixed"] is False
    assert context["has_vector_metrics"] is False
    assert context["comparison_summary"]["fom_change"]["ratio_display"] == "0.900"


def test_build_result_compare_context_summarizes_evidence_differences():
    context = build_result_compare_context(
        [
            {
                "timestamp": "2026-09-01 00:00:00",
                "data": {
                    "system": "DemoSystem",
                    "code": "demoapp",
                    "Exp": "CASE0",
                    "FOM": 10.0,
                    "source_info": {
                        "source_type": "git",
                        "repo_url": "https://example.test/demoapp.git",
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
                        "stored": False,
                        "entry": {
                            "host_environment_fingerprint": "sha256:env-a",
                            "digests": {
                                "build_inputs": "sha256:input-a",
                                "source_info": "sha256:source-a",
                                "artifacts": "sha256:artifacts-a",
                            },
                        },
                    },
                    "profile_data": {"tool": "ncu", "level": "kernel"},
                },
            },
            {
                "timestamp": "2026-09-02 00:00:00",
                "data": {
                    "system": "DemoSystem",
                    "code": "demoapp",
                    "Exp": "CASE0",
                    "FOM": 12.0,
                    "source_info": {
                        "source_type": "git",
                        "repo_url": "https://example.test/demoapp.git",
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
                        "status": "hit",
                        "stored": False,
                        "entry": {
                            "host_environment_fingerprint": "sha256:env-b",
                            "digests": {
                                "build_inputs": "sha256:input-a",
                                "source_info": "sha256:source-a",
                                "artifacts": "sha256:artifacts-a",
                            },
                        },
                    },
                    "profile_data": {"tool": "ncu", "level": "kernel"},
                },
            },
        ]
    )

    summary = context["comparison_summary"]
    assert summary["baseline"]["timestamp"] == "2026-09-01 00:00:00"
    assert summary["latest"]["timestamp"] == "2026-09-02 00:00:00"
    assert summary["include_evidence"] is True
    assert summary["fom_change"]["ratio_display"] == "1.200"
    assert summary["fom_change"]["delta_display"] == "+2.000"
    assert summary["fom_change"]["percent_display"] == "+20.000%"

    diff_rows = {row["label"]: row for row in summary["diff_rows"]}
    assert diff_rows["Source"]["status"] == "changed"
    assert diff_rows["Build Cache"]["status"] == "changed"
    assert diff_rows["Input"]["status"] == "same"
    assert diff_rows["Profile"]["status"] == "same"

    summary_text = repr(summary)
    assert "example.test/demoapp.git" not in summary_text
    assert "/site/input" not in summary_text


def test_build_result_compare_context_detects_build_cache_digest_changes():
    base_entry = {
        "host_environment_fingerprint": "sha256:env-a",
        "digests": {
            "build_inputs": "sha256:input-a",
            "source_info": "sha256:source-a",
            "artifacts": "sha256:artifacts-a",
        },
    }
    latest_entry = {
        **base_entry,
        "digests": {
            **base_entry["digests"],
            "artifacts": "sha256:artifacts-b",
        },
    }
    context = build_result_compare_context(
        [
            {
                "data": {
                    "system": "DemoSystem",
                    "code": "demoapp",
                    "FOM": 1.0,
                    "build_cache": {
                        "status": "hit",
                        "stored": False,
                        "entry": base_entry,
                    },
                },
            },
            {
                "data": {
                    "system": "DemoSystem",
                    "code": "demoapp",
                    "FOM": 1.0,
                    "build_cache": {
                        "status": "hit",
                        "stored": False,
                        "entry": latest_entry,
                    },
                },
            },
        ]
    )

    diff_rows = {
        row["label"]: row
        for row in context["comparison_summary"]["diff_rows"]
    }
    assert diff_rows["Build Cache"]["status"] == "changed"


def test_build_result_compare_context_marks_mixed_rows():
    context = build_result_compare_context(
        [
            {"data": {"system": "DemoSystem", "code": "demoapp"}},
            {"data": {"system": "Other", "code": "demoapp"}},
        ]
    )

    assert context["mixed"] is True


def test_input_comparison_uses_full_digest_beyond_display_prefix():
    first_digest = "a" * 64
    changed_digest = "a" * 63 + "b"
    for digest, expected_status in [(first_digest, "same"), (changed_digest, "changed")]:
        results = [
            {"data": {
                "system": "DemoSystem",
                "code": "demoapp",
                "input_info": {"inputs": [{
                    "dataset_id": "demo-matrix",
                    "dataset_version": "v1",
                    "verification_status": "verified",
                    "sha256": value,
                    "size_bytes": 3,
                }]},
            }}
            for value in (first_digest, digest)
        ]
        summary = build_result_compare_context(results)["comparison_summary"]
        input_row = next(row for row in summary["diff_rows"] if row["label"] == "Input")
        assert input_row["status"] == expected_status
        assert summary["baseline"]["input_display"] == summary["latest"]["input_display"]


def test_input_comparison_distinguishes_unavailable_and_reference_mismatch():
    base = {"dataset_id": "demo", "collection_status": "recorded", "sha256": "a" * 64}
    for change, message in [
        ({"dataset_id": "demo", "collection_status": "unavailable"}, "input observation unavailable"),
        ({**base, "verification_status": "mismatch"}, "differs from reference"),
    ]:
        results = [{"data": {"input_info": {"inputs": [item]}}} for item in (base, change)]
        summary = build_result_compare_context(results)["comparison_summary"]
        row = next(row for row in summary["diff_rows"] if row["label"] == "Input")
        assert row["status"] == ("unobserved" if change.get("collection_status") == "unavailable" else "changed")
        assert message in summary["latest"]["input_display"]


def test_build_result_compare_context_uses_vector_axis_metadata():
    context = build_result_compare_context(
        [
            {
                "data": {
                    "system": "DemoSystem",
                    "code": "demoapp",
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
        "code": "demoapp",
        "system": "DemoSystem",
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
    assert projected["code"] == "demoapp"
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
            "code": "demoapp",
            "system": "DemoSystem",
            "Exp": "CASE0",
            "FOM": fom,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.test/demoapp.git",
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
    assert summary["include_evidence"] is False
    assert summary["fom_change"]["ratio_display"] == "2.000"
    assert [row["label"] for row in summary["diff_rows"]] == ["System", "Code", "Exp"]


def _input_results(digests):
    return [{"timestamp": f"2026-10-01 00:00:0{index}", "data": {
        "system": "DemoSystem", "code": "demoapp", "Exp": "CASE0", "FOM": index + 1,
        **({"input_info": {"inputs": [{"dataset_id": "demo", "sha256": digest,
                                       "collection_status": "recorded"}]}} if digest else {}),
    }} for index, digest in enumerate(digests)]


def test_input_provenance_covers_middle_result_without_changing_fom():
    summary = build_result_compare_context(_input_results(["a" * 64, "b" * 64, "a" * 64]))["comparison_summary"]
    assert summary["input_provenance"]["changed"] is True
    assert summary["has_differences"] is True
    assert len(summary["input_provenance"]["rows"]) == 3
    assert summary["fom_change"]["ratio_display"] == "3.000"
    assert next(row for row in summary["diff_rows"] if row["label"] == "Input")["status"] == "same"


def test_missing_input_is_unobserved_even_when_both_results_are_missing():
    for digests in ([None, None], ["a" * 64, None]):
        summary = build_result_compare_context(_input_results(digests))["comparison_summary"]
        assert summary["input_provenance"]["has_unobserved"] is True
        assert summary["input_provenance"]["changed"] is False
        assert next(row for row in summary["diff_rows"] if row["label"] == "Input")["status"] == "unobserved"
        assert summary["fom_change"]["available"] is True


def test_input_provenance_template_exposes_full_digest_and_escapes_identifiers():
    from flask import render_template
    from test_support import build_portal_shell_app
    app = build_portal_shell_app(templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"))
    digests = ["a" * 64, "a" * 63 + "b", None]
    results = _input_results(digests)
    results[1]["data"]["input_info"]["inputs"][0]["dataset_id"] = "<script>bad()</script>"
    context = build_result_compare_context(results)
    with app.test_request_context("/compare"):
        html = render_template("result_compare.html", **context)
    assert "input-provenance-changed" in html
    assert "Recorded input provenance differs across selected results." in html
    assert "comparison-status-unobserved" in html
    assert digests[0] in html and digests[1] in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "<script>bad()</script>" not in html
    assert "scientific compatibility" in html
    with app.test_request_context("/compare"):
        from utils.result_compare_view import _project_public_compare_result
        public_rows = [_project_public_compare_result(row) for row in results]
        public_html = render_template("result_compare.html", **build_result_compare_context(public_rows, include_evidence=False))
    assert "<h3>Input Provenance</h3>" not in public_html
    assert digests[0] not in public_html


def test_matching_recorded_input_provenance_has_no_difference_highlight():
    context = build_result_compare_context(_input_results(["a" * 64] * 3))
    assert context["mixed"] is False
    assert context["comparison_summary"]["input_provenance"]["changed"] is False
    assert context["comparison_summary"]["input_provenance"]["has_unobserved"] is False
