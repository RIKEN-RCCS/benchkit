"""Trusted systemd supervision for opt-in public publication services.

All arguments are administrator-controlled. Run the writer in a dedicated
systemd service. Every publication starts a separate, bounded reader service.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
import uuid

from utils.public_delivery import Publisher, atomic_json


def systemctl(*arguments):
    return subprocess.run(['systemctl', *arguments], check=True, capture_output=True,
                          text=True, timeout=4)


def unit_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}\.service', value):
        raise ValueError('Invalid service name')
    return value


def process_start(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().split(') ', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def load_state(path):
    return json.loads(Path(path).read_text())


def stop_unit(unit):
    # A stopped main process alone does not establish an empty reader cgroup.
    unit_name(unit)
    loaded = subprocess.run(['systemctl', 'show', unit, '--property=LoadState', '--value'],
                            capture_output=True, text=True, timeout=2)
    if loaded.stdout.strip() == 'not-found':
        return
    systemctl('stop', unit)
    group = systemctl('show', unit, '--property=ControlGroup', '--value').stdout.strip()
    if group:
        events = Path('/sys/fs/cgroup') / group.lstrip('/') / 'cgroup.events'
        if events.exists() and 'populated 1' in events.read_text():
            raise RuntimeError('Service still has live processes')


class SystemdPublicationControl:
    """Connect Publisher to independent lease and reader service lifetimes."""
    def __init__(self, root, private_state, reader_uid, writer_unit, reader_command,
                 *, reader_environment=None):
        if os.geteuid() != 0:
            raise ValueError('A trusted privileged supervisor is required')
        self.root = Path(root).resolve()
        self.private_state = Path(private_state).resolve()
        self.registry = self.private_state.with_suffix('.supervision.json')
        self.reader_uid = reader_uid
        self.writer_unit = unit_name(writer_unit)
        self.reader_command = list(reader_command)
        self.reader_environment = dict(reader_environment or {})
        self.code = Path(__file__).resolve().parents[1]
        self.token = None

    def quiesce(self, *, timeout):
        if timeout != 5:
            raise ValueError('Unsupported shutdown deadline')
        if self.registry.exists():
            stop_unit(load_state(self.registry)['reader_unit'])

    def stage(self, *, expires_at):
        remaining = expires_at - time.time()
        if not 0 < remaining <= Publisher.maximum_age:
            raise ValueError('Invalid publication lifetime')
        pid = systemctl('show', self.writer_unit, '--property=MainPID', '--value').stdout.strip()
        if pid != str(os.getpid()):
            raise ValueError('Writer must be the dedicated service main process')
        self.token = uuid.uuid4().hex
        prefix = 'public-copy-' + self.token
        state = {'token': self.token, 'writer_pid': os.getpid(),
                 'writer_start': process_start(os.getpid()),
                 'writer_unit': self.writer_unit, 'reader_unit': prefix + '-reader.service',
                 'guard_unit': prefix + '-guard.service', 'expires_at': expires_at,
                 'reader_uid': self.reader_uid, 'root': str(self.root),
                 'private_state': str(self.private_state), 'activated': False, 'complete': False}
        atomic_json(self.registry, state)
        self.registry.chmod(0o600)
        cleanup = [sys.executable, '-m', 'utils.public_supervisor', 'cleanup',
                   str(self.registry), self.token]
        # systemd parses ExecStopPost as an argv string, with its own escaping.
        command = ' '.join('"' + arg.replace('\\', '\\\\').replace('"', '\\"')
                           .replace('%', '%%').replace('$', '$$') + '"' for arg in cleanup)
        subprocess.run(['systemd-run', '--quiet', '--unit=' + state['guard_unit'],
                        '--property=Type=exec', '--property=KillMode=control-group',
                        '--property=KillSignal=SIGKILL', '--property=TimeoutStopSec=1s',
                        '--property=RuntimeMaxSec=' + str(remaining),
                        '--property=ExecStopPost=' + command,
                        '--setenv=PYTHONPATH=' + str(self.code),
                        sys.executable, '-m', 'utils.public_supervisor', 'watch',
                        str(self.registry), self.token],
                       check=True, capture_output=True, timeout=4)

    def activate(self, *, expires_at):
        state = load_state(self.registry)
        if state['token'] != self.token or time.time() >= expires_at:
            raise RuntimeError('Publication lease unavailable')
        command = ['systemd-run', '--quiet', '--unit=' + state['reader_unit'],
                   '--property=Type=exec', '--property=User=' + str(self.reader_uid),
                   '--property=SupplementaryGroups=', '--property=NoNewPrivileges=yes',
                   '--property=KillMode=control-group', '--property=KillSignal=SIGKILL',
                   '--property=TimeoutStopSec=1s',
                   '--property=BindsTo=' + state['guard_unit'],
                   '--property=After=' + state['guard_unit'],
                   '--property=RuntimeMaxSec=' + str(max(.001, expires_at - time.time()))]
        for name, value in self.reader_environment.items():
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name) or '\x00' in value:
                raise ValueError('Invalid reader environment')
            command.append('--setenv=' + name + '=' + value)
        subprocess.run(command + self.reader_command, check=True, capture_output=True, timeout=4)
        state['activated'] = True
        atomic_json(self.registry, state)
        self.registry.chmod(0o600)

    def complete(self):
        state = load_state(self.registry)
        if state['token'] != self.token or time.time() >= state['expires_at']:
            raise RuntimeError('Publication expired before completion')
        state['complete'] = True
        atomic_json(self.registry, state)
        self.registry.chmod(0o600)


def watch(registry, token):
    state = load_state(registry)
    try:
        descriptor = os.pidfd_open(state['writer_pid'])
    except ProcessLookupError:
        if not state['complete']:
            return
        descriptor = None
    try:
        if not state['complete'] and process_start(state['writer_pid']) != state['writer_start']:
            return
        while True:
            state = load_state(registry)
            if state['token'] != token or time.time() >= state['expires_at']:
                return
            if not state['complete'] and (descriptor is None or select.select([descriptor], [], [], 0)[0]):
                return
            if state['activated']:
                result = subprocess.run(['systemctl', 'is-active', '--quiet', state['reader_unit']],
                                        timeout=2)
                if result.returncode != 0:
                    return
            time.sleep(.05)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def cleanup(registry, token):
    state = load_state(registry)
    if state['token'] != token:
        return
    # Stop the writer before taking its publication lock, including hung builds.
    # Each lease records unique unit identities, so old cleanup cannot stop a
    # later writer or reader. Recheck ownership under the lock before retiring.
    stop_unit(state['reader_unit'])
    result = subprocess.run(['systemctl', 'show', state['writer_unit'],
                             '--property=MainPID', '--value'],
                            capture_output=True, text=True, timeout=2)
    pid = result.stdout.strip()
    if pid == str(state['writer_pid']) and process_start(pid) == state['writer_start']:
        stop_unit(state['writer_unit'])
    class StoppedControl:
        def quiesce(self, *, timeout):
            pass
        def stage(self, **kwargs):
            raise RuntimeError('Cleanup cannot publish')
        activate = stage
    publisher = Publisher(None, state['root'], state['private_state'], state['reader_uid'],
                          control=StoppedControl(), policy=None)
    with publisher.private_state.with_suffix('.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if load_state(registry)['token'] == token:
            publisher._withdraw()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['watch', 'cleanup'])
    parser.add_argument('registry')
    parser.add_argument('token')
    args = parser.parse_args()
    if args.operation == 'watch':
        watch(args.registry, args.token)
    else:
        cleanup(args.registry, args.token)


if __name__ == '__main__':
    main()
