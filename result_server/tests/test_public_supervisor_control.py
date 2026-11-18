"""Regression checks for stale supervisor callbacks and reused process IDs."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from utils import public_supervisor


@pytest.mark.parametrize('main_pid', ['101', '102'])
def test_old_cleanup_cannot_kill_a_reused_writer_service(tmp_path, monkeypatch, main_pid):
    registry = tmp_path/'supervision.json'
    state = {'token':'old', 'writer_pid':101, 'writer_start':'original-start',
             'writer_unit':'sample-writer.service', 'reader_unit':'old-reader.service',
             'root':str(tmp_path/'public'), 'private_state':str(tmp_path/'publisher.json'),
             'reader_uid':123}
    registry.write_text(json.dumps(state))
    stopped = []
    def stop(unit):
        stopped.append(unit)
        # A new writer takes over before the old cleanup acquires its lock.
        registry.write_text(json.dumps(dict(state, token='new')))
    monkeypatch.setattr(public_supervisor, 'stop_unit', stop)
    monkeypatch.setattr(public_supervisor.subprocess, 'run',
                        lambda *args, **kwargs: SimpleNamespace(stdout=main_pid))
    monkeypatch.setattr(public_supervisor, 'process_start', lambda pid:'new-start')
    class Publisher:
        def __init__(self, *args, **kwargs):
            self.private_state = Path(state['private_state'])
        def _withdraw(self):
            pytest.fail('Old cleanup must not withdraw the new generation')
    monkeypatch.setattr(public_supervisor, 'Publisher', Publisher)
    public_supervisor.cleanup(registry, 'old')
    assert stopped == ['old-reader.service']


def test_watcher_rejects_reused_pid_before_polling(tmp_path, monkeypatch):
    registry = tmp_path/'supervision.json'
    registry.write_text(json.dumps({'writer_pid':101, 'writer_start':'old', 'complete':False}))
    monkeypatch.setattr(public_supervisor.os, 'pidfd_open', lambda pid:os.open('/dev/null', os.O_RDONLY))
    monkeypatch.setattr(public_supervisor, 'process_start', lambda pid:'new')
    monkeypatch.setattr(public_supervisor.select, 'select',
                        lambda *args:pytest.fail('A reused process ID must not be watched'))
    public_supervisor.watch(registry, 'old')
