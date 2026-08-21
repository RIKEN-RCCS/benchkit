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
