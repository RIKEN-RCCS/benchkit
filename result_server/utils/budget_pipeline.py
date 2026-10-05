"""Plan one explicitly selected Budget destination without submitting a job."""

from __future__ import annotations

from dataclasses import dataclass
import json

from .budget_registry import RegistryConflict, RegistryError
from .execution_profiles import _profile_validity_error
from .gitlab_pipeline import GitLabPipelinePlan, GitLabPipelineTarget, build_profile_pipeline_plan


@dataclass(frozen=True)
class BudgetPipelinePlan:
    plan: GitLabPipelinePlan
    target: GitLabPipelineTarget
    snapshot: dict


def build_budget_pipeline_plan(*, registry, actor, destination_id, expected_revision,
                               profile, target_ref, result_server_url, code=""):
    """Resolve a trusted stored profile and selection through current permissions.

    Callers must authorize profile access separately. Rebuild at submission time;
    a previously generated plan is not an enduring authorization grant.
    """
    if type(expected_revision) is not int or expected_revision < 0:
        raise RegistryConflict("A valid registry revision is required")
    resolved = registry.resolve(actor, destination_id)
    if resolved["registry_revision"] != expected_revision:
        raise RegistryConflict("Registry changed; review the selection again")
    if (not profile or not profile.get("enabled") or profile.get("status") != "approved"
            or _profile_validity_error(profile)):
        raise RegistryError("An active approved execution profile is required")
    if profile.get("system") and resolved["system"] not in profile["system"]:
        raise RegistryError("Budget destination is outside the profile system scope")
    if code and profile.get("code") and any(item.strip() not in profile["code"] for item in code.split(",")):
        raise RegistryError("Selected application is outside the profile scope")
    allocation = profile.get("allocation_project_id", "")
    if allocation and allocation != resolved["route"]["allocation_project_id"]:
        raise RegistryError("Profile allocation conflicts with the selected Budget")
    if profile.get("scheduler_extra_args"):
        raise RegistryError("Scheduler overrides require review before using a Budget")

    # Keep credentials/references and administrative labels out of CI variables.
    snapshot = {key: resolved[key] for key in
                ("version", "registry_revision", "budget_id", "destination_id", "target", "route")}
    repo = resolved["target"]["server_url"].removeprefix("https://") + "/" + resolved["target"]["project_path"]
    target = GitLabPipelineTarget(id=resolved["connection_id"], repo=repo, token_env=resolved["token_env"])
    plan = build_profile_pipeline_plan(
        profile=profile, allocation_project_id=resolved["route"]["allocation_project_id"],
        gitlab_repo=repo, target_ref=target_ref, result_server_url=result_server_url,
        target_id=target.id, code=code, system=resolved["system"],
    )
    if plan.errors:
        raise RegistryError("Budget pipeline target configuration is invalid")
    plan.payload["variables"]["BK_EXECUTION_ROUTE_SNAPSHOT"] = json.dumps(snapshot, separators=(",", ":"))
    return BudgetPipelinePlan(plan=plan, target=target, snapshot=snapshot)
