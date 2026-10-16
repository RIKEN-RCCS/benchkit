"""Dedicated observation credentials and scopes; never use ingest/proxy auth."""

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

from .gitlab_pipeline import configured_gitlab_targets
from .runner_observation_protocol import ProtocolError, RUNNER_TYPES, SourcePolicy, TargetSpec


class ObservationConfigurationError(ValueError):
    def __init__(self):
        super().__init__("observation_configuration_unavailable")


@dataclass(frozen=True)
class ObservationSource:
    policy: SourcePolicy
    key_sha256: str = field(repr=False)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ObservationConfigurationError()
        result[key] = value
    return result


def configured_observation_sources(env, *, forbidden_keys=()):
    """Resolve explicit scopes from the existing target catalog, without I/O."""
    try:
        raw = env.get("RESULT_SERVER_RUNNER_OBSERVATION_SOURCES", "")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1024 * 1024:
            raise ValueError
        settings = json.loads(raw, object_pairs_hook=_object)
        if not isinstance(settings, dict) or not 0 < len(settings) <= 100:
            raise ValueError
        catalog, errors = configured_gitlab_targets(env)
        if errors:
            raise ValueError
        catalog = {target.id: target for target in catalog}
        forbidden_hashes = {hashlib.sha256(key.encode("utf-8")).hexdigest() for key in forbidden_keys}
        sources, hashes, target_ids, servers = [], set(), set(), set()
        for source_id, spec in settings.items():
            if not isinstance(spec, dict) or set(spec) != {"collector_id", "generation", "key_sha256", "targets"}:
                raise ValueError
            digest = spec["key_sha256"]
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or digest in hashes or digest in forbidden_hashes or not isinstance(spec["targets"], list)):
                raise ValueError
            hashes.add(digest)
            targets = []
            for item in spec["targets"]:
                if (not isinstance(item, dict) or not {"target_id", "server_id"} <= set(item)
                        or set(item) - {"target_id", "server_id", "runner_types"}):
                    raise ValueError
                repo = catalog[item["target_id"]].repo.removesuffix(".git")
                if "://" in repo:
                    raise ValueError
                parsed = urlsplit("https://" + repo)
                if parsed.query or parsed.fragment:
                    raise ValueError
                kinds = item.get("runner_types", sorted(RUNNER_TYPES))
                if not isinstance(kinds, list) or any(not isinstance(kind, str) for kind in kinds):
                    raise ValueError
                targets.append(TargetSpec(item["target_id"], item["server_id"],
                                          "https://" + parsed.netloc.lower(), parsed.path.removeprefix("/"),
                                          frozenset(kinds)))
            policy = SourcePolicy(spec["collector_id"], source_id, spec["generation"], tuple(targets))
            owned_targets = {target.target_id for target in targets}
            owned_servers = {target.server_url for target in targets}
            if target_ids & owned_targets or servers & owned_servers:
                raise ValueError
            target_ids.update(owned_targets)
            servers.update(owned_servers)
            sources.append(ObservationSource(policy, digest))
        return tuple(sources)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ObservationConfigurationError() from None


def authenticate_observation_key(presented, sources):
    """Return a configured policy, not any identity claimed by the request body."""
    if not isinstance(presented, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", presented):
        raise ProtocolError("invalid_collector_key", 401)
    digest = hashlib.sha256(presented.encode("ascii")).hexdigest()
    selected = None
    for source in sources:
        if hmac.compare_digest(source.key_sha256, digest):
            selected = source.policy
    if selected is None:
        raise ProtocolError("invalid_collector_key", 401)
    return selected
