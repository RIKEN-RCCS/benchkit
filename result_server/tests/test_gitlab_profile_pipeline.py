"""Contracts for translating resolved execution profiles to pipeline inputs."""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.gitlab_pipeline import (  # noqa: E402
    build_pipeline_plan,
    build_profile_pipeline_plan,
    profile_scope_csv,
)


@pytest.mark.parametrize("profile", [None, {}, {"code": []}, {"code": None}])
def test_empty_profile_scope(profile):
    assert profile_scope_csv(profile, "code") == ""


@pytest.mark.parametrize(
    "overrides, expected_scope",
    [
        ({}, {"code": "app-a,app-b", "system": "system-a,system-b"}),
        ({"code": "app-b"}, {"code": "app-b", "system": "system-a,system-b"}),
        ({"system": "system-b"}, {"code": "app-a,app-b", "system": "system-b"}),
    ],
)
def test_profile_plan_preserves_selection_and_resolved_allocation(overrides, expected_scope):
    profile = {
        "code": [" app-a ", "", "app-b"],
        "system": ["system-a", "system-b"],
        "exp": ["case-a"],
        "activity": "Example activity",
        "allocation_project_id": "unresolved-example",
        "scheduler_extra_args": "--exclusive",
    }
    original = copy.deepcopy(profile)
    destination = {
        "gitlab_repo": "gitlab.example.org/group/project.git",
        "target_ref": "candidate",
        "target_id": "example",
        "result_server_url": "https://results.example.org",
    }

    plan = build_profile_pipeline_plan(
        profile=profile,
        allocation_project_id="resolved-example",
        **destination,
        **overrides,
    )

    assert plan == build_pipeline_plan(
        **destination,
        **expected_scope,
        activity="Example activity",
        allocation_project_id="resolved-example",
    )
    assert plan.payload["variables"] == {
        **expected_scope,
        "BK_EXECUTION_ACTIVITY": "Example activity",
        "BK_ALLOCATION_PROJECT_ID": "resolved-example",
        "RESULT_SERVER": "https://results.example.org",
    }
    assert profile == original


@pytest.mark.parametrize("profile", [None, {"code": [], "system": []}])
def test_profile_plan_keeps_destination_errors_without_inventing_profile_values(profile):
    plan = build_profile_pipeline_plan(
        profile=profile,
        allocation_project_id="",
        gitlab_repo="",
        target_ref="candidate",
        result_server_url="",
    )

    assert plan == build_pipeline_plan(gitlab_repo="", target_ref="candidate")
    assert plan.errors
    assert plan.payload["variables"] == {}
