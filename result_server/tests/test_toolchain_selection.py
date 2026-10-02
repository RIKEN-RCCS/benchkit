"""Toolchain selection contracts shared by result views and evidence packets."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.evidence_packet import build_result_evidence_packet
from utils.result_detail_view import build_result_detail_context
from utils.result_records import select_display_toolchain


@pytest.mark.parametrize("value", [None, [], "unknown", {}, {"build": []}])
def test_missing_or_invalid_toolchain(value):
    assert select_display_toolchain(value) == {}


@pytest.mark.parametrize("flat", [{"commands": {}}, {"modules": []}])
def test_flat_toolchain_takes_precedence(flat):
    toolchain = {**flat, "build_actual": {"modules": ["nested-module"]}}
    assert select_display_toolchain(toolchain) is toolchain


@pytest.mark.parametrize("stage", ["build_actual", "build_run", "build", "run"])
def test_first_available_stage_is_selected_without_mutation(stage):
    stages = ["build_actual", "build_run", "build", "run"]
    toolchain = {name: {} for name in stages}
    for name in stages[stages.index(stage):]:
        toolchain[name] = {"modules": [f"{name}-module"]}
    original = copy.deepcopy(toolchain)

    assert select_display_toolchain(toolchain) == toolchain[stage]
    assert toolchain == original


@pytest.mark.parametrize("public_surface", [False, True])
def test_both_presentations_keep_toolchain_private(public_surface):
    result = {
        "environment_snapshot": {
            "payload": {
                "toolchain": {
                    "build_actual": {"modules": ["selected-module"]},
                    "run": {"modules": ["other-module"]},
                },
            },
        },
    }
    context = build_result_detail_context(result, {}, public_surface=public_surface)
    packet = build_result_evidence_packet(
        result, "result.json", {}, public_surface=public_surface,
    )

    if public_surface:
        assert context["environment_rows"] == []
        assert "selected-module" not in packet
    else:
        assert {"label": "Modules", "list": ["selected-module"]} in context["environment_rows"]
        assert "selected-module" in packet
    assert "other-module" not in packet
