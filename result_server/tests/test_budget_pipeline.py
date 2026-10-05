"""Budget selection to generated CI using isolated registries and synthetic jobs."""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("sqlcipher3")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_budget_registry import registry, configured_target, ADMIN, MANAGER, STRANGER  # noqa: F401
from test_execution_routes import project, config, env, generate  # noqa: F401
from utils.budget_pipeline import build_budget_pipeline_plan
from utils.budget_registry import RegistryError, RegistryConflict, RegistryPermissionError
from utils.execution_profiles import normalize_profile


@pytest.fixture
def selection(registry, configured_target):
    revision = registry.save_budget(ADMIN, 0, id="research", label="Research", system="Example Center", enabled=True)
    revision = registry.set_manager(ADMIN, revision, budget_id="research", principal=MANAGER.principal, assigned=True)
    revision = registry.save_account(ADMIN, revision, id="settings", label="Settings", system="Example Center",
                                     connection_id=configured_target, build_tag="selected-build", run_tag="selected-run")
    revision = registry.save_destination(ADMIN, revision, id="selected", budget_id="research", system="Fugaku",
                                         account_id="settings", allocation_project_id="example-allocation")
    profile, errors = normalize_profile(dict(id="profile", enabled=True, status="approved", code=["demo"],
                                            system=["Fugaku", "Legacy"], activity="Public Example"))
    assert not errors
    return dict(registry=registry, actor=MANAGER, destination_id="selected", expected_revision=revision,
                profile=profile, target_ref="develop", result_server_url="https://results.example.org")


def test_selection_derives_target_tags_allocation_and_snapshot(selection, project, monkeypatch):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN_EXAMPLE", "DO_NOT_INCLUDE_CREDENTIAL")
    before = deepcopy(selection["profile"])
    result = build_budget_pipeline_plan(**selection)
    variables = result.plan.payload["variables"]
    assert result.target.repo == "gitlab.example.org/group/project"
    assert result.target.token_env == "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_EXAMPLE"
    assert variables["system"] == "Fugaku"
    assert variables["BK_ALLOCATION_PROJECT_ID"] == "example-allocation"
    assert variables["BK_EXECUTION_ACTIVITY"] == "Public Example"
    assert "DO_NOT_INCLUDE_CREDENTIAL" not in json.dumps(asdict(result))
    assert "token_env" not in variables["BK_EXECUTION_ROUTE_SNAPSHOT"]
    assert json.loads(variables["BK_EXECUTION_ROUTE_SNAPSHOT"]) == result.snapshot
    assert selection["profile"] == before
    project[1].pop("BK_EXECUTION_ROUTES_FILE")
    generated = generate(project, **variables)
    assert generated.returncode == 0, generated.stderr
    content = (project[0] / ".gitlab-ci.generated.yml").read_text()
    assert 'tags: ["selected-build"]' in content
    assert 'tags: ["selected-run"]' in content
    assert '-g example-allocation' in content
    assert 'legacy-run' not in content
    for value in ("example-allocation", "selected-run", "selected-build"):
        assert value not in generated.stdout + generated.stderr


def test_admin_can_select_and_unassigned_identity_cannot(selection):
    assert build_budget_pipeline_plan(**{**selection, "actor": ADMIN}).snapshot["budget_id"] == "research"
    with pytest.raises(RegistryPermissionError):
        build_budget_pipeline_plan(**{**selection, "actor": STRANGER})


@pytest.mark.parametrize("change", [
    {"enabled": False}, {"status": "draft"}, {"valid_until": "2000-01-01"},
    {"valid_from": "9999-01-01"}, {"system": ["Other"]},
    {"allocation_project_id": "conflicting"}, {"scheduler_extra_args": "--account=conflicting"},
])
def test_profile_constraints_are_not_overridden(selection, change):
    selection["profile"].update(change)
    with pytest.raises(RegistryError):
        build_budget_pipeline_plan(**selection)


def test_application_scope_is_not_broadened(selection):
    assert build_budget_pipeline_plan(**selection, code="demo").plan.payload["variables"]["code"] == "demo"
    with pytest.raises(RegistryError):
        build_budget_pipeline_plan(**selection, code="demo,other")


@pytest.mark.parametrize("revision", [None, True, -1, "1", 0])
def test_missing_invalid_or_stale_revision_is_rejected(selection, revision):
    with pytest.raises(RegistryConflict):
        build_budget_pipeline_plan(**{**selection, "expected_revision": revision})


def test_replanning_checks_current_budget_and_preserves_previous_snapshot(selection):
    first = build_budget_pipeline_plan(**selection)
    snapshot = deepcopy(first.snapshot)
    store = selection["registry"]
    revision = store.save_budget(ADMIN, selection["expected_revision"], id="research", label="Paused",
                                  system="Example Center", enabled=False)
    with pytest.raises(RegistryError):
        build_budget_pipeline_plan(**{**selection, "expected_revision": revision})
    assert first.snapshot == snapshot


def test_revoked_manager_cannot_replan(selection):
    store = selection["registry"]
    revision = store.set_manager(ADMIN, selection["expected_revision"], budget_id="research",
                                 principal=MANAGER.principal, assigned=False)
    with pytest.raises(RegistryPermissionError):
        build_budget_pipeline_plan(**{**selection, "expected_revision": revision})


def test_removed_connection_is_not_replaced_by_default(selection, monkeypatch):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", "other=other.example.org/group/project")
    with pytest.raises(RegistryError):
        build_budget_pipeline_plan(**selection)


def test_allocation_free_target_is_explicit_and_supported(selection, project):
    store = selection["registry"]
    revision = store.save_budget(ADMIN, selection["expected_revision"], id="free-budget", label="Shared resources",
                                  system="Example Center", enabled=True)
    revision = store.save_destination(ADMIN, revision, id="free", budget_id="free-budget",
                                       system="Legacy", account_id="settings", allocation_project_id="")
    result = build_budget_pipeline_plan(**{**selection, "actor": ADMIN,
                                           "destination_id": "free", "expected_revision": revision})
    assert result.snapshot["route"]["allocation_project_id"] == ""
    assert "BK_ALLOCATION_PROJECT_ID" not in result.plan.payload["variables"]
    project[1].pop("BK_EXECUTION_ROUTES_FILE")
    generated = generate(project, **result.plan.payload["variables"])
    assert generated.returncode == 0, generated.stderr
    assert 'BK_ROUTE_ALLOCATION_PROJECT_ID: ""' in (project[0] / ".gitlab-ci.generated.yml").read_text()
