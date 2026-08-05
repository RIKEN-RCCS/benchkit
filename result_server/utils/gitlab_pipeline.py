"""GitLab pipeline trigger request planning helpers for Portal-triggered runs."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


GITLAB_REPO_RE = re.compile(r"^[A-Za-z0-9_.:-]+/[A-Za-z0-9_.~/:-]+(?:\\.git)?$")
GITLAB_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class GitLabPipelineTarget:
    """Configured GitLab pipeline destination."""

    id: str
    repo: str
    token_env: str


@dataclass(frozen=True)
class GitLabPipelinePlan:
    """A dry-run representation of a GitLab pipeline trigger request."""

    api_url: str
    payload: dict[str, Any]
    errors: list[str]
    warnings: list[str]
    target_id: str = ""


@dataclass(frozen=True)
class GitLabPipelineSubmitResult:
    """Result of submitting a GitLab pipeline trigger request."""

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


def _target_token_env(target_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "_", target_id).upper()
    return f"RESULT_SERVER_GITLAB_TRIGGER_TOKEN_{normalized}"


def configured_gitlab_targets(
    env: dict[str, str] | None = None,
) -> tuple[list[GitLabPipelineTarget], list[str]]:
    """Return configured GitLab pipeline targets and validation errors."""
    source = env if env is not None else os.environ
    raw_targets = source.get("RESULT_SERVER_GITLAB_TARGETS", "").strip()
    targets: list[GitLabPipelineTarget] = []
    errors: list[str] = []
    seen: set[str] = set()

    if raw_targets:
        for chunk in raw_targets.replace("\n", ",").split(","):
            entry = chunk.strip()
            if not entry:
                continue
            if "=" not in entry:
                errors.append(
                    "RESULT_SERVER_GITLAB_TARGETS entries must use target=host/path"
                )
                continue
            target_id, repo = [part.strip() for part in entry.split("=", 1)]
            if not GITLAB_TARGET_ID_RE.match(target_id):
                errors.append(f"invalid GitLab target id: {target_id}")
                continue
            if target_id in seen:
                errors.append(f"duplicate GitLab target id: {target_id}")
                continue
            seen.add(target_id)
            targets.append(
                GitLabPipelineTarget(
                    id=target_id,
                    repo=repo,
                    token_env=_target_token_env(target_id),
                )
            )
        return targets, errors

    repo = configured_gitlab_repo(source)
    if repo:
        targets.append(
            GitLabPipelineTarget(
                id="default",
                repo=repo,
                token_env="RESULT_SERVER_GITLAB_TRIGGER_TOKEN",
            )
        )
    return targets, errors


def configured_gitlab_target(
    target_id: str = "",
    env: dict[str, str] | None = None,
) -> tuple[GitLabPipelineTarget | None, list[str]]:
    """Return the selected GitLab target, defaulting to the first configured target."""
    targets, errors = configured_gitlab_targets(env)
    if errors:
        return None, errors
    if not targets:
        return None, ["RESULT_SERVER_GITLAB_REPO or RESULT_SERVER_GITLAB_TARGETS is not set"]

    selected = target_id.strip()
    if not selected:
        return targets[0], []

    for target in targets:
        if target.id == selected:
            return target, []
    return None, [f"unknown GitLab target: {selected}"]


def configured_gitlab_trigger_token(
    target: GitLabPipelineTarget | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Return the configured GitLab trigger token for Portal submits."""
    source = env if env is not None else os.environ
    if target is not None:
        token = source.get(target.token_env, "").strip()
        if token:
            return token
        if target.token_env != "RESULT_SERVER_GITLAB_TRIGGER_TOKEN":
            return ""
    return source.get("RESULT_SERVER_GITLAB_TRIGGER_TOKEN", "").strip()


def _split_gitlab_repo(repo: str) -> tuple[str, str] | None:
    if not repo or "://" in repo or not GITLAB_REPO_RE.match(repo):
        return None
    normalized = repo.removesuffix(".git")
    host, project_path = normalized.split("/", 1)
    if not host or not project_path:
        return None
    return host, project_path


def _add_variable(variables: dict[str, str], key: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    variables[key] = text


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
    target_id: str = "",
) -> GitLabPipelinePlan:
    """Build the GitLab trigger API URL and form-like payload without sending it."""
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
        api_url = f"https://{host}/api/v4/projects/{encoded_project}/trigger/pipeline"

    variables: dict[str, str] = {}
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
        target_id=target_id,
    )


def submit_pipeline_plan(
    plan: GitLabPipelinePlan,
    *,
    token: str,
    timeout: float = 20.0,
    urlopen=urllib.request.urlopen,
) -> GitLabPipelineSubmitResult:
    """Submit a planned GitLab trigger API request."""
    errors = list(plan.errors)
    if not token:
        if plan.target_id:
            errors.append(f"GitLab trigger token is not set for target: {plan.target_id}")
        else:
            errors.append("RESULT_SERVER_GITLAB_TRIGGER_TOKEN is not set")
    if not plan.api_url:
        errors.append("GitLab trigger API URL is not configured")
    if errors:
        return GitLabPipelineSubmitResult(status_code=0, response={}, errors=errors)

    form_fields = _trigger_form_fields(plan.payload, token)
    body = urllib.parse.urlencode(form_fields).encode("utf-8")
    request = urllib.request.Request(
        plan.api_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
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
            errors=[f"GitLab trigger API returned HTTP {status_code}"],
        )
    except urllib.error.URLError as exc:
        return GitLabPipelineSubmitResult(
            status_code=0,
            response={},
            errors=[f"GitLab trigger API request failed: {exc.reason}"],
        )
    except TimeoutError:
        return GitLabPipelineSubmitResult(
            status_code=0,
            response={},
            errors=["GitLab trigger API request timed out"],
        )

    errors = []
    if not 200 <= status_code < 300:
        errors.append(f"GitLab trigger API returned HTTP {status_code}")
    return GitLabPipelineSubmitResult(
        status_code=status_code,
        response=payload,
        errors=errors,
    )


def _trigger_form_fields(payload: dict[str, Any], token: str) -> dict[str, str]:
    """Convert a dry-run payload into GitLab trigger API form fields."""
    fields = {
        "token": token,
        "ref": str(payload.get("ref", "")),
    }
    variables = payload.get("variables", {})
    if isinstance(variables, dict):
        for key, value in variables.items():
            fields[f"variables[{key}]"] = str(value)
    return fields


def _decode_json_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    import json

    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw.decode("utf-8", errors="replace")}
    return decoded if isinstance(decoded, dict) else {"response": decoded}
