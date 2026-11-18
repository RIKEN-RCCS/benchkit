"""Opt-in acceptance against isolated transient systemd services and synthetic DBs."""
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 or os.environ.get('RUN_PUBLIC_SUPERVISOR_ACCEPTANCE') != '1',
    reason='Requires explicit isolated systemd acceptance approval')


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError('Acceptance deadline exceeded')


def alive(pid):
    path = Path('/proc')/str(pid)/'stat'
    try:
        return path.read_text().split(') ', 1)[1][0] != 'Z'
    except (FileNotFoundError, ProcessLookupError):
        return False


@pytest.fixture
def service():
    root = Path(tempfile.mkdtemp(prefix='public-supervision-'))
    root.chmod(0o755)
    code = root/'code'
    shutil.copytree(Path(__file__).parents[1], code,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
    for path in [code, *code.rglob('*')]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    (root/'sessions').mkdir(mode=0o700)
    os.chown(root/'sessions', 65534, 65534)
    (root/'state').mkdir(mode=0o700)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    units = set()
    def state():
        value = json.loads((root/'state/publisher.supervision.json').read_text())
        units.update([value['guard_unit'], value['reader_unit']])
        return value
    def start(mode, lifetime=20):
        unit = 'public-test-writer-' + uuid.uuid4().hex + '.service'
        units.add(unit)
        (root/'writer-complete').unlink(missing_ok=True)
        subprocess.run(['systemd-run', '--quiet', '--unit='+unit,
                        '--property=Type=exec', '--property=KillMode=control-group',
                        '--property=KillSignal=SIGKILL', '--property=TimeoutStopSec=1s',
                        '--setenv=PYTHONPATH='+str(code),
                        '--setenv=PYTHONDONTWRITEBYTECODE=1',
                        sys.executable, str(code/'tests/public_supervisor_fixture.py'),
                        str(root), mode, '--unit', unit, '--port', str(port),
                        '--lifetime', str(lifetime)], check=True, capture_output=True)
        wait_for(lambda: (root/'state/publisher.supervision.json').exists())
        value = state()
        wait_for(lambda: value['writer_unit'] == unit or state()['writer_unit'] == unit)
        return state()
    def connect(path='/results/?search=1'):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        connection.request('GET', path)
        return connection, connection.getresponse()
    yield root, state, start, connect
    if (root/'state/publisher.supervision.json').exists():
        state()
    for unit in units:
        subprocess.run(['systemctl', 'stop', unit], capture_output=True, timeout=10)
    with open('/tmp/portal-supervisor-unit-debug.log', 'a') as log:
        for unit in units:
            subprocess.run(['journalctl', '--no-pager', '-u', unit, '-n', '60', '-o', 'cat'], stdout=log, stderr=log)
    for unit in units:
        subprocess.run(['systemctl', 'reset-failed', unit], capture_output=True)
    shutil.rmtree(root)


def assert_retired(root, connect, state):
    wait_for(lambda: not (root/'public/current.json').exists())
    wait_for(lambda: not list((root/'public/generations').iterdir()))
    assert not list((root/'public').glob('.pending-*'))
    assert (root/'public/withdrawn').exists()
    unit = state()['reader_unit']
    result = subprocess.run(['systemctl', 'is-active', '--quiet', unit])
    assert result.returncode != 0
    try:
        connection, response = connect()
    except (ConnectionError, OSError):
        pass
    else:
        try:
            assert response.status >= 500
        finally:
            connection.close()
    # A fresh process with the public reader UID cannot reopen an old copy.
    result = subprocess.run([sys.executable, '-c',
                             'import pathlib,sys; print(list(pathlib.Path(sys.argv[1]).rglob("*.json")))',
                             str(root/'public/generations')],
                            user=65534, group=65534, extra_groups=[], capture_output=True)
    assert result.returncode == 0 and result.stdout.strip() == b'[]'


@pytest.mark.parametrize('reason', ['withdraw', 'expiry', 'guard-crash', 'reader-crash'])
def test_active_http_and_descendants_stop(service, reason):
    root, state, start, connect = service
    current = start('withdraw' if reason == 'withdraw' else 'normal', lifetime=8)
    wait_for(lambda: (root/'writer-complete').exists())
    def ready():
        try:
            connection, response = connect()
            good = response.status == 200 and b'allowed' in response.read()
            connection.close()
            return good
        except (OSError, http.client.HTTPException):
            return False
    wait_for(ready)
    connection, response = connect('/stream')
    assert response.status == 200 and response.read(1)
    child = int((root/'sessions/child-pid').read_text())
    assert alive(child)
    started = time.monotonic()
    if reason == 'withdraw':
        (root/'withdraw-now').touch()
    elif reason == 'expiry':
        started += max(0, state()['expires_at'] - time.time())
    else:
        unit = current['guard_unit'] if reason == 'guard-crash' else current['reader_unit']
        subprocess.run(['systemctl', 'kill', '--signal=SIGKILL', unit], check=True)
    wait_for(lambda: not alive(child), timeout=10)
    elapsed = time.monotonic() - started
    assert elapsed <= 5
    assert_retired(root, connect, state)
    try:
        response.read()  # Bytes already sent before withdrawal can remain buffered.
    except (ConnectionError, OSError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    (root/'measured.json').write_text(json.dumps({'reason':reason,'stop_seconds':elapsed}))
    print(json.dumps({'reason':reason,'stop_seconds':round(elapsed, 3)}))


@pytest.mark.parametrize('mode', ['crash-build', 'hung-build', 'crash-active'])
def test_writer_failure_and_incomplete_build_are_revoked(service, mode):
    root, state, start, connect = service
    start(mode, lifetime=3)
    unit = state()['writer_unit']
    wait_for(lambda: subprocess.run(['systemctl', 'is-active', '--quiet', unit],
                                   capture_output=True).returncode != 0)
    wait_for(lambda: (root/'public/withdrawn').exists())
    wait_for(lambda: not list((root/'public/generations').iterdir()) and
             not list((root/'public').glob('.pending-*')), timeout=10)
    assert_retired(root, connect, state)
    if mode != 'hung-build':
        elapsed = time.monotonic() - float((root/'failure-time').read_text())
    else:
        elapsed = time.time() - state()['expires_at']
    assert elapsed < 5
    print(json.dumps({'reason':mode, 'revoked_seconds':round(elapsed, 3)}))


def test_renewal_old_guard_cannot_withdraw_new_generation(service):
    root, state, start, connect = service
    first = start('normal', lifetime=4)
    wait_for(lambda: (root/'writer-complete').exists())
    first_generation = json.loads((root/'public/current.json').read_text())['generation']
    second = start('normal', lifetime=15)
    wait_for(lambda: (root/'writer-complete').exists())
    assert second['token'] != first['token']
    wait_for(lambda: time.time() > first['expires_at'] + .3)
    assert (root/'public/current.json').exists()
    assert not (root/'public/generations'/first_generation).exists()
    assert state()['token'] == second['token']
