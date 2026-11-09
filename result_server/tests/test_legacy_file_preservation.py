"""Generated-copy acceptance of legacy retention without new public bindings."""

import hashlib
import json
from pathlib import Path
import sys

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip('sqlcipher3.dbapi2')

from utils.cx_persistence import CxPersistence
from utils import cx_migration
from utils.cx_migration import import_snapshot, recover_copy
from utils.encrypted_sqlite import EncryptedDatabaseError, generate_key
from utils.execution_profiles import ExecutionProfileStore
from utils.legacy_files import document_file_identity


@pytest.fixture
def snapshot(tmp_path):
    tmp_path.chmod(0o700)
    roots = {}
    for role in ('results', 'estimates', 'artifacts', 'inputs'):
        path = tmp_path / role
        path.mkdir(mode=0o700)
        roots[role] = str(path)
    for folder in ('keys', 'database', 'recovered'):
        (tmp_path / folder).mkdir(mode=0o700)
    key = tmp_path / 'keys/synthetic.key'
    generate_key(key)
    profile = tmp_path / 'profile.sqlite3'
    ExecutionProfileStore(str(profile)).migrate()
    result = 'result_20261106_010203_00000000-0000-4000-8000-000000000001.json'
    raw = b'{"code":"demo","system":"A","FOM":1.25,"confidential":["team"],"node_status_snapshot":{"artifact":{"type":"file_reference","path":"../../never-open.json"}}}'
    files = {('results', result): raw,
             ('results', 'padata_legacy.tgz'): b'synthetic opaque archive',
             ('estimates', 'estimate_.json'): b'{"unknown":{"preserve":true}}'}
    for (role, name), payload in files.items():
        (Path(roots[role]) / name).write_bytes(payload)
    store = CxPersistence(tmp_path / 'database/cx.sqlite3', key, roots=roots)
    return store, profile, roots, files


def test_explicit_migration_recovery_and_rebuild_keep_opaque_bytes(snapshot, tmp_path):
    store, profile, roots, files = snapshot
    original = {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
    report = import_snapshot(store, profile_copy=profile, source_roots=roots, preserve_legacy_files=True)
    assert report['legacy_files_preserved'] == 2
    assert report['objects']['results'] == 1 and report['objects']['estimates'] == 0
    assert sorted(store.names('legacy_files')) == ['estimates/estimate_.json', 'results/padata_legacy.tgz']
    assert store.names('estimates') == []
    assert store.candidates()['total'] == 0
    assert store.candidates(public_only=False, authenticated=True, affiliations=['team'])['total'] == 1
    assert store.candidates(public_only=False, authenticated=True, affiliations=['other'])['total'] == 0
    for (role, name), raw in files.items():
        if document_file_identity(role, name):
            assert store.read(role, name) == raw
        else:
            assert store.read('legacy_files', role + '/' + name) == raw
    store.rebuild()
    store.check()
    recovered = recover_copy(store, tmp_path / 'recovered/cx.sqlite3')
    for name in store.names('legacy_files'):
        assert store.read('legacy_files', name) == recovered.read('legacy_files', name)
    with recovered._connect(readonly=True) as conn:
        assert conn.execute('SELECT COUNT(*) FROM cx_identities').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM query_records').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM query_records WHERE directory=?', (roots['estimates'],)).fetchone()[0] == 0
    assert {k: hashlib.sha256((Path(roots[k[0]]) / k[1]).read_bytes()).hexdigest() for k in files} == original


def test_retained_file_change_is_rejected_before_final_snapshot_check(snapshot, monkeypatch):
    store, profile, roots, _ = snapshot
    original_put = store.put
    snapshot_files = cx_migration._snapshot_files
    scan_count = 0

    def initial_scan_only(roots):
        nonlocal scan_count
        scan_count += 1
        assert scan_count == 1, 'Migration reached the final snapshot comparison'
        return snapshot_files(roots)

    def put_and_change_source(role, name, source, **kwargs):
        result = original_put(role, name, source, **kwargs)
        if role == store.LEGACY_FILES_ROLE:
            with open(source.name, 'ab') as changed:
                changed.write(b' changed during import')
        return result

    monkeypatch.setattr(cx_migration, '_snapshot_files', initial_scan_only)
    monkeypatch.setattr(store, 'put', put_and_change_source)
    with pytest.raises(ValueError, match='^Snapshot changed while reading$'):
        import_snapshot(store, profile_copy=profile, source_roots=roots, preserve_legacy_files=True)
    assert scan_count == 1
    with store._connect(readonly=True) as conn:
        assert conn.execute('SELECT ready FROM catalog_state').fetchone()[0] == 0


def test_default_migration_still_rejects_non_json(snapshot):
    store, profile, roots, _ = snapshot
    with pytest.raises(ValueError, match='Unexpected non-JSON'):
        import_snapshot(store, profile_copy=profile, source_roots=roots)


@pytest.mark.parametrize('flag', [1, None, 'true'])
def test_preservation_requires_boolean(snapshot, flag):
    store, profile, roots, _ = snapshot
    with pytest.raises(ValueError, match='Explicit legacy preservation'):
        import_snapshot(store, profile_copy=profile, source_roots=roots, preserve_legacy_files=flag)
    assert not store.path.exists()


@pytest.mark.parametrize('name', ['../secret', 'results/../secret', '/results/file',
    'results/sub/file', 'unknown/file', 'results/file\n'])
def test_retained_names_cannot_escape_or_alias(name):
    with pytest.raises(ValueError):
        CxPersistence._object_name('legacy_files', name)


def test_retained_files_do_not_create_public_storage_binding(snapshot):
    store, profile, roots, _ = snapshot
    import_snapshot(store, profile_copy=profile, source_roots=roots, preserve_legacy_files=True)
    from utils.storage_files import binding, list_names
    app = Flask(__name__)
    app.extensions['cx_persistence'] = store
    with app.app_context():
        assert list_names(roots['estimates']) == []
        with pytest.raises(EncryptedDatabaseError, match='outside'):
            binding(str(Path(roots['results']).parent / 'legacy_files/results/padata_legacy.tgz'))


def test_retained_checksum_failure_is_not_ignored(snapshot):
    store, profile, roots, _ = snapshot
    import_snapshot(store, profile_copy=profile, source_roots=roots, preserve_legacy_files=True)
    with store.blobs.connect() as conn:
        conn.execute("UPDATE chunks SET data=? WHERE role='legacy_files'", (b'changed',))
        conn.commit()
    with pytest.raises(EncryptedDatabaseError):
        store.check()


def test_canonical_duplicate_rejection_is_not_relaxed(snapshot):
    store, profile, roots, files = snapshot
    name = next(name for role, name in files if document_file_identity(role, name))
    (Path(roots['results']) / name).write_bytes(b'{"FOM":1,"FOM":1}')
    with pytest.raises(ValueError, match='Duplicate JSON object member'):
        import_snapshot(store, profile_copy=profile, source_roots=roots, preserve_legacy_files=True)


def test_cli_exposes_explicit_copy_preservation(snapshot, tmp_path, capsys):
    store, profile, roots, _ = snapshot
    from cx_storage import main
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'database': str(store.path), 'key_file': str(store.storage.key_file),
        'roots': roots, 'profile_copy': str(profile), 'source_roots': roots, 'preserve_legacy_files': True}))
    plan.chmod(0o600)
    assert main(['migrate-copy', '--plan', str(plan)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['legacy_files_preserved'] == 2
