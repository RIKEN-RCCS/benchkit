"""Offline checks of scope boundaries, projection weights and failure handling."""
import copy
import csv
import os
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'programs/sbd/estimation/aggregate_davidson.py'
spec = importlib.util.spec_from_file_location('sbd_davidson', SCRIPT)
sbd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sbd)
LABEL = 'sbdiag.h:461 [diag] : Davidson'


class DavidsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'nsys.sqlite'
        self.names = ['void sbd::tpb_for_each_n_kernel<sbd::MultAlphaBeta<double>>(unsigned long, T1)']
        self.names += [f'void sbd::tpb_for_each_n_kernel<sbd::MultUnified<double, (int){a}, (int){b}>>(unsigned long, T1)'
                       for a, b in ((0, 1), (1, 1), (1, 0), (0, 0))]
        with sqlite3.connect(self.db) as c:
            c.executescript('''
CREATE TABLE StringIds(id INTEGER, value TEXT);
CREATE TABLE NVTX_EVENTS(domainId INTEGER,start INTEGER,end INTEGER,globalTid INTEGER,text TEXT,textId INTEGER);
CREATE TABLE CUPTI_ACTIVITY_KIND_RUNTIME(correlationId INTEGER,globalTid INTEGER,start INTEGER,end INTEGER);
CREATE TABLE CUPTI_ACTIVITY_KIND_KERNEL(start INTEGER,end INTEGER,globalPid INTEGER,correlationId INTEGER,demangledName INTEGER,gridX INTEGER,gridY INTEGER,gridZ INTEGER,blockX INTEGER,blockY INTEGER,blockZ INTEGER,deviceId INTEGER);
CREATE TABLE CUPTI_ACTIVITY_KIND_MEMCPY(start INTEGER,end INTEGER,globalPid INTEGER);
CREATE TABLE CUPTI_ACTIVITY_KIND_MEMSET(start INTEGER,end INTEGER,globalPid INTEGER);
''')
            c.executemany('INSERT INTO StringIds VALUES (?,?)', enumerate(self.names))
            c.execute('INSERT INTO NVTX_EVENTS VALUES (0,0,1000,1,?,NULL)', (LABEL,))
            # Two launches per family; unequal weights, no overlap. Total 300 ns.
            for i in range(10):
                f = i // 2
                start = i * 40 + 10
                c.execute('INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES (?,?,?,?,?,10,1,1,64,1,1,0)',
                          (start, start+10*(f+1), 0, i, f))
                c.execute('INSERT INTO CUPTI_ACTIVITY_KIND_RUNTIME VALUES (?,1,?,?)', (i,start-2,start-1))
            # Events after Davidson must not contribute to its weights.
            c.execute('INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES (1100,1300,0,10,0,10,1,1,64,1,1,0)')
            c.execute('INSERT INTO CUPTI_ACTIVITY_KIND_RUNTIME VALUES (10,1,1098,1099)')
            # Overlapping transfer events: union 70, sum 90.
            c.executemany('INSERT INTO CUPTI_ACTIVITY_KIND_MEMCPY VALUES (?,?,0)', [(500,550),(530,570)])
            # Long host synchronization overlaps kernels and is not an additive weight.
            c.execute('INSERT INTO CUPTI_ACTIVITY_KIND_RUNTIME VALUES (999,1,0,1000)')
        # Fix the last two 50ns launches to avoid overlap in the synthetic timeline.
        with sqlite3.connect(self.db) as c:
            c.execute('UPDATE CUPTI_ACTIVITY_KIND_KERNEL SET start=400,end=450 WHERE correlationId=9')
        self.trace = sbd.load_trace(self.db, LABEL)
        self.pred = {'metrics': {'kernels': [dict(name=n, source_time_ns=200,
                     predicted_time_ns=100, sample_count=1,
                     configuration={'grid_size': 10, 'block_size': 64},
                     source_gpu='source', target_gpu='target') for n in self.names]}}
        self.samples = dict(scope=dict(nsys_sha256=self.trace['sha256'], nvtx_range=LABEL,
                                      mpi_size=1, mpi_rank=0), source_gpu='source', target_gpu='target',
                            samples=[dict(family=f, kernel_name=n, grid=[10,1,1], block=[64,1,1],
                                          launch_index=1,prediction_index=i)
                                     for i,(f,n) in enumerate(zip(sbd.FAMILIES,self.names))])

    def run_ratio(self):
        return sbd.aggregate(self.trace, self.pred, self.samples)

    def test_weighted_ratio_and_unchanged_residual(self):
        for i, row in enumerate(self.pred['metrics']['kernels']):
            row['predicted_time_ns'] = 200*(i+1)
        result = self.run_ratio()
        self.assertEqual(result['selected_kernel_time_ns'], 300)
        self.assertEqual(result['residual_unchanged_ns'], 700)
        self.assertEqual(result['predicted_wall_time_ns'], 700+20+80+180+320+500)
        self.assertEqual(result['time_ratio_predicted_over_source'], 1.8)
        self.assertEqual(result['host_wait_added_ns'], 0)
        self.assertEqual(result['residual_components_ns'], dict(
            unselected_kernels=0, memory_event_union=70, gpu_event_gaps=630))
        self.assertEqual([t['nsys_launch_count'] for t in result['terms']], [2]*5)

    def test_identity_halving_zero_and_reversed_prediction_order(self):
        for value, expected in ((200,1), (100,.85), (0,.7)):
            for row in self.pred['metrics']['kernels']:
                row['predicted_time_ns'] = value
            self.assertAlmostEqual(self.run_ratio()['time_ratio_predicted_over_source'], expected)
        self.pred['metrics']['kernels'].reverse()
        for p in self.samples['samples']:
            p['prediction_index'] = 4-p['prediction_index']
        self.assertAlmostEqual(self.run_ratio()['time_ratio_predicted_over_source'], .7)

    def test_reject_missing_or_duplicate_samples(self):
        original = copy.deepcopy(self.samples)
        self.samples['samples'].pop()
        with self.assertRaises(ValueError): self.run_ratio()
        self.samples = original
        self.samples['samples'][1]['prediction_index'] = 0
        with self.assertRaises(ValueError): self.run_ratio()

    def test_scope_and_rank_must_match(self):
        for field, value in (('nsys_sha256','wrong'), ('nvtx_range','post mult'),
                             ('mpi_size',2), ('mpi_rank',1)):
            with self.subTest(field=field):
                original = self.samples['scope'][field]
                self.samples['scope'][field] = value
                with self.assertRaises(ValueError): self.run_ratio()
                self.samples['scope'][field] = original

    def test_invalid_predictions_fail(self):
        row = self.pred['metrics']['kernels'][0]
        for field, value in (('source_time_ns',0), ('predicted_time_ns',-1),
                             ('predicted_time_ns',float('nan')), ('sample_count',2),
                             ('source_gpu','other'), ('target_gpu','other'),
                             ('time_ratio_predicted_over_source',7),
                             ('configuration',{'grid_size': 11,'block_size':64})):
            with self.subTest(field=field, value=value):
                old = copy.deepcopy(row)
                row[field] = value
                with self.assertRaises(ValueError): self.run_ratio()
                row.clear(); row.update(old)

    def test_signature_and_namespace_match_is_narrow(self):
        row = self.pred['metrics']['kernels'][0]
        original = row['name']
        row['name'] = original.replace('sbd::','')
        self.run_ratio()
        for name in (original.replace('double','float'), original.replace('T1','T2'),
                     original.replace('sbd::','other::sbd::')):
            row['name'] = name
            with self.assertRaises(ValueError): self.run_ratio()

    def test_warmup_and_sample_configuration(self):
        p = self.samples['samples'][0]
        for field, value in (('launch_index',0), ('launch_index',22),
                             ('grid',[11,1,1]), ('block',[32,1,1]), ('kernel_name','different')):
            old = copy.deepcopy(p)
            p[field] = value
            with self.assertRaises(ValueError): self.run_ratio()
            p.clear(); p.update(old)

    def change_sql(self, sql):
        with sqlite3.connect(self.db) as c: c.execute(sql)

    def test_reject_multiple_configurations(self):
        self.change_sql('UPDATE CUPTI_ACTIVITY_KIND_KERNEL SET gridX=11 WHERE correlationId=0')
        self.trace = sbd.load_trace(self.db,LABEL)
        self.samples['scope']['nsys_sha256'] = self.trace['sha256']
        with self.assertRaises(ValueError): self.run_ratio()

    def test_missing_family_and_multiple_devices_fail(self):
        old = self.trace['kernels']
        self.trace['kernels'] = [k for k in old if sbd.family(k['name']) != sbd.FAMILIES[0]]
        with self.assertRaises(ValueError): self.run_ratio()
        self.trace['kernels'] = old
        self.change_sql('UPDATE CUPTI_ACTIVITY_KIND_KERNEL SET deviceId=1 WHERE correlationId=0')
        with self.assertRaises(ValueError): sbd.load_trace(self.db,LABEL)

    def test_overlaps_and_cross_boundary_fail(self):
        for sql in (
            'UPDATE CUPTI_ACTIVITY_KIND_KERNEL SET end=55 WHERE correlationId=0',
            'INSERT INTO CUPTI_ACTIVITY_KIND_MEMCPY VALUES (10,15,0)',
            'UPDATE CUPTI_ACTIVITY_KIND_KERNEL SET end=1001 WHERE correlationId=9',
            'UPDATE CUPTI_ACTIVITY_KIND_KERNEL SET start=999 WHERE correlationId=10',
        ):
            with self.subTest(sql=sql):
                before = self.db.read_bytes()
                self.change_sql(sql)
                with self.assertRaises(ValueError): sbd.load_trace(self.db,LABEL)
                self.db.write_bytes(before)

    def test_ambiguous_range_or_origin_fail(self):
        for sql in ('INSERT INTO NVTX_EVENTS SELECT * FROM NVTX_EVENTS',
                    'INSERT INTO CUPTI_ACTIVITY_KIND_RUNTIME SELECT * FROM CUPTI_ACTIVITY_KIND_RUNTIME WHERE correlationId=0'):
            before = self.db.read_bytes()
            self.change_sql(sql)
            with self.assertRaises(ValueError): sbd.load_trace(self.db,LABEL)
            self.db.write_bytes(before)

    def test_common_lightgbm_parser_output(self):
        path = Path(self.tmp.name)/'pred.csv'
        columns = ['meta-kernel','meta-src_gpu','meta-tgt_gpu','O-Execution Time',
                   'benchkit-source-time-ns','benchkit-grid-size','benchkit-block-size',
                   'benchkit-sample-count']
        with path.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for name in self.names:
                writer.writerow([name,'source','target',100,200,10,64,1])
        run = subprocess.run(['bash','-c',
            'source "$1"; _bk_gpu_lightgbm_parse_prediction_csv "$2" "" gpu_kernel_lightgbm_v11 1.1',
            'bash',str(ROOT/'scripts/estimation/section_packages/gpu_kernel_lightgbm_v10.sh'),
            str(path)], capture_output=True,text=True,check=True,
            env=dict(os.environ, BK_GPU_LIGHTGBM_PYTHON=sys.executable))
        self.pred = json.loads(run.stdout)
        self.assertEqual(self.run_ratio()['time_ratio_predicted_over_source'],.85)

    def test_cli_and_read_only_inputs(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        pred = Path(self.tmp.name)/'prediction.json'; pred.write_text(json.dumps(self.pred))
        samples = Path(self.tmp.name)/'samples.json'; samples.write_text(json.dumps(self.samples))
        cmd = [sys.executable,str(SCRIPT),'--nsys-sqlite',str(self.db),'--nvtx-range',LABEL,
               '--predictions',str(pred),'--samples',str(samples)]
        run = subprocess.run(cmd, capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(run.stdout)['time_ratio_predicted_over_source'],.85)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)
        cmd[cmd.index('--nvtx-range')+1] = 'sbdiag.h:515 [diag] : device_mult.run'
        run = subprocess.run(cmd, capture_output=True,text=True)
        self.assertEqual(run.returncode,2)
        self.assertEqual(run.stdout,'')


if __name__ == '__main__':
    unittest.main()
