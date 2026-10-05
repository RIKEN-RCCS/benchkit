"""Explicit profile bindings and live authorization for Budget-backed submits."""

from __future__ import annotations

import hashlib
import json
import os

from .budget_pipeline import build_budget_pipeline_plan
from .budget_registry import BudgetRegistry, RegistryActor, RegistryError
from .encrypted_sqlite import EncryptedDatabaseError
from .gitlab_pipeline import GITLAB_TARGET_ID_RE, configured_gitlab_target


def profile_fingerprint(profile):
    fields = ("id", "enabled", "status", "activity", "code", "system", "exp",
              "allocation_project_id", "scheduler_extra_args", "valid_from", "valid_until")
    content = {key: profile.get(key) for key in fields}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def has_budget_binding(profile):
    metadata = (profile or {}).get("metadata_json") or {}
    return (not isinstance(metadata, dict) or "budget_binding" in metadata
            or "_invalid_metadata_json" in metadata)


def selection_fingerprint(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_budget_pipeline_capability(target, ref):
    """Fail closed until an operator enables a snapshot-capable target/ref."""
    try:
        capabilities = json.loads(os.environ.get("RESULT_SERVER_BUDGET_PIPELINE_TARGET_REFS", "{}"))
        if not isinstance(capabilities, dict):
            raise ValueError
        if any(not GITLAB_TARGET_ID_RE.fullmatch(name) or not isinstance(refs, list)
               or not all(isinstance(item, str) and item for item in refs)
               for name, refs in capabilities.items()):
            raise ValueError
        for name, refs in capabilities.items():
            configured, errors = configured_gitlab_target(name)
            if (configured and not errors and configured.repo.removesuffix(".git") == target.repo
                    and configured.token_env == target.token_env and ref in refs):
                return
    except (ValueError, TypeError, AttributeError):
        pass
    raise RegistryError("Budget submission is not enabled for this target and ref")


def configured_registry(config=None):
    source = os.environ if config is None else config
    path = source.get("RESULT_SERVER_BUDGET_DB_PATH") if config is None else source.get("BUDGET_REGISTRY_DB_PATH")
    key = source.get("RESULT_SERVER_BUDGET_DB_KEY_FILE") if config is None else source.get("BUDGET_REGISTRY_KEY_FILE")
    if not path or not key:
        raise RegistryError("Budget registry is unavailable")
    return BudgetRegistry(path, key)


def current_actor(principal, users=None):
    try:
        if users is None:
            import redis
            from .user_store import UserStore

            prefix = os.environ.get("RESULT_SERVER_REDIS_PREFIX")
            if not prefix:
                raise RegistryError("Identity namespace must be configured")
            connection = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                                        decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
            try:
                return current_actor(principal, UserStore(connection, prefix))
            finally:
                connection.close()
        if not principal or not users.user_exists(principal):
            raise RegistryError("Budget authorizing identity is unavailable")
        return RegistryActor(principal, "admin" in users.get_affiliations(principal))
    except Exception:
        raise RegistryError("Budget authorizing identity is unavailable") from None


def prepare_binding(profile, registry, actor, destination_id, revision):
    result = build_budget_pipeline_plan(registry=registry, actor=actor, destination_id=destination_id,
                                       expected_revision=revision, profile=profile, target_ref="develop",
                                       result_server_url="")
    if profile.get("system") != result.snapshot["route"]["systems"]:
        raise RegistryError("Budget selection requires one matching profile system")
    return dict(version=1, selected_by=actor.principal, profile_fingerprint=profile_fingerprint(profile),
                snapshot=result.snapshot)


def build_bound_profile_plan(profile, *, target_ref, result_server_url, registry=None, users=None,
                             actor=None, code="", system=""):
    try:
        binding = (profile or {}).get("metadata_json", {}).get("budget_binding")
        if not isinstance(binding, dict) or binding.get("version") != 1:
            raise RegistryError("Budget binding requires review")
        if binding.get("profile_fingerprint") != profile_fingerprint(profile):
            raise RegistryError("Profile changed; review its Budget selection")
        selected = binding["snapshot"]
        registry = registry or configured_registry()
        grant_actor = current_actor(binding["selected_by"], users)
        resolved = registry.resolve(grant_actor, selected["destination_id"])
        result = build_budget_pipeline_plan(
            registry=registry, actor=actor or grant_actor, destination_id=selected["destination_id"],
            expected_revision=resolved["registry_revision"], profile=profile, target_ref=target_ref,
            result_server_url=result_server_url, code=code)
        # Unrelated registry edits do not invalidate a reviewed destination.
        for key in ("budget_id", "destination_id", "target", "route"):
            if result.snapshot[key] != selected[key]:
                raise RegistryError("Budget execution settings changed; review the selection")
        if system and system != resolved["system"]:
            raise RegistryError("Requested system differs from the selected Budget")
        return result
    except (KeyError, TypeError, ValueError, AttributeError, EncryptedDatabaseError):
        raise RegistryError("Budget selection is unavailable or requires review") from None
