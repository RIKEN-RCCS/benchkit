import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response
from utils.cx_persistence import CxPersistence
from utils.encrypted_sqlite import generate_key
from utils.public_disclosure import DisclosurePolicy, digest
from utils.public_projection import export_public
from utils.public_delivery import PublicApplication

SECRET = 'synthetic-do-not-publish'
UUID = '12345678-1234-1234-1234-123456789abc'
NAME = 'result_20260101_010101_' + UUID + '.json'
ARCHIVE = 'padata_20260101_010101_' + UUID + '.tgz'


@pytest.fixture
def store(tmp_path):
    for name in ['data', 'keys', 'results', 'estimates', 'artifacts', 'inputs']:
        (tmp_path/name).mkdir(mode=0o700)
    key = tmp_path/'keys/key'
    generate_key(key)
    value = CxPersistence(tmp_path/'data/cx.db', key, roots={k:str(tmp_path/k) for k in ['results','estimates','artifacts','inputs']})
    value.initialize()
    return value


def tar(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, data in members.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def fixture(store):
    source = {'system':'sample','code':'demo','Exp':'allowed','FOM':2.0,'_server_uuid':UUID,
              'description':SECRET,'profile_data':{'ncu_options':SECRET},
              'source_info':{'branch':SECRET},'fom_breakdown':{'sections':[{'name':SECRET,'artifacts':[{'type':'file_reference','path':SECRET}]}]}}
    payload = tar({'public.txt':b'approved result', 'private.txt':SECRET.encode()})
    store.put_document('results', NAME, json.dumps(source).encode())
    store.put('artifacts', ARCHIVE, io.BytesIO(payload), limit=len(payload))
    allowed = {'system':'sample','code':'demo','Exp':'allowed','FOM':2.0,'_server_uuid':UUID}
    policy = DisclosurePolicy({NAME:{'source_sha256':digest(source),'value':allowed}},
                              {ARCHIVE:{'source_sha256':hashlib.sha256(payload).hexdigest(),
                                        'members':{'public.txt':hashlib.sha256(b'approved result').hexdigest()}}})
    return source, policy


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
    for variable in ['RESULT_SERVER_PERSISTENCE_DB','RESULT_SERVER_PERSISTENCE_KEY', 'RESULT_SERVER_PERSISTENCE_ARTIFACT_DB', 'RESULT_SERVER_KEYS','RESULT_SERVER_KEY','RESULT_SERVER_BUDGET_DB_KEY_FILE','RESULT_SERVER_RUNNER_MONITOR_KEY_FILE', 'RESULT_SERVER_SHARED_DB_POLICY']:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv('FLASK_SECRET_KEY','x'*64)
    monkeypatch.setenv('RESULT_SERVER_PUBLIC_STATE_DIR',str(tmp_path/'session'))
    import app
    def no_redis(application, *args):
        application.config.update(REDIS_CONN=None,REDIS_PREFIX='test:',AUTH_REQUIRES_REDIS=False)
    monkeypatch.setattr(app,'_configure_redis',no_redis)
    client = Client(PublicApplication(root, os.geteuid()), Response)
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


def test_source_change_invalidates_previous_approval(store, tmp_path):
    source, policy = fixture(store)
    source['FOM'] = 3
    store.put_document('results',NAME,json.dumps(source).encode())
    assert export_public(store,tmp_path/'changed',policy=policy)['results'] == 0


def test_unreviewed_archive_content_is_denied():
    raw = tar({'public.txt':b'changed'})
    policy = DisclosurePolicy(archives={ARCHIVE:{'source_sha256':hashlib.sha256(raw).hexdigest(),
                            'members':{'public.txt':hashlib.sha256(b'expected').hexdigest()}}})
    assert policy.archive(ARCHIVE,raw,maximum_bytes=1024) is None


def test_result_approval_does_not_approve_archive_contents(store,tmp_path):
    _, policy = fixture(store)
    policy.archives = {}
    result = export_public(store,tmp_path/'without-attachment',policy=policy)
    assert result['results']==1 and result['archives']==0
    assert not list((tmp_path/'without-attachment/received_padata').iterdir())
