import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.estimate_versions import compare_estimate_versions


def estimate():
    return {
        "code": "sample",
        "estimate_metadata": {
            "app_estimation_method": {"version": "method-a"},
            "estimation_package": "aggregate",
            "estimation_package_version": "aggregate-a",
            "current_package": {"estimation_package": "scaling",
                                "estimation_package_version": "scaling-a"},
        },
        "future_system": {"fom_breakdown": {"sections": [{
            "name": "compute", "estimation_package": "identity",
            "estimation_package_version": "identity-a",
            "requested_estimation_package": "ensemble",
            "requested_estimation_package_version": "ensemble-a",
            "model": {"name": "mean", "version": "mean-a"},
            "candidate_estimates": [
                {"estimation_package": "predictor-a", "estimation_package_version": "a",
                 "model": {"name": "trained-a", "version": "weights-a"}},
                {"estimation_package": "predictor-b", "estimation_package_version": "b"},
            ],
        }]}},
    }


def section(payload):
    return payload["future_system"]["fom_breakdown"]["sections"][0]


def test_identical_versions_ignore_measurements_conditions_commits_and_observation():
    previous = estimate()
    candidate = copy.deepcopy(previous)
    candidate.update(performance_ratio=99, benchkit_commit="other")
    candidate["future_system"].update(fom=42, target_nodes=8)
    candidate["estimate_metadata"]["app_observation"] = {"version": "changed"}
    section(candidate)["time"] = 42
    section(candidate)["candidate_estimates"].reverse()
    assert compare_estimate_versions(previous, candidate) == {
        "status": "same", "complete": True, "changes": [], "unknowns": [],
    }


@pytest.mark.parametrize("component", ["app", "top", "current", "requested", "model", "candidate"])
def test_explicit_versions_are_compared_at_each_level(component):
    previous = estimate()
    candidate = copy.deepcopy(previous)
    if component == "app":
        candidate["estimate_metadata"]["app_estimation_method"]["version"] = "method-b"
    elif component == "top":
        candidate["estimate_metadata"]["estimation_package_version"] = "aggregate-b"
    elif component == "current":
        candidate["estimate_metadata"]["current_package"]["estimation_package_version"] = "scaling-b"
    elif component == "requested":
        section(candidate)["requested_estimation_package_version"] = "ensemble-b"
    elif component == "model":
        section(candidate)["model"]["version"] = "mean-b"
    else:
        section(candidate)["candidate_estimates"][0]["model"]["version"] = "weights-b"
    result = compare_estimate_versions(previous, candidate)
    assert result["status"] == "different"
    assert result["complete"]
    assert len(result["changes"]) == 1
    assert previous == estimate()


@pytest.mark.parametrize("version", [None, "", "   ", False, [], {}])
def test_missing_or_invalid_version_is_unknown_not_same(version):
    previous = estimate()
    previous["estimate_metadata"]["app_estimation_method"]["version"] = version
    result = compare_estimate_versions(previous, estimate())
    assert result["status"] == "unknown"
    assert not result["complete"]


def test_legacy_payload_does_not_inherit_candidate_versions():
    assert compare_estimate_versions({"code": "sample"}, estimate())["status"] == "unknown"
    assert compare_estimate_versions({"code": "sample"}, {"code": "sample"})["status"] == "unknown"


def test_known_change_and_unknown_records_are_both_preserved():
    previous = estimate()
    candidate = estimate()
    candidate["estimate_metadata"]["app_estimation_method"]["version"] = "method-b"
    section(previous)["model"].pop("version")
    result = compare_estimate_versions(previous, candidate)
    assert result["status"] == "different"
    assert not result["complete"]
    assert result["changes"] and result["unknowns"]


def test_duplicate_candidate_identity_is_unknown():
    candidate = estimate()
    candidates = section(candidate)["candidate_estimates"]
    candidates.append(copy.deepcopy(candidates[0]))
    result = compare_estimate_versions(estimate(), candidate)
    assert result["status"] == "unknown"
    assert any(item["reason"] == "ambiguous_component" for item in result["unknowns"])


@pytest.mark.parametrize("candidate", [None, {}, {"code": "other"}])
def test_unrelated_or_invalid_app_is_not_an_update(candidate):
    assert compare_estimate_versions(estimate(), candidate)["status"] == "unknown"


def test_versions_are_opaque_and_not_sorted_as_releases():
    candidate = estimate()
    candidate["estimate_metadata"]["app_estimation_method"]["version"] = "older-label"
    assert compare_estimate_versions(estimate(), candidate)["status"] == "different"


def test_overlaps_and_duplicate_section_names():
    previous = estimate()
    previous["future_system"]["fom_breakdown"]["overlaps"] = [{
        "name": "overlap", "estimation_package": "merge", "estimation_package_version": "a",
    }]
    candidate = copy.deepcopy(previous)
    candidate["future_system"]["fom_breakdown"]["overlaps"][0]["estimation_package_version"] = "b"
    assert compare_estimate_versions(previous, candidate)["status"] == "different"
    candidate = estimate()
    candidate["future_system"]["fom_breakdown"]["sections"].append(copy.deepcopy(section(candidate)))
    assert compare_estimate_versions(estimate(), candidate)["status"] == "unknown"


@pytest.mark.parametrize("field,value", [
    ("estimate_metadata", None), ("current_system", []),
    ("future_system", {"fom_breakdown": None}),
    ("future_system", {"fom_breakdown": {"sections": [None, {"name": []}]}}),
])
def test_malformed_record_shapes_remain_unknown(field, value):
    candidate = estimate()
    candidate[field] = value
    result = compare_estimate_versions(estimate(), candidate)
    assert result["status"] == "unknown"
    assert not result["complete"]


def test_top_and_system_models_and_section_reordering():
    previous = estimate()
    previous["model"] = {"name": "aggregate-model", "version": "a"}
    previous["current_system"] = {"model": {"name": "scale-model", "version": "a"}}
    other = copy.deepcopy(section(previous))
    other["name"] = "other"
    previous["future_system"]["fom_breakdown"]["sections"].append(other)
    candidate = copy.deepcopy(previous)
    candidate["future_system"]["fom_breakdown"]["sections"].reverse()
    assert compare_estimate_versions(previous, candidate)["status"] == "same"
    candidate["model"]["version"] = "b"
    candidate["current_system"]["model"]["version"] = "b"
    result = compare_estimate_versions(previous, candidate)
    assert len(result["changes"]) == 2
    assert result["complete"]
