"""Indexed/JSON parity, using generated records and disposable databases only."""

import builtins
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.result_catalog import CatalogUnavailable, ResultCatalog
from utils.results_loader import load_results_table
from utils.node_hours import aggregate_node_hours
from utils.performance_telemetry import build_performance_telemetry
from utils.profile_usage_overview import build_profile_usage_overview
from utils.evidence_snapshot import build_evidence_snapshot
from utils.execution_profiles import ExecutionProfileStore
from test_profile_usage_overview import _profile, _trigger
from test_usage_route import app, client, tmp_dirs, _login_session


@pytest.fixture
def indexed(tmp_path):
    directories = [tmp_path / name for name in ('results', 'estimates', 'archives', 'index')]
    for directory in directories:
        directory.mkdir(mode=0o700)
    results, estimates, archives, index = directories
    for number, (stamp, system, tags) in enumerate([
        ('20260331_235959', 'Fugaku', []), ('20260401_000000', 'Fugaku', ['a']),
        ('20260810_010101', 'DemoSystem', []), ('20260930_235959', 'DemoSystem', ['a', 'b']),
        ('20261001_000000', 'Fugaku', ['b']), ('20270331_235959', 'Other', ['secret']),
        ('20270401_000000', 'Fugaku', []),
    ]):
        identifier = f'{number:08x}-bbbb-cccc-dddd-eeeeeeeeeeee'
        payload = dict(code='genesis', system=system, Exp='CASE0', FOM=1.25,
                       FOM_unit='s', FOM_version='v1', node_count='2', numproc_node='1', nthreads='2',
                       confidential=tags, execution_mode='native' if number % 2 else 'cross',
                       pipeline_timing=dict(run_time=120+number, build_time=30, queue_time=12,
                                            scheduler_queue_time=3, profiled_job=number == 4),
                       build_cache=dict(status='hit' if number % 2 else 'miss', stored=True),
                       environment_snapshot={'hash': f'sha256:{number}', 'summary': {'system': system}},
                       execution_trigger={'id': 'demoapp-demosystem-time', 'type': 'scheduled', 'reason': 'fixture'},
                       source_info=dict(source_type='git', repo_url='https://github.com/example/app',
                                        ref_name='main', resolved_commit='a'*40,
                                        public_access_check=dict(confirmed=True,method='github_rest_api_anonymous',host='github.com')),
                       input_info=dict(inputs=[dict(repo_relative_path='input', source='source_info', verification_status='covered_by_source_commit')]),
                       unindexed_secret='not copied', raw_output='x'*1024)
        if number % 2:
            payload['profile_data'] = dict(tool='ncu', raw='not copied')
        (results / f'result_{stamp}_{identifier}.json').write_text(json.dumps(payload))
        (archives / f'padata_{stamp}_{identifier}.tgz').touch()
        estimate = dict(code='genesis', exp='CASE0', current_system={'system':system},
                        future_system={'system':'Future','benchmark':{'system':system}},
                        applicability={'status':'applicable'}, estimation_timing={'elapsed_time':42},
                        estimate_metadata={'source_result':{'system':system}})
        (estimates / f'estimate_{stamp}_{identifier}.json').write_text(json.dumps(estimate))
    catalog = ResultCatalog(index / 'index.sqlite3', results, estimated_directory=estimates,
                            artifact_directory=archives)
    catalog.initialize()
    catalog.rebuild()
    db = str(tmp_path / 'profiles.sqlite3')
    store = ExecutionProfileStore(db)
    store.upsert_profile(_profile(code='genesis'), actor='test@example.invalid')
    store.upsert_profile(_profile(id='other-profile',code='genesis'), actor='test@example.invalid')
    store.upsert_trigger_definition(_trigger(), actor='test@example.invalid')
    return catalog, results, estimates, archives, db


@pytest.mark.parametrize('system', ['', 'Fugaku', 'DemoSystem', 'Absent'])
@pytest.mark.parametrize('bounds', [(date(2026,4,1),date(2027,4,1)),
                                   (date(2026,9,1),date(2026,10,1)),
                                   (date(2026,10,1),date(2027,4,1))])
def test_all_report_values_match_json(indexed, system, bounds):
    catalog, results, estimates, _, db = indexed
    selection = dict(code='genesis',system=system,since=bounds[0],until=bounds[1])
    calls = [
        (aggregate_node_hours, (str(results),2026,'monthly'), {}),
        (build_profile_usage_overview,(str(results),db),{}),
        (build_performance_telemetry,(str(results),str(estimates)),{}),
        (build_evidence_snapshot,(str(results),str(estimates)),dict(generated_at='2026-11-02T00:00:00Z',app_support_rows=[])),
    ]
    for function,args,kwargs in calls:
        expected = function(*args,selection=selection,**kwargs)
        with catalog.snapshot() as reader:
            actual = function(*args,selection=selection,record_source=reader,**kwargs)
        assert actual == expected, function.__name__


@pytest.mark.parametrize('public,authenticated,affiliations', [
    (True,False,[]), (True,True,['admin']), (False,False,['admin']),
    (False,True,[]), (False,True,['a']), (False,True,['a','b']), (False,True,['admin'])])
def test_search_pages_permissions_and_rows_match(indexed, app, public, authenticated, affiliations):
    catalog, results, _, archives, _ = indexed
    with app.test_request_context():
        for system in (None,'Fugaku','Absent'):
            kwargs = dict(public_only=public,authenticated=authenticated,affiliations=affiliations,
                          filter_system=system,filter_code='genesis',per_page=50,page=2,
                          padata_directory=str(archives))
            expected = load_results_table(str(results),**kwargs)
            with catalog.snapshot() as reader:
                actual = load_results_table(str(results),query_reader=reader,**kwargs)
            assert actual == expected


def test_reports_never_read_source_files_or_scan(indexed, monkeypatch):
    catalog, results, estimates, _, db = indexed
    # Profile DB remains a separate current-definition source, not a Result scan.
    def forbidden(*args, **kwargs):
        raise AssertionError('Indexed report read source JSON or scanned a directory')
    monkeypatch.setattr(os,'listdir',forbidden)
    monkeypatch.setattr(Path,'iterdir',forbidden)
    monkeypatch.setattr(builtins,'open',forbidden)
    with catalog.snapshot() as reader:
        assert aggregate_node_hours(str(results),2026,'monthly',record_source=reader)['apps']
        assert build_profile_usage_overview(str(results),db,record_source=reader)['available']
        assert build_performance_telemetry(str(results),str(estimates),record_source=reader)['rows']
        assert build_evidence_snapshot(str(results),str(estimates),record_source=reader,
                                       generated_at='fixed',app_support_rows=[])['rows']


def test_search_reads_only_its_page(indexed, app, monkeypatch):
    catalog, results, _, archives, _ = indexed
    import utils.results_loader as loader
    original = loader.load_visible_result_json
    read_names = []
    def read(filename,*args,**kwargs):
        read_names.append(filename)
        return original(filename,*args,**kwargs)
    monkeypatch.setattr(loader,'load_visible_result_json',read)
    monkeypatch.setattr(os,'listdir',lambda *a: pytest.fail('Directory scan'))
    with app.test_request_context(), catalog.snapshot() as reader:
        rows,_,pagination = loader.load_results_table(str(results),query_reader=reader,
                                                      padata_directory=str(archives))
    assert pagination['total'] == len(rows) == len(read_names) == 3


def test_unknown_or_dirty_catalog_never_falls_back(client, app, indexed, monkeypatch):
    catalog, results, estimates, archives, _ = indexed
    app.config.update(RESULT_CATALOG_PATH=str(catalog.path),RECEIVED_DIR=str(results),
                      ESTIMATED_DIR=str(estimates),RECEIVED_MEASUREMENT_ARTIFACTS_DIR=str(archives))
    with catalog.writer():
        with pytest.raises(CatalogUnavailable):
            with catalog.snapshot():
                pass
    with catalog._connect() as conn:
        conn.execute('UPDATE catalog_state SET ready=0')
        conn.commit()
    monkeypatch.setattr(os,'listdir',lambda *a: pytest.fail('Fallback scan'))
    assert client.get('/results/?search=1').status_code == 503
    _login_session(client,'admin@example.com',['admin'])
    assert client.get('/results/usage?run=1&report=node_hours').status_code == 503
    assert client.get('/results/usage/evidence-snapshot.csv').status_code == 503


def test_fact_allowlist_and_source_binding(indexed, tmp_path):
    catalog, results, estimates, _, _ = indexed
    with catalog._connect(readonly=True) as conn:
        raw = ' '.join(row[0] for row in conn.execute('SELECT facts FROM query_records'))
    assert 'not copied' not in raw and 'raw_output' not in raw and 'repo_url' not in raw
    other = tmp_path / 'other'
    other.mkdir()
    with pytest.raises(CatalogUnavailable):
        with ResultCatalog(catalog.path,results,estimated_directory=other).snapshot():
            pass
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for root in (results,estimates) for path in root.iterdir()}
    catalog.rebuild()
    assert all(hashlib.sha256(path.read_bytes()).hexdigest()==digest for path,digest in before.items())


def test_related_replace_delete_and_failure(indexed):
    catalog, _, estimates, archives, _ = indexed
    name = 'estimate_20261102_000000_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json'
    payload = dict(code='genesis',current_system={'system':'New'})
    def write():
        (estimates/name).write_text(json.dumps(payload))
    for _ in range(2):
        catalog.replace_related('estimates',name,payload,write)
    with catalog.snapshot() as reader:
        assert sum(r['data']['current_system']['system']=='New' for r in reader.records(str(estimates)))==1
    catalog.delete_related('estimates',name,lambda:(estimates/name).unlink())
    def fail():
        write()
        raise OSError('synthetic interruption')
    with pytest.raises(OSError):
        catalog.replace_related('estimates',name,payload,fail)
    with pytest.raises(CatalogUnavailable):
        with catalog.snapshot():
            pass
    catalog.rebuild()


def test_profile_definition_changes_are_not_baked_into_facts(indexed):
    catalog, results, _, _, db = indexed
    store=ExecutionProfileStore(db)
    with catalog.snapshot() as reader:
        before=build_profile_usage_overview(str(results),db,record_source=reader)
    store.upsert_profile(_profile(id='third',code='genesis'),actor='test@example.invalid')
    with catalog.snapshot() as reader:
        after=build_profile_usage_overview(str(results),db,record_source=reader)
    assert after['summary']['profile_count']==before['summary']['profile_count']+1


def test_explicit_v1_upgrade_and_rebuild_only(indexed):
    catalog, results, _, _, _ = indexed
    with catalog._connect() as conn:
        for table in ('query_records','catalog_sources','artifact_uuids','artifact_entries'):
            conn.execute('DROP TABLE '+table)
        conn.execute('DROP INDEX result_group_files')
        conn.execute('UPDATE catalog_state SET version=1')
        conn.commit()
    before=catalog.path.read_bytes()
    with pytest.raises(CatalogUnavailable):
        with catalog.snapshot():
            pass
    assert catalog.path.read_bytes()==before
    catalog.upgrade()
    with pytest.raises(CatalogUnavailable):
        with catalog.snapshot():
            pass
    catalog.rebuild()
    with catalog.snapshot() as reader:
        assert len(list(reader.records(str(results))))==7


def test_usage_and_csv_routes_use_index(client, app, indexed, monkeypatch):
    catalog, results, estimates, archives, db=indexed
    app.config.update(RESULT_CATALOG_PATH=str(catalog.path),RECEIVED_DIR=str(results),
                      ESTIMATED_DIR=str(estimates),EXECUTION_PROFILE_DB_PATH=db,
                      RECEIVED_MEASUREMENT_ARTIFACTS_DIR=str(archives))
    _login_session(client,'admin@example.com',['admin'])
    monkeypatch.setattr(os,'listdir',lambda *a:pytest.fail('Report scanned directories'))
    for report in ('node_hours','profiles','performance','evidence'):
        response=client.get('/results/usage?run=1&fiscal_year=2026&report='+report)
        assert response.status_code==200
    response=client.get('/results/usage/evidence-snapshot.csv?fiscal_year=2026')
    assert response.status_code==200 and 'genesis' in response.text


def test_query_filters_are_parameters_not_sql(indexed):
    catalog, _, _, _, _=indexed
    with catalog.snapshot() as reader:
        names,paging=reader.result_page(public_only=False,authenticated=True,affiliations=['admin'],
            page=1,per_page=50,filter_system="' OR 1=1--")
    assert names==[] and paging['total']==0


def test_archive_receipt_is_indexed_and_failure_before_write_preserves_bytes(indexed):
    import io
    from test_support import build_api_route_app
    catalog, results, estimates, archives, _=indexed
    app=build_api_route_app(received_dir=str(results),estimated_dir=str(estimates),
        received_padata_dir=str(archives),received_estimation_artifacts_dir=str(archives))
    app.config.update(RESULT_CATALOG_PATH=str(catalog.path),INGEST_KEYS={'fixture':'runner'})
    client=app.test_client()
    identifier='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    def upload(contents):
        return client.post('/api/ingest/measurement-artifact',headers={'X-API-Key':'fixture'},
            data=dict(id=identifier,timestamp='20261102_010101',artifact_path='results/profile.tgz',
                      file=(io.BytesIO(contents),'profile.tgz')))
    response=upload(b'first fixture')
    assert response.status_code==200
    name=response.json['file']
    with catalog.snapshot() as reader:
        assert name in reader.archives(str(archives),identifier)
    app.config['RESULT_CATALOG_PATH']=str(catalog.path.with_name('missing'))
    assert upload(b'must not write').status_code==503
    assert (archives/name).read_bytes()==b'first fixture'
    assert not (archives/(name+'.bak')).exists()


def test_page_rechecks_changed_confidentiality_and_symlinks(indexed, app):
    catalog, results, _, archives, _=indexed
    name=next(path.name for path in results.iterdir() if '20260810' in path.name)
    payload=json.loads((results/name).read_text())
    payload['confidential']=['new-private-tag']
    (results/name).write_text(json.dumps(payload))
    with app.test_request_context(),catalog.snapshot() as reader,pytest.raises(CatalogUnavailable):
        load_results_table(str(results),query_reader=reader,padata_directory=str(archives))
    (results/name).unlink()
    (results/name).symlink_to(next(path for path in results.iterdir() if '20270401' in path.name))
    with app.test_request_context(),catalog.snapshot() as reader,pytest.raises(CatalogUnavailable):
        load_results_table(str(results),query_reader=reader,padata_directory=str(archives))


def test_same_directory_results_and_estimates(tmp_path):
    source=tmp_path/'source'
    source.mkdir()
    private=tmp_path/'private'
    private.mkdir(mode=0o700)
    catalog=ResultCatalog(private/'index',source,estimated_directory=source,artifact_directory=source)
    catalog.initialize()
    catalog.rebuild()
    name='estimate_20261102_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json'
    payload={'code':'genesis','current_system':{'system':'System'}}
    catalog.replace_related('estimates',name,payload,lambda:(source/name).write_text(json.dumps(payload)))
    assert catalog.candidates()['total']==1  # The legacy Result loader includes every JSON in this directory.
    with catalog.snapshot() as reader:
        assert len(list(reader.records(str(source),prefix='estimate_')))==1
    catalog.rebuild()
    assert catalog.candidates()['total']==1


def test_archive_guard_indexes_the_actual_legacy_replacement_name(indexed):
    catalog, _, _, archives, _=indexed
    actual='padata_20261102_010101_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.tgz'
    def write():
        (archives/actual).write_bytes(b'fixture')
        return actual
    catalog.replace_related('artifacts','unused.tgz',None,write)
    with catalog.snapshot() as reader:
        assert reader.archives(str(archives),'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')==[actual]


def test_legacy_non_uuid_archive_identifiers_keep_their_match(indexed):
    catalog, _, _, archives, _=indexed
    name='legacy-custom-id.tgz'
    catalog.replace_related('artifacts',name,None,lambda:(archives/name).write_bytes(b'fixture'))
    with catalog.snapshot() as reader:
        assert reader.archives(str(archives),'custom-id')==[name]


def test_profile_scope_cache_uses_the_existing_string_comparison(indexed):
    catalog, results, _, _, db = indexed
    store = ExecutionProfileStore(db)
    for number, exp in enumerate(({'first':1,'second':2}, {'second':2,'first':1})):
        profile = _profile(id=f'ordered-{number}', code='genesis', system='OrderedSystem', exp=[str(exp)])
        store.upsert_profile(profile, actor='test@example.invalid')
        name = f'result_20261102_00000{number}_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json'
        data = dict(code='genesis',system='OrderedSystem',Exp=exp,node_count=1,
                    pipeline_timing=dict(run_time=3600))
        catalog.replace(name, data, lambda name=name,data=data:(results/name).write_text(json.dumps(data)))
    with catalog.snapshot() as reader:
        result = build_profile_usage_overview(str(results),db,record_source=reader)
    rows = {row['profile_id']:row for row in result['rows']}
    assert rows['ordered-0']['result_count'] == rows['ordered-1']['result_count'] == 1
