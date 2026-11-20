"""Execution receipt lookup over disposable catalogs and encrypted synthetic data."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.execution_history import execution_result_links
from utils.result_catalog import ResultCatalog, CatalogUnavailable
from utils.result_query_reader import ResultQueryReader


PROJECT = 'gitlab.example.org/team/benchmarks'
OTHER = 'old.example.org/team/benchmarks'


def run(number=1, pipeline=42, project=PROJECT, **response):
    return {'id': number, 'status': 'submitted', 'dry_run': False,
            'payload_json': {'gitlab_project': project, 'payload': {'variables': {}},
                             'submit': {'response': {'id': pipeline, **response}}}}


@pytest.fixture(params=['files', 'encrypted'])
def indexed(request, tmp_path):
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    if request.param == 'encrypted':
        pytest.importorskip('sqlcipher3.dbapi2')
        from utils.cx_persistence import CxPersistence
        from utils.encrypted_sqlite import generate_key
        for role in ('results', 'estimates', 'artifacts', 'inputs', 'private', 'keys'):
            (tmp_path / role).mkdir(mode=0o700)
        key = tmp_path / 'keys/key'
        generate_key(key)
        store = CxPersistence(tmp_path / 'private/db', key, roots={
            role: str(tmp_path / role) for role in ('results', 'estimates', 'artifacts', 'inputs')})
        app = Flask(__name__)
        app.extensions['cx_persistence'] = store
        with app.app_context():
            store.initialize()
    else:
        results, private = tmp_path / 'results', tmp_path / 'catalog'
        results.mkdir()
        private.mkdir(mode=0o700)
        store = ResultCatalog(private / 'index.db', results)
        store.initialize()
        store.rebuild()
        app = Flask(__name__)
    app.config['RESULT_CATALOG_PATH'] = str(store.path)

    def put(name, payload):
        raw = json.dumps(payload).encode()
        if request.param == 'encrypted':
            store.put_document('results', name, raw, update_metadata=False)
        else:
            store.replace(name, payload, lambda: (Path(store.directory) / name).write_bytes(raw))
        (legacy / name).write_bytes(raw)

    def lookup(runs, **kwargs):
        with app.app_context():
            return execution_result_links(store.directory, runs, **kwargs)

    def scan(runs, **kwargs):
        return execution_result_links(str(legacy), runs, **kwargs)

    return SimpleNamespace(store=store, app=app, put=put, lookup=lookup, scan=scan,
                           legacy=legacy, backend=request.param)


def test_parent_child_duplicates_and_project_boundaries_match_scan(indexed):
    fixtures = {
        'result_20260101_000001_a.json': {'pipeline_id': 101, 'parent_pipeline_id': 42, 'ci_project': PROJECT},
        'result_20260101_000002_b.json': {'pipeline_id': '42', 'ci_project': PROJECT + '.git'},
        'result_20260101_000003_c.json': {'pipeline_id': 42, 'ci_project': OTHER},
        'result_20260101_000004_d.json': {'pipeline_id': 42},
        'result_20260101_000005_e.json': {'pipeline_id': 42, 'execution_backend': 'benchpark'},
        'result_20260101_000006_f.json': {'execution_trigger': {'id': 'reusable-profile'}},
    }
    for name, data in fixtures.items():
        indexed.put(name, dict(data, _server_uuid='same-uuid', Exp='case'))
    for runs, projects in [([run()], None),
                           ([run(), run(2, project=OTHER)], None),
                           ([run()], {'42': {PROJECT, OTHER}}),
                           ([run(project='')], None),
                           ([run(pipeline=101)], None),
                           ([run(pipeline=7, child_pipeline_ids=[42, 101])], None)]:
        assert indexed.lookup(runs, pipeline_projects=projects) == indexed.scan(runs, pipeline_projects=projects)


def test_only_matching_documents_are_loaded(indexed, monkeypatch):
    for number in range(250):
        indexed.put(f'result_20260101_000000_{number}.json',
                    {'pipeline_id': number + 1000, 'ci_project': PROJECT})
    target = 'result_20260101_000001_target.json'
    indexed.put(target, {'pipeline_id': 101, 'parent_pipeline_id': 42, 'ci_project': PROJECT})
    from utils import trigger_display
    original = trigger_display._load_result_json
    read = []
    def load(name, directory):
        read.append(name)
        return original(name, directory)
    def enumeration(*args):
        raise AssertionError('Indexed history must not enumerate all Results')
    monkeypatch.setattr(trigger_display, '_load_result_json', load)
    monkeypatch.setattr(trigger_display, '_os_listdir', enumeration)
    links = indexed.lookup([run()])
    assert [item['filename'] for item in links[1]] == [target]
    assert read == [target]


def test_replacement_rebuild_and_old_database_read_only_fallback(indexed):
    name = 'result_20260101_000001_replace.json'
    indexed.put(name, {'pipeline_id': 42, 'ci_project': PROJECT})
    assert indexed.lookup([run()]) == indexed.scan([run()])
    indexed.put(name, {'pipeline_id': 99, 'ci_project': PROJECT})
    assert indexed.lookup([run()]) == {}
    assert indexed.lookup([run(pipeline=99)]) == indexed.scan([run(pipeline=99)])
    with indexed.store._connect() as conn:
        for operation in ('insert', 'update', 'delete'):
            conn.execute('DROP TRIGGER execution_lookup_' + operation)
        conn.execute('DROP TABLE execution_pipeline_refs')
        conn.execute('DROP TABLE execution_lookup_state')
        conn.commit()
    indexed.put('result_20260101_000002_legacy_receipt.json', {'pipeline_id': 99, 'ci_project': PROJECT})
    assert indexed.lookup([run(pipeline=99)]) == indexed.scan([run(pipeline=99)])
    with indexed.store._connect(readonly=True) as conn:
        assert not ResultCatalog._has_execution_index(conn)
    indexed.store.rebuild()
    with indexed.store.snapshot() as reader:
        assert reader.conn.execute('SELECT ready FROM execution_lookup_state').fetchone()[0] == 1
    assert indexed.lookup([run(pipeline=99)]) == indexed.scan([run(pipeline=99)])


def test_failed_replace_does_not_publish_index(indexed, monkeypatch):
    name = 'result_20260101_000001_atomic.json'
    indexed.put(name, {'pipeline_id': 42, 'ci_project': PROJECT})
    before = indexed.lookup([run()])
    original = ResultCatalog._put_execution.__func__
    def fail(cls, conn, filename, payload, *, ready):
        original(cls, conn, filename, payload, ready=ready)
        raise ValueError('synthetic index failure')
    monkeypatch.setattr(ResultCatalog, '_put_execution', classmethod(fail))
    with pytest.raises(ValueError):
        indexed.put(name, {'pipeline_id': 99, 'ci_project': PROJECT})
    if indexed.backend == 'encrypted':
        assert indexed.lookup([run()]) == before
        assert indexed.lookup([run(pipeline=99)]) == {}
    else:
        with pytest.raises(OSError):
            indexed.lookup([run()])


def test_index_is_only_a_candidate_not_proof_of_a_match(indexed):
    name = 'result_20260101_000001_candidate.json'
    indexed.put(name, {'pipeline_id': 99, 'ci_project': PROJECT})
    with indexed.store._connect() as conn:
        conn.execute('UPDATE execution_pipeline_refs SET pipeline_id=?', ('42',))
        conn.commit()
    assert indexed.lookup([run()]) == {}


def test_encrypted_integrity_check_verifies_pipeline_projection(indexed):
    if indexed.backend != 'encrypted':
        pytest.skip('Encrypted copy integrity check')
    from utils.encrypted_sqlite import EncryptedDatabaseError
    indexed.put('result_20260101_000001_integrity.json', {'pipeline_id': 42, 'ci_project': PROJECT})
    indexed.store.check()
    with indexed.store._connect() as conn:
        conn.execute('UPDATE execution_pipeline_refs SET ci_project=?', (OTHER,))
        conn.commit()
    with pytest.raises(EncryptedDatabaseError, match='Execution lookup disagrees'):
        indexed.store.check()
    indexed.store.rebuild()
    indexed.store.check()


def test_invalid_index_is_unavailable_not_zero_results(indexed):
    with indexed.store._connect() as conn:
        conn.execute('UPDATE execution_lookup_state SET ready=0')
        conn.commit()
    with pytest.raises(OSError):
        indexed.lookup([run()])


def test_execution_candidates_use_covering_index(indexed):
    indexed.put('result_20260101_000001_plan.json', {'pipeline_id': 42, 'ci_project': PROJECT})
    with indexed.store.snapshot() as reader:
        plan = reader.conn.execute('''EXPLAIN QUERY PLAN SELECT filename
            FROM execution_pipeline_refs WHERE pipeline_id=? AND ci_project IN ('',?)''',
            ('42', PROJECT)).fetchall()
    assert any('execution_pipeline_lookup' in row[3] and 'SEARCH' in row[3] for row in plan)


def test_writer_without_execution_hook_invalidates_index_until_rebuild(indexed):
    name = 'result_20260101_000001_old_writer.json'
    indexed.put(name, {'pipeline_id': 42, 'ci_project': PROJECT})
    # Older supported writers still update result_entries, but not this new index.
    with indexed.store._connect() as conn:
        conn.execute('UPDATE result_entries SET group_id=group_id WHERE filename=?', (name,))
        conn.commit()
    with pytest.raises(OSError):
        indexed.lookup([run()])
    indexed.put('result_20260101_000002_new_writer.json', {'pipeline_id': 42, 'ci_project': PROJECT})
    with pytest.raises(OSError):
        indexed.lookup([run()])
    indexed.store.rebuild()
    assert indexed.lookup([run()]) == indexed.scan([run()])


def test_ineligible_history_does_not_resolve_any_result(indexed, monkeypatch):
    def denied(*args):
        raise AssertionError('Preview and non-submitted history must not query Results')
    monkeypatch.setattr(ResultQueryReader, 'execution_candidates', denied)
    assert indexed.lookup([dict(run(), status='submission_unknown'), dict(run(2), dry_run=True)]) == {}


def test_encrypted_candidates_and_documents_use_one_snapshot(indexed, monkeypatch):
    if indexed.backend != 'encrypted':
        pytest.skip('Encrypted WAL snapshot behavior')
    name = 'result_20260101_000001_snapshot.json'
    indexed.put(name, {'pipeline_id': 42, 'ci_project': PROJECT})
    expected = indexed.lookup([run()])
    original = ResultQueryReader.execution_candidates
    def replacing(reader, runs):
        names = original(reader, runs)
        indexed.put(name, {'pipeline_id': 99, 'ci_project': PROJECT})
        return names
    with monkeypatch.context() as patch:
        patch.setattr(ResultQueryReader, 'execution_candidates', replacing)
        assert indexed.lookup([run()]) == expected
    assert indexed.lookup([run()]) == {}


def test_plaintext_reader_excludes_concurrent_json_writer(indexed, monkeypatch):
    if indexed.backend != 'files':
        pytest.skip('Plaintext filesystem writer lock')
    name = 'result_20260101_000001_snapshot.json'
    indexed.put(name, {'pipeline_id': 42, 'ci_project': PROJECT})
    expected = indexed.lookup([run()])
    original = ResultQueryReader.execution_candidates
    def replacing(reader, runs):
        names = original(reader, runs)
        with pytest.raises(CatalogUnavailable, match='busy'):
            indexed.put(name, {'pipeline_id': 99, 'ci_project': PROJECT})
        return names
    monkeypatch.setattr(ResultQueryReader, 'execution_candidates', replacing)
    assert indexed.lookup([run()]) == expected


def test_plaintext_delete_removes_pipeline_candidates(indexed):
    if indexed.backend != 'files':
        pytest.skip('Plaintext lifecycle hook')
    name = 'result_20260101_000001_delete.json'
    indexed.put(name, {'pipeline_id': 42, 'ci_project': PROJECT})
    indexed.store.delete(name, lambda: (Path(indexed.store.directory) / name).unlink())
    assert indexed.lookup([run()]) == {}
