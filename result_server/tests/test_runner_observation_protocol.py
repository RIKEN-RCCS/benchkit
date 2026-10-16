"""Synthetic, storage-free protocol cases; no live configuration or services."""

import builtins
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import runner_observation_protocol as protocol  # noqa: E402


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
GENERATION = "11111111-1111-4111-8111-111111111111"


def target(name="first", server_id="server", server="https://gitlab.example.org"):
    return protocol.TargetSpec(name, server_id, server, "group/" + name)


def policy(*targets, **overrides):
    return protocol.SourcePolicy(**{
        "collector_id": "collector", "source_id": "source", "generation": GENERATION,
        "targets": targets or (target(),), **overrides,
    })


def summary(runner_id=7, **overrides):
    return {"id": runner_id, "description": "Example", "runner_type": "instance_type",
            "status": "online", "paused": False, **overrides}


def ok(data, at=STAMP):
    return {"status": "ok", "observed_at": at, "data": data}


def error(code="http_403", at=STAMP):
    return {"status": "error", "observed_at": at, "error_code": code}


def runner(runner_id=7, server_id="server"):
    return {"server_id": server_id, "runner_id": runner_id,
            "detail": ok(summary(runner_id, tag_list=["example"], contacted_at=STAMP,
                                 access_level="not_protected", run_untagged=False)),
            "managers": ok([{"id": 3, "system_id": "example-manager", "version": "example",
                             "platform": "linux", "architecture": "arm64", "contacted_at": STAMP,
                             "status": "online"}])}


def batch(sequence=1, **overrides):
    return {"schema_version": 1, "collector_id": "collector", "source_id": "source",
            "generation": GENERATION, "sequence": sequence,
            "batch_id": str(uuid.uuid5(uuid.UUID(GENERATION), str(sequence))),
            "started_at": STAMP, "finished_at": STAMP,
            "targets": [{"target_id": "first", "inventory": ok([summary()])}],
            "runners": [runner()], **overrides}


def raw(value):
    return json.dumps(value).encode()


def apply(previous=None, value=None, scope=None, at=NOW):
    return protocol.apply_batch(previous if previous is not None else {},
                                raw(value if value is not None else batch()),
                                scope or policy(), received_at=at)


def only_runner(snapshot):
    assert len(snapshot["runners"]) == 1
    return next(iter(snapshot["runners"].values()))


def test_first_success_is_compatible_and_does_not_mutate_input():
    previous, value = {"targets": {}, "runners": {}, "extra": "preserved"}, batch()
    before = deepcopy((previous, value))
    update = apply(previous, value)
    assert (previous, value) == before
    assert update.changed and update.acknowledgement["status"] == "accepted"
    assert update.snapshot["extra"] == "preserved"
    observed = only_runner(update.snapshot)
    assert observed["targets"] == ["first"]
    assert observed["detail"]["data"]["tag_list"] == ["example"]
    assert observed["detail"]["last_success_at"] == STAMP
    assert observed["managers"]["error"] == ""
    observed["detail"]["data"]["tag_list"].append("changed")
    assert value["runners"][0]["detail"]["data"]["tag_list"] == ["example"]


@pytest.mark.parametrize("resource", ["inventory", "detail", "managers"])
def test_failure_keeps_last_success_and_recovery_replaces_it(resource):
    previous = apply().snapshot
    value = batch(2)
    if resource == "inventory":
        value["targets"][0][resource] = error()
        value["runners"] = []
    else:
        value["runners"][0][resource] = error()
    updated = apply(previous, value).snapshot
    old = previous["targets"]["first"]["inventory"] if resource == "inventory" else only_runner(previous)[resource]
    failed = updated["targets"]["first"]["inventory"] if resource == "inventory" else only_runner(updated)[resource]
    assert failed["data"] == old["data"]
    assert failed["last_success_at"] == old["last_success_at"]
    assert failed["error"] == "http_403"
    if resource == "inventory":
        assert only_runner(updated)["detail"]["error"] == "inventory_unavailable"
    restored = apply(updated, batch(3)).snapshot
    assert restored["targets"]["first"]["inventory"]["error"] == ""
    assert only_runner(restored)["detail"]["error"] == ""
    assert only_runner(restored)["managers"]["error"] == ""


def test_initial_failure_is_not_observed_not_empty_success():
    snapshot = apply(value=batch(targets=[{"target_id": "first", "inventory": error()}], runners=[])).snapshot
    inventory = snapshot["targets"]["first"]["inventory"]
    assert "data" not in inventory and "last_success_at" not in inventory
    assert inventory["error"] == "http_403" and not snapshot["runners"]


def test_complete_empty_inventory_removes_membership_only_after_success():
    previous = apply().snapshot
    snapshot = apply(previous, batch(2, targets=[{"target_id": "first", "inventory": ok([])}], runners=[])).snapshot
    assert snapshot["targets"]["first"]["inventory"]["data"] == []
    assert not snapshot["runners"] and only_runner(previous)


def test_projects_share_runner_and_failed_project_keeps_membership():
    scope = policy(target(), target("second"))
    value = batch()
    value["targets"].append({"target_id": "second", "inventory": ok([summary(description="second")])})
    previous = apply(value=value, scope=scope).snapshot
    assert only_runner(previous)["targets"] == ["first", "second"]
    assert only_runner(previous)["summary"]["description"] == "Example"
    value = batch(2, targets=[{"target_id": "second", "inventory": error()},
                              {"target_id": "first", "inventory": ok([])}], runners=[])
    snapshot = apply(previous, value, scope).snapshot
    assert only_runner(snapshot)["targets"] == ["second"]
    assert only_runner(snapshot)["detail"]["error"] == "inventory_unavailable"


def test_same_numeric_id_on_two_servers_remains_distinct():
    scope = policy(target(), target("second", "other", "https://other.example.org"))
    value = batch()
    value["targets"].append({"target_id": "second", "inventory": ok([summary()])})
    value["runners"].append(runner(server_id="other"))
    assert len(apply(value=value, scope=scope).snapshot["runners"]) == 2


def test_duplicate_is_idempotent_even_after_delay_and_json_key_reordering():
    first = apply()
    previous = deepcopy(first.snapshot)
    reordered = dict(reversed(list(batch().items())))
    duplicate = apply(previous, reordered, at=NOW + timedelta(days=1))
    assert not duplicate.changed and duplicate.snapshot == previous == first.snapshot
    assert duplicate.acknowledgement["status"] == "duplicate"
    assert duplicate.acknowledgement["received_at"] == first.acknowledgement["received_at"]
    duplicate.snapshot["targets"].clear()
    assert first.snapshot["targets"]


@pytest.mark.parametrize("change, code", [
    (lambda value: value["runners"][0]["detail"]["data"].update(description="different"), "sequence_conflict"),
    (lambda value: value.update(generation="22222222-2222-4222-8222-222222222222"), "generation_mismatch"),
])
def test_conflicting_replay_does_not_mutate_state(change, code):
    previous = apply().snapshot
    before = deepcopy(previous)
    value = batch()
    change(value)
    with pytest.raises(protocol.ProtocolError, match=code) as exc:
        apply(previous, value)
    assert exc.value.status == 409 and previous == before


def test_sequence_gaps_are_allowed_but_old_batches_are_rejected():
    previous = apply(value=batch(5)).snapshot
    updated = apply(previous, batch(9)).snapshot
    assert updated["_ingest"]["source"]["sequence"] == 9
    with pytest.raises(protocol.ProtocolError, match="stale_sequence"):
        apply(updated, batch(5))


def test_policy_change_requires_explicit_state_handoff():
    previous = apply().snapshot
    changed = policy(target("first", server="https://new.example.org"))
    with pytest.raises(protocol.ProtocolError, match="scope_changed"):
        apply(previous, batch(2), changed)
    new_generation = "22222222-2222-4222-8222-222222222222"
    changed = policy(generation=new_generation)
    value = batch(generation=new_generation,
                  batch_id=str(uuid.uuid5(uuid.UUID(new_generation), "1")))
    with pytest.raises(protocol.ProtocolError, match="generation_mismatch"):
        apply(previous, value, changed)


def test_non_overlapping_sources_are_preserved_and_overlapping_servers_are_denied():
    previous = apply().snapshot
    only_runner(previous)["summary"]["description"] = "Preserve the other source's stored summary"
    scope = policy(target("second", "other", "https://other.example.org"), source_id="second-source")
    value = batch(source_id="second-source", targets=[{"target_id": "second", "inventory": ok([summary()])}],
                  runners=[runner(server_id="other")])
    snapshot = apply(previous, value, scope).snapshot
    first_key = next(iter(previous["runners"]))
    assert snapshot["runners"][first_key] == previous["runners"][first_key]
    assert snapshot["_ingest"]["source"] == previous["_ingest"]["source"]
    overlapping = policy(target("second"), source_id="second-source")
    value["runners"] = [runner()]
    with pytest.raises(protocol.ProtocolError, match="scope_denied"):
        apply(previous, value, overlapping)


@pytest.mark.parametrize("corrupt", [
    lambda state: state.update(_ingest=[]),
    lambda state: state["_ingest"].update(source={}),
    lambda state: state["_ingest"].update(source=None),
    lambda state: state["_ingest"]["source"].update(sequence=True),
    lambda state: state["_ingest"]["source"].update(digest="not-a-digest"),
    lambda state: state["_ingest"]["source"].update(identities={}),
    lambda state: state["targets"].update(first="not-an-observation"),
])
def test_corrupt_state_is_not_an_implicit_sequence_reset(corrupt):
    previous = apply().snapshot
    corrupt(previous)
    before = deepcopy(previous)
    with pytest.raises(protocol.ProtocolError, match="^invalid_state$") as exc:
        apply(previous, batch(2))
    assert exc.value.status == 503 and previous == before


def test_manager_limit_is_aggregate_not_only_per_runner(monkeypatch):
    value = batch()
    value["targets"][0]["inventory"]["data"].append(summary(8))
    value["runners"].append(runner(8))
    monkeypatch.setattr(protocol, "MAX_MANAGERS", 1)
    with pytest.raises(protocol.ProtocolError):
        apply(value=value)


def test_clock_skew_and_payload_size_boundaries(monkeypatch):
    scope, data = policy(), raw(batch())
    monkeypatch.setattr(protocol, "MAX_BYTES", len(data))
    assert protocol.validate_batch(data, scope, received_at=NOW - timedelta(minutes=5))
    monkeypatch.setattr(protocol, "MAX_BYTES", len(data) - 1)
    with pytest.raises(protocol.ProtocolError, match="payload_too_large") as exc:
        protocol.validate_batch(data, scope, received_at=NOW)
    assert exc.value.status == 413


def test_previous_target_with_different_identity_is_not_reused():
    previous = apply().snapshot
    previous.pop("_ingest")
    previous["targets"]["first"]["identity"]["project"] = "group/old"
    value = batch(targets=[{"target_id": "first", "inventory": error()}], runners=[])
    snapshot = apply(previous, value).snapshot
    assert "data" not in snapshot["targets"]["first"]["inventory"]
    assert not snapshot["runners"]


def test_snapshot_preserves_existing_presentation_semantics():
    from utils.runner_observations import presentation

    previous = apply().snapshot
    current = presentation(previous, now=NOW)
    assert current["targets"][0]["state"] == "current"
    assert current["runners"][0]["heartbeat"] == "online"
    assert current["runners"][0]["record"]["tag_list"] == ["example"]
    failed = apply(previous, batch(2, targets=[{"target_id": "first", "inventory": error()}],
                                    runners=[])).snapshot
    unavailable = presentation(failed, now=NOW)
    assert unavailable["targets"][0]["state"] == "unavailable"
    assert unavailable["runners"][0]["heartbeat"] == "unknown"
    expired = presentation(previous, now=NOW + timedelta(hours=1))
    assert expired["runners"][0]["state"] == "expired"
    assert expired["runners"][0]["heartbeat"] == "unknown"


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(secret="not-allowed"),
    lambda b: b.update(schema_version=True),
    lambda b: b.update(schema_version=2),
    lambda b: b.update(sequence=True),
    lambda b: b.update(sequence=0),
    lambda b: b.update(sequence=2**53),
    lambda b: b.update(batch_id=str(uuid.uuid4())),
    lambda b: b.update(targets=[]),
    lambda b: b["targets"].append(deepcopy(b["targets"][0])),
    lambda b: b["targets"][0]["inventory"]["data"].append(summary()),
    lambda b: b["targets"][0]["inventory"]["data"][0].update(id=True),
    lambda b: b["targets"][0]["inventory"]["data"][0].update(runner_type="unexpected"),
    lambda b: b["targets"][0]["inventory"]["data"][0].update(paused=1),
    lambda b: b.update(runners=[]),
    lambda b: b["runners"].append(deepcopy(b["runners"][0])),
    lambda b: b["runners"][0]["detail"]["data"].update(id=8),
    lambda b: b["runners"][0]["detail"]["data"].update(run_untagged=1),
    lambda b: b["runners"][0]["detail"]["data"].update(tag_list=[1]),
    lambda b: b["runners"][0]["detail"]["data"].update(tag_list=["x"] * 1001),
    lambda b: b["runners"][0]["detail"]["data"].update(description="x" * 2049),
    lambda b: b["runners"][0]["detail"]["data"].update(description="\ud800"),
    lambda b: b["runners"][0]["detail"].update(token="forbidden"),
    lambda b: b["runners"][0].update(managers=error("private-response-body")),
    lambda b: b["runners"][0]["managers"]["data"].append(deepcopy(b["runners"][0]["managers"]["data"][0])),
    lambda b: b["runners"][0]["managers"]["data"][0].update(id=False),
    lambda b: b["runners"][0]["detail"].update(status="error", error_code="http_403"),
    lambda b: b.update(started_at="2026-01-01T12:00:01Z"),
    lambda b: b.update(finished_at="2026-01-01T11:59:59Z"),
    lambda b: b["targets"][0]["inventory"].update(observed_at="2026-01-01T12:00:01Z"),
    lambda b: b["runners"][0]["detail"]["data"].update(contacted_at="2026-01-01T12:00:00"),
])
def test_invalid_payload_is_value_free_and_leaves_previous_unchanged(mutate):
    previous = apply().snapshot
    before = deepcopy(previous)
    value = batch(2)
    mutate(value)
    with pytest.raises(protocol.ProtocolError) as exc:
        apply(previous, value)
    assert exc.value.code in {"invalid_payload", "unsupported_schema"}
    assert str(exc.value) == exc.value.code and previous == before


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(collector_id="other"),
    lambda b: b.update(source_id="other"),
    lambda b: b["targets"][0].update(target_id="other"),
    lambda b: b["runners"][0].update(server_id="other"),
    lambda b: b["runners"][0].update(runner_id=8),
])
def test_scope_is_bound_to_server_configuration(mutate):
    value = batch()
    mutate(value)
    with pytest.raises(protocol.ProtocolError) as exc:
        apply(value=value)
    assert exc.value.status == 403 and exc.value.code == "scope_denied"


@pytest.mark.parametrize("body", [
    b'{"schema_version":1,"schema_version":1}',
    b'{"nested":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":-Infinity}', b'\xff', b'{', b'[]', b'null', b'[' * 2000,
])
def test_invalid_json_is_fixed_error(body):
    with pytest.raises(protocol.ProtocolError):
        protocol.validate_batch(body, policy(), received_at=NOW)


@pytest.mark.parametrize("limit", ["MAX_BYTES", "MAX_TARGETS", "MAX_RUNNERS", "MAX_MANAGERS"])
def test_limits_reject_overflow(monkeypatch, limit):
    scope = policy()
    monkeypatch.setattr(protocol, limit, 0)
    with pytest.raises(protocol.ProtocolError):
        protocol.validate_batch(raw(batch()), scope, received_at=NOW)


def test_time_normalization_unknown_heartbeat_and_expired_arrival():
    value = batch()
    value["started_at"] = value["finished_at"] = "2026-01-01T12:00:00Z"
    value["runners"][0]["detail"]["data"].update(status="upstream-new-status", contacted_at=None)
    snapshot = apply(value=value, at=NOW + timedelta(days=3)).snapshot
    record = only_runner(snapshot)["detail"]
    assert record["last_success_at"] == STAMP
    assert record["data"]["status"] == "unknown" and record["data"]["contacted_at"] is None
    with pytest.raises(protocol.ProtocolError, match="clock_skew"):
        apply(at=NOW - timedelta(minutes=6))
    with pytest.raises(protocol.ProtocolError, match="invalid_clock"):
        apply(at=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("overrides", [
    {"source_id": "../source"}, {"generation": "not-uuid"}, {"targets": ()},
    {"targets": (target(), target())},
    {"targets": (target(server="http://gitlab.example.org"),)},
    {"targets": (target(server="https://user:password@gitlab.example.org"),)},
    {"targets": (target(server="https://gitlab.example.org/path"),)},
    {"targets": (target(), target("second", "other"))},
    {"targets": (target(), target("second", server="https://other.example.org"))},
])
def test_invalid_policy_has_no_configuration_values_in_error(overrides):
    with pytest.raises(protocol.ProtocolError, match="^invalid_policy$"):
        policy(**overrides)


def test_pure_operations_need_no_file_network_or_database(monkeypatch):
    scope, data = policy(), raw(batch())

    def forbidden(*_args, **_kwargs):
        pytest.fail("unexpected I/O")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(io, "open", forbidden)
        guard.setattr(os, "open", forbidden)
        guard.setattr(os, "getenv", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        update = protocol.apply_batch({}, data, scope, received_at=NOW)
        duplicate = protocol.apply_batch(update.snapshot, data, scope, received_at=NOW)
        assert update.changed and not duplicate.changed


def test_module_import_does_not_require_cx_or_sqlcipher(monkeypatch):
    name = "isolated_observation_protocol"
    spec = importlib.util.spec_from_file_location(name, protocol.__file__)
    module = importlib.util.module_from_spec(spec)
    original = builtins.__import__

    def limited_import(name, *args, **kwargs):
        assert not name.startswith(("utils", "result_server", "sqlcipher3", "flask"))
        return original(name, *args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setitem(sys.modules, name, module)
        guard.setattr(builtins, "__import__", limited_import)
        spec.loader.exec_module(module)
        assert module.RUNNER_TYPES == protocol.RUNNER_TYPES
