"""Offline receipt lookup comparison over temporary synthetic stores only."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.cx_persistence import CxPersistence
from utils.encrypted_sqlite import generate_key
from utils.execution_history import execution_result_links
from utils.result_catalog import ResultCatalog
from utils.result_query_reader import ResultQueryReader
from utils import trigger_display


def measure(count, backend, repeats):
    with tempfile.TemporaryDirectory(prefix='execution-index-synthetic-') as directory:
        root = Path(directory)
        roots = {}
        for role in ('results', 'estimates', 'artifacts', 'inputs', 'private', 'keys'):
            path = root / role
            path.mkdir(mode=0o700)
            roots[role] = str(path)
        app = Flask(__name__)
        if backend == 'encrypted':
            key = root / 'keys/key'
            generate_key(key)
            store = CxPersistence(root / 'private/db', key,
                                  roots={name: roots[name] for name in ('results', 'estimates', 'artifacts', 'inputs')})
            app.extensions['cx_persistence'] = store
        else:
            store = ResultCatalog(root / 'private/db', roots['results'])
        app.config['RESULT_CATALOG_PATH'] = str(store.path)
        started = time.perf_counter()
        with app.app_context():
            store.initialize()
            with (store.transaction() if backend == 'encrypted' else store.writer(complete=True)) as conn:
                for number in range(count):
                    name = f'result_20260101_000000_{number:08d}.json'
                    payload = {'pipeline_id': number + 1, 'ci_project': 'gitlab.example.org/group/benchmark',
                               'Exp': 'synthetic-case', 'code': 'example', 'system': 'ExampleSystem',
                               'FOM': 1.5, 'source_info': {'fixture': 'x' * 1024}}
                    raw = json.dumps(payload).encode()
                    if backend == 'encrypted':
                        store.put_document('results', name, raw, update_metadata=False, conn=conn)
                    else:
                        (Path(store.directory) / name).write_bytes(raw)
                        store._put(conn, name, payload)
                conn.execute('UPDATE execution_lookup_state SET ready=1 WHERE id=1')
            build_seconds = time.perf_counter() - started
            runs = [{'id': 1, 'status': 'submitted', 'dry_run': False,
                     'payload_json': {'gitlab_project': 'gitlab.example.org/group/benchmark',
                                      'submit': {'response': {'id': count}}}}]
            reports, results = {}, {}
            read = trigger_display._load_result_json
            candidates = ResultQueryReader.execution_candidates
            try:
                for mode in ('scan', 'index'):
                    samples, reads = [], []
                    ResultQueryReader.execution_candidates = candidates if mode == 'index' else lambda *_: None
                    for _ in range(repeats):
                        loaded = []
                        def loading(name, directory):
                            loaded.append(name)
                            return read(name, directory)
                        trigger_display._load_result_json = loading
                        began = time.perf_counter()
                        results[mode] = execution_result_links(store.directory, runs)
                        samples.append(time.perf_counter() - began)
                        reads.append(len(loaded))
                    reports[mode] = {'median_seconds': statistics.median(samples), 'document_reads': reads}
            finally:
                ResultQueryReader.execution_candidates = candidates
                trigger_display._load_result_json = read
            assert results['scan'] == results['index'] and len(results['index'][1]) == 1
            assert reports['scan']['document_reads'] == [count] * repeats
            assert reports['index']['document_reads'] == [1] * repeats
            return dict(backend=backend, results=count, build_seconds=build_seconds, output_equal=True, **reports)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counts', type=int, nargs='+', default=[1000, 10000])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.repeats < 1 or any(count < 1 for count in args.counts):
        parser.error('Counts and repeats must be positive')
    if Path(args.output).exists():
        parser.error('Output must be a new file')
    report = []
    for backend in ('files', 'encrypted'):
        for count in args.counts:
            item = measure(count, backend, args.repeats)
            report.append(item)
            print(json.dumps(item), flush=True)
    with Path(args.output).open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
