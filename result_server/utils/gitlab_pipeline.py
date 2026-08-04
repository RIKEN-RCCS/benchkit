"""GitLab Pipeline API request planning helpers for Portal-triggered runs."""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any


GITLAB_REPO_RE = re.compile(r"^[A-Za-z0-9_.:-]+/[A-Za-z0-9_.~/:-]+(?:\\.git)?$")


@dataclass(frozen=True)
class GitLabPipelinePlan:
    """A dry-run representation of a GitLab Pipeline API request."""

    api_url: str
    payload: dict[str, Any]
    errors: list[str]
    warnings: list[str]


def configured_gitlab_repo(env: dict[str, str] | None = None) -> str:
    """Return the configured host/path GitLab repo for Portal submits."""
    source = env if env is not None else os.environ
    return (
        source.get("RESULT_SERVER_GITLAB_REPO", "").strip()
        or source.get("GITLAB_REPO", "").strip()
    )


def _split_gitlab_repo(repo: str) -> tuple[str, str] | None:
    if not repo or "://" in repo or not GITLAB_REPO_RE.match(repo):
        return None
    normalized = repo.removesuffix(".git")
    host, project_path = normalized.split("/", 1)
    if not host or not project_path:
        return None
    return host, project_path


def _add_variable(variables: list[dict[str, str]], key: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    variables.append({"key": key, "value": text, "variable_type": "env_var"})


def _scheduler_extra_args_key(system: str) -> str:
    system_key = re.sub(r"[^A-Za-z0-9_]", "_", system)
    return f"BK_SCHEDULER_EXTRA_ARGS_{system_key}" if system_key else "BK_SCHEDULER_EXTRA_ARGS"


def build_pipeline_plan(
    *,
    gitlab_repo: str,
    target_ref: str,
    code: str = "",
    system: str = "",
    app: str = "",
    benchpark: bool = False,
    park_only: bool = False,
    park_send: bool = False,
    scheduler_extra_args: str = "",
) -> GitLabPipelinePlan:
    """Build the GitLab Pipeline API URL and JSON payload without sending it."""
    errors: list[str] = []
    warnings: list[str] = []
    ref = target_ref.strip() or "develop"
    split_repo = _split_gitlab_repo(gitlab_repo)
    api_url = ""
    if split_repo is None:
        errors.append(
            "RESULT_SERVER_GITLAB_REPO or GITLAB_REPO must be host/path format"
        )
    else:
        host, project_path = split_repo
        encoded_project = urllib.parse.quote(project_path, safe="")
        api_url = f"https://{host}/api/v4/projects/{encoded_project}/pipeline"

    variables: list[dict[str, str]] = []
    _add_variable(variables, "code", code)
    _add_variable(variables, "system", system)
    _add_variable(variables, "app", app)
    if benchpark:
        _add_variable(variables, "benchpark", "true")
    if park_only:
        _add_variable(variables, "park_only", "true")
    if park_send:
        _add_variable(variables, "park_send", "true")
    if scheduler_extra_args:
        if system and "," not in system:
            _add_variable(variables, _scheduler_extra_args_key(system), scheduler_extra_args)
        else:
            _add_variable(variables, "BK_SCHEDULER_EXTRA_ARGS", scheduler_extra_args)
            if not system:
                warnings.append(
                    "scheduler extra args are not scoped to a single system"
                )

    return GitLabPipelinePlan(
        api_url=api_url,
        payload={"ref": ref, "variables": variables},
        errors=errors,
        warnings=warnings,
    )
