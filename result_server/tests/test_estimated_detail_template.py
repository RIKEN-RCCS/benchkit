import os
import sys

import pytest
from flask import render_template


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app
from utils.estimated_detail_view import build_estimated_detail_context


ESTIMATE_RESULT = {
    "code": "qws",
    "exp": "CASE0",
    "performance_ratio": 0.104,
    "execution_mode": "cross",
    "ci_trigger": "push",
    "pipeline_id": 2468,
    "estimate_job": "qws_Fugaku_estimate",
    "applicability": {
        "status": "partially_applicable",
        "missing_inputs": ["section_package_unsupported:half"],
        "required_actions": ["collect-section-specific-package-inputs"],
    },
    "estimate_metadata": {
        "requested_estimation_package": "instrumented_app_sections_dummy",
        "estimation_package": "instrumented_app_sections_dummy",
        "method_class": "detailed",
        "detail_level": "intermediate",
        "source_result_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "source_result_timestamp": "2026-04-10 11:11:11",
        "source_result": {
            "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "timestamp": "2026-04-10 11:11:11",
            "code": "qws",
            "exp": "CASE0",
            "system": "Fugaku",
            "node_count": "1",
            "numproc_node": "4",
        },
        "current_source_result": {
            "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "timestamp": "2026-04-10 11:11:11",
            "code": "qws",
            "exp": "CASE0",
            "system": "Fugaku",
            "node_count": "1",
            "numproc_node": "4",
        },
        "future_source_result": {
            "uuid": "ffffffff-1111-2222-3333-444444444444",
            "timestamp": "2026-04-10 11:22:22",
            "code": "qws",
            "exp": "CASE0",
            "system": "MiyabiG",
            "node_count": "1",
            "numproc_node": "1",
        },
        "estimation_result_uuid": "11111111-2222-3333-4444-555555555555",
        "estimation_result_timestamp": "2026-04-10 12:34:56",
        "current_package": {
            "requested_estimation_package": "weakscaling",
            "estimation_package": "weakscaling",
        },
        "future_package": {
            "requested_estimation_package": "instrumented_app_sections_dummy",
            "estimation_package": "instrumented_app_sections_dummy",
        },
    },
    "current_system": {
        "system": "Fugaku",
        "fom": 0.944,
        "target_nodes": "1024",
        "scaling_method": "weakscaling",
        "benchmark": {"system": "Fugaku", "fom": 0.386, "nodes": "1"},
        "model": {"name": "weakscaling-current", "type": "intra_system_scaling_model"},
        "fom_breakdown": {
            "sections": [
                {
                    "name": "prepare_rhs",
                    "time": 0.062,
                    "estimation_package": "identity",
                    "scaling_method": "identity",
                    "fallback_used": "identity",
                    "package_applicability": {
                        "status": "fallback",
                        "missing_inputs": ["section_package_unsupported:half"],
                    },
                }
            ],
            "overlaps": [
                {
                    "sections": ["compute_hopping", "halo_exchange"],
                    "time": 0.015,
                    "estimation_package": "identity",
                    "scaling_method": "identity",
                    "fallback_used": "identity",
                    "package_applicability": {
                        "status": "fallback",
                        "missing_inputs": ["overlap_package_unsupported:half"],
                    },
                }
            ],
        },
    },
    "future_system": {
        "system": "FugakuNEXT",
        "fom": 9.054,
        "target_nodes": "256",
        "scaling_method": "instrumented-app-sections-dummy",
        "benchmark": {"system": "MiyabiG", "fom": 5.712, "nodes": "1"},
        "model": {"name": "instrumented-app-sections-future-projection", "type": "cross_system_projection_model"},
        "fom_breakdown": {
            "sections": [
                {
                    "name": "allreduce",
                    "time": 7.312,
                    "estimation_package": "logp",
                    "scaling_method": "logP",
                }
            ],
            "overlaps": [],
        },
    },
    "measurement": {"tool": "application-section-timer", "method": "section-timing"},
    "confidence": {"level": "experimental", "score": 0.2},
    "assumptions": {"scaling_assumption": "weak-scaling"},
    "reestimation": {
        "reason": "package-update",
        "trigger": "ci-reestimation",
        "scope": "both",
        "baseline_policy": "reuse-recorded-baseline",
        "request": {
            "reason": "package-update",
            "trigger": "ci-reestimation",
            "scope": "both",
            "baseline_policy": "reuse-recorded-baseline",
        },
        "source_result_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "source_result_timestamp": "2026-04-10 11:11:11",
        "source_estimate_result_uuid": "99999999-8888-7777-6666-555555555555",
        "source_estimate_result_timestamp": "2026-04-10 12:00:00",
        "source_result": {
            "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "timestamp": "2026-04-10 11:11:11",
        },
        "source_estimate": {
            "uuid": "99999999-8888-7777-6666-555555555555",
            "timestamp": "2026-04-10 12:00:00",
            "requested_estimation_package": "instrumented_app_sections_dummy",
            "estimation_package": "instrumented_app_sections_dummy",
            "method_class": "detailed",
            "detail_level": "intermediate",
            "ci_trigger": "push",
            "pipeline_id": 1234,
            "estimate_job": "qws_MiyabiG_reestimate",
        },
    },
}


@pytest.fixture
def app():
    yield build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )


def test_estimated_detail_template_renders_sections(app):
    with app.test_request_context("/estimated/detail/estimate.json"):
        html = render_template(
            "estimated_detail.html",
            result=ESTIMATE_RESULT,
            **build_estimated_detail_context(ESTIMATE_RESULT),
        )

    assert "Estimate Detail" in html
    assert "Applicability Summary" in html
    assert "Package Resolution" in html
    assert "Re-Estimation Context" in html
    assert "Current System" in html
    assert "Future System" in html
    assert "Estimate succeeded, but part of the breakdown used fallback handling." in html
    assert "required action: collect-section-specific-package-inputs" in html
    assert "weakscaling" in html
    assert "instrumented_app_sections_dummy" in html
    assert "Source Result UUID" in html
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in html
    assert "Source Result Timestamp" in html
    assert "Current Source UUID" in html
    assert "Future Source UUID" in html
    assert "ffffffff-1111-2222-3333-444444444444" in html
    assert "CI Trigger" in html
    assert "push" in html
    assert "Pipeline ID" in html
    assert "2468" in html
    assert "Estimate Job" in html
    assert "qws_Fugaku_estimate" in html
    assert "Source Estimate UUID" in html
    assert "99999999-8888-7777-6666-555555555555" in html
    assert "Source Estimate Job" in html
    assert "qws_MiyabiG_reestimate" in html
    assert "fallback" in html
    assert "Missing Inputs" in html
    assert "Required Actions" in html
    assert "section_package_unsupported:half" in html
    assert "overlap_package_unsupported:half" in html
