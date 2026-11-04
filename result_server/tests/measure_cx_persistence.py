#!/usr/bin/env python3
"""Generated-data-only persistence rehearsal. No services, network or input DBs."""

import argparse
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.cx_persistence import CxPersistence
from utils.cx_migration import import_snapshot, recover_copy
from utils.cx_identity import EncryptedUserStore
from utils.encrypted_sqlite import generate_key
from utils.execution_profiles import ExecutionProfileStore
from utils.node_hours import aggregate_node_hours
from utils.cx_upload import EncryptedUpload


class GeneratedBytes:
    def __init__(self, size):
        self.remaining = size

    def read(self, size):
        size = min(size, self.remaining)
        self.remaining -= size
        return b'x' * size


def rehearse(records, artifact_bytes):
    os.umask(0o077)
    tracemalloc.start()
    timings = {}
    digest = hashlib.sha256()
    code = Path(__file__).resolve().parents[1]
    for path in sorted(code.rglob('*.py')):
        if 'tests' in path.relative_to(code).parts:
            continue
        digest.update(path.relative_to(code).as_posix().encode() + b'\x00' + path.read_bytes())
    with tempfile.TemporaryDirectory(prefix='bk-cx-persistence-fixture-') as temporary:
        root = Path(temporary)
        for name in ('snapshot', 'database', 'keys', 'recovered'):
            (root / name).mkdir(mode=0o700)
        roots = {}
        for role in ('results', 'estimates', 'artifacts', 'inputs'):
            path = root / 'snapshot' / role
            path.mkdir(mode=0o700)
            roots[role] = str(path)
        profile = root / 'snapshot' / 'profile.db'
        ExecutionProfileStore(str(profile)).migrate()
        expected = {}
        for number in range(records):
            name = f'result_20261104_010203_{number:08x}-0000-0000-0000-000000000001.json'
            raw = json.dumps(dict(code=f'synthetic-{number % 3}', system=f'System-{number % 5}',
                Exp=f'case-{number % 7}', FOM=1.23456789012345, node_count=2,
                pipeline_timing=dict(run_time=60), confidential=['team'] if number % 4 == 0 else [],
                unknown_extension=dict(preserve=True))).encode()
            (Path(roots['results']) / name).write_bytes(raw)
            expected[name] = raw
        key = root / 'keys' / 'key'
        generate_key(key)
        store = CxPersistence(root / 'database' / 'cx.db', key, roots=roots)
        started = time.perf_counter()
        migration = import_snapshot(store, profile_copy=profile, source_roots=roots)
        timings['migration_and_check_seconds'] = time.perf_counter() - started
        started = time.perf_counter()
        with EncryptedUpload(store.path.parent, artifact_bytes) as spool:
            content = GeneratedBytes(artifact_bytes)
            while True:
                chunk = content.read(64 * 1024)
                if not chunk:
                    break
                spool.write(chunk)
            timings['encrypted_upload_spool_seconds'] = time.perf_counter() - started
            spool.seek(0)
            started = time.perf_counter()
            store.put('artifacts', 'synthetic.tgz', spool, limit=artifact_bytes)
            timings['artifact_write_seconds'] = time.perf_counter() - started
        started = time.perf_counter()
        candidates = store.candidates()
        timings['public_candidates_seconds'] = time.perf_counter() - started
        started = time.perf_counter()
        with store.snapshot() as reader:
            usage = aggregate_node_hours(store.directory, 2026, 'monthly', record_source=reader)
        timings['usage_seconds'] = time.perf_counter() - started
        name = 'estimate_20261104_020304_ffffffff-0000-0000-0000-000000000001.json'
        store.put_document('estimates', name, b'{"new_write":"preserved"}')
        EncryptedUserStore(store).create_user('synthetic@example.invalid', 'synthetic-secret', ['team'])
        started = time.perf_counter()
        restored = recover_copy(store, root / 'recovered' / 'cx.db')
        timings['encrypted_backup_and_check_seconds'] = time.perf_counter() - started
        for filename, raw in expected.items():
            assert restored.read('results', filename) == raw
        assert restored.read('estimates', name) == b'{"new_write":"preserved"}'
        assert EncryptedUserStore(restored).get_affiliations('synthetic@example.invalid') == ['team']
        read_bytes = sum(len(chunk) for chunk in restored.chunks('artifacts', 'synthetic.tgz'))
        assert read_bytes == artifact_bytes
        database_bytes = sum(path.stat().st_size for path in store.path.parent.iterdir() if path.is_file())
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        return dict(status='success', layout='metadata+immutable_artifacts', runtime_python_sha256=digest.hexdigest(), generated_records=records, artifact_bytes=artifact_bytes,
            database_and_sidecar_bytes=database_bytes, python_peak_traced_bytes=peak,
            public_count=candidates['total'], usage_has_apps=bool(usage['apps']),
            post_migration_writes_restored=True, cross_store_atomic=False,
            migration=migration, timings={name: round(value, 6) for name, value in timings.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=1000)
    parser.add_argument('--artifact-mib', type=int, default=32)
    parser.add_argument('--output')
    args = parser.parse_args()
    if not 1 <= args.records <= 10000 or not 1 <= args.artifact_mib <= 512:
        parser.error('Generated fixture limits exceeded')
    result = rehearse(args.records, args.artifact_mib * 1024 * 1024)
    raw = json.dumps(result, sort_keys=True, indent=2) + '\n'
    if args.output:
        path = Path(args.output).absolute()
        if path.parent.resolve() != path.parent or path.parent.stat().st_mode & 0o077:
            raise ValueError('Private output directory required')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(raw)
    print(raw, end='')


if __name__ == '__main__':
    main()
