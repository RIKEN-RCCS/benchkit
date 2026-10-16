"""Handoff rehearsal on copies of synthetic encrypted DBs and Collector state."""

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
import uuid

import pytest

pytest.importorskip("sqlcipher3")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector.delivery import run_once  # noqa: E402
from collector.errors import DeliveryError  # noqa: E402
from collector.state import DeliveryState  # noqa: E402
from collector.transport import Response  # noqa: E402
from routes.runner_observation_ingest import register_runner_observation_ingest  # noqa: E402
from utils.encrypted_sqlite import generate_key  # noqa: E402
from utils.runner_observation_auth import ObservationSource  # noqa: E402
from utils.runner_observation_protocol import ProtocolError  # noqa: E402
from utils.runner_observations import RunnerObservations, collect, presentation  # noqa: E402
from test_runner_monitor import FakeClient, target as monitor_target, reset_fake  # noqa: E402, F401
from test_runner_observation_protocol import NOW, batch, error, only_runner, policy, raw, target  # noqa: E402
from test_runner_observation_ingest import FakeRedis, KEY, PATH, settings  # noqa: E402


ENDPOINT = "https://cx.example.org/console/api/v1/runner-observations"
NEW_GENERATION = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*_args, **_kwargs):
        raise AssertionError("unexpected external connection")
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)


@pytest.fixture
def copies(tmp_path):
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    key = keys / "fixture.key"
    generate_key(key)
    root = tmp_path / "source"
    root.mkdir(mode=0o700)
    source = RunnerObservations(root / "observations.db", key)
    source.initialize()
    source.save(collect([monitor_target()], {}, client_factory=FakeClient, now=NOW.isoformat()))
    original = source.read()
    original_bytes = source.storage.path.read_bytes()

    def copy_store(label, previous=None):
        directory = tmp_path / label
        directory.mkdir(mode=0o700)
        previous = previous or source
        destination = directory / "observations.db"
        previous.storage.backup(destination)
        result = RunnerObservations(destination, key)
        result.storage.check()
        assert result.read() == previous.read()
        assert not destination.read_bytes().startswith(b"SQLite format 3")
        assert b"Example runner" not in destination.read_bytes()
        return result

    yield source, copy_store
    assert source.read() == original
    assert source.storage.path.read_bytes() == original_bytes


def web(store, scope=None):
    from flask import Flask
    app = Flask(__name__)
    app.config.update(TESTING=True, PUBLIC_PORTAL_MODE=False, AUTH_REQUIRES_REDIS=True,
                      REDIS_CONN=FakeRedis(), RUNNER_MONITOR_DB_PATH=str(store.storage.path),
                      RUNNER_MONITOR_KEY_FILE=str(store.storage.key_file))
    register_runner_observation_ingest(app, env=settings())
    app.config["RUNNER_OBSERVATION_SOURCES"] = (
        ObservationSource(scope or policy(), hashlib.sha256(KEY.encode()).hexdigest()),)
    return app


def post(app, value):
    return app.test_client().post(PATH, data=raw(value), content_type="application/json",
                                  headers={"X-Collector-Key": KEY})


def new_batch(sequence=1):
    return batch(sequence, generation=NEW_GENERATION,
                 batch_id=str(uuid.uuid5(uuid.UUID(NEW_GENERATION), str(sequence))))


def spool(tmp_path, scope=None, name="spool"):
    directory = tmp_path / name
    directory.mkdir(mode=0o700)
    DeliveryState(directory, scope or policy(), ENDPOINT).initialize()
    return directory


def state(directory):
    return json.loads((directory / "delivery.json").read_bytes())


def copy_spool(directory, destination, scope=None):
    destination.mkdir(mode=0o700)
    store = DeliveryState(directory, scope or policy(), ENDPOINT)
    with store.locked() as fd:
        store.load(fd, now=NOW)
        shutil.copy2(directory / "delivery.json", destination / "delivery.json")
    return destination


def no_collect(_sequence):
    raise AssertionError("pending replay must not collect")


def deliver(directory, sender, producer=no_collect, scope=None):
    return run_once(directory, scope or policy(), sender, producer, now=lambda: NOW,
                    sleep=lambda _seconds: None)


class Sender:
    endpoint = ENDPOINT

    def __init__(self, store, scope=None, *, lose_ack=False):
        self.store, self.scope = store, scope or policy()
        self.lose_ack = lose_ack
        self.calls = []

    def send(self, data, *, timeout):
        self.calls.append(data)
        update = self.store.ingest(data, self.scope, received_at=NOW)
        if self.lose_ack:
            raise DeliveryError("delivery_connection_failed")
        return Response(200, raw(update.acknowledgement))


def test_legacy_to_api_preserves_success_on_first_failed_inventory(copies):
    source, copy_store = copies
    trial = copy_store("trial")
    before = trial.read()
    value = batch(targets=[{"target_id": "first", "inventory": error("http_503")}], runners=[])
    response = post(web(trial), value)
    assert response.status_code == 200 and response.json["status"] == "accepted"
    after = trial.read()
    assert "_ingest" not in source.read() and after["_ingest"]["source"]["sequence"] == 1
    old = before["targets"]["first"]["inventory"]
    observed = after["targets"]["first"]["inventory"]
    assert observed["data"] == old["data"] and observed["last_success_at"] == old["last_success_at"]
    assert observed["error"] == "http_503"
    assert only_runner(after)["detail"]["data"] == only_runner(before)["detail"]["data"]
    assert presentation(after, now=NOW)["runners"][0]["state"] == "unavailable"


def test_copy_pair_after_lost_response_replays_without_refresh(copies, tmp_path):
    _, copy_store = copies
    trial = copy_store("trial")
    directory = spool(tmp_path)
    with pytest.raises(DeliveryError, match="delivery_retry_pending"):
        deliver(directory, Sender(trial, lose_ack=True), lambda _seq: raw(batch()))
    frozen_db, frozen_state = trial.read(), state(directory)
    moved_db = copy_store("moved-db", trial)
    moved_state = copy_spool(directory, tmp_path / "moved-state")
    assert deliver(moved_state, Sender(moved_db)) == "acknowledged"
    assert moved_db.read() == frozen_db and trial.read() == frozen_db
    assert state(directory) == frozen_state and state(moved_state)["next_sequence"] == 2
    assert state(moved_state)["pending"] is None
    moved_db.storage.check()


def test_pending_collector_can_catch_up_an_older_copy_but_not_rewrite_newer_cursor(copies, tmp_path):
    _, copy_store = copies
    trial = copy_store("trial")
    old_db = copy_store("before-first-write", trial)
    directory = spool(tmp_path)
    with pytest.raises(DeliveryError):
        deliver(directory, Sender(trial, lose_ack=True), lambda _seq: raw(batch()))
    moved = copy_spool(directory, tmp_path / "catchup-state")
    assert deliver(moved, Sender(old_db)) == "acknowledged"
    assert old_db.read() == trial.read()
    trial.ingest(raw(batch(2)), policy(), received_at=NOW)
    later = trial.read()
    with pytest.raises(ProtocolError, match="stale_sequence"):
        deliver(directory, Sender(trial))
    assert trial.read() == later and state(directory)["pending"] is not None


def test_same_sequence_with_wrong_pending_content_cannot_be_handed_off(copies, tmp_path):
    _, copy_store = copies
    trial = copy_store("trial")
    trial.ingest(raw(batch()), policy(), received_at=NOW)
    directory = spool(tmp_path)
    value = state(directory)
    changed = batch()
    changed["runners"][0]["detail"]["data"]["description"] = "Different pending content"
    value["pending"] = raw(changed).decode()
    (directory / "delivery.json").write_text(json.dumps(value))
    before = trial.read()
    with pytest.raises(ProtocolError, match="sequence_conflict"):
        deliver(directory, Sender(trial))
    assert trial.read() == before and state(directory) == value


def test_acknowledged_state_with_older_database_has_a_missing_history(copies, tmp_path):
    _, copy_store = copies
    trial = copy_store("trial")
    old = copy_store("old-database", trial)
    directory = spool(tmp_path)
    assert deliver(directory, Sender(trial), lambda seq: raw(batch(seq))) == "acknowledged"
    assert state(directory)["pending"] is None and state(directory)["next_sequence"] == 2
    assert trial.read()["_ingest"]["source"]["sequence"] == 1
    assert "_ingest" not in old.read()
    # Protocol sequence gaps are legal, but cannot reconstruct acknowledged data.
    # This mismatched backup pair requires reconciliation, not automatic delivery.
    assert trial.read()["runners"] != old.read()["runners"]
    assert old.read()["runners"] and trial.read()["runners"]


def test_generation_change_in_config_alone_rejects_and_preserves_copy(copies, tmp_path):
    _, copy_store = copies
    trial = copy_store("trial")
    trial.ingest(raw(batch()), policy(), received_at=NOW)
    before = trial.read()
    changed = policy(generation=NEW_GENERATION)
    assert post(web(trial, changed), new_batch()).status_code == 409
    assert trial.read() == before
    directory = spool(tmp_path)
    with DeliveryState(directory, changed, ENDPOINT).locked() as fd:
        with pytest.raises(DeliveryError, match="delivery_state_invalid"):
            DeliveryState(directory, changed, ENDPOINT).load(fd, now=NOW)


def test_explicit_copy_only_epoch_replacement_preserves_observations_and_other_source(copies, tmp_path):
    _, copy_store = copies
    trial = copy_store("trial")
    trial.ingest(raw(batch()), policy(), received_at=NOW)
    other = policy(target("second", "other-server", "https://other.example.org"), source_id="other")
    from test_runner_observation_protocol import ok, summary, runner
    other_batch = batch(source_id="other", targets=[{"target_id": "second", "inventory": ok([summary()])}],
                        runners=[runner(server_id="other-server")])
    trial.ingest(raw(other_batch), other, received_at=NOW)
    frozen = trial.read()
    archive = copy_store("epoch-archive", trial)
    changed = policy(generation=NEW_GENERATION)
    # Rehearsal-only administrative edit: no production reset helper is added.
    candidate = deepcopy(frozen)
    del candidate["_ingest"]["source"]
    trial.save(candidate)
    assert trial.read()["targets"] == frozen["targets"] and trial.read()["runners"] == frozen["runners"]
    assert trial.read()["_ingest"]["other"] == frozen["_ingest"]["other"]
    application = web(trial, changed)
    assert post(application, batch(2)).status_code == 409
    value = new_batch()
    value.update(targets=[{"target_id": "first", "inventory": error("http_503")}], runners=[])
    assert post(application, value).status_code == 200
    current = trial.read()
    assert current["targets"]["first"]["inventory"]["data"] == frozen["targets"]["first"]["inventory"]["data"]
    assert current["_ingest"]["other"] == frozen["_ingest"]["other"]
    assert archive.read() == frozen
    trial.storage.check()


def test_backup_is_safe_before_first_write_but_stale_after_acceptance(copies):
    _, copy_store = copies
    trial = copy_store("trial")
    backup = copy_store("prewrite-backup", trial)
    assert trial.read() == backup.read()
    post(web(trial), batch())
    current = trial.read()
    assert current != backup.read() and "_ingest" not in backup.read()
    # The changed snapshot/cursor comparison is the stop condition, not a restore.
    assert current["_ingest"]["source"]["sequence"] == 1
    assert trial.read() == current


def test_rollback_after_api_write_keeps_latest_data_and_blocks_delivery(copies):
    _, copy_store = copies
    trial = copy_store("trial")
    application = web(trial)
    value = batch()
    value["runners"][0]["detail"]["data"]["description"] = "Newly observed"
    assert post(application, value).status_code == 200
    latest = trial.read()
    rollback_archive = copy_store("latest-before-legacy", trial)
    application.config["RUNNER_OBSERVATION_INGEST_ENABLED"] = False
    assert post(application, batch(2)).status_code == 404 and trial.read() == latest
    snapshot = collect([monitor_target()], latest, client_factory=FakeClient,
                       now=(NOW + timedelta(minutes=1)).isoformat())
    trial.save(snapshot)
    assert "_ingest" not in trial.read()
    assert rollback_archive.read() == latest
    # With legacy collection unavailable, its current input snapshot keeps API data.
    FakeClient.inventory_errors = {"first"}
    failed = collect([monitor_target()], latest, client_factory=FakeClient, now=NOW.isoformat())
    assert only_runner(failed)["detail"]["data"]["description"] == "Newly observed"


def test_return_to_api_after_legacy_writer_uses_new_generation(copies):
    _, copy_store = copies
    trial = copy_store("trial")
    trial.ingest(raw(batch()), policy(), received_at=NOW)
    latest = trial.read()
    trial.save(collect([monitor_target()], latest, client_factory=FakeClient, now=NOW.isoformat()))
    assert "_ingest" not in trial.read()
    changed = policy(generation=NEW_GENERATION)
    application = web(trial, changed)
    before = trial.read()
    assert post(application, batch()).status_code == 409 and trial.read() == before
    assert post(application, new_batch()).status_code == 200
    assert trial.read()["_ingest"]["source"]["generation"] == NEW_GENERATION


def test_different_target_identity_does_not_carry_old_membership(copies):
    _, copy_store = copies
    trial = copy_store("trial")
    trial.ingest(raw(batch()), policy(), received_at=NOW)
    candidate = trial.read()
    del candidate["_ingest"]["source"]
    trial.save(candidate)
    from utils.runner_observation_protocol import SourcePolicy, TargetSpec
    changed = SourcePolicy("collector", "source", NEW_GENERATION,
                           (TargetSpec("first", "server", "https://gitlab.example.org", "group/new"),))
    value = new_batch()
    value.update(targets=[{"target_id": "first", "inventory": error("http_503")}], runners=[])
    assert post(web(trial, changed), value).status_code == 200
    assert "data" not in trial.read()["targets"]["first"]["inventory"]
    assert trial.read()["runners"] == {}
