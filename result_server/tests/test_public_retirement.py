import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

import pytest
from test_public_disclosure import store, fixture, NAME
from utils.public_delivery import Publisher, read_current


class Control:
    def __init__(self):
        self.active = False
    def quiesce(self, *, timeout):
        assert timeout == 5
        self.active = False
    def stage(self, *, expires_at):
        assert 0 < expires_at-time.time() <= 900
    def activate(self, *, expires_at):
        assert 0 < expires_at-time.time() <= 900
        self.active = True


def test_reclassification_and_failure_do_not_restore_old_data(store, tmp_path):
    source, policy = fixture(store)
    control = Control()
    publisher = Publisher(store,tmp_path/'public',tmp_path/'state/publisher.json',123,control=control,policy=policy)
    publisher.update()
    old, _ = read_current(publisher.root)
    assert (old/ 'received'/NAME).exists()
    import json
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


@pytest.mark.skipif(os.geteuid()!=0, reason='Reader UID acceptance runs separately as root')
def test_open_fds_streams_and_lease_are_revoked():
    import shutil
    from utils.public_disclosure import DisclosurePolicy
    root = Path(tempfile.mkdtemp(prefix='publication-reader-'))
    root.chmod(0o711)
    class Supervisor(Control):
        timer = None
        children = None
        def quiesce(self, *, timeout):
            if self.timer:self.timer.cancel()
            for child in self.children or []:
                if child.poll() is None:os.killpg(child.pid,signal.SIGKILL)
                child.wait(timeout=timeout)
            self.active = False
        def stage(self, *, expires_at):
            if self.timer:self.timer.cancel()
            self.timer = threading.Timer(max(0,expires_at-time.time()),publisher.expire)
            self.timer.start()
        def activate(self, *, expires_at):
            self.active = True
            generation, _ = read_current(publisher.root)
            target = generation/'received/probe'
            target.write_bytes(b'synthetic')
            subprocess.run(['setfacl','-m','u:65534:r',str(target)],check=True)
            code = "import sys,time; f=open(sys.argv[1],'rb'); print('open',flush=True); time.sleep(30); print(f.read(),flush=True)"
            self.children = [subprocess.Popen([sys.executable,'-c',code,str(target)],user=65534,group=65534,extra_groups=[],start_new_session=True,stdout=subprocess.PIPE) for _ in range(2)]
            for child in self.children:assert child.stdout.readline()==b'open\n'
    class Store:pass
    supervisor = Supervisor()
    publisher = Publisher(Store(),root/'public',root/'state/p.json',65534,control=supervisor,policy=DisclosurePolicy())
    import utils.public_projection as projection
    def export(store, destination, **kwargs):
        destination.mkdir();(destination/'received').mkdir()
        return {'results':0,'archives':0}
    original = projection.export_public
    projection.export_public = export
    try:
        publisher.maximum_age = 1
        publisher.update()
        old, _ = read_current(publisher.root)
        assert all(child.poll() is None for child in supervisor.children)
        started = time.monotonic()
        publisher.expire()
        assert time.monotonic()-started < 5
        assert all(child.poll() is not None for child in supervisor.children)
        assert not old.exists()
        denied = subprocess.run([sys.executable,'-c','import pathlib,sys; pathlib.Path(sys.argv[1]).read_bytes()',str(old/'received/probe')],
                                user=65534,group=65534,extra_groups=[],capture_output=True)
        assert denied.returncode != 0
        publisher.update()
        old, _ = read_current(publisher.root)
        deadline = time.monotonic()+4
        while old.exists() and time.monotonic()<deadline:
            time.sleep(.02)
        assert not old.exists()
        assert all(child.poll() is not None for child in supervisor.children)
        orphan = publisher.root/'.pending-abandoned'
        orphan.mkdir()
        (orphan/'probe').write_bytes(b'synthetic')
        supervisor.stage(expires_at=time.time()+.1)
        deadline = time.monotonic()+4
        while orphan.exists() and time.monotonic()<deadline:time.sleep(.02)
        assert not orphan.exists()
    finally:
        supervisor.quiesce(timeout=5)
        projection.export_public = original
        shutil.rmtree(root)


def test_response_stops_and_http_rejects_retired_content(store, tmp_path, monkeypatch):
    _, policy = fixture(store)
    p = Publisher(store,tmp_path/'public',tmp_path/'state/p.json',123,control=Control(),policy=policy)
    p.update()
    generation, _ = read_current(p.root)
    for name in ['RESULT_SERVER_PERSISTENCE_DB','RESULT_SERVER_PERSISTENCE_KEY', 'RESULT_SERVER_PERSISTENCE_ARTIFACT_DB', 'RESULT_SERVER_KEYS','RESULT_SERVER_KEY','RESULT_SERVER_BUDGET_DB_KEY_FILE','RESULT_SERVER_RUNNER_MONITOR_KEY_FILE']:
        monkeypatch.delenv(name,raising=False)
    from utils.public_delivery import PublicApplication
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
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
