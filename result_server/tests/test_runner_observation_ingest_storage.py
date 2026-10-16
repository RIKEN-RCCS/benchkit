"""Atomic receiver persistence, using only synthetic encrypted temporary DBs."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Barrier

import pytest

pytest.importorskip("sqlcipher3")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.encrypted_sqlite import EncryptedDatabaseError, generate_key  # noqa: E402
from utils.runner_observations import RunnerObservations  # noqa: E402
from utils.runner_observation_protocol import ProtocolError  # noqa: E402
from test_runner_observation_protocol import NOW, batch, only_runner, policy, raw  # noqa: E402


@pytest.fixture
def store(tmp_path):
    (tmp_path / "db").mkdir(mode=0o700)
    (tmp_path / "keys").mkdir(mode=0o700)
    key = tmp_path / "keys" / "fixture.key"
    generate_key(key)
    result = RunnerObservations(tmp_path / "db" / "fixture.db", key)
    result.initialize()
    return result


def ingest(store, value=None):
    return store.ingest(raw(batch() if value is None else value), policy(), received_at=NOW)


def test_snapshot_and_cursor_survive_reopen_as_one_encrypted_record(store):
    update = ingest(store)
    reopened = RunnerObservations(store.storage.path, store.storage.key_file)
    assert reopened.read() == update.snapshot
    assert reopened.read()["_ingest"]["source"]["sequence"] == 1
    with reopened.storage.connect(readonly=True) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert only_runner(reopened.read())["detail"]["data"]["description"] == "Example"
    encrypted = store.storage.path.read_bytes()
    assert not encrypted.startswith(b"SQLite format 3") and b"Example" not in encrypted


def test_duplicate_does_not_issue_an_update(store):
    first = ingest(store)
    with store.storage.connect() as conn:
        conn.execute("CREATE TRIGGER reject_updates BEFORE UPDATE ON runner_observations "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic-write-failure'); END")
        conn.commit()
    duplicate = ingest(store)
    assert not duplicate.changed and duplicate.acknowledgement["status"] == "duplicate"
    assert store.read() == first.snapshot


def test_update_failure_rolls_back_data_and_replay_cursor(store):
    before = ingest(store).snapshot
    value = batch(2)
    value["runners"][0]["detail"]["data"]["description"] = "Not committed"
    with store.storage.connect() as conn:
        conn.execute("CREATE TRIGGER fail_after_update AFTER UPDATE ON runner_observations "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic-write-failure'); END")
        conn.commit()
    with pytest.raises(EncryptedDatabaseError):
        ingest(store, value)
    assert store.read() == before
    with store.storage.connect() as conn:
        conn.execute("DROP TRIGGER fail_after_update")
        conn.commit()
    assert ingest(store, value).acknowledgement["sequence"] == 2


def test_protocol_failure_keeps_transaction_state_unchanged(store):
    before = ingest(store).snapshot
    changed = batch()
    changed["runners"][0]["detail"]["data"]["description"] = "Conflicting replay"
    with pytest.raises(ProtocolError, match="sequence_conflict"):
        ingest(store, changed)
    assert store.read() == before
    assert ingest(store, batch(2)).changed


def test_each_transaction_reads_latest_cursor_not_a_cached_snapshot(store):
    other = RunnerObservations(store.storage.path, store.storage.key_file)
    stale = deepcopy(other.read())
    ingest(store, batch(5))
    with pytest.raises(ProtocolError, match="stale_sequence"):
        ingest(other, batch(3))
    assert stale == {"targets": {}, "runners": {}}
    assert other.read()["_ingest"]["source"]["sequence"] == 5


def test_competing_writers_cannot_overwrite_a_newer_batch(store):
    ready = Barrier(2)

    def writer(sequence):
        ready.wait(timeout=5)
        value = batch(sequence)
        value["runners"][0]["detail"]["data"]["description"] = str(sequence)
        try:
            return ingest(RunnerObservations(store.storage.path, store.storage.key_file), value).changed
        except ProtocolError as error:
            assert error.code == "stale_sequence"
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (1, 2)))
    assert any(results)
    final = store.read()
    assert final["_ingest"]["source"]["sequence"] == 2
    assert only_runner(final)["detail"]["data"]["description"] == "2"


def test_missing_database_wrong_key_and_bad_schema_do_not_initialize(store, tmp_path):
    missing = tmp_path / "db" / "missing.db"
    with pytest.raises(EncryptedDatabaseError):
        ingest(RunnerObservations(missing, store.storage.key_file))
    assert not missing.exists()
    wrong = tmp_path / "keys" / "wrong.key"
    generate_key(wrong)
    with pytest.raises(EncryptedDatabaseError):
        ingest(RunnerObservations(store.storage.path, wrong))
    with store.storage.connect() as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(EncryptedDatabaseError, match="schema is unsupported"):
        ingest(store)
    with store.storage.connect(readonly=True) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 99


def test_corrupt_cursor_is_not_reset_by_ingestion(store):
    before = ingest(store).snapshot
    before["_ingest"]["source"] = {}
    store.save(before)
    with pytest.raises(ProtocolError, match="invalid_state"):
        ingest(store, batch(2))
    assert store.read() == before


def test_stored_row_missing_is_not_created(store):
    with store.storage.connect() as conn:
        conn.execute("DELETE FROM runner_observations")
        conn.commit()
    with pytest.raises(EncryptedDatabaseError, match="data is invalid"):
        ingest(store)
    with store.storage.connect(readonly=True) as conn:
        assert conn.execute("SELECT count(*) FROM runner_observations").fetchone()[0] == 0


def test_http_receiver_saves_a_real_synthetic_store(store):
    from flask import Flask
    from routes.runner_observation_ingest import register_runner_observation_ingest
    from test_runner_observation_ingest import KEY, PATH, settings

    app = Flask(__name__)
    app.config.update(TESTING=True, PUBLIC_PORTAL_MODE=False,
                      RUNNER_MONITOR_DB_PATH=str(store.storage.path),
                      RUNNER_MONITOR_KEY_FILE=str(store.storage.key_file))
    register_runner_observation_ingest(app, env=settings())
    client = app.test_client()
    response = client.post(PATH, data=raw(batch()), content_type="application/json",
                           headers={"X-Collector-Key": KEY})
    assert response.status_code == 200 and response.json["status"] == "accepted"
    before = store.read()
    repeated = client.post(PATH, data=raw(batch()), content_type="application/json",
                           headers={"X-Collector-Key": KEY})
    assert repeated.status_code == 200 and repeated.json["status"] == "duplicate"
    assert store.read() == before
    assert json.loads(json.dumps(before))["_ingest"]["source"]["sequence"] == 1
    conflicting = batch()
    conflicting["runners"][0]["detail"]["data"]["description"] = "Conflicting sample"
    rejected = client.post(PATH, data=raw(conflicting), content_type="application/json",
                           headers={"X-Collector-Key": KEY})
    assert rejected.status_code == 409 and rejected.json == {"error": "sequence_conflict"}
    assert store.read() == before
