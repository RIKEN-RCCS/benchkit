import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import estimate_version_view as view


CONFIG = {"ESTIMATION_VERSION_REPO": "/configured/repository",
          "ESTIMATION_VERSION_REF": "refs/heads/test"}


def estimate():
    return {
        "code": "sample",
        "estimate_metadata": {"app_estimation_method": {"version": "a"},
                              "estimation_package": "scaling", "estimation_package_version": "a"},
        "future_system": {"fom_breakdown": {"sections": [{
            "name": "compute", "estimation_package": "identity", "estimation_package_version": "a",
            "requested_estimation_package": "ensemble", "requested_estimation_package_version": "a",
            "candidate_estimates": [{"estimation_package": "predictor", "estimation_package_version": "a"}],
            "model": {"name": "model", "version": "weights-a"},
        }]}},
    }


@pytest.fixture
def snapshot(monkeypatch):
    data = {"ref": "refs/heads/test", "commit": "a" * 40,
            "app": {"version": "b"}, "packages": {"scaling": {"version": "a"}},
            "section_packages": {name: {"version": "a"} for name in ("identity", "ensemble", "predictor")},
            "unknowns": []}
    calls = []

    def read(*args, **kwargs):
        calls.append((args, kwargs))
        return data

    monkeypatch.setattr(view, "read_estimation_version_snapshot", read)
    return data, calls


@pytest.mark.parametrize("config", [{}, {"ESTIMATION_VERSION_REPO": "repo"},
                                     {**CONFIG, "PUBLIC_PORTAL_MODE": True}])
def test_disabled_or_public_surface_performs_no_git_read(snapshot, config):
    assert view.build_estimate_version_check(estimate(), config) is None
    assert not snapshot[1]


def test_selects_requested_applied_and_candidate_packages_without_mutating_input(snapshot):
    payload = estimate()
    original = copy.deepcopy(payload)
    result = view.build_estimate_version_check(payload, CONFIG)
    assert result["changed_count"] == 1
    assert result["unknown_count"] == 1  # No external model version declaration.
    assert result["status"] == "different"
    assert snapshot[1][0][1] == {"packages": ["scaling"],
                                "section_packages": ["ensemble", "identity", "predictor"]}
    assert payload == original
    assert "/configured/repository" not in str(result)


def test_model_version_is_not_inferred_from_package_version(snapshot):
    snapshot[0]["app"]["version"] = "a"
    result = view.build_estimate_version_check(estimate(), CONFIG)
    assert result["status"] == "unknown"
    assert result["rows"][0]["component"] == "model"
    assert result["rows"][0]["reference"] == "Unknown"


def test_only_comparable_records_can_match(snapshot):
    snapshot[0]["app"]["version"] = "a"
    payload = estimate()
    del payload["future_system"]["fom_breakdown"]["sections"][0]["model"]
    result = view.build_estimate_version_check(payload, CONFIG)
    assert result["status"] == "same"
    assert result["rows"] == []


def test_missing_declaration_and_legacy_version_stay_unknown(snapshot):
    snapshot[0]["section_packages"]["ensemble"] = None
    payload = estimate()
    del payload["estimate_metadata"]["app_estimation_method"]
    result = view.build_estimate_version_check(payload, CONFIG)
    assert result["status"] == "unknown"
    assert result["unknown_count"] == 3


def test_invalid_configuration_does_not_expose_error_or_repository_path(monkeypatch):
    def read(*args, **kwargs):
        raise ValueError("sensitive configuration")

    monkeypatch.setattr(view, "read_estimation_version_snapshot", read)
    result = view.build_estimate_version_check(estimate(), CONFIG)
    assert result["status"] == "unknown"
    assert "sensitive" not in str(result) and CONFIG["ESTIMATION_VERSION_REPO"] not in str(result)


def test_ambiguous_candidates_are_counted_unknown(snapshot):
    payload = estimate()
    items = payload["future_system"]["fom_breakdown"]["sections"][0]["candidate_estimates"]
    items.append(copy.deepcopy(items[0]))
    result = view.build_estimate_version_check(payload, CONFIG)
    assert result["unknown_count"] == 2


def test_configured_ref_is_operator_selected(monkeypatch):
    from flask import Flask
    app = Flask(__name__)
    monkeypatch.setenv("RESULT_SERVER_ESTIMATION_VERSION_REPO", "repository")
    monkeypatch.setenv("RESULT_SERVER_ESTIMATION_VERSION_REF", "refs/heads/test")
    view.configure_estimate_version_check(app)
    assert app.config["ESTIMATION_VERSION_REPO"] == "repository"
    assert app.config["ESTIMATION_VERSION_REF"] == "refs/heads/test"
