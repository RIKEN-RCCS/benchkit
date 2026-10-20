"""Benchpark profiles use the same manual/scheduled execution and result views."""
import copy
import json
from datetime import UTC, datetime

import pytest

from test_execution_profiles import _admin_app, _cleanup, _login_admin, _profile
from routes.admin import _build_execution_pipeline_plan
from trigger_runner import run_triggers
from utils.execution_profiles import ExecutionProfileStore, normalize_profile, normalize_trigger_definition
from utils.gitlab_pipeline import build_profile_pipeline_plan, GitLabPipelineSubmitResult
from utils.result_detail_view import build_result_detail_context
from utils.result_table_rows import build_result_table_row
from utils.trigger_display import build_trigger_run_lookup, summarize_execution_trigger, build_trigger_result_links


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TARGETS', 'kit=gitlab.example.org/group/kit,park=swc.example.org/group/park')
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TARGET_BACKENDS', '{"park":"benchpark"}')
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TRIGGER_TOKEN_PARK', 'fake-park-token')
    monkeypatch.setenv('RESULT_SERVER_PUBLIC_URL', 'https://results.example.org/dev2')
    return _profile(id='park-qws', code=['qws'], system=['ExampleSystem'], exp=[],
                    allocation_project_id='', scheduler_extra_args='',
                    metadata_json={'terms_version': 'v1', 'pipeline': {
                        'backend': 'benchpark', 'gitlab_target': 'park',
                        'site': 'example-site', 'experiment_config': 'config/experiments/qws.yaml'}})


def plan(profile, **overrides):
    values = dict(profile=profile, allocation_project_id='', gitlab_repo='swc.example.org/group/park',
                  target_ref='main', result_server_url='https://results.example.org/dev2', target_id='park')
    values.update(overrides)
    return build_profile_pipeline_plan(**values)


def test_profile_roundtrip_and_plan(configured, tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'profiles.sqlite'))
    store.upsert_profile(configured, actor='admin@example.org')
    restored = store.list_profiles()[0]
    result = plan(restored)
    assert result.errors == []
    assert result.payload == {'ref': 'main', 'variables': {
        'SITE': 'example-site', 'EXPERIMENT_CONFIG': 'config/experiments/qws.yaml',
        'BK_PIPELINE_BACKEND': 'benchpark', 'BK_PORTAL_MANAGED': '1',
        'BK_EXECUTION_ACTIVITY': 'FutureSystem',
        'BK_PORTAL_RESULT_SERVER': 'https://results.example.org/dev2'}}
    assert restored['metadata_json'] == configured['metadata_json']


@pytest.mark.parametrize('values', [
    {'target_id': 'kit'}, {'target_ref': ''}, {'result_server_url': ''},
    {'result_server_url': 'http://results.example.org'}, {'result_server_url': 'https://'},
    {'result_server_url': 'https://user:password@example.org'},
    {'result_server_url': 'https://results.example.org/ bad'}, {'allocation_project_id': 'account'},
    {'code': 'other'}, {'system': 'OtherSystem'}])
def test_invalid_destination_or_selection_blocks(configured, values):
    assert plan(configured, **values).errors


@pytest.mark.parametrize('key,value', [
    ('site', '../other'), ('site', 'site;command'), ('experiment_config', '../../secret.yaml'),
    ('experiment_config', 'config/experiments/sub/file.yaml'), ('gitlab_target', ''), ('backend', 'unknown')])
def test_invalid_profile_inputs_are_rejected(configured, key, value):
    raw = copy.deepcopy(configured)
    raw['metadata_json']['pipeline'][key] = value
    assert normalize_profile(raw)[1]


def test_backend_declaration_is_required(configured, monkeypatch):
    monkeypatch.delenv('RESULT_SERVER_GITLAB_TARGET_BACKENDS')
    assert plan(configured).errors
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TARGET_BACKENDS', '[]')
    assert plan(configured).errors


def test_benchkit_profile_cannot_use_benchpark_target(configured):
    raw = copy.deepcopy(configured)
    raw['metadata_json'].pop('pipeline')
    assert plan(raw).errors


def test_manual_plan_and_form_roundtrip_only_adds_benchpark_settings(configured, tmp_path):
    db = tmp_path / 'portal.sqlite'
    store = ExecutionProfileStore(str(db))
    store.upsert_profile(configured, actor='admin@test.com')
    app, dirs = _admin_app(db)
    try:
        with app.test_client() as client:
            _login_admin(client)
            response = client.post('/admin/execution-profiles/upsert', data={
                'id': 'park-qws', 'status': 'approved', 'activity': 'FutureSystem',
                'code': 'qws', 'system': 'ExampleSystem', 'pipeline_backend': 'benchpark',
                'benchpark_gitlab_target': 'park', 'benchpark_site': 'example-site',
                'benchpark_experiment_config': 'config/experiments/qws.yaml'})
            assert response.status_code == 302
            response = client.get('/admin/execution-profiles?edit=park-qws')
            assert b'example-site' in response.data
            assert b'config/experiments/qws.yaml' in response.data
        assert 'terms_version' not in store.list_profiles()[0]['metadata_json']
        with app.test_request_context('/admin/execution-profiles/submit-dry-run', method='POST', data={
            'profile_id': 'park-qws', 'gitlab_target': 'park', 'target_ref': 'main'}):
            manual = _build_execution_pipeline_plan(store)
        assert manual['errors'] == []
        assert manual['plan'].payload['variables']['SITE'] == 'example-site'
        assert manual['plan'].payload['variables']['BK_TRIGGER_TYPE'] == 'manual_button'
    finally:
        _cleanup(dirs)


def test_scheduled_runs_use_same_inputs_and_deduplicate(configured, tmp_path):
    db = tmp_path / 'portal.sqlite'
    store = ExecutionProfileStore(str(db))
    store.upsert_profile(configured, actor='admin@test.com')
    trigger, errors = normalize_trigger_definition({
        'id': 'park-daily', 'profile_id': 'park-qws', 'trigger_type': 'scheduled',
        'gitlab_target': 'park', 'target_ref': 'main', 'enabled': True,
        'cron_expr': '0 10 * * *', 'timezone': 'Asia/Tokyo'})
    assert not errors
    store.upsert_trigger_definition(trigger, actor='admin@test.com')
    submitted = []
    def fake_submit(planned, *, token):
        submitted.append((planned, token))
        return GitLabPipelineSubmitResult(201, {'id': 42}, [])
    args = dict(db_path=str(db), dry_run=False, result_server_url='https://results.example.org/dev2',
                submit=True, submit_pipeline=fake_submit, use_lock=False)
    first = run_triggers(**args, now=datetime(2026, 10, 20, 1, 0, 15, tzinfo=UTC))
    second = run_triggers(**args, now=datetime(2026, 10, 20, 1, 0, 45, tzinfo=UTC))
    assert first[0].status == 'submitted'
    assert second[0].status == 'already_submitted'
    assert len(submitted) == 1
    variables = submitted[0][0].payload['variables']
    assert variables['SITE'] == 'example-site'
    assert variables['BK_TRIGGER_TYPE'] == 'scheduled'
    assert variables['BK_TRIGGER_REASON'].startswith('cron:0 10 * * *@2026-10-20T10:00')
    assert submitted[0][1] == 'fake-park-token'
    # Pausing the definition stops subsequent evaluations without deleting history.
    store.upsert_trigger_definition(dict(trigger, enabled=False), actor='admin@test.com')
    assert run_triggers(**args, now=datetime(2026, 10, 21, 1, 0, 15, tzinfo=UTC)) == []
    assert len(submitted) == 1


def run(project, activity):
    return {'id': 1 if 'kit' in project else 2, 'trigger_id': activity, 'trigger_type': 'scheduled',
            'payload_json': {'gitlab_project': project, 'activity': activity,
                             'submit': {'response': {'id': 42}}}}


def test_results_do_not_cross_project_boundaries(configured, tmp_path):
    runs = [run('gitlab.example.org/group/kit', 'Kit activity'), run('swc.example.org/group/park', 'Park activity')]
    lookup = build_trigger_run_lookup(runs)
    assert '42' not in lookup
    result = {'pipeline_id': 42, 'ci_project': 'swc.example.org/group/park', 'execution_backend': 'benchpark',
              'code': 'qws', 'system': 'ExampleSystem', 'Exp': 'qws.case', 'FOM': 2.5, 'FOM_unit': 's'}
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    try:
        with app.test_request_context('/'):
            row = build_result_table_row('result_20261020_010000_uuid.json', result, [], lookup)
        assert row['activity_context']['activity'] == 'Park activity'
        assert row['fom'] == 2.5 and row['fom_unit'] == 's'
        assert row['execution_backend'] == 'benchpark'
        context = build_result_detail_context(dict(result, execution_activity='Park activity'), {})
        assert {'label': 'Execution Backend', 'value': 'benchpark'} in context['meta_rows']
        unknown = dict(result, ci_project='other.example.org/group/park')
        assert not summarize_execution_trigger(unknown, lookup)['has_trigger']
        (tmp_path / 'result.json').write_text(json.dumps(result))
        links = build_trigger_result_links(str(tmp_path), runs)
        assert set(links) == {2}
    finally:
        _cleanup(dirs)


def test_legacy_harness_metadata_identifies_backend_without_caliper_guess():
    from utils.benchpark import result_pipeline_backend
    assert result_pipeline_backend({'build': {'harness': {'name': 'benchpark'}}}) == 'benchpark'
    assert result_pipeline_backend({'profile_data': {'tool': 'caliper'}}) == ''


def test_ambiguous_legacy_results_do_not_link_to_either_project(tmp_path):
    runs = [run('gitlab.example.org/group/kit', 'Kit activity'), run('swc.example.org/group/park', 'Park activity')]
    (tmp_path / 'result.json').write_text(json.dumps({'pipeline_id': 42, 'Exp': 'case0'}))
    assert build_trigger_result_links(str(tmp_path), runs) == {}
    assert not summarize_execution_trigger({'pipeline_id': 42}, build_trigger_run_lookup(runs))['has_trigger']


def test_ingest_preserves_shared_result_and_producer_metadata(tmp_path):
    from routes.api import save_json_file
    data = {'code': 'qws', 'system': 'ExampleSystem', 'Exp': 'case0', 'FOM': 12.5,
            'FOM_unit': 's', 'execution_backend': 'benchpark', 'ci_project': 'swc.example.org/group/park',
            'execution_activity': 'Shared activity',
            'execution_trigger': {'id': 'daily', 'type': 'scheduled', 'reason': 'cron:0 10 * * *@date'}}
    saved = save_json_file(json.dumps(data).encode(), 'result', str(tmp_path))
    restored = json.loads((tmp_path / saved['json_file']).read_text())
    assert all(restored[key] == value for key, value in data.items())


def test_benchkit_activity_can_still_be_completed_from_parent(tmp_path):
    child = run('gitlab.example.org/group/kit', '')
    parent = run('gitlab.example.org/group/kit', 'Parent activity')
    parent['payload_json']['submit']['response']['id'] = 41
    parent['payload_json']['allocation_project_id'] = 'parent-account'
    lookup = build_trigger_run_lookup([child, parent])
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    try:
        with app.test_request_context('/'):
            row = build_result_table_row('result.json', {'pipeline_id': 42, 'parent_pipeline_id': 41}, [], lookup)
        assert row['activity_context']['activity'] == 'Parent activity'
        assert row['activity_context']['allocation_project_id'] == 'parent-account'
    finally:
        _cleanup(dirs)


@pytest.mark.parametrize('metadata', [[], ['invalid'], {'pipeline': []}, {'pipeline': 'invalid'}])
def test_corrupt_metadata_blocks_plans_without_crashing(configured, metadata):
    assert plan(dict(configured, metadata_json=metadata)).errors


@pytest.mark.parametrize('authenticated', [False, True])
def test_non_admin_cannot_change_backend_or_submit(configured, tmp_path, monkeypatch, authenticated):
    from test_execution_profiles import _login_user
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(configured, actor='admin@test.com')
    before = copy.deepcopy(store.list_profiles())
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    monkeypatch.setattr('routes.admin.submit_pipeline_plan', lambda *a, **k: pytest.fail('must not submit'))
    try:
        with app.test_client() as client:
            if authenticated:
                _login_user(client)
            for endpoint in ['upsert', 'submit', 'dry-run-submit', 'triggers/upsert']:
                response = client.post('/admin/execution-profiles/' + endpoint, data={
                    'id': 'park-qws', 'profile_id': 'park-qws', 'pipeline_backend': 'benchpark',
                    'benchpark_site': 'other', 'confirm_submit': 'on', 'target_ref': 'main'})
                assert response.status_code in (302, 403)
        assert store.list_profiles() == before
        assert store.list_trigger_definitions() == []
        with store.connect() as connection:
            assert connection.execute('SELECT count(*) FROM execution_requests').fetchone()[0] == 0
    finally:
        _cleanup(dirs)


@pytest.mark.parametrize('metadata', [['invalid'], {'pipeline': ['invalid']}, {'pipeline': 'invalid'}])
def test_admin_corrupt_metadata_renders_and_blocks_submit(configured, tmp_path, monkeypatch, metadata):
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(configured, actor='admin@test.com')
    with store.connect() as connection:
        connection.execute('UPDATE execution_profiles SET metadata_json=?', (json.dumps(metadata),))
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    monkeypatch.setattr('routes.admin.submit_pipeline_plan', lambda *a, **k: pytest.fail('must not submit'))
    try:
        with app.test_client() as client:
            _login_admin(client)
            assert client.get('/admin/execution-profiles?edit=park-qws').status_code == 200
            response = client.post('/admin/execution-profiles/submit', data={
                'profile_id': 'park-qws', 'gitlab_target': 'park', 'target_ref': 'main', 'confirm_submit': 'on'})
            assert response.status_code == 200
            assert b'submit_blocked' in response.data
        assert store.list_profiles()[0]['metadata_json'] == metadata
    finally:
        _cleanup(dirs)


def test_backend_does_not_change_existing_budget_fingerprints(configured):
    import hashlib
    from utils.budget_profile_binding import profile_fingerprint
    legacy = copy.deepcopy(configured)
    legacy['metadata_json'] = {}
    keys = ('id', 'enabled', 'status', 'activity', 'code', 'system', 'exp',
            'allocation_project_id', 'scheduler_extra_args', 'valid_from', 'valid_until')
    original = hashlib.sha256(json.dumps({key: legacy.get(key) for key in keys},
                                         sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert profile_fingerprint(legacy) == original
    legacy['metadata_json']['pipeline'] = {'backend': 'benchkit'}
    assert profile_fingerprint(legacy) == original
    assert profile_fingerprint(configured) == original  # Budget routing itself remains unchanged.


def test_benchpark_without_project_does_not_borrow_kit_history(tmp_path):
    lookup = build_trigger_run_lookup([run('gitlab.example.org/group/kit', 'Kit activity')])
    result = {'pipeline_id': 42, 'build': {'harness': {'name': 'benchpark'}}}
    assert not summarize_execution_trigger(result, lookup)['has_trigger']
    (tmp_path / 'result.json').write_text(json.dumps(result))
    assert build_trigger_result_links(str(tmp_path), list(lookup.values())) == {}


def test_legacy_explicit_trigger_match_is_preserved(tmp_path):
    record = run('gitlab.example.org/group/kit', 'daily')
    record['reason'] = 'unique-run-reason'
    result = {'pipeline_id': 43, 'execution_trigger': {
        'id': 'daily', 'type': 'scheduled', 'reason': 'unique-run-reason'}}
    (tmp_path / 'result.json').write_text(json.dumps(result))
    assert 1 in build_trigger_result_links(str(tmp_path), [record])


def test_profile_backend_posts_still_require_csrf(configured, tmp_path, monkeypatch):
    from utils.csrf import init_csrf
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(configured, actor='admin@test.com')
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    init_csrf(app)
    monkeypatch.setattr('routes.admin.submit_pipeline_plan', lambda *a, **k: pytest.fail('must not submit'))
    try:
        with app.test_client() as client:
            _login_admin(client)
            for endpoint in ['upsert', 'submit', 'dry-run-submit', 'triggers/upsert']:
                assert client.post('/admin/execution-profiles/' + endpoint, data={
                    'id': 'park-qws', 'profile_id': 'park-qws', 'pipeline_backend': 'benchpark',
                    'confirm_submit': 'on'}).status_code == 400
        assert store.list_profiles()[0]['metadata_json'] == configured['metadata_json']
    finally:
        _cleanup(dirs)


def test_manual_controls_keep_benchkit_default_but_require_benchpark_ref(configured, tmp_path):
    import re
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(configured, actor='admin@test.com')
    kit = dict(configured, id='kit-qws', metadata_json={})
    store.upsert_profile(kit, actor='admin@test.com')
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    try:
        with app.test_client() as client:
            _login_admin(client)
            response = client.get('/admin/execution-profiles')
        rows = re.findall(r'<tr data-profile-row.*?</tr>', response.get_data(as_text=True), re.S)
        park = next(row for row in rows if 'value="park-qws"' in row)
        kit = next(row for row in rows if 'value="kit-qws"' in row)
        assert 'name="target_ref" required' in park
        assert re.search(r'<option value="park"\s+selected>', park)
        assert 'type="hidden" name="target_ref" value="main"' in kit
    finally:
        _cleanup(dirs)


@pytest.mark.parametrize('backend', ['benchkit', 'benchpark'])
def test_new_metadata_does_not_bypass_confidential_permissions(tmp_path, backend):
    from test_public_result_routes import _build_public_app, _write_result, _authenticate_dev
    app, received = _build_public_app(tmp_path)
    filename = 'result_20260824_090000_11111111-2222-3333-4444-555555555555.json'
    _write_result(received, filename, {
        'code': 'qws', 'system': 'ExampleSystem', 'Exp': 'secret-case', 'FOM': 2.5,
        'confidential': ['dev'], 'execution_backend': backend, 'ci_project': 'private.example.org/group/ci',
        'execution_activity': 'Private activity', 'execution_trigger': {'id': 'private-trigger'}})
    public_filename = 'result_20260824_091000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json'
    _write_result(received, public_filename, {'code': 'qws', 'system': 'ExampleSystem', 'Exp': 'public-case', 'FOM': 3.0})
    with app.test_client() as client:
        _authenticate_dev(client)
        assert client.get('/results/detail/' + filename).status_code == 404
        assert client.get('/results/compare?files=' + filename + ',' + public_filename).status_code == 404
        app.config['PUBLIC_PORTAL_MODE'] = False
        with client.session_transaction() as sess:
            sess.clear()
        assert client.get('/results/detail/' + filename).status_code in (302, 403)


def test_benchkit_detail_keeps_existing_rows_without_new_producer_fields():
    result = {'environment_snapshot': {'summary': {'activity': 'Existing activity'}}}
    context = build_result_detail_context(result, {})
    labels = {row['label'] for row in context['meta_rows']}
    assert not labels.intersection({'Activity', 'Execution Backend', 'CI Project'})


def test_public_surface_blocks_backend_editor_even_for_admin(configured, tmp_path):
    from utils.portal_access import register_public_portal_guard
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(configured, actor='admin@test.com')
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    app.config['PUBLIC_PORTAL_MODE'] = True
    register_public_portal_guard(app)
    try:
        with app.test_client() as client:
            _login_admin(client)
            for endpoint in ['upsert', 'submit', 'dry-run-submit', 'triggers/upsert']:
                assert client.post('/admin/execution-profiles/' + endpoint, data={
                    'id': 'park-qws', 'pipeline_backend': 'benchpark'}).status_code == 404
        assert store.list_profiles()[0]['metadata_json'] == configured['metadata_json']
    finally:
        _cleanup(dirs)


def test_legacy_profile_update_preserves_only_new_pipeline_setting(configured, tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(configured, actor='admin@test.com')
    # Existing clients need not know the newly added field; preserve it atomically.
    store.upsert_profile(dict(configured, metadata_json={}), actor='admin@test.com')
    restored = store.list_profiles()[0]
    assert restored['metadata_json'] == {'pipeline': configured['metadata_json']['pipeline']}
    # An explicit backend selection switches back to the original Benchkit planner.
    store.upsert_profile(dict(configured, metadata_json={'pipeline': {'backend': 'benchkit'}}), actor='admin@test.com')
    assert store.list_profiles()[0]['metadata_json']['pipeline'] == {'backend': 'benchkit'}


@pytest.mark.parametrize('binding', [{}, {'version': 1}, None])
def test_benchpark_budget_rejection_does_not_require_changed_fingerprint(configured, binding):
    profile = copy.deepcopy(configured)
    profile['metadata_json']['budget_binding'] = binding
    assert 'Benchpark Budget routes are not supported' in plan(profile).errors
