"""Offline observations never imply unrecorded compute or Result outcomes."""

import copy
import json
import sys
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.execution_evidence import (ExecutionEvidenceStore, parse_evidence,
    validate_evidence, presentation, CURRENT, HISTORY)
from utils.execution_profiles import ExecutionProfileStore
from utils.execution_history import list_execution_history, summarize_execution_history
from test_execution_history import request as submission
from test_execution_profiles import _admin_app, _cleanup, _login_admin, _login_user
from test_cx_persistence import storage


def observation(record_id=1):
    return {'version': 1, 'source': 'manual', 'record_id': record_id,
        'project': 'gitlab.example.org/group/park', 'pipeline_id': 42,
        'observed_at': '2026-11-20T01:00:00Z',
        'pipelines': [{'project': 'gitlab.example.org/group/park', 'id': 42,
                       'parent': None, 'status': 'failed'}],
        'jobs': [{'project': 'gitlab.example.org/group/park', 'pipeline_id': 42,
                  'id': 90, 'name': 'batch-wait', 'stage': 'run', 'phase': 'queue',
                  'status': 'failed', 'compute': {
                      'scheduler': 'batch', 'job_id': '12345', 'started': None,
                      'status': 'unknown', 'exit_code': None, 'source': 'runner_record',
                      'observed_at': '2026-11-20T00:59:00Z'}}]}


@pytest.fixture
def bound(storage):
    profiles = ExecutionProfileStore(str(storage.path), key_file=storage.storage.key_file)
    record_id = submission(profiles)
    evidence = ExecutionEvidenceStore(storage)
    return profiles, evidence, observation(record_id)


def summaries(profiles):
    return [summarize_execution_history(run) for run in list_execution_history(profiles)]


def test_roundtrip_encrypted_without_result_and_idempotent(bound, storage):
    profiles, store, data = bound
    assert store.import_observation(data)
    assert not store.import_observation(data)
    envelope = next(iter(store.current(summaries(profiles)).values()))
    assert envelope['observation']['jobs'][0]['compute']['started'] is None
    assert presentation(envelope)['stages'] == 'run: failed'
    assert b'batch-wait' not in storage.path.read_bytes()
    assert not storage.path.read_bytes().startswith(b'SQLite format')
    storage.check()


def test_older_observation_archived_without_rewinding_and_conflicts_rollback(bound):
    profiles, store, data = bound
    store.import_observation(data)
    older = copy.deepcopy(data)
    older['observed_at'] = '2026-11-20T00:59:00Z'
    older['pipelines'][0]['status'] = 'running'
    store.import_observation(older)
    assert next(iter(store.current(summaries(profiles)).values()))['observation']['pipelines'][0]['status'] == 'failed'
    conflict = copy.deepcopy(data)
    conflict['pipelines'][0]['status'] = 'success'
    with pytest.raises(ValueError, match='Conflicting'):
        store.import_observation(conflict)
    with store.persistence._connect(readonly=True) as conn:
        assert conn.execute('SELECT COUNT(*) FROM cx_values WHERE namespace=?', (HISTORY,)).fetchone()[0] == 2


@pytest.mark.parametrize('change', ['host', 'pipeline', 'record', 'source'])
def test_binding_rejects_same_number_in_other_host_or_record(bound, change):
    profiles, store, data = bound
    if change == 'host':
        data['project'] = data['pipelines'][0]['project'] = data['jobs'][0]['project'] = 'other.example.org/group/park'
    elif change == 'pipeline':
        data['pipeline_id'] = data['pipelines'][0]['id'] = data['jobs'][0]['pipeline_id'] = 43
    elif change == 'record':
        data['record_id'] += 1
    else:
        data['source'] = 'runner'
    with pytest.raises(ValueError, match='recorded submission'):
        store.import_observation(data)
    assert store.current(summaries(profiles)) == {}


@pytest.mark.parametrize('status,dry_run', [('submit_failed', False), ('submitted', True), ('submission_unknown', False)])
def test_unaccepted_or_preview_cannot_import(storage, status, dry_run):
    profiles = ExecutionProfileStore(str(storage.path), key_file=storage.storage.key_file)
    record_id = submission(profiles, status=status, dry_run=dry_run)
    with pytest.raises(ValueError):
        ExecutionEvidenceStore(storage).import_observation(observation(record_id))


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(token='do-not-store'),
    lambda d: d.update(record_id=True),
    lambda d: d.update(observed_at='2026-11-20T01:00:00'),
    lambda d: d.update(project='https://gitlab.example.org/group/park'),
    lambda d: d.update(project='gitlab.example.org/../park'),
    lambda d: d['jobs'][0].update(name='bad\nlog'),
    lambda d: d['jobs'][0].update(phase='site-specific'),
    lambda d: d['jobs'][0].update(id=True),
    lambda d: d['jobs'][0]['compute'].update(started='yes'),
    lambda d: d['jobs'][0]['compute'].update(started=False, status='completed'),
    lambda d: d['jobs'][0]['compute'].update(observed_at='2027-01-01T00:00:00Z'),
    lambda d: d['jobs'].append(copy.deepcopy(d['jobs'][0])),
    lambda d: d['pipelines'].append(copy.deepcopy(d['pipelines'][0])),
    lambda d: d['pipelines'][0].update(parent={'project': d['project'], 'id': 42}),
    lambda d: d['jobs'][0].update(pipeline_id=999),
    lambda d: d.update(jobs=[d['jobs'][0]] * 1025),
])
def test_invalid_input_rejected(mutation):
    data = observation()
    mutation(data)
    with pytest.raises(ValueError):
        validate_evidence(data)


def test_duplicate_json_and_size_rejected():
    for raw in (b'{"version":1,"version":1}', b' ' * (1024 * 1024 + 1), b'\xff'):
        with pytest.raises(ValueError):
            parse_evidence(raw)


@pytest.mark.parametrize('status', ['success', 'failed', 'running'])
def test_no_jobs_does_not_infer_compute_state(status):
    data = observation()
    data['pipelines'][0]['status'] = status
    data['jobs'] = []
    view = presentation({'observation': validate_evidence(data), 'imported_at': data['observed_at']})
    assert view['status'] == status
    assert view['stages'] == 'Job stages unknown'


def test_timestamp_normalization_and_no_caller_alias():
    data = observation()
    data['observed_at'] = '2026-11-20T10:00:00+09:00'
    normalized = validate_evidence(data)
    data['jobs'][0]['compute']['job_id'] = 'changed'
    assert normalized['observed_at'] == '2026-11-20T01:00:00.000000+00:00'
    assert normalized['jobs'][0]['compute']['job_id'] == '12345'


def test_successful_compute_and_delivery_do_not_create_a_result(bound):
    profiles, store, data = bound
    data['pipelines'][0]['status'] = 'success'
    data['jobs'][0].update(status='success', phase='compute')
    data['jobs'][0]['compute'].update(started=True, status='completed', exit_code=0)
    delivery = copy.deepcopy(data['jobs'][0])
    delivery.update(id=91, name='deliver', stage='delivery', phase='delivery', compute=None)
    data['jobs'].append(delivery)
    store.import_observation(data)
    view = presentation(next(iter(store.current(summaries(profiles)).values())))
    assert view['status'] == 'success'
    assert view['observation']['jobs'][0]['compute']['exit_code'] == 0
    with store.persistence.snapshot() as snapshot:
        assert list(snapshot.records(store.persistence.directory)) == []


def test_history_remains_bounded_and_no_current_replacement(bound):
    profiles, store, data = bound
    for minute in range(22):
        value = copy.deepcopy(data)
        value['observed_at'] = f'2026-11-20T01:{minute:02d}:00Z'
        store.import_observation(value)
    page = store.observations(summaries(profiles)[0])
    assert len(page) == 20
    assert page[0]['observed_at'].startswith('2026-11-20T01:21:00')
    with store.persistence._connect(readonly=True) as conn:
        assert conn.execute('SELECT COUNT(*) FROM cx_values WHERE namespace=?', (HISTORY,)).fetchone()[0] == 22


def test_child_graph_explicit_cross_project_and_unknown_compute(bound):
    profiles, store, data = bound
    data['pipelines'].append({'project': 'child.example.org/team/compute', 'id': 42,
        'parent': {'project': data['project'], 'id': 42}, 'status': 'pending'})
    data['jobs'][0].update(project='child.example.org/team/compute', compute=None, status='pending')
    store.import_observation(data)
    result = next(iter(store.current(summaries(profiles)).values()))
    assert result['observation']['jobs'][0]['compute'] is None
    assert presentation(result)['stages'] == 'run: pending'
    assert presentation(result)['children'] == '#42: pending'
    invalid = copy.deepcopy(data)
    invalid['pipelines'][1]['parent']['id'] = 999
    with pytest.raises(ValueError, match='Unlinked'):
        validate_evidence(invalid)


def test_backup_includes_observations(bound, storage, tmp_path):
    profiles, store, data = bound
    store.import_observation(data)
    destination = tmp_path / 'backup' / 'cx.db'
    destination.parent.mkdir(mode=0o700)
    storage.backup(destination)
    from utils.cx_persistence import CxPersistence
    recovered = CxPersistence.open_existing(destination, storage.storage.key_file)
    recovered.check()
    assert ExecutionEvidenceStore(recovered).current(summaries(profiles))


def test_admin_display_without_result_scan_and_nonadmin_denied(bound, monkeypatch):
    profiles, store, data = bound
    data['jobs'][0]['name'] = '<script>alert(1)</script>'
    store.import_observation(data)
    app, paths = _admin_app(profiles.db_path)
    app.extensions['cx_persistence'] = store.persistence
    def forbidden(*args, **kwargs):
        raise AssertionError('Result lookup must not run')
    monkeypatch.setattr('routes.admin.execution_result_links', forbidden)
    try:
        client = app.test_client()
        url = f"/admin/execution-profiles/history/manual/{data['record_id']}/evidence"
        assert client.get(url).status_code in (302, 401, 403)
        _login_user(client)
        assert client.get(url).status_code in (302, 403)
        _login_admin(client)
        response = client.get(url)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert '12345' in html and 'Unknown / unknown / Unknown' in html
        assert '&lt;script&gt;' in html and '<script>alert' not in html
        assert client.get(url.replace('/manual/', '/runner/')).status_code == 404
        response = client.get('/admin/execution-profiles?tab=runs')
        assert response.status_code == 200
        assert 'CI observed: failed' in response.get_data(as_text=True)
    finally:
        _cleanup(paths)


def test_unavailable_does_not_create_plaintext_fallback(tmp_path):
    with pytest.raises(ValueError, match='Encrypted'):
        ExecutionEvidenceStore(None)


def test_scheduled_and_manual_ids_are_distinct(bound):
    profiles, store, data = bound
    payload = {'gitlab_project': data['project'], 'submit': {'response': {'id': 42}}}
    scheduled_id = profiles.create_trigger_run(trigger_id='nightly', trigger_type='scheduled',
        status='submitted', dry_run=False, payload=payload)
    scheduled = copy.deepcopy(data)
    scheduled.update(source='runner', record_id=scheduled_id)
    scheduled['jobs'][0]['status'] = 'running'
    store.import_observation(data)
    store.import_observation(scheduled)
    values = store.current(summaries(profiles))
    assert len(values) == 2
    assert values[f'manual:{data["record_id"]}']['observation']['jobs'][0]['status'] == 'failed'
    assert values[f'runner:{scheduled_id}']['observation']['jobs'][0]['status'] == 'running'


def test_transaction_failure_leaves_no_partial_observation(bound):
    profiles, store, data = bound
    with store.persistence.transaction() as conn:
        conn.execute("CREATE TRIGGER fail_evidence BEFORE INSERT ON cx_values WHEN NEW.namespace='execution_evidence_current' BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
    with pytest.raises(Exception):
        store.import_observation(data)
    with store.persistence._connect(readonly=True) as conn:
        assert conn.execute('SELECT COUNT(*) FROM cx_values WHERE namespace IN (?, ?)', (CURRENT, HISTORY)).fetchone()[0] == 0


def test_page_uses_one_connection_and_edit_does_not_read_evidence(bound, monkeypatch):
    profiles, store, data = bound
    store.import_observation(data)
    for pipeline in range(100, 139):
        submission(profiles, pipeline=pipeline)
    page = summaries(profiles)
    calls = []
    original = store.persistence._connect
    @contextmanager
    def counted(*args, **kwargs):
        calls.append(kwargs)
        with original(*args, **kwargs) as conn:
            yield conn
    monkeypatch.setattr(store.persistence, '_connect', counted)
    assert len(page) == 40
    assert len(store.current(page)) == 1
    assert calls == [{'readonly': True}]
    app, paths = _admin_app(profiles.db_path)
    app.extensions['cx_persistence'] = store.persistence
    def forbidden(*args, **kwargs):
        raise AssertionError('Editor must not read evidence')
    monkeypatch.setattr(ExecutionEvidenceStore, 'current', forbidden)
    try:
        client = app.test_client()
        _login_admin(client)
        for tab in ('profiles', 'triggers', 'diagnostics'):
            assert client.get('/admin/execution-profiles', query_string={'tab': tab}).status_code == 200
    finally:
        _cleanup(paths)


@pytest.mark.parametrize('module', [True, False])
def test_cli_import_modes(module):
    root = Path(__file__).resolve().parents[2]
    target = ['-m', 'result_server.execution_evidence'] if module else ['result_server/execution_evidence.py']
    result = subprocess.run([sys.executable, *target, '--help'], cwd=root,
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('module', [True, False])
def test_cli_actual_import_in_separate_process(bound, tmp_path, module):
    profiles, store, data = bound
    plan = tmp_path / 'plan.json'
    incoming = tmp_path / 'incoming.json'
    plan.write_text(json.dumps({'database': str(store.persistence.path), 'key_file': str(store.persistence.storage.key_file)}))
    incoming.write_text(json.dumps(data))
    plan.chmod(0o600)
    incoming.chmod(0o600)
    root = Path(__file__).resolve().parents[2]
    target = ['-m', 'result_server.execution_evidence'] if module else ['result_server/execution_evidence.py']
    result = subprocess.run([sys.executable, *target, '--plan', str(plan), '--input', str(incoming)],
        cwd=root, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'status': 'success', 'changed': True}
    assert store.current(summaries(profiles))


def test_public_projection_excludes_evidence(bound, tmp_path):
    from utils.public_projection import export_public
    profiles, store, data = bound
    store.import_observation(data)
    output = tmp_path / 'public'
    export_public(store.persistence, output)
    for path in output.rglob('*'):
        if path.is_file():
            assert b'batch-wait' not in path.read_bytes()
            assert b'execution_evidence' not in path.read_bytes()


def test_cli_private_input_and_sanitized_error(bound, tmp_path, capsys):
    from execution_evidence import main
    profiles, store, data = bound
    plan = tmp_path / 'plan.json'
    incoming = tmp_path / 'observation.json'
    plan.write_text(json.dumps({'database': str(store.persistence.path), 'key_file': str(store.persistence.storage.key_file)}))
    incoming.write_text(json.dumps(data))
    plan.chmod(0o600)
    incoming.chmod(0o600)
    assert main(['--plan', str(plan), '--input', str(incoming)]) == 0
    assert json.loads(capsys.readouterr().out)['changed'] is True
    incoming.write_text('{"token":"synthetic-secret-never-print"}')
    assert main(['--plan', str(plan), '--input', str(incoming)]) == 1
    output = capsys.readouterr().out
    assert 'synthetic-secret' not in output and str(tmp_path) not in output
