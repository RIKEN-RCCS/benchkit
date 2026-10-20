"""Benchpark-specific profile, pipeline and result adapters for the Portal."""

import json
import os
import re
import urllib.parse


def normalize_pipeline_config(raw):
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["pipeline configuration must be an object"]
    backend = raw.get("backend", "benchkit")
    if backend not in ("benchkit", "benchpark"):
        return {}, ["pipeline backend must be benchkit or benchpark"]
    if backend == "benchkit":
        if any(raw.get(k) for k in ("site", "experiment_config", "gitlab_target")):
            return {}, ["Benchpark inputs require the benchpark backend"]
        return {}, []
    config = {key: str(raw.get(key) or "").strip() for key in
              ("site", "experiment_config", "gitlab_target")}
    config["backend"] = backend
    errors = []
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", config["site"]):
        errors.append("Benchpark SITE must be a site configuration name")
    if not re.fullmatch(r"config/experiments/[A-Za-z0-9][A-Za-z0-9_-]*\.ya?ml", config["experiment_config"]):
        errors.append("Benchpark EXPERIMENT_CONFIG must be a file under config/experiments")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", config["gitlab_target"]):
        errors.append("Benchpark requires an explicit GitLab target")
    return config, errors


def result_pipeline_backend(result):
    """Use recorded producer metadata; an absent producer remains unknown."""
    backend = result.get("execution_backend")
    if isinstance(backend, str) and backend.strip():
        return backend.strip()
    build = result.get("build")
    harness = build.get("harness") if isinstance(build, dict) else None
    if isinstance(harness, dict) and harness.get("name") == "benchpark":
        return "benchpark"
    return ""


def profile_pipeline_config(profile):
    """Read stored metadata defensively; malformed metadata must block execution."""
    metadata = (profile or {}).get("metadata_json", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        return {}, ["Profile metadata must be an object and requires review"]
    return normalize_pipeline_config(metadata.get("pipeline"))


def build_benchpark_profile_plan(*, profile, allocation_project_id, gitlab_repo, target_ref,
                                result_server_url, target_id="", code="", system=""):
    """Return a Benchpark/error plan, or None for the existing Benchkit planner."""
    from .gitlab_pipeline import build_pipeline_plan, profile_scope_csv, _add_variable

    config, errors = profile_pipeline_config(profile)
    metadata = (profile or {}).get("metadata_json")
    metadata = metadata if isinstance(metadata, dict) else {}
    try:
        backends = json.loads(os.environ.get("RESULT_SERVER_GITLAB_TARGET_BACKENDS", "{}"))
        if not isinstance(backends, dict) or any(
            not isinstance(key, str) or value not in ("benchkit", "benchpark")
            for key, value in backends.items()
        ):
            raise ValueError
    except (ValueError, TypeError):
        backends = {}
        errors.append("RESULT_SERVER_GITLAB_TARGET_BACKENDS must map targets to benchkit or benchpark")
    backend = config.get("backend", "benchkit")
    if backends.get(target_id, "benchkit") != backend:
        errors.append("Profile pipeline backend does not match the configured GitLab target")
    if backend == "benchpark":
        if target_id != config["gitlab_target"]:
            errors.append("Benchpark GitLab target differs from the profile selection")
        if not target_ref.strip():
            errors.append("Benchpark requires an explicit target ref")
        if allocation_project_id or (profile or {}).get("scheduler_extra_args"):
            errors.append("Benchpark allocation and scheduler overrides require a supported execution route")
        if "budget_binding" in metadata:
            errors.append("Benchpark Budget routes are not supported")
        if code and code != profile_scope_csv(profile, "code"):
            errors.append("Benchpark application selection comes from EXPERIMENT_CONFIG")
        if system and system != profile_scope_csv(profile, "system"):
            errors.append("Benchpark system selection comes from SITE")
        plan = build_pipeline_plan(gitlab_repo=gitlab_repo, target_ref=target_ref, target_id=target_id)
        plan.errors.extend(errors)
        variables = plan.payload["variables"]
        variables.update(SITE=config["site"], EXPERIMENT_CONFIG=config["experiment_config"],
                         BK_PIPELINE_BACKEND="benchpark", BK_PORTAL_MANAGED="1")
        _add_variable(variables, "BK_EXECUTION_ACTIVITY", str((profile or {}).get("activity") or ""))
        try:
            endpoint = urllib.parse.urlsplit(result_server_url)
            valid_endpoint = (endpoint.scheme == "https" and endpoint.hostname
                              and not endpoint.username and not endpoint.password
                              and not endpoint.query and not endpoint.fragment
                              and not any(c.isspace() for c in result_server_url))
        except ValueError:
            valid_endpoint = False
        if not valid_endpoint:
            plan.errors.append("Benchpark requires an explicit HTTPS result server URL")
        _add_variable(variables, "BK_PORTAL_RESULT_SERVER", result_server_url)
        return plan
    if errors:
        plan = build_pipeline_plan(gitlab_repo=gitlab_repo, target_ref=target_ref, target_id=target_id)
        plan.errors.extend(errors)
        return plan
    return None


def parse_benchpark_profile_form(form):
    if "pipeline_backend" not in form:
        return {}
    return {"pipeline": {
        "backend": form.get("pipeline_backend", "benchkit"),
        "site": form.get("benchpark_site", ""),
        "experiment_config": form.get("benchpark_experiment_config", ""),
        "gitlab_target": form.get("benchpark_gitlab_target", ""),
    }}


def benchpark_manual_errors(profile, form):
    from .gitlab_pipeline import profile_scope_csv

    config, _errors = profile_pipeline_config(profile)
    if config.get("backend") != "benchpark":
        return []
    errors = []
    if not form.get("target_ref", "").strip():
        errors.append("Benchpark requires an explicit target ref")
    exp = form.get("exp", "").strip()
    if exp and exp != profile_scope_csv(profile, "exp"):
        errors.append("Benchpark experiment selection comes from EXPERIMENT_CONFIG")
    return errors


def benchpark_detail_rows(result):
    if result_pipeline_backend(result) != "benchpark":
        return []
    rows = [("Execution Backend", "benchpark")]
    for label, key in (("Activity", "execution_activity"), ("CI Project", "ci_project")):
        if result.get(key):
            rows.append((label, result[key]))
    return rows


def benchpark_run_context(variables):
    if variables.get("BK_PIPELINE_BACKEND") != "benchpark":
        return {}
    return {"code": variables.get("EXPERIMENT_CONFIG"), "system": variables.get("SITE"),
            "result_server": variables.get("BK_PORTAL_RESULT_SERVER")}
