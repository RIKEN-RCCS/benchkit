import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid
import socket
import http.client

from test_cx_persistence import encrypted_app, storage
from test_public_disclosure import tar
from urllib.parse import quote
from test_public_supervision import service, wait_for, pytestmark


def test_normal_ingest_automatic_publication(service, encrypted_app, storage, monkeypatch, tmp_path):
    root, state, _, connect = service
    # Real path activation uses the same command as the trusted one-shot worker.
    code = root/'code'
    # Reserve a loopback test port independently of the other service fixtures.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    queue = root/'queue'
    queue.mkdir(mode=0o700)
    monkeypatch.setenv('RESULT_SERVER_PUBLICATION_QUEUE', str(queue))
    identifier = 'public-ingest-test-' + uuid.uuid4().hex
    unit = identifier + '.service'
    private = Path(storage.roots['artifacts'])/'internal.tgz'
    private.write_bytes(b'internal-attachment')
    paths = [storage.path, storage.storage.key_file, storage.blobs.path, private]
    assert all(p.is_file() for p in paths)
    (root/'access-probe.json').write_text(json.dumps([str(p) for p in paths]))
    config = {
        'queue':str(queue),
        'store':{'path':str(storage.path),'key_file':str(storage.storage.key_file),'roots':storage.roots},
        'benchmarks':{'demo':{'profile':{'tool':['sample'], 'events':['cycles']},
                              'packages':{'math':['1']},
                              'pa':{'report.tgz':{'member':'metrics.csv','columns':['cycles']}}}},
        'supervisor':{'root':str(root/'public'), 'private_state':str(root/'state/publisher.json'),
                      'reader_uid':65534, 'writer_unit':unit,
                      'reader_command':[sys.executable,str(code/'tests/public_supervisor_fixture.py'),
                                        str(root),'reader','--port',str(port)],
                      'reader_environment':{'PYTHONPATH':str(code),'FLASK_SECRET_KEY':'synthetic'*8,
                                            'RESULT_SERVER_PUBLIC_STATE_DIR':str(root/'sessions')}}
    }
    config['benchmarks']['demo']['pa']['unlisted.tgz'] = config['benchmarks']['demo']['pa']['report.tgz']
    config_path = root/'state/config.json'
    config_path.write_text(json.dumps(config))
    subprocess.run(['systemd-run','--quiet','--unit='+identifier,'--path-property=PathExists='+str(queue/'pending'),
                    '--path-property=PathExists='+str(queue/'publishing'),
                    '--property=Type=exec','--setenv=PYTHONPATH='+str(code),
                    sys.executable,'-m','utils.public_events',str(config_path)],check=True)
    client = encrypted_app.test_client()
    headers = {'X-API-Key':'synthetic-key'}
    marker = 'synthetic-private-marker'
    activity = 'synthetic-public-project'
    private_path = 'results/'+marker+'/report.tgz'
    source = {'system':'sample','code':'demo','Exp':'public-experiment','FOM':12,
              'environment_snapshot':{'summary':{'activity':activity}},
              'source_info':{'source_type':'git','branch':marker},
              'profile_data':{'tool':'sample','events':['cycles',marker]},
              'build':{'spack':{'packages':[{'name':'math','version':'1'},{'name':marker,'version':'1'}]}},
              'fom_breakdown':{'sections':[{'name':marker,'artifacts':[{'type':'file_reference','path':private_path}]}]}}
    def get_http(path):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        try:
            c.request('GET',path)
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()
    leases = set()
    def rebuild():
        response = subprocess.run([sys.executable, '-m', 'utils.public_events',
                                   '--request-rebuild', str(config_path)], cwd=code,
                                  capture_output=True, text=True, check=True)
        assert response.stdout.strip() == 'queued'

    try:
        # Lose the response after the first Result commits but before its marker exists.
        child = os.fork()
        if child == 0:
            try:
                import routes.api
                routes.api.notify_publication = lambda: os._exit(37)
                client.post('/api/ingest/result', headers=headers,
                            json={'code':'second', 'Exp':'independent', 'FOM':2})
            finally:
                os._exit(1)
        assert os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) == 37
        second_name, = storage.names('results')
        assert not (queue/'pending').exists() and not (queue/'publishing').exists()
        # Fail only the notification for the second receipt, using a missing directory.
        monkeypatch.setenv('RESULT_SERVER_PUBLICATION_QUEUE', str(root/'missing'))
        source['fom_breakdown']['sections'].extend([None, {'artifacts':42}])
        source['fom_breakdown']['sections'][0]['artifacts'].extend(
            [False, {'type':'file_reference','path':['results/unlisted.tgz']}])
        saved = client.post('/api/ingest/result', headers=headers, json=source)
        assert saved.status_code == 200
        saved = saved.get_json()
        assert saved['publication_notification'] == 'failed'
        assert set(storage.names('results')) == {second_name, saved['json_file']}
        assert not (queue/'pending').exists() and not (root/'public/current.json').exists()
        from utils.public_events import publish_pending
        assert publish_pending(queue, None) == 'idle'
        rebuild()
        monkeypatch.setenv('RESULT_SERVER_PUBLICATION_QUEUE', str(queue))
        def done():
            if not (root/'state/publisher.supervision.json').exists():
                return False
            st = state()
            leases.update([st['guard_unit'],st['reader_unit']])
            return st['complete'] and not (queue/'publishing').exists() and not (queue/'pending').exists()
        wait_for(done)
        def listed():
            try:
                status, body = get_http('/results/?search=1')
                return status == 200 and activity.encode() in body and b'public-experiment' in body
            except OSError:
                return False
        wait_for(listed)
        unlisted = client.post('/api/ingest/padata', headers=headers, data={
            'id':saved['id'], 'timestamp':saved['timestamp'], 'artifact_path':'results/unlisted.tgz',
            'file':(io.BytesIO(tar({'metrics.csv':b'cycles\n99\n'})), 'unlisted.tgz')})
        assert unlisted.status_code == 200 and unlisted.get_json()['publication_notification'] == 'queued'
        private_name = unlisted.get_json()['file']
        assert storage.exists('artifacts', private_name)
        wait_for(done)
        payload = tar({'metrics.csv':('cycles,internal\n42,'+marker+'\n').encode(),'secret.txt':marker.encode()})
        original = storage.read('results',saved['json_file'])
        monkeypatch.setenv('RESULT_SERVER_PUBLICATION_QUEUE', str(root/'missing'))
        upload = client.post('/api/ingest/padata',headers=headers,data={'id':saved['id'],'timestamp':saved['timestamp'],
                             'artifact_path':private_path,'file':(io.BytesIO(payload),'report.tgz')})
        assert upload.status_code == 200
        assert upload.get_json()['publication_notification'] == 'failed'
        archive = upload.get_json()['file']
        assert storage.exists('artifacts', archive) and not (queue/'pending').exists()
        for _ in range(2):
            rebuild()
            wait_for(done)
            current, = (root/'public/generations').iterdir()
            assert {p.name for p in (current/'received').iterdir()} == {saved['json_file'], second_name}
            assert [p.name for p in (current/'received_padata').iterdir()] == [archive]
        assert set(storage.names('artifacts')) == {archive, private_name}
        assert set(storage.names('results')) == {saved['json_file'], second_name}
        wait_for(done)
        wait_for(lambda:(root/'sessions/access.json').exists())
        assert json.loads((root/'sessions/access.json').read_text()) == [True]*4
        wait_for(listed)
        for path in ['/results/?search=1','/results/detail/'+saved['json_file']]:
            status, body = get_http(path)
            assert status == 200 and marker.encode() not in body and b'public-experiment' in body
            assert archive.encode() in body
            if 'search' in path:
                assert activity.encode() in body
        second_status, second_body = get_http('/results/detail/'+second_name)
        assert second_status == 200 and b'independent' in second_body
        assert get_http('/results/'+quote(private_name))[0] == 404
        status, body = get_http('/results/'+archive)
        assert status == 200
        with tarfile.open(fileobj=io.BytesIO(body)) as bundle:
            assert bundle.getnames() == ['metrics.csv']
            assert bundle.extractfile('metrics.csv').read().splitlines() == [b'cycles',b'42.0']
        generation = next((root/'public/generations').iterdir())
        document = json.loads((generation/'received'/saved['json_file']).read_bytes())
        assert document['profile_data']['events'] == ['cycles']
        assert document['build']['spack']['packages'] == [{'name':'math','version':'1'}]
        assert 'source_info' not in document and marker not in json.dumps(document)
        assert marker.encode() not in (generation/'index/catalog.sqlite3').read_bytes()
        assert storage.read('results',saved['json_file']) == original
        (tmp_path/"accepted-result.json").write_bytes((generation/"received"/saved["json_file"]).read_bytes())
        (tmp_path/"accepted-pa.tgz").write_bytes(body)
        monkeypatch.setenv('RESULT_SERVER_PUBLICATION_QUEUE', str(queue))
        normal = client.post('/api/ingest/result', headers=headers,
                             json={'code':'normal', 'Exp':'normal-notification', 'FOM':3})
        assert normal.status_code == 200 and normal.get_json()['publication_notification'] == 'queued'
        wait_for(done)
        wait_for(listed)
        status, body = get_http('/results/detail/'+normal.get_json()['json_file'])
        assert status == 200 and b'normal-notification' in body
    finally:
        for item in [identifier+'.path',unit,*leases]:
            subprocess.run(['systemctl','stop',item],capture_output=True)
            subprocess.run(['systemctl','reset-failed',item],capture_output=True)
