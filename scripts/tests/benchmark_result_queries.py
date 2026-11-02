#!/usr/bin/env python3
"""Measure JSON/index parity on generated, disposable data, never live storage."""

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch
import builtins
import os

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'result_server'))
from flask import Flask
from utils.result_catalog import ResultCatalog
from utils.results_loader import load_results_table
from utils.node_hours import aggregate_node_hours
from utils.performance_telemetry import build_performance_telemetry
from utils.evidence_snapshot import build_evidence_snapshot
from utils.profile_usage_overview import build_profile_usage_overview
from utils.execution_profiles import ExecutionProfileStore, normalize_profile


def measure(callback, roots):
    counters = dict(json_reads=0, directory_scans=0)
    original_open, original_listdir = builtins.open, os.listdir
    def read(path, *args, **kwargs):
        if isinstance(path, (str, Path)) and str(path).endswith('.json') and Path(path).parent in roots:
            counters['json_reads'] += 1
        return original_open(path, *args, **kwargs)
    def scan(path, *args, **kwargs):
        if Path(path) in roots:
            counters['directory_scans'] += 1
        return original_listdir(path, *args, **kwargs)
    tracemalloc.start()
    start = time.perf_counter()
    with patch('builtins.open', read), patch('os.listdir', scan):
        result = callback()
    elapsed = time.perf_counter()-start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, dict(seconds=round(elapsed,6),python_peak_bytes=peak,**counters)


def benchmark(count):
    with tempfile.TemporaryDirectory(prefix='result-query-fixture-') as temporary:
        root = Path(temporary)
        roots = [root/name for name in ('results','estimates','archives','index')]
        for directory in roots:
            directory.mkdir(mode=0o700)
        results, estimates, archives, index = roots
        start = datetime(2026,4,1)
        for number in range(count):
            timestamp = (start+timedelta(seconds=number)).strftime('%Y%m%d_%H%M%S')
            identifier = f'{number:08x}-bbbb-cccc-dddd-eeeeeeeeeeee'
            payload = dict(code='genesis',system=f'System{number%100:03}',Exp='CASE0',FOM=1,
                           node_count='1',execution_mode='native',pipeline_timing={'build_time':30,'run_time':120},
                           unindexed_padding='x'*512)
            (results/f'result_{timestamp}_{identifier}.json').write_text(json.dumps(payload))
        catalog = ResultCatalog(index/'catalog.sqlite3',results,estimated_directory=estimates,artifact_directory=archives)
        catalog.initialize()
        print(f'{count}: rebuilding synthetic index',file=sys.stderr,flush=True)
        before = time.perf_counter()
        catalog.rebuild()
        rebuild_seconds = time.perf_counter()-before
        db = str(root/'profiles.sqlite3')
        store = ExecutionProfileStore(db)
        profile, errors = normalize_profile(dict(id='genesis',code='genesis',system='System007',enabled=True,status='approved'))
        assert not errors
        store.upsert_profile(profile,actor='fixture@example.invalid')
        app = Flask(__name__)
        app.add_url_rule('/detail/<filename>',endpoint='results.result_detail',view_func=lambda filename:'')
        app.add_url_rule('/json/<filename>',endpoint='results.show_result',view_func=lambda filename:'')
        selection = dict(code='genesis',system='System007',since=date(2026,4,1),until=date(2027,4,1))
        comparisons = {}
        with app.test_request_context(), catalog.snapshot() as reader:
            cases = [
                ('list',lambda source: load_results_table(str(results),filter_system='System007',per_page=50,
                    padata_directory=str(archives),**({'query_reader':source} if source else {}))),
                ('node_hours',lambda source: aggregate_node_hours(str(results),2026,'monthly',selection=selection,record_source=source)),
                ('profiles',lambda source: build_profile_usage_overview(str(results),db,selection=selection,record_source=source)),
                ('performance',lambda source: build_performance_telemetry(str(results),str(estimates),selection=selection,record_source=source)),
                ('evidence',lambda source: build_evidence_snapshot(str(results),str(estimates),selection=selection,
                    record_source=source,app_support_rows=[],generated_at='2026-11-02T00:00:00Z')),
            ]
            for name, function in cases:
                old, old_measurement = measure(lambda:function(None), roots[:3])
                new, new_measurement = measure(lambda:function(reader), roots[:3])
                if old != new:
                    raise AssertionError(f'{name}: indexed output differs')
                comparisons[name] = dict(json=old_measurement,index=new_measurement,parity=True)
                print(f'{count}: {name} parity confirmed',file=sys.stderr,flush=True)
                if name == 'list':
                    assert new_measurement['json_reads'] <= 100
                else:
                    assert new_measurement['json_reads'] == 0
                assert new_measurement['directory_scans'] == 0
            plans = [row[3] for row in reader.conn.execute('''EXPLAIN QUERY PLAN SELECT filename FROM query_records
                WHERE directory=? AND selected_system=? AND timestamp>=? AND timestamp<?''',
                (str(results),'System007','2026-04-01','2027-04-01'))]
        return dict(records=count,rebuild_seconds=round(rebuild_seconds,6),index_bytes=catalog.path.stat().st_size,
                    target_fraction='1/100',page_size=50,query_plan=plans,cases=comparisons)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes',nargs='+',type=int,default=[10000,100000])
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if any(size<100 or size>100000 for size in args.sizes):
        parser.error('Synthetic sizes must be between 100 and 100000')
    report=dict(synthetic=True,source_io='generated local files; temporary directories removed',
                measurements=[benchmark(size) for size in args.sizes])
    text=json.dumps(report,indent=2)
    if args.output:
        with args.output.open('x') as handle:
            handle.write(text+'\n')
    print(text)


if __name__=='__main__':
    main()
