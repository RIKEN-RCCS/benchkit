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
    "applicability": {"status": "applicable"},
    "estimate_metadata": {
        "requested_estimation_package": "instrumented_app_sections_dummy",
        "estimation_package": "instrumented_app_sections_dummy",
        "method_class": "detailed",
        "detail_level": "intermediate",
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
    assert "Package Resolution" in html
    assert "Current System" in html
    assert "Future System" in html
    assert "weakscaling" in html
    assert "instrumented_app_sections_dummy" in html
    assert "fallback" in html
    assert "section_package_unsupported:half" in html
    assert "overlap_package_unsupported:half" in html
