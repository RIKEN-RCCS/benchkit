"""GitLab Pipeline API request planning helpers for Portal-triggered runs."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
import urllib.request
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


@dataclass(frozen=True)
class GitLabPipelineSubmitResult:
    """Result of submitting a GitLab Pipeline API request."""

    status_code: int
    response: dict[str, Any]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300 and not self.errors


def configured_gitlab_repo(env: dict[str, str] | None = None) -> str:
    """Return the configured host/path GitLab repo for Portal submits."""
    source = env if env is not None else os.environ
    return (
        source.get("RESULT_SERVER_GITLAB_REPO", "").strip()
        or source.get("GITLAB_REPO", "").strip()
    )


def configured_gitlab_token(env: dict[str, str] | None = None) -> str:
    """Return the configured GitLab API token for Portal submits."""
    source = env if env is not None else os.environ
    return source.get("RESULT_SERVER_GITLAB_TOKEN", "").strip()


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


def submit_pipeline_plan(
    plan: GitLabPipelinePlan,
    *,
    token: str,
    timeout: float = 20.0,
    urlopen=urllib.request.urlopen,
) -> GitLabPipelineSubmitResult:
    """Submit a planned GitLab Pipeline API request."""
    errors = list(plan.errors)
    if not token:
        errors.append("RESULT_SERVER_GITLAB_TOKEN is not set")
    if not plan.api_url:
        errors.append("GitLab Pipeline API URL is not configured")
    if errors:
        return GitLabPipelineSubmitResult(status_code=0, response={}, errors=errors)

    body = json_dumps_bytes(plan.payload)
    request = urllib.request.Request(
        plan.api_url,
        data=body,
        headers={
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = int(response.getcode())
            payload = _decode_json_response(response.read())
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        payload = _decode_json_response(exc.read())
        return GitLabPipelineSubmitResult(
            status_code=status_code,
            response=payload,
            errors=[f"GitLab Pipeline API returned HTTP {status_code}"],
        )
    except urllib.error.URLError as exc:
        return GitLabPipelineSubmitResult(
            status_code=0,
            response={},
            errors=[f"GitLab Pipeline API request failed: {exc.reason}"],
        )
    except TimeoutError:
        return GitLabPipelineSubmitResult(
            status_code=0,
            response={},
            errors=["GitLab Pipeline API request timed out"],
        )

    errors = []
    if not 200 <= status_code < 300:
        errors.append(f"GitLab Pipeline API returned HTTP {status_code}")
    return GitLabPipelineSubmitResult(
        status_code=status_code,
        response=payload,
        errors=errors,
    )


def json_dumps_bytes(payload: dict[str, Any]) -> bytes:
    """Encode a JSON payload for urllib."""
    import json

    return json.dumps(payload).encode("utf-8")


def _decode_json_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    import json

    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw.decode("utf-8", errors="replace")}
    return decoded if isinstance(decoded, dict) else {"response": decoded}
