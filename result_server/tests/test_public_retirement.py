import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
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
