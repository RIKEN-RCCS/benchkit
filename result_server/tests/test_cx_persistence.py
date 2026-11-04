"""Offline SQLCipher acceptance using generated data only."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from flask import Flask

pytest.importorskip("sqlcipher3.dbapi2", reason="SQLCipher tests also run in the encrypted DB selection")

from utils.cx_persistence import CxPersistence, CHUNK_SIZE
from utils.encrypted_sqlite import generate_key, EncryptedDatabaseError
from utils.cx_identity import EncryptedUserStore, EncryptedSessionCache


@pytest.fixture
def storage(tmp_path):
    for name in ("data", "keys", "results", "estimates", "artifacts", "inputs"):
        (tmp_path / name).mkdir(mode=0o700)
    key = tmp_path / "keys" / "key"
    generate_key(key)
    store = CxPersistence(tmp_path / "data" / "cx.db", key, roots={
        role: str(tmp_path / role) for role in ("results", "estimates", "artifacts", "inputs")})
    store.initialize()
    return store


def test_roundtrip_atomic_facts_and_no_plaintext(storage):
    raw = b'{"code":"synthetic-secret-code","system":"A","Exp":"e","FOM":1.23456789012345,"unknown":{"x":[1,null]}}'
    storage.put_document("results", "result_20261104_010203_a.json", raw)
    assert storage.read("results", "result_20261104_010203_a.json") == raw
    assert storage.candidates()["total"] == 1
    with storage.snapshot() as reader:
        assert list(reader.records(storage.directory))[0]["data"]["FOM"] == 1.23456789012345
    for path in storage.path.parent.iterdir():
        assert b"synthetic-secret-code" not in path.read_bytes()
    assert not list(Path(storage.directory).iterdir())
    storage.check()


def test_failed_publication_rolls_back_payload_and_facts(storage):
    name = "result_20261104_010203_a.json"
    storage.put_document("results", name, b'{"system":"old"}')
    def fail():
        raise ValueError("synthetic publication failure")
    with pytest.raises(ValueError):
        storage.put_document("results", name, b'{"system":"new"}', index_metadata=fail)
    assert json.loads(storage.read("results", name))["system"] == "old"
    assert storage.candidates()["rows"][0]["system"] == "old"


def test_chunk_limit_and_replacement(storage):
    payload = b"x" * (CHUNK_SIZE * 2 + 19)
    storage.put("artifacts", "archive.tgz", io.BytesIO(payload), limit=len(payload))
    with storage.blobs.connect(readonly=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 3
    assert storage.read("artifacts", "archive.tgz") == payload
    with pytest.raises(ValueError):
        storage.put("artifacts", "archive.tgz", io.BytesIO(payload), limit=7)
    assert storage.read("artifacts", "archive.tgz") == payload


def archive_bytes(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def test_input_archive_atomic_replacement(storage):
    raw = archive_bytes([("nested/a.json", b'{"unknown":3}')])
    limits = dict(upload_limit=4096, member_limit=2048, total_limit=2048, count_limit=10)
    assert not storage.replace_inputs("result_a", io.BytesIO(raw), **limits)
    assert storage.read("inputs", "result_a/nested/a.json") == b'{"unknown":3}'
    bad = archive_bytes([("../escape", b"bad")])
    with pytest.raises(ValueError):
        storage.replace_inputs("result_a", io.BytesIO(bad), **limits)
    assert storage.read("input_archives", "result_a") == raw


@pytest.mark.parametrize("name", ["../x", "/abs", "a/../b", "a\\b", "", "a//b", "a/./b"])
def test_unsafe_names_rejected(storage, name):
    with pytest.raises(ValueError):
        storage.put("inputs", name, io.BytesIO(b"x"), limit=1)


def test_identity_sessions_and_expiry(storage, monkeypatch):
    users = EncryptedUserStore(storage)
    users.create_user("synthetic@example.invalid", "synthetic-totp", ["a"])
    assert users.update_affiliations("synthetic@example.invalid", ["b"])
    assert users.get_affiliations("synthetic@example.invalid") == ["b"]
    token = users.create_invitation("new@example.invalid", ["a"])
    assert users.get_invitation(token)["affiliations"] == ["a"]
    sessions = EncryptedSessionCache(storage)
    sessions.set("session:a", {"authenticated": True}, timeout=30)
    assert sessions.get("session:a")["authenticated"]
    import utils.cx_persistence as module
    now = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: now + 86401)
    assert sessions.get("session:a") is None
    assert users.get_invitation(token) is None
    assert users.has_totp_secret("synthetic@example.invalid")


def test_backup_restore_retains_post_migration_writes(storage):
    storage.put_document("results", "result_20261104_010203_a.json", b'{"system":"A"}')
    storage.put_document("estimates", "estimate_20261104_010203_b.json", b'{"unknown":"new-write"}')
    EncryptedUserStore(storage).create_user("new@example.invalid", "synthetic", [])
    target = storage.path.with_name("backup.db")
    storage.backup(target)
    recovered = CxPersistence(target, storage.storage.key_file, roots=storage.roots)
    assert recovered.read("estimates", "estimate_20261104_010203_b.json") == b'{"unknown":"new-write"}'
    assert EncryptedUserStore(recovered).user_exists("new@example.invalid")
    recovered.rebuild()
    assert recovered.candidates()["total"] == 1


def test_wrong_key_and_instance_binding_fail_closed(storage, tmp_path):
    other = tmp_path / "keys" / "other"
    generate_key(other)
    with pytest.raises(EncryptedDatabaseError):
        CxPersistence(storage.path, other, roots=storage.roots).check()
    with pytest.raises(EncryptedDatabaseError):
        CxPersistence(storage.path, storage.storage.key_file,
                      roots={**storage.roots, "results": str(tmp_path / "elsewhere")}).check()


@pytest.fixture
def encrypted_app(storage, monkeypatch):
    from test_support import build_portal_route_app, install_portal_test_stubs
    install_portal_test_stubs()
    from utils.cx_persistence import configure_persistence
    app = build_portal_route_app(templates_dir=str(Path(__file__).resolve().parents[1] / 'templates'),
        received_dir=storage.roots['results'], estimated_dir=storage.roots['estimates'])
    from routes.api import api_bp
    app.register_blueprint(api_bp)
    app.config.update(RECEIVED_PADATA_DIR=storage.roots['artifacts'],
        RECEIVED_MEASUREMENT_ARTIFACTS_DIR=storage.roots['artifacts'],
        RECEIVED_ESTIMATION_ARTIFACTS_DIR=storage.roots['inputs'])
    app.secret_key = 'synthetic-session-secret'
    app.config.update(INGEST_KEYS={'synthetic-key': 'synthetic-runner'},
        MAX_CONTENT_LENGTH=1024 * 1024 * 5, MAX_ARCHIVE_MEMBER_SIZE=1024 * 1024,
        MAX_ARCHIVE_TOTAL_EXTRACTED_SIZE=1024 * 1024, MAX_ARCHIVE_MEMBER_COUNT=20)
    monkeypatch.setenv('RESULT_SERVER_PERSISTENCE_DB', str(storage.path))
    monkeypatch.setenv('RESULT_SERVER_PERSISTENCE_KEY', str(storage.storage.key_file))
    configure_persistence(app)
    return app


def test_encrypted_api_ingest_query_and_artifacts(encrypted_app, storage):
    app = encrypted_app
    client = app.test_client()
    headers = {'X-API-Key': 'synthetic-key'}
    result = client.post('/api/ingest/result', headers=headers, json={
        'system': 'A', 'code': 'demo', 'Exp': 'e', 'FOM': 123.456,
        'unknown_extension': {'preserve': ['yes', None]},
        'fom_breakdown': {'sections': [{'name': 's', 'artifacts': [
            {'type': 'file_reference', 'path': 'results/archive.tgz'}]}]}})
    assert result.status_code == 200
    saved = result.get_json()
    assert storage.names('results') == [saved['json_file']]
    assert not list(Path(storage.roots['results']).iterdir())
    query = client.get('/api/query/result', query_string={'uuid': saved['id']}, headers=headers)
    assert query.status_code == 200
    assert query.get_json()['unknown_extension']['preserve'] == ['yes', None]
    measurement = archive_bytes([('metrics.csv', b'name,value\nsynthetic,1\n')])
    response = client.post('/api/ingest/measurement-artifact', headers=headers, data={
        'id': saved['id'], 'timestamp': saved['timestamp'], 'artifact_path': 'results/archive.tgz',
        'file': (io.BytesIO(measurement), 'archive.tgz')})
    assert response.status_code == 200
    response = client.get('/api/query/measurement-artifact', headers=headers,
        query_string={'uuid': saved['id'], 'artifact_path': 'results/archive.tgz'})
    assert response.status_code == 200
    assert response.data == measurement
    assert client.get('/api/query/measurement-artifact', headers=headers,
        query_string={'uuid': saved['id'], 'artifact_path': 'results/unreferenced.tgz'}).status_code == 404
    estimate = client.post('/api/ingest/estimate', headers=headers, json={
        'code': 'demo', 'estimate_metadata': {'source_result_uuid': saved['id']}, 'FOM': 0.123})
    assert estimate.status_code == 200
    inputs = archive_bytes([('nested/test.json', b'{"x":1}')])
    response = client.post('/api/ingest/estimation-artifacts', headers=headers, data={
        'id': saved['id'], 'file': (io.BytesIO(inputs), 'inputs.tgz')})
    assert response.status_code == 200
    response = client.get('/api/query/estimation-artifacts', headers=headers, query_string={'uuid': saved['id']})
    assert response.status_code == 200
    assert response.data == inputs
    assert not list(Path(storage.roots['inputs']).iterdir())
    with app.app_context():
        from utils.execution_profiles import ExecutionProfileStore
        with ExecutionProfileStore(str(storage.path)).connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM result_metadata_index').fetchone()[0] == 2


def test_encrypted_browser_readers_and_sessions(encrypted_app, storage):
    app = encrypted_app
    from utils.cx_identity import EncryptedUserStore
    app.config['USER_STORE'] = EncryptedUserStore(storage)
    app.config['USER_STORE'].create_user('reader@example.invalid', 'synthetic', ['team'])
    public = 'result_20261104_010203_a.json'
    private = 'result_20261104_010204_b.json'
    storage.put_document('results', public, b'{"code":"demo","system":"A","FOM":1}')
    storage.put_document('results', private, b'{"code":"demo","system":"B","confidential":["team"],"FOM":2}')
    with app.test_request_context('/'):
        from utils.results_loader import load_results_table
        from utils.result_records import load_visible_result_json
        from utils.storage_files import list_names
        assert len(list_names(storage.directory)) == 2
        assert load_visible_result_json(private, storage.directory) is None
        assert load_visible_result_json(private, storage.directory, affiliations=['team'],
                                       public_only=False, authenticated=True)['FOM'] == 2
        with storage.snapshot() as reader:
            rows = load_results_table(storage.directory, storage.roots['artifacts'], query_reader=reader)[0]
            assert len(rows) == 1
    client = app.test_client()
    with client.session_transaction() as session:
        session['authenticated'] = True
        session['user_email'] = 'reader@example.invalid'
    # A new interface instance (as after restart) reads the same signed SID.
    from flask_session.cachelib import CacheLibSessionInterface
    app.session_interface = CacheLibSessionInterface(app, client=EncryptedSessionCache(storage), use_signer=True)
    with client.session_transaction() as session:
        assert session['user_email'] == 'reader@example.invalid'


@pytest.mark.parametrize('source_version', [11, 12])
def test_snapshot_migration_and_recovery(tmp_path, source_version, monkeypatch):
    from utils.cx_migration import import_snapshot, recover_copy
    from utils.execution_profiles import ExecutionProfileStore, normalize_profile
    root = tmp_path / 'snapshot'
    root.mkdir(mode=0o700)
    roots = {}
    for role in ('results', 'estimates', 'artifacts', 'inputs'):
        path = root / role
        path.mkdir(mode=0o700)
        roots[role] = str(path)
    profile = root / 'profile.sqlite3'
    profiles = ExecutionProfileStore(str(profile))
    historical = monkeypatch.context()
    patcher = historical.__enter__()
    if source_version == 11:
        patcher.setattr(ExecutionProfileStore, '_apply_v12', lambda self, conn: None)
    profiles.migrate()
    normalized, errors = normalize_profile(dict(id='sample', display_name='Synthetic profile',
        code='demo', system=['A'], exp=['case'], owner='a', activity='a',
        allocation_project_id='a', status='approved', visibility='public-results'))
    assert not errors
    profiles.upsert_profile(normalized, actor='synthetic')
    run_id = profiles.create_trigger_run(trigger_id='sample-trigger', trigger_type='scheduled',
        status='submission_unknown', dry_run=False, reason='existing-uncertain', payload={'preserve': True})
    historical.__exit__(None, None, None)
    name = 'result_20261104_010203_a.json'
    raw = b'{ "system":"A", "code":"demo", "FOM":12.34567890123, "unknown":{"keep":true} }'
    (Path(roots['results']) / name).write_bytes(raw)
    nested = Path(roots['inputs']) / 'result_a' / 'nested'
    nested.mkdir(parents=True)
    (nested / 'input.json').write_bytes(b'{"original":true}')
    original = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}
    for item in ('db', 'keys', 'recovery'):
        (tmp_path / item).mkdir(mode=0o700)
    key = tmp_path / 'keys' / 'key'
    generate_key(key)
    store = CxPersistence(tmp_path / 'db' / 'cx.db', key, roots=roots)
    report = import_snapshot(store, profile_copy=profile, source_roots=roots, identity={
        'users': {'test@example.invalid': {'value': dict(email='test@example.invalid', totp_secret='synthetic', affiliations=['a'])}}})
    assert report['objects']['results'] == 1
    assert store.read('results', name) == raw
    imported = store.read('input_archives', 'result_a')
    with tarfile.open(fileobj=io.BytesIO(imported)) as archive:
        assert archive.extractfile('nested/input.json').read() == b'{"original":true}'
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()} == original
    new = 'estimate_20261104_020304_b.json'
    store.put_document('estimates', new, b'{"new":"retained-after-restore"}')
    updated_profile = ExecutionProfileStore(str(store.path), key_file=key)
    updated_profile.upsert_profile({**normalized, 'enabled': False}, actor='changed-after-migration')
    EncryptedUserStore(store).update_affiliations('test@example.invalid', ['changed'])
    backup = tmp_path / 'recovery' / 'cx.db'
    restored = recover_copy(store, backup)
    assert restored.read('estimates', new) == b'{"new":"retained-after-restore"}'
    with store._connect(readonly=True) as before, restored._connect(readonly=True) as after:
        for table in ('execution_profiles', 'execution_profile_scopes', 'execution_profile_events'):
            assert [tuple(row) for row in before.execute('SELECT * FROM ' + table)] == [tuple(row) for row in after.execute('SELECT * FROM ' + table)]
    assert EncryptedUserStore(restored).user_exists('test@example.invalid')
    assert EncryptedUserStore(restored).get_affiliations('test@example.invalid') == ['changed']
    with restored._connect(readonly=True) as conn:
        assert conn.execute('SELECT enabled FROM execution_profiles WHERE id=?', ('sample',)).fetchone()[0] == 0
        assert conn.execute('SELECT status FROM trigger_runs WHERE id=?', (run_id,)).fetchone()[0] == 'submission_unknown'


def test_legacy_session_copy_continues_and_cannot_revive_after_logout(storage, tmp_path):
    from cachelib import FileSystemCache
    from utils.cx_migration import read_session_snapshot
    directory = tmp_path / 'old-sessions'
    directory.mkdir(mode=0o700)
    cache = FileSystemCache(str(directory), mode=0o600)
    cache.set('session:existing-signed-sid', {'authenticated': True, 'user_email': 'test@example.invalid'}, timeout=1800)
    for key, entry in read_session_snapshot(directory).items():
        with storage.transaction() as conn:
            conn.execute('INSERT INTO cx_values VALUES(?,?,?,?)',
                         ('legacy_sessions', key, json.dumps(entry['value']), entry['expires']))
    sessions = EncryptedSessionCache(storage)
    assert sessions.get('session:existing-signed-sid')['authenticated']
    assert sessions.delete('session:existing-signed-sid')
    assert sessions.get('session:existing-signed-sid') is None


def test_session_copy_rejects_executable_pickle(storage, tmp_path):
    import pickle
    import struct
    import time
    from utils.cx_migration import read_session_snapshot
    directory = tmp_path / 'bad-session'
    directory.mkdir(mode=0o700)
    marker = tmp_path / 'must-not-exist'
    class Executable:
        def __reduce__(self):
            return (os.system, (f'touch {marker}',))
    path = directory / ('a' * 32)
    path.write_bytes(struct.pack('I', int(time.time()) + 1800) + pickle.dumps(Executable()))
    path.chmod(0o600)
    with pytest.raises(ValueError):
        read_session_snapshot(directory)
    assert not marker.exists()


def test_invitation_is_consumed_atomically_once(storage):
    users = EncryptedUserStore(storage)
    token = users.create_invitation('new@example.invalid', ['a'])
    assert users.register_invited_user(token, 'new@example.invalid', 'synthetic', ['a'])
    assert not users.register_invited_user(token, 'new@example.invalid', 'different', ['a'])
    assert users.get_user('new@example.invalid')['totp_secret'] == 'synthetic'


def test_upload_spool_is_encrypted_bounded_and_removed(storage):
    from utils.cx_upload import EncryptedUpload, PAGE_SIZE
    from werkzeug.exceptions import RequestEntityTooLarge
    payload = b'synthetic-upload-plaintext' * (PAGE_SIZE // 12)
    before = set(storage.path.parent.iterdir())
    stream = EncryptedUpload(storage.path.parent, len(payload) + 10)
    stream.write(payload)
    directory = Path(stream.directory.name)
    assert stream.seek(0) == 0
    assert stream.read() == payload
    for path in (directory / 'data').iterdir():
        assert b'synthetic-upload-plaintext' not in path.read_bytes()
    stream.seek(0)
    stream.write(b'changed')
    stream.seek(0)
    assert stream.read(7) == b'changed'
    stream.seek(0, 2)
    with pytest.raises(RequestEntityTooLarge):
        stream.write(b'x' * 11)
    stream.close()
    assert not directory.exists()
    assert set(storage.path.parent.iterdir()) == before


def test_download_pins_a_snapshot_across_concurrent_replacement(storage):
    payload = b'a' * (CHUNK_SIZE + 1)
    storage.put('artifacts', 'a.tgz', io.BytesIO(payload), limit=len(payload))
    reading = storage.chunks('artifacts', 'a.tgz')
    first = next(reading)
    storage.put('artifacts', 'a.tgz', io.BytesIO(b'new'), limit=3)
    assert first + b''.join(reading) == payload
    assert storage.read('artifacts', 'a.tgz') == b'new'


def test_interrupted_writer_and_explicit_fact_rebuild(storage):
    name = 'result_20261104_010203_a.json'
    with pytest.raises(KeyboardInterrupt):
        with storage.transaction() as conn:
            storage.put_document('results', name, b'{"system":"A"}', conn=conn)
            raise KeyboardInterrupt()
    assert storage.names('results') == []
    storage.put_document('results', name, b'{"system":"A"}')
    with storage._connect() as conn:
        conn.execute("UPDATE query_records SET facts='{}'")
        conn.commit()
    with pytest.raises(EncryptedDatabaseError):
        storage.check()
    storage.rebuild()
    storage.check()


def test_get_failure_never_falls_back_to_stale_json(encrypted_app, storage):
    name = 'result_20261104_010203_a.json'
    (Path(storage.directory) / name).write_text('{"system":"stale"}')
    client = encrypted_app.test_client()
    assert client.get('/api/query/result?system=stale&code=demo', headers={'X-API-Key': 'synthetic-key'}).status_code == 404
    storage.storage.key_file.unlink()
    response = client.get('/api/query/result?system=stale&code=demo', headers={'X-API-Key': 'synthetic-key'})
    assert response.status_code == 503
    assert b'stale' not in response.data


def test_disk_full_rolls_back_the_whole_receipt(storage):
    name = 'result_20261104_010203_a.json'
    storage.put_document('results', name, b'{"kept":true}')
    with pytest.raises(EncryptedDatabaseError):
        with storage.transaction() as conn:
            pages = conn.execute('PRAGMA page_count').fetchone()[0]
            conn.execute('PRAGMA max_page_count=' + str(pages + 2))
            storage.put_document('results', name, json.dumps({'large': 'x' * CHUNK_SIZE}).encode(), conn=conn)
    assert storage.read('results', name) == b'{"kept":true}'
    storage.check()


def test_process_exit_before_commit_preserves_previous_generation(storage):
    import subprocess
    storage.put_document('results', 'result_20261104_010203_a.json', b'{"system":"kept"}')
    script = '''
import os, sys
from utils.cx_persistence import CxPersistence
store = CxPersistence.open_existing(sys.argv[1], sys.argv[2])
with store.transaction() as conn:
    store.put_document('results', 'result_20261104_010203_a.json', b'{"system":"uncommitted"}', conn=conn)
    os._exit(17)
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(storage.path), str(storage.storage.key_file)],
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 17
    assert json.loads(storage.read('results', 'result_20261104_010203_a.json'))['system'] == 'kept'
    storage.check()


def test_parallel_writers_preserve_all_documents_and_counts(storage):
    from concurrent.futures import ThreadPoolExecutor
    def write(number):
        storage.put_document('results', f'result_20261104_010203_{number}.json',
                             json.dumps({'system': 'A', 'FOM': number}).encode())
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))
    assert storage.candidates()['total'] == len(storage.names('results')) == 12
    storage.check()


def test_legacy_and_encrypted_search_reports_and_csv_agree(tmp_path):
    from datetime import date
    import csv
    from utils.cx_migration import import_snapshot
    from test_result_query_index import indexed
    from utils.results_loader import load_results_table
    from utils.node_hours import aggregate_node_hours
    from utils.performance_telemetry import build_performance_telemetry
    from utils.profile_usage_overview import build_profile_usage_overview
    from utils.evidence_snapshot import build_evidence_snapshot, EVIDENCE_SNAPSHOT_CSV_COLUMNS
    _, results, estimates, archives, profile = indexed.__wrapped__(tmp_path)
    inputs = tmp_path / 'inputs'
    inputs.mkdir(mode=0o700)
    for name in ('cipher', 'keys'):
        (tmp_path / name).mkdir(mode=0o700)
    key = tmp_path / 'keys' / 'key'
    generate_key(key)
    roots = dict(results=str(results), estimates=str(estimates), artifacts=str(archives), inputs=str(inputs))
    store = CxPersistence(tmp_path / 'cipher' / 'cx.db', key, roots=roots)
    import_snapshot(store, profile_copy=profile, source_roots=roots)
    calls = [
        (aggregate_node_hours, (str(results), 2026, 'monthly'), (str(results), 2026, 'monthly'), {}),
        (build_profile_usage_overview, (str(results), profile), (str(results), str(store.path)), {}),
        (build_performance_telemetry, (str(results), str(estimates)), (str(results), str(estimates)), {}),
        (build_evidence_snapshot, (str(results), str(estimates)), (str(results), str(estimates)),
         dict(generated_at='2026-11-04T00:00:00Z', app_support_rows=[])),
    ]
    app = Flask(__name__)
    from routes.results import results_bp
    app.register_blueprint(results_bp, url_prefix='/results')
    for system in ('', 'Fugaku', 'DemoSystem', 'Absent'):
        for since, until in ((date(2026, 4, 1), date(2027, 4, 1)), (date(2026, 9, 1), date(2026, 10, 1))):
            selection = dict(code='genesis', system=system, since=since, until=until)
            for function, legacy_args, encrypted_args, kwargs in calls:
                expected = function(*legacy_args, selection=selection, **kwargs)
                if function is build_profile_usage_overview:
                    assert expected['path'] == profile
                    expected = {**expected, 'path': str(store.path)}
                with app.app_context():
                    app.extensions['cx_persistence'] = store
                    with store.snapshot() as reader:
                        actual = function(*encrypted_args, selection=selection, record_source=reader, **kwargs)
                    del app.extensions['cx_persistence']
                assert actual == expected, (function.__name__, selection)
                if function is build_evidence_snapshot:
                    def export(report):
                        output = io.StringIO()
                        writer = csv.DictWriter(output, fieldnames=EVIDENCE_SNAPSHOT_CSV_COLUMNS)
                        writer.writeheader()
                        for row in report['rows']:
                            writer.writerow({column: row.get(column, '') for column in EVIDENCE_SNAPSHOT_CSV_COLUMNS})
                        return output.getvalue()
                    assert export(actual) == export(expected)
    for public, authenticated, affiliations in ((True, False, []), (False, True, ['a']),
            (False, True, ['a', 'b']), (False, True, ['admin']), (False, False, ['admin'])):
        for system in (None, 'Fugaku', 'Absent'):
            kwargs = dict(public_only=public, authenticated=authenticated, affiliations=affiliations,
                          filter_system=system, filter_code='genesis', per_page=50, page=2,
                          padata_directory=str(archives))
            with app.test_request_context():
                expected = load_results_table(str(results), **kwargs)
                app.extensions['cx_persistence'] = store
                with store.snapshot() as reader:
                    actual = load_results_table(str(results), query_reader=reader, **kwargs)
                del app.extensions['cx_persistence']
            assert actual == expected


def test_browser_pages_use_encrypted_records(encrypted_app, storage):
    from test_support import StaticAffiliationUserStore
    app = encrypted_app
    app.config['USER_STORE'] = StaticAffiliationUserStore({'admin@example.invalid': ['admin']})
    name = 'result_20261104_010203_00000000-0000-0000-0000-000000000001.json'
    storage.put_document('results', name, b'{"code":"genesis","system":"Fugaku","FOM":12,"Exp":"SYNTHETIC"}')
    client = app.test_client()
    with client.session_transaction() as session:
        session['authenticated'] = True
        session['user_email'] = 'admin@example.invalid'
        session['user_affiliations'] = ['admin']
    for path in ('/results/?search=1', '/results/confidential?search=1',
                 '/results/usage?run=1&report=node_hours',
                 '/results/usage?run=1&report=profiles',
                 '/results/usage?run=1&report=performance',
                 '/results/usage?run=1&report=evidence',
                 '/results/usage/evidence-snapshot.csv', '/estimated/', '/estimated/version-checks'):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)


def test_encrypted_guards_are_atomic_expiring_and_backup_compatible(storage, monkeypatch):
    from utils.cx_security_state import EncryptedSecurityState
    from concurrent.futures import ThreadPoolExecutor
    state = EncryptedSecurityState(storage)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: state.claim_once('replay', 90), range(8)))
    assert sum(results) == 1
    assert [state.increment_with_ttl('limit', 60) for _ in range(3)] == [1, 2, 3]
    storage.backup(storage.path.with_name('guards-backup.db'))
    recovered = EncryptedSecurityState(CxPersistence.open_existing(storage.path.with_name('guards-backup.db'), storage.storage.key_file))
    assert not recovered.claim_once('replay', 90)
    assert recovered.get('limit') == 3
    import utils.cx_security_state as module
    now = module.time.time()
    monkeypatch.setattr(module.time, 'time', lambda: now + 91)
    assert recovered.get('limit') is None
    assert recovered.claim_once('replay', 90)


def test_identity_export_preserves_invitation_and_security_guard_expiry(storage):
    import fakeredis
    from utils.user_store import UserStore
    from utils.cx_migration import export_identity
    redis = fakeredis.FakeRedis(decode_responses=True)
    source = UserStore(redis, 'synthetic:')
    source.create_user('test@example.invalid', 'synthetic', ['a'])
    invitation = source.create_invitation('new@example.invalid', ['a'])
    redis.setex('synthetic:totp_used:test@example.invalid:000000', 90, '1')
    exported = export_identity(source)
    assert exported['users']['test@example.invalid']['value']['totp_secret'] == 'synthetic'
    assert exported['invitations'][invitation]['expires'] is not None
    assert exported['guards']['synthetic:totp_used:test@example.invalid:000000']['value'] == 1
    assert redis.exists('synthetic:totp_used:test@example.invalid:000000')


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -0.0, 'unknown'])
def test_original_scientific_json_values_are_not_reinterpreted(storage, value):
    raw = json.dumps({'FOM': value, 'unknown': {'preserve': value}}).encode()
    storage.put_document('results', 'result_20261104_010203_a.json', raw)
    assert storage.read('results', 'result_20261104_010203_a.json') == raw
    storage.check()


def test_existing_signed_session_key_failure_is_503_not_logout(encrypted_app, storage):
    client = encrypted_app.test_client()
    with client.session_transaction() as session:
        session['authenticated'] = True
        session['user_email'] = 'synthetic@example.invalid'
    storage.storage.key_file.unlink()
    response = client.get('/results/?search=1')
    assert response.status_code == 503
    assert 'Set-Cookie' not in response.headers


def test_trigger_budget_identity_uses_encrypted_store_without_redis(encrypted_app, storage, monkeypatch):
    from utils.budget_profile_binding import current_actor
    from utils.cx_identity import identity_from_environment
    EncryptedUserStore(storage).create_user('grant@example.invalid', 'synthetic', ['admin'])
    import redis
    monkeypatch.setattr(redis, 'from_url', lambda *args, **kwargs: pytest.fail('Redis must not be contacted'), raising=False)
    assert current_actor('grant@example.invalid').is_admin
    assert identity_from_environment().user_exists('grant@example.invalid')


def test_profile_binding_cannot_silently_use_plaintext(encrypted_app, storage, tmp_path):
    from utils.execution_profiles import ExecutionProfileStore
    other = tmp_path / 'wrong-plain.db'
    with encrypted_app.app_context(), pytest.raises(EncryptedDatabaseError):
        ExecutionProfileStore(str(other)).migrate()
    assert not other.exists()


def test_artifact_staging_does_not_block_identity_or_result_publication(storage):
    from threading import Event
    from concurrent.futures import ThreadPoolExecutor
    import time
    entered, release = Event(), Event()
    class Paused:
        done = False
        def read(self, size):
            if self.done:
                return b''
            self.done = True
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Synthetic staging wait expired')
            return b'large-object-placeholder'
    with ThreadPoolExecutor(max_workers=1) as pool:
        upload = pool.submit(storage.put, 'artifacts', 'staged.tgz', Paused(), limit=100)
        try:
            assert entered.wait(5)
            started = time.monotonic()
            storage.value_set('guards', 'synthetic', 1, ttl=60)
            storage.put_document('results', 'result_20261104_010203_a.json', b'{"written":true}')
            assert time.monotonic() - started < 2
            assert storage.names('artifacts') == []
        finally:
            release.set()
        upload.result(timeout=10)
    assert storage.read('artifacts', 'staged.tgz') == b'large-object-placeholder'


def test_unpublished_artifact_generation_is_not_visible(storage, monkeypatch):
    storage.put('artifacts', 'a.tgz', io.BytesIO(b'kept'), limit=4)
    with monkeypatch.context() as patch:
        def fail(*args):
            raise ValueError('Synthetic pointer publication failure')
        patch.setattr(storage, '_publish_blob', fail)
        with pytest.raises(ValueError):
            storage.put('artifacts', 'a.tgz', io.BytesIO(b'unpublished'), limit=11)
    assert storage.read('artifacts', 'a.tgz') == b'kept'
    with storage.blobs.connect(readonly=True) as conn:
        assert conn.execute('SELECT COUNT(DISTINCT generation) FROM objects').fetchone()[0] == 2
    storage.check()


def test_metadata_first_backup_keeps_old_references_during_replacement(storage, monkeypatch):
    storage.put('artifacts', 'a.tgz', io.BytesIO(b'old'), limit=3)
    original = storage.storage.backup
    def backup_then_replace(destination):
        original(destination)
        storage.put('artifacts', 'a.tgz', io.BytesIO(b'new'), limit=3)
    monkeypatch.setattr(storage.storage, 'backup', backup_then_replace)
    target = storage.path.with_name('snapshot.db')
    storage.backup(target)
    recovered = CxPersistence.open_existing(target, storage.storage.key_file)
    assert recovered.read('artifacts', 'a.tgz') == b'old'
    assert storage.read('artifacts', 'a.tgz') == b'new'


def test_wrong_artifact_pair_is_rejected_even_with_the_same_key(storage):
    other = CxPersistence(storage.path.with_name('other.db'), storage.storage.key_file, roots=storage.roots)
    other.initialize()
    mismatch = CxPersistence(storage.path, storage.storage.key_file, roots=storage.roots, artifact_path=other.blobs.path)
    with pytest.raises(EncryptedDatabaseError):
        mismatch.check()


def test_common_dot_prefixed_tar_paths_are_preserved(storage):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        directory = tarfile.TarInfo('.')
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        item = tarfile.TarInfo('./nested/input.json')
        item.size = 2
        archive.addfile(item, io.BytesIO(b'{}'))
    storage.replace_inputs('result_a', io.BytesIO(output.getvalue()), upload_limit=32768,
        member_limit=1024, total_limit=1024, count_limit=10)
    assert storage.read('inputs', 'result_a/nested/input.json') == b'{}'
    with tarfile.open(fileobj=io.BytesIO(storage.read('input_archives', 'result_a'))) as archive:
        assert archive.extractfile('nested/input.json').read() == b'{}'


def test_headless_profile_commands_keep_their_standard_library_backend(tmp_path):
    import subprocess
    script = '''
import importlib.abc, sys
class NoFlask(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'flask' or fullname.startswith('flask.'):
            raise ModuleNotFoundError('Flask deliberately unavailable in headless fixture')
sys.meta_path.insert(0, NoFlask())
from utils.execution_profiles import ExecutionProfileStore
store = ExecutionProfileStore(sys.argv[1])
store.migrate()
with store.connect() as conn:
    assert conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 12
'''
    env = {key: value for key, value in os.environ.items() if not key.startswith('RESULT_SERVER_PERSISTENCE_')}
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, '-B', '-c', script, str(tmp_path / 'headless.db')],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, result.stderr.decode()


def test_artifact_disk_full_keeps_the_previous_pointer(storage):
    storage.put('artifacts', 'a.tgz', io.BytesIO(b'kept'), limit=4)
    with pytest.raises(EncryptedDatabaseError):
        with storage.blobs.stage() as (generation, conn):
            pages = conn.execute('PRAGMA page_count').fetchone()[0]
            conn.execute('PRAGMA max_page_count=' + str(pages + 2))
            storage.blobs.put(generation, 'artifacts', 'a.tgz', io.BytesIO(b'x' * CHUNK_SIZE),
                              limit=CHUNK_SIZE, conn=conn)
    assert storage.read('artifacts', 'a.tgz') == b'kept'
    storage.check()


def test_copy_cli_checks_and_recovers_both_encrypted_files(storage, capsys):
    from cx_storage import main
    plan = storage.path.parent / 'copy-plan.json'
    target = storage.path.with_name('cli-copy.db')
    plan.write_text(json.dumps(dict(database=str(storage.path), key_file=str(storage.storage.key_file), destination=str(target))))
    plan.chmod(0o600)
    storage.put('artifacts', 'a.tgz', io.BytesIO(b'kept'), limit=4)
    assert main(['check', '--plan', str(plan)]) == 0
    assert main(['backup-copy', '--plan', str(plan)]) == 0
    assert CxPersistence.open_existing(target, storage.storage.key_file).read('artifacts', 'a.tgz') == b'kept'
    lines = capsys.readouterr().out.splitlines()
    assert all(json.loads(line)['status'] == 'success' for line in lines)
    assert str(storage.path) not in '\n'.join(lines)


def test_failed_import_cannot_be_loaded_as_a_runtime(storage, tmp_path, monkeypatch):
    from utils.cx_migration import import_snapshot
    from utils.cx_persistence import configure_persistence
    from utils.execution_profiles import ExecutionProfileStore
    source = tmp_path / 'profile.db'
    ExecutionProfileStore(str(source)).migrate()
    (Path(storage.roots['results']) / 'broken.json').write_bytes(b'not-json')
    target = CxPersistence(storage.path.with_name('partial.db'), storage.storage.key_file, roots=storage.roots)
    with pytest.raises(ValueError):
        import_snapshot(target, profile_copy=source, source_roots=storage.roots)
    monkeypatch.setenv('RESULT_SERVER_PERSISTENCE_DB', str(target.path))
    monkeypatch.setenv('RESULT_SERVER_PERSISTENCE_KEY', str(target.storage.key_file))
    app = Flask(__name__)
    app.config.update(RECEIVED_DIR=storage.roots['results'], ESTIMATED_DIR=storage.roots['estimates'],
        RECEIVED_MEASUREMENT_ARTIFACTS_DIR=storage.roots['artifacts'], RECEIVED_ESTIMATION_ARTIFACTS_DIR=storage.roots['inputs'])
    with pytest.raises(EncryptedDatabaseError):
        configure_persistence(app)


def test_recovered_pair_boots_a_fresh_application_with_continued_session(tmp_path, monkeypatch):
    from test_support import install_portal_test_stubs
    install_portal_test_stubs()
    import redis
    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError('Redis/network use forbidden in encrypted recovery fixture')
    monkeypatch.setattr(redis, 'from_url', lambda *args, **kwargs: NoNetwork(), raising=False)
    from app import create_app
    for name in list(os.environ):
        if name.startswith('RESULT_SERVER_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('REDIS_URL', 'redis://127.0.0.1/0')
    monkeypatch.setenv('TOTP_ISSUER', 'Synthetic')
    base = tmp_path / 'logical'
    base.mkdir(mode=0o700)
    roots = dict(results=str(base / 'received'), estimates=str(base / 'estimated_results'),
                 artifacts=str(base / 'received_padata'), inputs=str(base / 'received_estimation_artifacts'))
    for name in ('private', 'keys', 'recovery'):
        (tmp_path / name).mkdir(mode=0o700)
    key = tmp_path / 'keys' / 'key'
    generate_key(key)
    store = CxPersistence(tmp_path / 'private' / 'cx.db', key, roots=roots)
    store.initialize()
    settings = dict(FLASK_SECRET_KEY='s' * 64, RESULT_SERVER_KEYS='synthetic-runner:' + 'x' * 40,
        RESULT_SERVER_PERSISTENCE_DB=str(store.path), RESULT_SERVER_PERSISTENCE_KEY=str(key),
        RESULT_SERVER_REDIS_PREFIX='synthetic:', FLASK_DEBUG='0')
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    source = create_app(prefix='/offline', base_dir=str(base))
    EncryptedUserStore(store).create_user('reader@example.invalid', 'synthetic', ['team'])
    client = source.test_client()
    with client.session_transaction() as session:
        session['authenticated'] = True
        session['user_email'] = 'reader@example.invalid'
    response = client.post('/offline/api/ingest/result', headers={'X-API-Key': 'x' * 40}, json={
        'code': 'demo', 'system': 'Synthetic', 'FOM': 1.23456789012345})
    assert response.status_code == 200
    saved = response.get_json()
    store.put('artifacts', 'a.tgz', io.BytesIO(b'new-bytes'), limit=9)
    EncryptedUserStore(store).update_affiliations('reader@example.invalid', ['changed'])
    target = tmp_path / 'recovery' / 'cx.db'
    store.backup(target)
    monkeypatch.setenv('RESULT_SERVER_PERSISTENCE_DB', str(target))
    recovered = create_app(prefix='/offline', base_dir=str(base))
    other = recovered.test_client()
    cookie_name = source.config['SESSION_COOKIE_NAME']
    other.set_cookie(cookie_name, client.get_cookie(cookie_name).value)
    with other.session_transaction() as session:
        assert session['authenticated']
        assert session['user_email'] == 'reader@example.invalid'
    response = other.get('/offline/api/query/result', headers={'X-API-Key': 'x' * 40}, query_string={'uuid': saved['id']})
    assert response.status_code == 200
    assert response.get_json()['FOM'] == 1.23456789012345
    assert recovered.config['USER_STORE'].get_affiliations('reader@example.invalid') == ['changed']
    assert recovered.extensions['cx_persistence'].read('artifacts', 'a.tgz') == b'new-bytes'


def test_uuid_lookup_uses_the_index_and_preserves_duplicate_filename_order(encrypted_app, storage, monkeypatch):
    identifier = '00000000-0000-0000-0000-000000000001'
    for stamp, value in (('010203', 'old'), ('020304', 'new')):
        name = f'result_20261104_{stamp}_{identifier}.json'
        storage.put_document('results', name, json.dumps({'_server_uuid': identifier, 'value': value}).encode())
    assert storage.candidates()['total'] == 2
    storage.rebuild()
    storage.check()
    monkeypatch.setattr(CxPersistence, 'names', lambda *args, **kwargs: pytest.fail('UUID lookup must not scan document names'))
    response = encrypted_app.test_client().get('/api/query/result', query_string={'uuid': identifier},
                                               headers={'X-API-Key': 'synthetic-key'})
    assert response.status_code == 200
    assert response.get_json()['value'] == 'new'
