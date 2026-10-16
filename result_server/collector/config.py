"""Explicit private Collector configuration; no CX environment or secret values."""

from dataclasses import dataclass, field
import json
from pathlib import Path

from utils.runner_observation_protocol import SourcePolicy, TargetSpec
from .errors import DeliveryError
from .gitlab import MonitorTarget, ObservationError, RUNNER_TYPES, validate_target
from .state import _object, _read, private_directory
from .transport import validate_endpoint


@dataclass(frozen=True)
class Configuration:
    policy: SourcePolicy
    endpoint: str
    state_directory: Path = field(repr=False)
    key_file: Path = field(repr=False)
    targets: tuple[MonitorTarget, ...] = field(repr=False)


def _path(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError
    return Path(value)


def load_configuration(path):
    try:
        path = _path(str(path))
        with private_directory(path.parent) as directory:
            value = json.loads(_read(directory, path.name, 1024 * 1024), object_pairs_hook=_object)
        if (not isinstance(value, dict) or set(value) != {
                "schema_version", "collector_id", "source_id", "generation", "endpoint",
                "state_directory", "key_file", "targets"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or not isinstance(value["targets"], list) or not 0 < len(value["targets"]) <= 100):
            raise ValueError
        targets, specs = [], []
        key = _path(value["key_file"])
        for item in value["targets"]:
            if (not isinstance(item, dict) or not {
                    "target_id", "server_id", "server_url", "project", "token_file"} <= set(item)
                    or set(item) - {"target_id", "server_id", "server_url", "project", "token_file", "runner_types"}):
                raise ValueError
            kinds = item.get("runner_types", sorted(RUNNER_TYPES))
            if not isinstance(kinds, list) or any(not isinstance(kind, str) for kind in kinds):
                raise ValueError
            target = MonitorTarget(item["target_id"], item["server_url"], item["project"],
                                   _path(item["token_file"]), frozenset(kinds))
            validate_target(target)
            if target.token_file == key:
                raise ValueError
            targets.append(target)
            specs.append(TargetSpec(target.id, item["server_id"], target.server, target.project, target.runner_types))
        policy = SourcePolicy(value["collector_id"], value["source_id"], value["generation"], tuple(specs))
        return Configuration(policy, validate_endpoint(value["endpoint"]), _path(value["state_directory"]),
                             key, tuple(targets))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError,
            DeliveryError, ObservationError):
        raise DeliveryError("invalid_collector_configuration") from None
