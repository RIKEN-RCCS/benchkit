"""Synthetic snapshot, authorization and UUID-index equivalence checks."""

from contextlib import contextmanager
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest
from flask import session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip('sqlcipher3.dbapi2')
from test_cx_persistence import storage, encrypted_app
from test_support import StaticAffiliationUserStore
from utils.document_snapshot import document_snapshot, current_snapshot
from utils.estimate_lineage import build_estimate_lineage
from utils.storage_files import read_json, is_file, list_names
from utils.results_loader import load_results_table, load_estimated_results_table


SOURCE, OTHER, PARENT, CHILD = [str(UUID(int=i)) for i in range(10, 14)]


def estimate(uid=CHILD, parent=PARENT, source=SOURCE):
    return {'estimate_metadata': {'estimation_result_uuid': uid, 'source_result_uuid': source},
            'reestimation': {'previous_estimation_result_uuid': parent}}


def put(storage, role, uid, payload, *, prefix='record'):
    name = f'{prefix}_20260101_000000_{uid}.json'
    raw = json.dumps(payload).encode()
    storage.put_document(role, name, raw, update_metadata=False)
    # The legacy comparison uses identical synthetic files, not exported live data.
    (Path(storage.roots[role]) / name).write_bytes(raw)
    return name


def compare_lineage(app, storage, payload, filename, affiliations):
    app.config['USER_STORE'] = StaticAffiliationUserStore({'reader@example.invalid': affiliations})
    with app.test_request_context():
        session.update(authenticated=True, user_email='reader@example.invalid')
        actual = build_estimate_lineage(payload, filename, estimate=True)
        app.extensions.pop('cx_persistence')
        try:
            expected = build_estimate_lineage(payload, filename, estimate=True)
        finally:
            app.extensions['cx_persistence'] = storage
    assert actual == expected
    return actual


@pytest.mark.parametrize('affiliations', [[], ['dev'], ['other'], ['admin'], ['dev', 'other']])
@pytest.mark.parametrize('scenario', [
    'normal', 'duplicate_source', 'hidden_source', 'filename_mismatch', 'invalid_declared',
    'uppercase', 'compact', 'braces', 'urn', 'uppercase_filename', 'filename_only', 'parent_duplicate',
    'hidden_parent', 'cross_family_duplicate', 'cycle', 'parent_conflict', 'source_conflict',
    'unrelated_invalid_json', 'unrelated_nonobject_json', 'large_source',
])
def test_lineage_matches_legacy(encrypted_app, storage, affiliations, scenario):
    source = {'_server_uuid': SOURCE}
    if scenario == 'hidden_source':
        source['confidential'] = ['dev']
    if scenario == 'filename_mismatch':
        source['_server_uuid'] = OTHER
    if scenario == 'invalid_declared':
        source['_server_uuid'] = 'not-a-uuid'
    if scenario in ('uppercase', 'compact', 'braces', 'urn'):
        # Include alphabetic digits so uppercase is not a vacuous test.
        source['_server_uuid'] = {'uppercase': SOURCE.upper(), 'compact': SOURCE.replace('-', ''),
                                  'braces': '{' + SOURCE + '}', 'urn': 'urn:uuid:' + SOURCE}[scenario]
    if scenario in ('filename_only', 'uppercase_filename'):
        source.pop('_server_uuid')
    if scenario == 'large_source':
        source['padding'] = 'x' * (1024 * 1024 + 100)
    source_filename_uuid = OTHER if scenario in ('uppercase', 'compact', 'braces', 'urn') else SOURCE
    put(storage, 'results', SOURCE.upper() if scenario == 'uppercase_filename' else source_filename_uuid, source)
    if scenario == 'duplicate_source':
        put(storage, 'results', SOURCE, source, prefix='duplicate')
    parent = estimate(PARENT, None)
    if scenario == 'hidden_parent':
        parent['confidential'] = ['dev']
    if scenario == 'cycle':
        parent['reestimation']['previous_estimation_result_uuid'] = CHILD
    put(storage, 'estimates', PARENT, parent)
    if scenario in ('parent_duplicate', 'cross_family_duplicate'):
        put(storage, 'estimates', PARENT,
            estimate(PARENT, None, OTHER if scenario == 'cross_family_duplicate' else SOURCE), prefix='duplicate')
    child = estimate()
    if scenario == 'parent_conflict':
        child['reestimation']['source_estimate_result_uuid'] = OTHER
    if scenario == 'source_conflict':
        child['reestimation']['source_result_uuid'] = OTHER
    name = put(storage, 'estimates', CHILD, child)
    if scenario in ('unrelated_invalid_json', 'unrelated_nonobject_json'):
        import io
        name_bad = 'bad.json'
        raw = b'{bad' if scenario == 'unrelated_invalid_json' else b'[]'
        with storage.transaction() as conn:
            storage.put('results', name_bad, io.BytesIO(raw), limit=len(raw), conn=conn)
        (Path(storage.roots['results']) / name_bad).write_bytes(raw)
    compare_lineage(encrypted_app, storage, child, name, affiliations)


def test_snapshot_pins_payload_index_and_names(storage, encrypted_app):
    storage = encrypted_app.extensions['cx_persistence']
    name = put(storage, 'results', SOURCE, {'_server_uuid': SOURCE, 'system': 'old'})
    root = Path(storage.roots['results'])
    with encrypted_app.app_context():
        with storage.snapshot() as reader:
            first, _ = reader.result_page(public_only=True, authenticated=False, affiliations=[], page=1, per_page=50)
            storage.put_document('results', name, json.dumps({'_server_uuid': OTHER, 'system': 'new'}).encode(), update_metadata=False)
            put(storage, 'results', OTHER, {'_server_uuid': OTHER}, prefix='new')
            assert first == [name]
            assert list_names(root) == [name]
            assert is_file(root / name)
            document = read_json(root / name)
            assert document['system'] == 'old'
            document['system'] = 'mutated by caller'
            assert read_json(root / name)['system'] == 'old'
            assert current_snapshot(storage).source_names(SOURCE) == [name]
        assert read_json(root / name)['system'] == 'new'
        assert current_snapshot(storage) is None


def test_snapshot_reset_on_exception_and_instance_isolation(storage, encrypted_app):
    with encrypted_app.app_context():
        with pytest.raises(RuntimeError, match='synthetic'):
            with document_snapshot() as first:
                with document_snapshot() as nested:
                    assert first is nested
                    assert current_snapshot(object()) is None
                raise RuntimeError('synthetic')
        assert current_snapshot(storage) is None


@pytest.mark.parametrize('count', [1, 50])
def test_list_and_lineage_connection_count_is_bounded(storage, encrypted_app, monkeypatch, count):
    storage = encrypted_app.extensions['cx_persistence']
    from utils.encrypted_sqlite import EncryptedSQLite
    for number in range(count):
        put(storage, 'results', str(UUID(int=number + 100)), {'system': 'A', 'code': 'demo'})
    put(storage, 'results', SOURCE, {'_server_uuid': SOURCE})
    name = put(storage, 'estimates', CHILD, estimate())
    opens = []
    original = EncryptedSQLite.connect

    @contextmanager
    def connect(self, **kwargs):
        opens.append(self.path)
        with original(self, **kwargs) as conn:
            yield conn

    monkeypatch.setattr(EncryptedSQLite, 'connect', connect)
    with encrypted_app.test_request_context():
        session.update(authenticated=True, user_email='reader@example.invalid')
        encrypted_app.config['USER_STORE'] = StaticAffiliationUserStore({'reader@example.invalid': []})
        with storage.snapshot() as reader:
            load_results_table(storage.directory, query_reader=reader, per_page=50,
                               padata_directory=storage.roots['artifacts'])
        assert len(opens) == 1
        opens.clear()
        load_estimated_results_table(storage.roots['estimates'])
        assert len(opens) == 1
        opens.clear()
        history = build_estimate_lineage(estimate(), name, estimate=True)
        assert history['source_link']
        assert len(opens) == 1


def test_uuid_lookup_uses_existing_index_and_verifies_payload(storage, encrypted_app):
    name = put(storage, 'results', SOURCE, {'_server_uuid': OTHER})
    put(storage, 'estimates', CHILD, estimate())
    with encrypted_app.test_request_context():
        with document_snapshot() as reader:
            plan = reader.conn.execute('EXPLAIN QUERY PLAN SELECT name FROM cx_identities '
                'WHERE role=? AND identifier=?', ('results', SOURCE)).fetchall()
            assert any('cx_identity_lookup' in str(tuple(row)) for row in plan)
            assert reader.source_names(SOURCE) == [name]
    history = compare_lineage(encrypted_app, storage, estimate(), 'estimate.json', [])
    assert not history['source_link']


def test_authorization_uses_snapshot_without_cross_operation_cache(storage, encrypted_app):
    from utils.cx_identity import EncryptedUserStore
    storage = encrypted_app.extensions['cx_persistence']
    users = EncryptedUserStore(storage)
    users.create_user('reader@example.invalid', 'synthetic', ['dev'])
    encrypted_app.config['USER_STORE'] = users
    source = {'_server_uuid': SOURCE, 'confidential': ['dev']}
    put(storage, 'results', SOURCE, source)
    name = put(storage, 'estimates', CHILD, estimate())
    with encrypted_app.test_request_context():
        session.update(authenticated=True, user_email='reader@example.invalid')
        with document_snapshot():
            assert users.get_affiliations('reader@example.invalid') == ['dev']
            users.update_affiliations('reader@example.invalid', [])
            assert build_estimate_lineage(estimate(), name, estimate=True)['source_link']
        assert not build_estimate_lineage(estimate(), name, estimate=True)['source_link']


def test_checksum_errors_are_not_cached_or_suppressed(storage, encrypted_app):
    from utils.encrypted_sqlite import EncryptedDatabaseError
    storage = encrypted_app.extensions['cx_persistence']
    name = put(storage, 'results', SOURCE, {'_server_uuid': SOURCE})
    with storage.transaction() as conn:
        conn.execute('UPDATE cx_objects SET sha256=? WHERE role=? AND name=?', ('bad', 'results', name))
    with encrypted_app.app_context():
        with pytest.raises(EncryptedDatabaseError, match='checksum'):
            with document_snapshot():
                read_json(Path(storage.roots['results']) / name)
        assert current_snapshot(storage) is None


def test_public_and_anonymous_lineage_do_not_open_snapshot(encrypted_app, monkeypatch):
    @contextmanager
    def forbidden(*args, **kwargs):
        raise AssertionError('Snapshot should not be opened')
        yield
    monkeypatch.setattr('utils.document_snapshot.document_snapshot', forbidden)
    with encrypted_app.test_request_context():
        assert build_estimate_lineage({}, 'result.json') is None
        session['authenticated'] = True
        encrypted_app.config['PUBLIC_PORTAL_MODE'] = True
        assert build_estimate_lineage({}, 'result.json') is None


def test_private_records_and_user_affiliations_share_connection(storage, encrypted_app, monkeypatch):
    from utils.cx_identity import EncryptedUserStore
    storage = encrypted_app.extensions['cx_persistence']
    users = EncryptedUserStore(storage)
    users.create_user('reader@example.invalid', 'synthetic', ['dev'])
    encrypted_app.config['USER_STORE'] = users
    put(storage, 'results', SOURCE, {'_server_uuid': SOURCE, 'confidential': ['dev']})
    for number in range(40):
        put(storage, 'estimates', str(UUID(int=number + 100)),
            {**estimate(str(UUID(int=number + 100))), 'confidential': ['dev']})
    opens = []
    original = storage._connect

    @contextmanager
    def connect(**kwargs):
        opens.append(1)
        with original(**kwargs) as conn:
            yield conn

    monkeypatch.setattr(storage, '_connect', connect)
    with encrypted_app.test_request_context():
        session.update(authenticated=True, user_email='reader@example.invalid')
        history = build_estimate_lineage(estimate(), 'estimate.json', estimate=True)
        assert len(history['rows']) == 40 and history['source_link']
    assert len(opens) == 1


def test_detail_document_and_lineage_use_same_snapshot(storage, encrypted_app, monkeypatch):
    storage = encrypted_app.extensions['cx_persistence']
    put(storage, 'results', SOURCE, {'_server_uuid': SOURCE})
    selected = estimate()
    name = put(storage, 'estimates', CHILD, selected)
    encrypted_app.config['USER_STORE'] = StaticAffiliationUserStore({'reader@example.invalid': []})

    def concurrent_update(result):
        assert result == selected
        storage.put_document('estimates', name, json.dumps(estimate(source=OTHER)).encode(), update_metadata=False)
        return {}

    monkeypatch.setattr('routes.estimated_detail_routes.build_estimated_detail_context', concurrent_update)
    monkeypatch.setattr('routes.estimated_detail_routes.render_template', lambda template, **context: context)
    with encrypted_app.test_request_context():
        session.update(authenticated=True, user_email='reader@example.invalid')
        context = encrypted_app.view_functions['estimated.estimated_detail'](name)
        assert context['result'] == selected
        assert context['estimate_lineage']['source_uuid'] == SOURCE
        assert len(context['estimate_lineage']['rows']) == 1
        assert current_snapshot(storage) is None


def test_multiple_lineages_share_verified_documents(storage, encrypted_app, monkeypatch):
    storage = encrypted_app.extensions['cx_persistence']
    put(storage, 'results', SOURCE, {'_server_uuid': SOURCE})
    name = put(storage, 'estimates', CHILD, estimate())
    encrypted_app.config['USER_STORE'] = StaticAffiliationUserStore({'reader@example.invalid': []})
    reads = []
    original = storage.chunks

    def chunks(role, name, **kwargs):
        reads.append((role, name))
        yield from original(role, name, **kwargs)

    monkeypatch.setattr(storage, 'chunks', chunks)
    with encrypted_app.test_request_context():
        session.update(authenticated=True, user_email='reader@example.invalid')
        with document_snapshot():
            first = build_estimate_lineage(estimate(), name, estimate=True)
            second = build_estimate_lineage(estimate(), name, estimate=True)
            assert first == second
        assert len(reads) == 2 and len(set(reads)) == 2
