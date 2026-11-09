"""Allocation ownership, grouped selection and copy-only migration rehearsals."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
import time

import pytest

pytest.importorskip('sqlcipher3')

from test_budget_registry import registry, configured_target, ADMIN, MANAGER, seed  # noqa: F401
from test_budget_groups import group_values
from test_budget_pipeline import selection  # noqa: F401
from test_execution_routes import project, config, env, generate  # noqa: F401
from test_budget_profile_binding import editor, save_selection  # noqa: F401
from test_budget_routes import login, hidden, portal  # noqa: F401
from utils.budget_registry import BudgetRegistry, RegistryError
from utils.budget_migrations import BudgetMigrationBackend
from utils.db_migrations import EncryptedSQLiteMigrator
from utils.budget_pipeline import build_budget_profile_plan
from utils.budget_profile_binding import (prepare_binding, build_bound_profile_plan, selection_fingerprint,
    has_budget_binding, allocation_display, build_profile_execution_plan)
from utils.profile_budget_migration import plan_bindings, apply_bindings, rehearse_bindings
from utils.execution_profiles import ExecutionProfileStore, normalize_profile
from utils.encrypted_sqlite import EncryptedDatabaseError


def migrate_copy(registry, path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return EncryptedSQLiteMigrator(BudgetMigrationBackend(registry.storage.path, registry.storage.key_file)).rehearse(
        destination=path)


def test_normalized_copy_has_one_allocation_and_preserves_route(registry, configured_target, tmp_path):
    values = group_values()
    values['allocation_project_id'] = 'synthetic-allocation'
    registry.save_budget_group(ADMIN, 0, **values)
    before = registry.catalog(ADMIN)
    original = registry.storage.path.read_bytes()
    resolved = registry.resolve(ADMIN, 'target-a')
    copied = tmp_path / 'migration' / 'copy.db'
    result = migrate_copy(registry, copied)
    normalized = BudgetRegistry(copied, registry.storage.key_file)
    assert result['schema_version'] == 5 and registry.storage.path.read_bytes() == original
    assert registry.catalog(ADMIN) == before
    assert normalized.resolve(ADMIN, 'target-a') == resolved
    with normalized.storage.connect(readonly=True) as conn:
        assert 'allocation_project_id' not in {r[1] for r in conn.execute('PRAGMA table_info(destinations)')}
        assert len(conn.execute('SELECT allocation_project_id FROM budget_defaults').fetchall()) == 1
    values.update(new_account=False, allocation_project_id='updated')
    normalized.save_budget_group(ADMIN, normalized.check(), **values)
    assert {r['allocation_project_id'] for r in normalized.catalog(ADMIN)['destinations']} == {'updated'}
    assert resolved['route']['allocation_project_id'] == 'synthetic-allocation'
    backup = tmp_path / 'restored' / 'before.db'
    backup.parent.mkdir(mode=0o700)
    normalized.storage.backup(backup)
    rollback = BudgetRegistry(backup, registry.storage.key_file)
    with rollback.storage.connect() as conn:
        with conn:
            BudgetMigrationBackend.restore_version_four(conn)
    assert rollback.catalog(ADMIN)['schema_version'] == 4
    assert rollback.resolve(ADMIN, 'target-a') == normalized.resolve(ADMIN, 'target-a')


def test_disagreeing_legacy_copies_are_not_inferred(registry, configured_target, tmp_path):
    registry.save_budget_group(ADMIN, 0, **group_values())
    with registry.storage.connect() as conn:
        with conn:
            conn.execute("UPDATE destinations SET allocation_project_id='different' WHERE id='target-a'")
    before = registry.storage.path.read_bytes()
    with pytest.raises((RegistryError, ValueError)):
        migrate_copy(registry, tmp_path / 'bad-copy' / 'copy.db')
    assert registry.storage.path.read_bytes() == before


def test_new_normalized_registry_and_legacy_reader_boundary(tmp_path):
    from utils.encrypted_sqlite import generate_key
    key = tmp_path / 'keys' / 'key'
    key.parent.mkdir(mode=0o700)
    (tmp_path / 'data').mkdir(mode=0o700)
    generate_key(key)
    store = BudgetRegistry(tmp_path / 'data' / 'new.db', key)
    store.initialize(normalized=True)
    assert store.catalog(ADMIN)['schema_version'] == 5
    # The old reader explicitly accepts only schemas 3/4, never silently reads 5.
    assert store.catalog(ADMIN)['schema_version'] not in (3, 4)


def grouped(selection):
    store = selection['registry']
    revision = store.save_budget(ADMIN, selection['expected_revision'], id='secondary', label='Allocation-free resources',
                                 system='Example Center', enabled=True)
    revision = store.set_manager(ADMIN, revision, budget_id='secondary', principal=MANAGER.principal, assigned=True)
    revision = store.save_destination(ADMIN, revision, id='second', budget_id='secondary',
        system='Legacy', account_id='settings', allocation_project_id='')
    selection['expected_revision'] = revision
    return selection


def group_plan(selection, **changes):
    args = {key: value for key, value in selection.items() if key != 'destination_id'}
    return build_budget_profile_plan(**dict(args, destination_ids=['selected', 'second'], **changes))


def test_grouped_profile_produces_one_parent_with_exact_systems(selection, project):
    grouped(selection)
    result = group_plan(selection)
    assert result.snapshot['version'] == 2
    assert result.plan.payload['variables']['system'] == 'Fugaku,Legacy'
    assert 'BK_ALLOCATION_PROJECT_ID' not in result.plan.payload['variables']
    route_file = Path(project[1]['BK_EXECUTION_ROUTES_FILE'])
    route_file.write_text(json.dumps(dict(version=1, target=result.snapshot['target'],
        routes=[entry['route'] for entry in result.snapshot['selections']])))
    variables = dict(result.plan.payload['variables'])
    variables.pop('BK_EXECUTION_ROUTE_SNAPSHOT')
    baseline = generate(project, **variables)
    assert baseline.returncode == 0, baseline.stderr
    previous_yaml = (project[0] / '.gitlab-ci.generated.yml').read_text()
    project[1].pop('BK_EXECUTION_ROUTES_FILE')
    shell_only = project[0] / 'shell-only'
    shell_only.mkdir()
    for command in ('bash', 'jq', 'awk', 'sed', 'tr', 'dirname', 'basename', 'grep', 'cat'):
        (shell_only / command).symlink_to(shutil.which(command))
    project[1]['PATH'] = str(shell_only)
    assert shutil.which('python3', path=project[1]['PATH']) is None
    output = generate(project, **result.plan.payload['variables'])
    assert output.returncode == 0, output.stderr
    generated = (project[0] / '.gitlab-ci.generated.yml').read_text()
    assert 'selected-run' in generated and '-g example-allocation' in generated
    assert generated == previous_yaml


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'scope', 'different-connection', 'override', 'benchpark'])
def test_group_rejects_partial_ambiguous_or_unsupported_routes(selection, kind):
    grouped(selection)
    ids = ['selected', 'second']
    if kind == 'missing':
        ids.pop()
    elif kind == 'duplicate':
        ids[1] = ids[0]
    elif kind == 'scope':
        selection['profile']['system'] = ['Fugaku']
    elif kind == 'override':
        selection['profile']['scheduler_extra_args'] = '--account=other'
    elif kind == 'benchpark':
        selection['profile']['metadata_json']['pipeline'] = {'backend': 'benchpark'}
    else:
        registry = selection['registry']
        with registry.storage.connect() as conn:
            with conn:
                conn.execute("INSERT INTO connections VALUES ('other','Other','https://other.example.org','g/p','OTHER','')")
                conn.execute("INSERT INTO execution_accounts VALUES ('other','Other','Example Center','','other','','other-run','')")
                conn.execute("UPDATE destinations SET account_id='other' WHERE id='second'")
    args = {k: v for k, v in selection.items() if k != 'destination_id'}
    with pytest.raises(RegistryError):
        build_budget_profile_plan(**args, destination_ids=ids)


@pytest.mark.parametrize('selected', ['Fugaku', 'Fugaku,Legacy,Other', 'Fugaku,Fugaku', 'Legacy,Fugaku'])
def test_group_snapshot_matches_matrix_selection(selection, project, selected):
    grouped(selection)
    result = group_plan(selection)
    project[1].pop('BK_EXECUTION_ROUTES_FILE')
    output = generate(project, selected, BK_EXECUTION_ROUTE_SNAPSHOT=json.dumps(result.snapshot))
    assert (output.returncode == 0) == (selected == 'Legacy,Fugaku')


def test_copy_profile_migration_atomicity_history_and_recovery(selection, tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'profiles.db'))
    profile = dict(selection['profile'], system=['Fugaku'], allocation_project_id='example-allocation')
    store.upsert_profile(profile, actor=ADMIN.principal)
    before = store.list_profiles()[0]
    with store.connect() as conn:
        conn.execute("INSERT INTO trigger_definitions(id,profile_id,trigger_type,enabled,created_at,updated_at) "
                     "VALUES ('timer','profile','scheduled',0,'now','now')")
        conn.execute("INSERT INTO execution_requests(request_type,status,profile_id,payload_json,created_at,updated_at) "
                     "VALUES ('manual','submitted','profile','{\"allocation\":\"historical\"}','now','now')")
    store.create_trigger_run(trigger_id='timer', trigger_type='scheduled', status='submitted', dry_run=False,
                             payload={'allocation': 'historical'})
    source_hash = hashlib.sha256(Path(store.db_path).read_bytes()).digest()
    copy = ExecutionProfileStore(str(tmp_path / 'profiles-copy.db'))
    with sqlite3.connect(f'file:{store.db_path}?mode=ro', uri=True) as src, sqlite3.connect(copy.db_path) as dst:
        src.backup(dst)
    mapping = [dict(profile_id='profile', destination_ids=['selected'], fingerprint=selection_fingerprint(before))]
    plan = plan_bindings(copy, selection['registry'], ADMIN, mapping, selection['expected_revision'])
    assert plan['profiles'][0]['allocation_copy_removed']
    result = apply_bindings(copy, selection['registry'], ADMIN, mapping, selection['expected_revision'])
    assert result == dict(applied=1, allocation_copies_removed=1)
    after = copy.list_profiles()[0]
    assert after['allocation_project_id'] == '' and has_budget_binding(after)
    assert allocation_display(after) == 'Budget selected'
    assert copy.list_trigger_definitions() == store.list_trigger_definitions()
    for table in ('execution_requests', 'trigger_runs', 'execution_profile_scopes', 'schema_migrations'):
        with store.connect() as original, copy.connect() as migrated:
            assert [tuple(row) for row in original.execute(f'SELECT * FROM {table}')] == [
                tuple(row) for row in migrated.execute(f'SELECT * FROM {table}')]
    assert hashlib.sha256(Path(store.db_path).read_bytes()).digest() == source_hash
    destination = tmp_path / 'recovered.db'
    with sqlite3.connect(f'file:{copy.db_path}?mode=ro', uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    assert ExecutionProfileStore(str(destination)).list_profiles() == copy.list_profiles()
    # A stale or duplicate map cannot partially update the copy.
    with pytest.raises(RegistryError):
        apply_bindings(copy, selection['registry'], ADMIN, mapping * 2, selection['expected_revision'])
    assert copy.list_profiles()[0] == after


def test_budget_required_never_falls_back(selection):
    profile = dict(selection['profile'], metadata_json={'execution_mode': 'budget'})
    with pytest.raises(RegistryError):
        build_profile_execution_plan(profile, target_ref='develop', result_server_url='https://cx.example.org')


def test_selection_and_normalized_allocation_save_are_atomic(editor, selection):
    app, users, store = editor
    previous = store.list_profiles()[0]
    store.save_profile_budget(previous, selection['registry'], ADMIN, ['selected'], selection['expected_revision'],
                              expected_fingerprint=selection_fingerprint(previous))
    saved = store.list_profiles()[0]
    assert saved['allocation_project_id'] == ''
    assert saved['metadata_json']['execution_mode'] == 'budget'
    before = deepcopy(saved)
    with pytest.raises(RegistryError):
        store.save_profile_budget(saved, selection['registry'], MANAGER, ['selected'], selection['expected_revision'],
                                  expected_fingerprint=selection_fingerprint(saved))
    assert store.list_profiles()[0] == before
    with pytest.raises(RegistryError):
        store.save_profile_budget(dict(saved, activity='changed'), selection['registry'], ADMIN, ['missing'],
                                  selection['expected_revision'], expected_fingerprint=selection_fingerprint(saved))
    assert store.list_profiles()[0] == before


def test_profile_form_has_one_selection_and_no_allocation_input(editor):
    app, _, _ = editor
    client = app.test_client()
    login(client)
    text = client.get('/admin/execution-profiles?edit=profile').get_data(as_text=True)
    assert 'name="allocation_project_id"' not in text
    assert text.count('name="destination_id"') == 1
    assert 'Save Budget' not in text


def test_snapshot_and_plan_are_unchanged_by_canonical_registry_migration(selection, tmp_path):
    selection['profile']['system'] = ['Fugaku']
    before = build_budget_profile_plan(**{k: v for k, v in selection.items() if k != 'destination_id'},
                                      destination_ids=['selected'])
    copy = tmp_path / 'canonical' / 'copy.db'
    migrate_copy(selection['registry'], copy)
    other = BudgetRegistry(copy, selection['registry'].storage.key_file)
    after = build_budget_profile_plan(**{k: v for k, v in selection.items() if k not in ('destination_id', 'registry')},
                                     registry=other, destination_ids=['selected'])
    assert before == after


@pytest.mark.parametrize('encrypted', [False, True])
def test_rehearsal_creates_only_new_profile_copy(selection, tmp_path, encrypted):
    from utils.encrypted_sqlite import generate_key, EncryptedSQLite
    key = tmp_path / 'keys' / 'profile.key'
    if encrypted:
        key.parent.mkdir(mode=0o700, exist_ok=True)
        generate_key(key)
        with EncryptedSQLite(tmp_path / 'source.db', key).connect(create=True):
            pass
    source = ExecutionProfileStore(str(tmp_path / 'source.db'), key_file=key if encrypted else None)
    profile = dict(selection['profile'], system=['Fugaku'], allocation_project_id='example-allocation')
    source.upsert_profile(profile, actor=ADMIN.principal)
    before = source.list_profiles()[0]
    mapping = [dict(profile_id='profile', destination_ids=['selected'], fingerprint=selection_fingerprint(before))]
    destination = tmp_path / 'new.db'
    result = rehearse_bindings(source, destination, selection['registry'], ADMIN, mapping, selection['expected_revision'])
    assert result == dict(applied=1, allocation_copies_removed=1, rehearsal=True)
    assert source.list_profiles() == [before]
    copied = ExecutionProfileStore(str(destination), key_file=key if encrypted else None)
    assert copied.list_profiles()[0]['allocation_project_id'] == ''
    if encrypted:
        assert not destination.read_bytes().startswith(b'SQLite format 3')
    assert destination.stat().st_mode & 0o777 == 0o600
    with pytest.raises((FileExistsError, ValueError, EncryptedDatabaseError)):
        rehearse_bindings(source, destination, selection['registry'], ADMIN, mapping, selection['expected_revision'])


def test_group_binding_survives_database_scope_order_and_rechecks_all_grants(selection, tmp_path):
    grouped(selection)
    source = ExecutionProfileStore(str(tmp_path / 'group.db'))
    profile = dict(selection['profile'], system=['Legacy', 'Fugaku'])
    source.upsert_profile(profile, actor=ADMIN.principal)
    before = source.list_profiles()[0]
    source.save_profile_budget(profile, selection['registry'], ADMIN, ['second', 'selected'],
        selection['expected_revision'], expected_fingerprint=selection_fingerprint(before))
    saved = source.list_profiles()[0]
    class Users:
        def user_exists(self, principal):
            return principal == ADMIN.principal
        def get_affiliations(self, principal):
            return ['admin']
    full = build_bound_profile_plan(saved, target_ref='develop', result_server_url='https://cx.example.org',
                                   registry=selection['registry'], users=Users())
    assert full.snapshot['version'] == 2
    subset = build_bound_profile_plan(saved, target_ref='develop', result_server_url='https://cx.example.org',
        registry=selection['registry'], users=Users(), system='Fugaku')
    assert subset.plan.payload['variables']['system'] == 'Fugaku'
    # A target removal invalidates the full reviewed Profile, even for a subset.
    with selection['registry'].storage.connect() as conn:
        with conn:
            conn.execute("DELETE FROM destinations WHERE id='second'")
    with pytest.raises(RegistryError):
        build_bound_profile_plan(saved, target_ref='develop', result_server_url='https://cx.example.org',
            registry=selection['registry'], users=Users(), system='Fugaku')


def test_batch_registry_change_rolls_back_all_profiles(selection, tmp_path, monkeypatch):
    source = ExecutionProfileStore(str(tmp_path / 'atomic.db'))
    for name in ['first', 'second']:
        source.upsert_profile(dict(selection['profile'], id=name, system=['Fugaku']), actor=ADMIN.principal)
    before = source.list_profiles()
    mapping = [dict(profile_id=p['id'], destination_ids=['selected'], fingerprint=selection_fingerprint(p)) for p in before]
    store = selection['registry']
    original = store.catalog
    def edit_between(actor):
        store.save_budget(ADMIN, selection['expected_revision'], id='research', label='Other label',
                          system='Example Center', enabled=True)
        return original(actor)
    monkeypatch.setattr(store, 'catalog', edit_between)
    with pytest.raises(RegistryError):
        apply_bindings(source, selection['registry'], ADMIN, mapping, selection['expected_revision'])
    assert source.list_profiles() == before


def test_profile_form_saves_selection_and_settings_together(editor):
    app, users, store = editor
    client = app.test_client()
    login(client)
    page = client.get('/admin/execution-profiles?edit=profile')
    values = {name: hidden(page, name) for name in ('csrf_token', 'registry_revision', 'profile_fingerprint')}
    values.update(id='profile', status='approved', code='demo', system='Fugaku',
                  activity='Reviewed activity', destination_id='selected')
    response = client.post('/admin/execution-profiles/upsert', data=values, follow_redirects=True)
    assert response.status_code == 200
    saved = store.list_profiles()[0]
    assert saved['activity'] == 'Reviewed activity'
    assert saved['allocation_project_id'] == ''
    assert saved['metadata_json']['budget_binding']['version'] == 2


def test_new_profile_cannot_submit_before_selection_but_legacy_is_unchanged(editor):
    app, users, store = editor
    client = app.test_client()
    login(client)
    old = store.list_profiles()[0]
    page = client.get('/admin/execution-profiles')
    values = {'csrf_token': hidden(page, 'csrf_token'), 'id': 'pending', 'status': 'approved',
              'code': 'demo', 'system': 'Fugaku'}
    response = client.post('/admin/execution-profiles/upsert', data=values, follow_redirects=True)
    assert response.status_code == 200
    saved = next(p for p in store.list_profiles() if p['id'] == 'pending')
    assert has_budget_binding(saved)
    assert saved['metadata_json'] == {'execution_mode': 'budget'}
    assert next(p for p in store.list_profiles() if p['id'] == 'profile') == old
    with pytest.raises(RegistryError):
        build_profile_execution_plan(saved, target_ref='develop', result_server_url='https://cx.example.org')


def test_group_checks_permission_on_every_budget(selection):
    store = selection['registry']
    revision = store.save_budget(ADMIN, selection['expected_revision'], id='other', label='Other budget',
                                 system='Example Center', enabled=True)
    revision = store.save_destination(ADMIN, revision, id='second', budget_id='other', system='Legacy',
                                     account_id='settings', allocation_project_id='')
    selection['expected_revision'] = revision
    with pytest.raises(RegistryError):
        group_plan(selection)
    revision = store.set_manager(ADMIN, revision, budget_id='other', principal=MANAGER.principal, assigned=True)
    selection['expected_revision'] = revision
    assert group_plan(selection).snapshot['version'] == 2
    revision = store.set_manager(ADMIN, revision, budget_id='other', principal=MANAGER.principal, assigned=False)
    selection['expected_revision'] = revision
    with pytest.raises(RegistryError):
        group_plan(selection)


def test_request_approval_and_budget_selection_commit_together(selection, tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'requests.db'))
    profile = dict(selection['profile'], system=['Fugaku'], status='draft')
    request_id = store.create_profile_request(requested_profile=profile, requester_email='applicant@example.org',
        requester_affiliation='research', status='submitted', actor='applicant@example.org')
    bad = (selection['registry'], ADMIN, ['missing'], selection['expected_revision'])
    ok, errors = store.review_profile_request(request_id, action='approve', actor=ADMIN.principal,
                                             budget_selection=bad, budget_required=True)
    assert not ok and errors
    assert not store.list_profiles() and store.get_profile_request(request_id)['status'] == 'submitted'
    good = (selection['registry'], ADMIN, ['selected'], selection['expected_revision'])
    ok, errors = store.review_profile_request(request_id, action='approve', actor=ADMIN.principal,
                                             budget_selection=good, budget_required=True)
    assert ok and not errors
    saved = store.list_profiles()[0]
    assert saved['metadata_json']['budget_binding']['version'] == 2
    assert saved['allocation_project_id'] == ''
    assert store.get_profile_request(request_id)['status'] == 'approved'


def test_canonical_copy_performance(selection, tmp_path):
    grouped(selection)
    start = time.perf_counter()
    destination = tmp_path / 'benchmark' / 'copy.db'
    migrate_copy(selection['registry'], destination)
    migrated = time.perf_counter()
    candidate = BudgetRegistry(destination, selection['registry'].storage.key_file)
    options = {**selection, 'registry': candidate}
    for _ in range(10):
        group_plan(options)
    planned = time.perf_counter()
    rollback = tmp_path / 'rollback' / 'copy.db'
    rollback.parent.mkdir(mode=0o700)
    BudgetMigrationBackend(destination, candidate.storage.key_file).compatibility_copy(rollback)
    print(json.dumps({'synthetic_targets': 2, 'migration_seconds': round(migrated-start, 4),
        'group_plan_mean_seconds': round((planned-migrated)/10, 4),
        'rollback_copy_seconds': round(time.perf_counter()-planned, 4)}))


def test_migration_preserves_original_authorizer_and_rejects_route_changes(selection, tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'authorizer.db'))
    store.upsert_profile(dict(selection['profile'], system=['Fugaku'], allocation_project_id='example-allocation'),
                         actor=ADMIN.principal)
    original = store.list_profiles()[0]
    binding = prepare_binding(original, selection['registry'], MANAGER, 'selected', selection['expected_revision'])
    store.set_budget_binding('profile', binding, expected_fingerprint=selection_fingerprint(original), actor=ADMIN.principal)
    before = store.list_profiles()[0]
    mapping = [dict(profile_id='profile', destination_ids=['selected'], fingerprint=selection_fingerprint(before))]
    apply_bindings(store, selection['registry'], ADMIN, mapping, selection['expected_revision'])
    after = store.list_profiles()[0]
    assert after['metadata_json']['budget_binding']['selected_by'] == MANAGER.principal
    assert after['allocation_project_id'] == ''
    revision = selection['registry'].save_account(ADMIN, selection['expected_revision'], id='settings',
        label='Settings', system='Example Center', connection_id='gitlab:example', build_tag='different', run_tag='different')
    mapping[0]['fingerprint'] = selection_fingerprint(after)
    with pytest.raises(RegistryError, match='cannot change'):
        plan_bindings(store, selection['registry'], ADMIN, mapping, revision)


@pytest.mark.parametrize('snapshot', [None, [], {}, {'version': 3}, {'version': 2, 'selections': []}])
def test_malformed_group_snapshots_block_without_fallback(selection, snapshot):
    from utils.budget_profile_binding import profile_fingerprint
    profile = dict(selection['profile'], system=['Fugaku'])
    profile['metadata_json'] = {'budget_binding': dict(version=2, snapshot=snapshot,
        selected_by=ADMIN.principal, profile_fingerprint=profile_fingerprint(profile))}
    class Users:
        def user_exists(self, principal):
            return True
        def get_affiliations(self, principal):
            return ['admin']
    with pytest.raises(RegistryError):
        build_bound_profile_plan(profile, target_ref='develop', result_server_url='https://cx.example.org',
                                 registry=selection['registry'], users=Users())


def test_rehearsal_cli_is_copy_only_and_value_free(selection, tmp_path, capsys):
    from profile_budget import main
    source = ExecutionProfileStore(str(tmp_path / 'cli-source.db'))
    source.upsert_profile(dict(selection['profile'], system=['Fugaku']), actor=ADMIN.principal)
    profile = source.list_profiles()[0]
    mapping = tmp_path / 'mapping.json'
    mapping.write_text(json.dumps([dict(profile_id='profile', destination_ids=['selected'],
                                       fingerprint=selection_fingerprint(profile))]))
    args = ['--source', source.db_path, '--destination', str(tmp_path / 'cli-copy.db'),
        '--registry', str(selection['registry'].storage.path),
        '--registry-key-file', str(selection['registry'].storage.key_file),
        '--registry-revision', str(selection['expected_revision']), '--mapping', str(mapping),
        '--actor', ADMIN.principal, '--confirm-local-admin']
    assert main(args) == 0
    assert source.list_profiles() == [profile]
    success = capsys.readouterr().out
    assert json.loads(success)['rehearsal']
    assert main(args) == 1
    failed = capsys.readouterr().out
    assert 'error' in json.loads(failed)
    for text in (success, failed):
        assert 'example-allocation' not in text and ADMIN.principal not in text
        assert str(selection['registry'].storage.key_file) not in text
