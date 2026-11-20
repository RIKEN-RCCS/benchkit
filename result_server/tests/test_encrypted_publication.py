"""Public disclosure and retirement checks that require an encrypted store."""
import io
import json
import math
import os
import tarfile
import time

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_public_disclosure import ARCHIVE, NAME, SECRET, UUID, fixture, store, tar
from test_public_retirement import Control
from utils.public_delivery import PublicApplication, Publisher, read_current
from utils.public_disclosure import AutomaticDisclosure
from utils.public_projection import export_public


def test_reclassification_and_failure_do_not_restore_old_data(store, tmp_path):
    source, policy = fixture(store)
    control = Control()
    publisher = Publisher(store,tmp_path/'public',tmp_path/'state/publisher.json',123,control=control,policy=policy)
    publisher.update()
    old, _ = read_current(publisher.root)
    assert (old/ 'received'/NAME).exists()
    def make_private():
        source['confidential'] = ['restricted']
        store.put_document('results',NAME,json.dumps(source).encode())
    with pytest.raises(RuntimeError):
        publisher.update(change=make_private,fault=lambda stage: (_ for _ in ()).throw(RuntimeError('injected')))
    assert not control.active and not old.exists()
    assert not list((publisher.root/'generations').iterdir())
    with pytest.raises(ValueError):read_current(publisher.root)
    publisher.update()
    generation, _ = read_current(publisher.root)
    assert not list((generation/'received').iterdir())


def test_continuous_updates_and_capacity(store, tmp_path):
    _, policy = fixture(store)
    p = Publisher(store,tmp_path/'public',tmp_path/'state/publisher.json',123,control=Control(),policy=policy)
    for _ in range(4):
        p.update()
        assert len(list((p.root/'generations').iterdir())) <= 2
        assert sum(f.stat().st_size for f in p.root.rglob('*') if f.is_file()) <= 256*1024*1024
    p.maximum_bytes = 32
    with pytest.raises(ValueError):p.update()
    assert not list((p.root/'generations').iterdir())


def test_response_stops_and_http_rejects_retired_content(store, tmp_path, monkeypatch):
    _, policy = fixture(store)
    p = Publisher(store,tmp_path/'public',tmp_path/'state/p.json',123,control=Control(),policy=policy)
    p.update()
    generation, _ = read_current(p.root)
    for name in ['RESULT_SERVER_PERSISTENCE_DB','RESULT_SERVER_PERSISTENCE_KEY', 'RESULT_SERVER_PERSISTENCE_ARTIFACT_DB', 'RESULT_SERVER_KEYS','RESULT_SERVER_KEY','RESULT_SERVER_BUDGET_DB_KEY_FILE','RESULT_SERVER_RUNNER_MONITOR_KEY_FILE']:
        monkeypatch.delenv(name,raising=False)
    application = PublicApplication(p.root,os.geteuid())
    closed = []
    def old_response(environ, start_response):
        start_response('200 OK',[('Content-Type','text/plain')])
        def body():
            try:
                yield b'first'
                yield b'old-copy'
            finally:closed.append(True)
        return body()
    application.applications[str(generation)] = old_response
    client = Client(application,Response)
    response = client.get('/',buffered=False)
    iterator = iter(response.response)
    assert next(iterator)==b'first'
    p.expire()
    assert list(iterator)==[] and closed
    assert client.get('/results/'+NAME).status_code==503


def test_default_denies_values_and_archives(store, tmp_path):
    fixture(store)
    result = export_public(store, tmp_path/'none')
    assert result['results'] == result['archives'] == 0


def test_sensitive_values_and_members_absent_in_http(store, tmp_path, monkeypatch):
    _, policy = fixture(store)
    root = tmp_path/'publication'
    destination = root/'generations'/('g-'+'a'*32)
    destination.parent.mkdir(parents=True)
    export_public(store, destination, policy=policy)
    for p in [destination,*destination.rglob('*')]:
        p.chmod(0o750 if p.is_dir() else 0o640)
    (root/'current.json').write_text(json.dumps({'generation':destination.name,'checked_at':time.time(),'expires_at':time.time()+900}))
    client = public_client(root, tmp_path, monkeypatch)
    for url in ['/results/?search=1','/results/detail/'+NAME]:
        response = client.get(url)
        assert response.status_code == 200
        assert SECRET.encode() not in response.data
        assert b'allowed' in response.data
    data = json.loads((destination/'received'/NAME).read_text())
    assert SECRET not in json.dumps(data)
    response = client.get('/results/'+ARCHIVE)
    assert response.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(response.data),mode='r:gz') as content:
        assert content.getnames() == ['public.txt']
        assert content.extractfile('public.txt').read() == b'approved result'
    assert SECRET.encode() not in (destination/'index/catalog.sqlite3').read_bytes()


def public_client(root, tmp_path, monkeypatch):
    for variable in ['RESULT_SERVER_PERSISTENCE_DB','RESULT_SERVER_PERSISTENCE_KEY', 'RESULT_SERVER_PERSISTENCE_ARTIFACT_DB', 'RESULT_SERVER_KEYS','RESULT_SERVER_KEY','RESULT_SERVER_BUDGET_DB_KEY_FILE','RESULT_SERVER_RUNNER_MONITOR_KEY_FILE', 'RESULT_SERVER_SHARED_DB_POLICY']:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv('FLASK_SECRET_KEY','x'*64)
    monkeypatch.setenv('RESULT_SERVER_PUBLIC_STATE_DIR',str(tmp_path/'session'))
    import app
    def no_redis(application, *args):
        application.config.update(REDIS_CONN=None,REDIS_PREFIX='test:',AUTH_REQUIRES_REDIS=False)
    monkeypatch.setattr(app,'_configure_redis',no_redis)
    return Client(PublicApplication(root, os.geteuid()), Response)


def test_automatic_publication_omits_only_nonfinite_fom(store, tmp_path, monkeypatch):
    originals = {}
    for i, fom in enumerate([float('nan'), float('inf'), -float('inf'), 42.5]):
        uid = f'12345678-1234-1234-1234-{i:012d}'
        name = f'result_20260101_010101_{uid}.json'
        doc = {'system': 'sample', 'code': 'demo', 'Exp': f'mixed-case-{i}',
               'FOM': fom, 'FOM_unit': 's', '_server_uuid': uid,
               'environment_snapshot': {'summary': {'activity': f'activity-{i}'}}}
        raw = json.dumps(doc).encode()
        store.put_document('results', name, raw)
        originals[name] = raw

    publisher = Publisher(store, tmp_path/'public', tmp_path/'state/p.json', 123,
                          control=Control(), policy=AutomaticDisclosure({}))
    assert publisher.update() == {'status': 'published', 'results': 4, 'archives': 0}
    generation, _ = read_current(publisher.root)
    client = public_client(publisher.root, tmp_path, monkeypatch)
    listing = client.get('/results/?search=1')
    assert listing.status_code == 200
    for name, raw in originals.items():
        assert store.read('results', name) == raw
        expected = json.loads(raw)
        if not math.isfinite(expected['FOM']):
            del expected['FOM']
        public = json.loads((generation/'received'/name).read_bytes(), parse_constant=pytest.fail)
        assert public == expected
        assert expected['Exp'].encode() in listing.data
        assert expected['environment_snapshot']['summary']['activity'].encode() in listing.data
        detail = client.get('/results/detail/' + name)
        assert detail.status_code == 200
        assert expected['Exp'].encode() in detail.data


def test_source_change_invalidates_previous_approval(store, tmp_path):
    source, policy = fixture(store)
    source['FOM'] = 3
    store.put_document('results',NAME,json.dumps(source).encode())
    assert export_public(store,tmp_path/'changed',policy=policy)['results'] == 0


def test_automatic_pa_rejects_unsafe_members_without_hiding_result(store, tmp_path, monkeypatch):
    timestamp = '20260101_010101'
    members = {'safe.tgz': 'metrics/data.csv', 'absolute.tgz': str(tmp_path/'data.csv'),
               'parent.tgz': 'metrics/../data.csv'}
    rules = {name: {'member': member, 'columns': ['seconds']} for name, member in members.items()}
    refs = [{'type': 'file_reference', 'path': 'results/' + name} for name in members]
    doc = {'code': 'demo', 'Exp': 'archive-case', '_server_uuid': UUID, '_server_timestamp': timestamp,
           'fom_breakdown': {'sections': [{'artifacts': refs}]}}
    store.put_document('results', NAME, json.dumps(doc).encode())
    stored_names = {}
    for name, member in members.items():
        stored = f'padata_{timestamp}_{UUID}_{name}'
        payload = tar({member: b'seconds,other\n12,34\n'})
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as source:
            assert source.getnames() == [rules[name]['member']]
        store.put('artifacts', stored, io.BytesIO(payload), limit=len(payload))
        stored_names[name] = stored

    publisher = Publisher(store, tmp_path/'public', tmp_path/'state/p.json', 123,
                          control=Control(), policy=AutomaticDisclosure({'demo': {'pa': rules}}))
    assert publisher.update() == {'status': 'published', 'results': 1, 'archives': 1}
    generation, _ = read_current(publisher.root)
    public = json.loads((generation/'received'/NAME).read_bytes())
    assert public['fom_breakdown']['sections'][0]['artifacts'] == [refs[0]]
    client = public_client(publisher.root, tmp_path, monkeypatch)
    detail = client.get('/results/detail/' + NAME)
    assert detail.status_code == 200 and b'archive-case' in detail.data
    for name in ('absolute.tgz', 'parent.tgz'):
        assert client.get('/results/' + stored_names[name]).status_code == 404
    response = client.get('/results/' + stored_names['safe.tgz'])
    assert response.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(response.data), mode='r:gz') as archive:
        assert archive.getnames() == ['metrics/data.csv']
        assert archive.extractfile('metrics/data.csv').read().splitlines() == [b'seconds', b'12.0']


def test_result_approval_does_not_approve_archive_contents(store,tmp_path):
    _, policy = fixture(store)
    policy.archives = {}
    result = export_public(store,tmp_path/'without-attachment',policy=policy)
    assert result['results']==1 and result['archives']==0
    assert not list((tmp_path/'without-attachment/received_padata').iterdir())
