"""Pure validation and snapshot updates for a proposed observation protocol.

No transport, environment, credentials or storage are accessed here. A future
receiver must derive SourcePolicy from authenticated configuration, then commit
the returned snapshot (including its cursor) in one transaction.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
from urllib.parse import urlsplit
import uuid


MAX_BYTES = 4 * 1024 * 1024
MAX_TARGETS = 100
MAX_RUNNERS = 10000
MAX_MANAGERS = 10000
RUNNER_TYPES = frozenset({"instance_type", "group_type", "project_type"})
HEARTBEATS = frozenset({"online", "offline", "stale", "never_contacted", "unknown"})
ERROR_CODES = frozenset({
    "connection_failed", "collection_timeout", "credential_unavailable",
    "response_too_large", "invalid_response", "invalid_pagination",
    "pagination_limit", "duplicate_runner",
})
SUMMARY_FIELDS = {"id", "description", "runner_type", "status", "paused"}
DETAIL_FIELDS = SUMMARY_FIELDS | {"tag_list", "contacted_at", "access_level", "run_untagged"}
MANAGER_FIELDS = {"id", "system_id", "version", "platform", "architecture", "contacted_at", "status"}
ENVELOPE_FIELDS = {
    "schema_version", "collector_id", "source_id", "generation", "sequence",
    "batch_id", "started_at", "finished_at", "targets", "runners",
}


class ProtocolError(ValueError):
    """Fixed codes only; never include rejected values in a diagnostic."""

    def __init__(self, code, status=422):
        super().__init__(code)
        self.code = code
        self.status = status


def _require(condition, code="invalid_payload", status=422):
    if not condition:
        raise ProtocolError(code, status)


def _fields(value, fields):
    _require(isinstance(value, dict) and set(value) == fields)


def _identifier(value):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value))
    return value


def _positive_id(value):
    _require(type(value) is int and 1 <= value <= 2**53 - 1)
    return value


def _uuid(value):
    _require(isinstance(value, str))
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ProtocolError("invalid_payload") from None
    _require(str(parsed) == value)
    return parsed


def _timestamp(value):
    _require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)", value))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ProtocolError("invalid_payload") from None
    return parsed


def _text(value):
    _require(isinstance(value, str) and len(value) <= 2048)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ProtocolError("invalid_payload") from None


@dataclass(frozen=True)
class TargetSpec:
    target_id: str
    server_id: str
    server_url: str
    project: str
    runner_types: frozenset[str] = RUNNER_TYPES

    def identity(self):
        return {"server": self.server_url, "project": self.project,
                "runner_types": sorted(self.runner_types)}


@dataclass(frozen=True)
class SourcePolicy:
    collector_id: str
    source_id: str
    generation: str
    targets: tuple[TargetSpec, ...]

    def __post_init__(self):
        try:
            _identifier(self.collector_id)
            _identifier(self.source_id)
            _uuid(self.generation)
            _require(isinstance(self.targets, tuple) and 0 < len(self.targets) <= MAX_TARGETS)
            ids, servers, urls = set(), {}, {}
            for target in self.targets:
                _require(isinstance(target, TargetSpec))
                _identifier(target.target_id)
                _identifier(target.server_id)
                _require(target.target_id not in ids)
                ids.add(target.target_id)
                parsed = urlsplit(target.server_url)
                _require(not any(character.isspace() for character in target.server_url)
                         and parsed.scheme == "https" and parsed.hostname and not parsed.username
                         and not parsed.password and not parsed.path and not parsed.query
                         and not parsed.fragment and parsed.netloc == parsed.netloc.lower())
                parsed.port
                _require(isinstance(target.project, str) and len(target.project) <= 2048
                         and all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) and part not in (".", "..")
                                 for part in target.project.split("/")))
                _require(isinstance(target.runner_types, frozenset) and target.runner_types
                         and target.runner_types <= RUNNER_TYPES)
                _require(servers.setdefault(target.server_id, target.server_url) == target.server_url)
                _require(urls.setdefault(target.server_url, target.server_id) == target.server_id)
        except (ProtocolError, ValueError, TypeError, AttributeError):
            raise ProtocolError("invalid_policy", 500) from None


@dataclass(frozen=True)
class BatchUpdate:
    snapshot: dict
    acknowledgement: dict
    changed: bool


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "invalid_json", 400)
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ProtocolError("invalid_json", 400)


def _record(value, *, detail=False, manager=False):
    _fields(value, MANAGER_FIELDS if manager else DETAIL_FIELDS if detail else SUMMARY_FIELDS)
    _positive_id(value["id"])
    for name in ("system_id", "version", "platform", "architecture") if manager else ("description",):
        _text(value[name])
    _require(isinstance(value["status"], str))
    if value["status"] not in HEARTBEATS:
        value["status"] = "unknown"
    if not manager:
        _require(isinstance(value["runner_type"], str) and value["runner_type"] in RUNNER_TYPES)
        _require(value["paused"] is None or type(value["paused"]) is bool)
    if detail:
        _require(isinstance(value["tag_list"], list) and len(value["tag_list"]) <= 1000)
        for tag in value["tag_list"]:
            _text(tag)
        _text(value["access_level"])
        _require(value["run_untagged"] is None or type(value["run_untagged"]) is bool)
    if detail or manager:
        if value["contacted_at"] is not None:
            value["contacted_at"] = _timestamp(value["contacted_at"]).isoformat()


def _resource(value, kind, start, finish):
    _require(isinstance(value, dict))
    status = value.get("status")
    _require(status in ("ok", "error"))
    _fields(value, {"status", "observed_at", "data" if status == "ok" else "error_code"})
    observed = _timestamp(value["observed_at"])
    _require(start <= observed <= finish)
    value["observed_at"] = observed.isoformat()
    if status == "error":
        code = value["error_code"]
        _require(isinstance(code, str) and (code in ERROR_CODES or re.fullmatch(r"http_[1-5][0-9]{2}", code)))
        return
    if kind == "detail":
        _record(value["data"], detail=True)
        return
    rows = value["data"]
    _require(isinstance(rows, list) and len(rows) <= (MAX_RUNNERS if kind == "inventory" else MAX_MANAGERS))
    ids = set()
    for row in rows:
        _record(row, manager=kind == "managers")
        _require(row["id"] not in ids)
        ids.add(row["id"])


def validate_batch(raw: bytes, policy: SourcePolicy, *, received_at: datetime) -> dict:
    """Decode and normalize a complete batch against an already authorized scope."""
    _require(type(raw) is bytes, "invalid_json", 400)
    _require(len(raw) <= MAX_BYTES, "payload_too_large", 413)
    _require(isinstance(received_at, datetime) and received_at.tzinfo is not None
             and received_at.utcoffset() == timedelta(0), "invalid_clock", 500)
    try:
        batch = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ProtocolError("invalid_json", 400) from None
    _fields(batch, ENVELOPE_FIELDS)
    _require(type(batch["schema_version"]) is int and batch["schema_version"] == 1, "unsupported_schema")
    for field in ("collector_id", "source_id"):
        _identifier(batch[field])
        _require(batch[field] == getattr(policy, field), "scope_denied", 403)
    generation = _uuid(batch["generation"])
    _require(batch["generation"] == policy.generation, "generation_mismatch", 409)
    sequence = _positive_id(batch["sequence"])
    _require(_uuid(batch["batch_id"]) == uuid.uuid5(generation, str(sequence)))
    start, finish = _timestamp(batch["started_at"]), _timestamp(batch["finished_at"])
    _require(start <= finish)
    _require(finish <= received_at + timedelta(minutes=5), "clock_skew")
    batch.update(started_at=start.isoformat(), finished_at=finish.isoformat())
    _require(isinstance(batch["targets"], list) and len(batch["targets"]) <= MAX_TARGETS)
    targets = {target.target_id: target for target in policy.targets}
    seen, expected = set(), set()
    for target in batch["targets"]:
        _fields(target, {"target_id", "inventory"})
        target_id = _identifier(target["target_id"])
        _require(target_id in targets, "scope_denied", 403)
        _require(target_id not in seen)
        seen.add(target_id)
        _resource(target["inventory"], "inventory", start, finish)
        if target["inventory"]["status"] == "ok":
            spec = targets[target_id]
            for row in target["inventory"]["data"]:
                _require(row["runner_type"] in spec.runner_types)
                expected.add((spec.server_id, row["id"]))
    _require(seen == set(targets) and len(expected) <= MAX_RUNNERS)
    _require(isinstance(batch["runners"], list) and len(batch["runners"]) <= MAX_RUNNERS)
    seen, managers = set(), 0
    for runner in batch["runners"]:
        _fields(runner, {"server_id", "runner_id", "detail", "managers"})
        key = (_identifier(runner["server_id"]), _positive_id(runner["runner_id"]))
        _require(key in expected, "scope_denied", 403)
        _require(key not in seen)
        seen.add(key)
        for resource in ("detail", "managers"):
            _resource(runner[resource], resource, start, finish)
        detail = runner["detail"]
        if detail["status"] == "ok":
            _require(detail["data"]["id"] == key[1])
        if runner["managers"]["status"] == "ok":
            managers += len(runner["managers"]["data"])
    _require(seen == expected and managers <= MAX_MANAGERS)
    return batch


def _observation(previous, resource):
    result = deepcopy(previous or {})
    result["attempted_at"] = resource["observed_at"]
    if resource["status"] == "ok":
        result.update(data=deepcopy(resource["data"]), last_success_at=resource["observed_at"], error="")
    else:
        result["error"] = resource["error_code"]
    return result


def _runner_key(server, runner_id):
    return json.dumps([server, runner_id], separators=(",", ":"))


def _state_cursors(previous):
    try:
        _require(isinstance(previous, dict) and isinstance(previous.get("targets", {}), dict)
                 and isinstance(previous.get("runners", {}), dict)
                 and isinstance(previous.get("_ingest", {}), dict))
        cursors = previous.get("_ingest", {})
        for source_id, cursor in cursors.items():
            _identifier(source_id)
            _fields(cursor, {"collector_id", "generation", "sequence", "batch_id", "digest",
                             "received_at", "identities"})
            _identifier(cursor["collector_id"])
            generation = _uuid(cursor["generation"])
            _positive_id(cursor["sequence"])
            _require(_uuid(cursor["batch_id"]) == uuid.uuid5(generation, str(cursor["sequence"])))
            _require(isinstance(cursor["digest"], str) and re.fullmatch(r"[0-9a-f]{64}", cursor["digest"]))
            _timestamp(cursor["received_at"])
            _require(isinstance(cursor["identities"], dict) and cursor["identities"])
            for target_id, identity in cursor["identities"].items():
                _identifier(target_id)
                _fields(identity, {"server", "project", "runner_types"})
                _text(identity["server"])
                _text(identity["project"])
                _require(isinstance(identity["runner_types"], list) and identity["runner_types"])
                _require(all(isinstance(kind, str) and kind in RUNNER_TYPES
                             for kind in identity["runner_types"]))
        return cursors
    except ProtocolError:
        raise ProtocolError("invalid_state", 503) from None


def apply_batch(previous: dict, raw: bytes, policy: SourcePolicy, *, received_at: datetime) -> BatchUpdate:
    """Return a new snapshot and cursor, without mutating or saving any input."""
    batch = validate_batch(raw, policy, received_at=received_at)
    digest = hashlib.sha256(json.dumps(batch, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()
    identities = {target.target_id: target.identity() for target in policy.targets}
    cursors = _state_cursors(previous)
    cursor = cursors.get(policy.source_id)
    if cursor:
        _require(cursor["generation"] == policy.generation, "generation_mismatch", 409)
        _require(cursor["identities"] == identities and cursor["collector_id"] == policy.collector_id,
                 "scope_changed", 409)
        _require(batch["sequence"] >= cursor["sequence"], "stale_sequence", 409)
        if batch["sequence"] == cursor["sequence"]:
            _require(cursor["batch_id"] == batch["batch_id"] and cursor["digest"] == digest,
                     "sequence_conflict", 409)
            return BatchUpdate(deepcopy(previous), _ack(policy, cursor, "duplicate"), False)
    owned_servers = {target.server_url for target in policy.targets}
    for source_id, other in cursors.items():
        if source_id != policy.source_id:
            _require(not (set(other["identities"]) & set(identities))
                     and not any(item["server"] in owned_servers for item in other["identities"].values()),
                     "scope_denied", 403)

    try:
        snapshot = _merge_snapshot(previous, batch, policy, identities, owned_servers)
    except (KeyError, TypeError, AttributeError):
        raise ProtocolError("invalid_state", 503) from None
    cursor = {"collector_id": policy.collector_id, "generation": policy.generation,
              "sequence": batch["sequence"], "batch_id": batch["batch_id"], "digest": digest,
              "received_at": received_at.isoformat(), "identities": identities}
    snapshot.setdefault("_ingest", {})[policy.source_id] = cursor
    return BatchUpdate(snapshot, _ack(policy, cursor, "accepted"), True)


def _merge_snapshot(previous, batch, policy, identities, owned_servers):
    snapshot = deepcopy(previous)
    targets = snapshot.setdefault("targets", {})
    for target in batch["targets"]:
        target_id = target["target_id"]
        old = targets.get(target_id, {})
        if old.get("identity") != identities[target_id]:
            old = {}
        targets[target_id] = {"identity": identities[target_id],
                              "inventory": _observation(old.get("inventory"), target["inventory"])}
    server_urls = {target.server_id: target.server_url for target in policy.targets}
    incoming = {_runner_key(server_urls[row["server_id"]], row["runner_id"]): row for row in batch["runners"]}
    runners = {key: deepcopy(row) for key, row in previous.get("runners", {}).items()
               if row["server"] not in owned_servers}
    for target_id, target in sorted(targets.items()):
        server = target["identity"]["server"]
        if server not in owned_servers:
            continue
        for summary in target["inventory"].get("data", []):
            key = _runner_key(server, summary["id"])
            if key not in runners:
                runners[key] = deepcopy(previous.get("runners", {}).get(key, {}))
                runners[key].update(server=server, id=summary["id"], summary=deepcopy(summary), targets=[])
            runners[key]["targets"].append(target_id)
    for key, runner in runners.items():
        if runner["server"] not in owned_servers:
            continue
        for name in ("detail", "managers"):
            resource = incoming.get(key, {}).get(name, {
                "status": "error", "observed_at": batch["finished_at"], "error_code": "inventory_unavailable",
            })
            runner[name] = _observation(runner.get(name), resource)
    snapshot.update(runners=runners, collected_at=batch["finished_at"])
    return snapshot


def _ack(policy, cursor, status):
    return {"schema_version": 1, "source_id": policy.source_id, "generation": cursor["generation"],
            "sequence": cursor["sequence"], "batch_id": cursor["batch_id"],
            "received_at": cursor["received_at"], "status": status}
