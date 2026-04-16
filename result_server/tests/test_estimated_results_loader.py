import json
import os
import shutil
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs(include_redis=False)

from utils.estimated_table_rows import build_estimated_table_columns
from utils.results_loader import load_estimated_results_table


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def flask_app(tmp_dir):
    yield build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=tmp_dir,
        estimated_dir=tmp_dir,
        include_admin=False,
    )


def _write_json(directory, filename, data):
    filepath = os.path.join(directory, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return filepath


def test_estimated_rows_prefer_metadata_fields(flask_app, tmp_dir):
    uid = str(uuid.uuid4())
    _write_json(tmp_dir, f"estimate_20250101_000000_{uid}.json", {
        "code": "est-app",
        "exp": "exp1",
        "current_system": {"system": "SysA", "fom": 1.0, "benchmark": {}},
        "future_system": {"system": "SysB", "fom": 2.0, "benchmark": {}},
        "performance_ratio": 2.0,
        "estimate_metadata": {
            "requested_estimation_package": "instrumented_app_sections_dummy",
            "estimation_package": "weakscaling",
            "method_class": "minimum",
            "detail_level": "basic",
            "current_package": {
                "estimation_package": "weakscaling",
                "requested_estimation_package": "weakscaling",
            },
            "future_package": {
                "estimation_package": "instrumented_app_sections_dummy",
                "requested_estimation_package": "instrumented_app_sections_dummy",
            },
            "estimation_result_uuid": "11111111-2222-3333-4444-555555555555",
            "estimation_result_timestamp": "2026-04-06 12:34:56",
        },
        "applicability": {"status": "fallback"},
    })

    with flask_app.test_request_context():
        rows, _, info = load_estimated_results_table(tmp_dir, public_only=True)

    assert info["total"] == 1
    assert rows[0]["timestamp"] == "2026-04-06 12:34:56"
    assert rows[0]["timestamp_date"] == "2026-04-06"
    assert rows[0]["timestamp_time"] == "12:34:56"
    assert rows[0]["estimate_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert rows[0]["estimate_uuid_short"] == "11111111"
    assert rows[0]["requested_estimation_package"] == "instrumented_app_sections_dummy"
    assert rows[0]["estimation_package"] == "weakscaling"
    assert rows[0]["requested_package_short"] == "instr_app_sec"
    assert rows[0]["applied_package_short"] == "weakscaling"
    assert rows[0]["systemA_fom_display"] == "1.000"
    assert rows[0]["systemB_fom_display"] == "2.000"
    assert rows[0]["performance_ratio_display"] == "2.000"
    assert rows[0]["method_class"] == "minimum"
    assert rows[0]["detail_level"] == "basic"
    assert rows[0]["current_estimation_package"] == "weakscaling"
    assert rows[0]["future_estimation_package"] == "instrumented_app_sections_dummy"
    assert rows[0]["applicability_status"] == "fallback"
    assert rows[0]["applicability_meta_line"] == ""


def test_estimated_rows_surface_applicability_context(flask_app, tmp_dir):
    uid = str(uuid.uuid4())
    _write_json(tmp_dir, f"estimate_20250101_000000_{uid}.json", {
        "code": "est-app",
        "exp": "exp2",
        "current_system": {"system": "SysA", "fom": 1.0, "benchmark": {}},
        "future_system": {"system": "SysB", "fom": 2.0, "benchmark": {}},
        "performance_ratio": 2.0,
        "estimate_metadata": {
            "requested_estimation_package": "instrumented_app_sections_dummy",
            "estimation_package": "instrumented_app_sections_dummy",
        },
        "applicability": {
            "status": "needs_remeasurement",
            "missing_inputs": ["fom_breakdown", "section_artifact"],
            "required_actions": ["provide-section-breakdown-for-weakscaling"],
        },
    })

    with flask_app.test_request_context():
        rows, _, info = load_estimated_results_table(tmp_dir, public_only=True)

    assert info["total"] == 1
    assert rows[0]["applicability_status"] == "needs_remeasurement"
    assert rows[0]["applicability_meta_line"] == "action: provide-section-breakdown-for-weakscaling"
    assert "missing: fom_breakdown, section_artifact" in rows[0]["applicability_title"]


def test_estimated_columns_use_compact_labels():
    columns = build_estimated_table_columns()
    labels = {column["key"]: column["label"] for column in columns}

    assert labels["systemA_target_nodes"] == "Nodes"
    assert labels["systemA_scaling_short"] == "Scaling"
    assert labels["requested_package_short"] == "Req. Pkg"
    assert labels["applied_package_short"] == "Applied Pkg"
    assert labels["estimate_uuid_short"] == "UUID"
    applicability_column = next(column for column in columns if column["key"] == "applicability_status")
    assert applicability_column["meta_key"] == "applicability_meta_line"
