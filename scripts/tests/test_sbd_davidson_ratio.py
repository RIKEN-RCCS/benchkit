"""Offline checks of scope boundaries, projection weights and failure handling."""
import copy
import csv
import io
import tarfile
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

    def test_nsys_ncu_spelling_in_both_directions(self):
        for row in self.pred['metrics']['kernels']:
            row['name'] = row['name'].replace('sbd::', '').replace('(int)', '')
        self.assertEqual(self.run_ratio()['time_ratio_predicted_over_source'], .85)
        # Reverse which input supplies the cast and namespace spelling.
        for k in self.trace['kernels']:
            k['name'] = k['name'].replace('sbd::', '').replace('(int)', '')
        for sample in self.samples['samples']:
            sample['kernel_name'] = sample['kernel_name'].replace('sbd::', '').replace('(int)', '')
        for row, name in zip(self.pred['metrics']['kernels'], self.names):
            row['name'] = name
        self.assertEqual(self.run_ratio()['time_ratio_predicted_over_source'], .85)

    def test_spelling_does_not_hide_other_kernel_differences(self):
        row = self.pred['metrics']['kernels'][1]
        original = row['name']
        for name in (
            self.names[2],  # Different boolean template argument.
            original.replace('double', 'float'),
            original.replace('(int)0', '(unsigned)0'),
            original.replace('(int)0', '(int)2'),
            original.replace('T1', 'T2'),
            original.replace('T1', '(int)T1'),
            original.replace('unsigned long, T1', 'T1, unsigned long'),
            original.replace('sbd::', 'other::'),
            original.replace('tpb_for_each_n_kernel', 'other_kernel'),
        ):
            with self.subTest(name=name):
                row['name'] = name
                with self.assertRaisesRegex(ValueError, 'signature mismatch'):
                    self.run_ratio()
        row['name'] = original

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

    def test_range_lookup_text_ids_and_ignored_events(self):
        # NSYS can store a label indirectly; other domains and open ranges
        # must not create a second match for this closed default-domain range.
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO StringIds VALUES (100,?)', (LABEL,))
            c.execute('UPDATE NVTX_EVENTS SET text=NULL,textId=100')
            c.execute('INSERT INTO NVTX_EVENTS VALUES (1,0,1000,1,?,NULL)', (LABEL,))
            c.execute('INSERT INTO NVTX_EVENTS VALUES (0,0,NULL,1,?,NULL)', (LABEL,))
            c.execute('INSERT INTO NVTX_EVENTS VALUES (0,0,1000,1,?,100)', ('other',))
        self.trace = sbd.load_trace(self.db, LABEL)
        self.samples['scope']['nsys_sha256'] = self.trace['sha256']
        self.assertEqual(self.run_ratio()['time_ratio_predicted_over_source'], .85)

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

    def test_local_plan_selection_is_unique_and_explicit_override_is_preserved(self):
        folder = Path(self.tmp.name)
        (folder/'scripts').symlink_to(ROOT/'scripts', target_is_directory=True)
        (folder/'programs').symlink_to(ROOT/'programs', target_is_directory=True)
        (folder/'results').mkdir()
        result = folder/'result.json'
        result.write_text(json.dumps(dict(code='sbd', Exp='test', system='source',
            FOM=1, FOM_unit='s', FOM_version='davidson_internal_s', node_count=1, numproc_node=1)))
        env = {k:v for k,v in os.environ.items() if not k.startswith(('BK_SBD_', 'BK_GPU_LIGHTGBM_'))}
        def run(extra=None):
            return subprocess.run(['bash', 'programs/sbd/estimate.sh', str(result)],
                cwd=folder, env=dict(env, **(extra or {})), text=True, capture_output=True)
        self.assertIn('exactly one local Davidson plan', run().stderr)
        for name in ('first', 'second'):
            directory = folder/'results'/name
            directory.mkdir(); (directory/'davidson-plan.json').write_text('{}')
        self.assertIn('exactly one local Davidson plan', run().stderr)
        selected = run(dict(BK_SBD_DAVIDSON_PLAN=str(folder/'results/first/davidson-plan.json')))
        self.assertNotEqual(selected.returncode, 0)
        self.assertIn('Set the observed source GPU', selected.stderr)
        (folder/'results/second/davidson-plan.json').unlink()
        self.assertIn('Set the observed source GPU', run().stderr)
        self.assertFalse(list((folder/'results').glob('estimate*.json')))

    def estimate_fixture(self):
        # Exercise real input preparation/aggregation/writing; mock inference only.
        import shutil
        plan, profiles, _ = self.bundle_fixture()
        work = Path(self.tmp.name)/'work'
        shutil.copytree(ROOT/'scripts', work/'scripts')
        shutil.copytree(ROOT/'programs/sbd', work/'programs/sbd')
        (work/'results').mkdir()
        (work/'bin').mkdir()
        (work/'bin/python3').symlink_to(sys.executable)
        result = work/'results/result0.json'
        result.write_text(json.dumps(dict(code='sbd', Exp='test', system='source',
            FOM='2.0', FOM_unit='s', FOM_version='davidson_internal_s',
            node_count='1', numproc_node='1', _server_uuid='11111111-1111-4111-8111-111111111111',
            _server_timestamp='2026-01-01 00:00:00')))
        components = work/'components'
        components.mkdir()
        manifest = components/'provenance.json'
        manifest.write_text('{}')
        for i, row in enumerate(self.pred['metrics']['kernels']):
            component = dict(package_applicability=dict(status='applicable'),
                model=dict(version='1.1', provenance=dict(external_commit='a'*40,
                    manifest=str(manifest), sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())),
                metrics=dict(kernels=[row]))
            (components/f'davidson_kernel_{i}.json').write_text(json.dumps(component))
        adapter = work/'scripts/estimation/section_packages/gpu_kernel_lightgbm_v11.sh'
        with adapter.open('a') as handle:
            handle.write("""
bk_section_package_transform_gpu_kernel_lightgbm_v11() {
  cat "$FAKE_COMPONENTS/$(jq -r .name <<< "$1").json"
}
""")
        env = {k:v for k,v in os.environ.items()
               if not k.startswith(('BK_SBD_', 'BK_GPU_', 'BK_ESTIMATION_', 'RESULT_SERVER'))}
        env.update(BK_SBD_DAVIDSON_PLAN=str(plan), BK_SBD_DAVIDSON_PROFILES_DIR=str(profiles),
            BK_GPU_LIGHTGBM_SOURCE_GPU='source', BK_GPU_LIGHTGBM_TARGET_GPU='target',
            BK_ESTIMATION_FUTURE_SYSTEM='target-system', BK_ESTIMATION_PYTHON=sys.executable,
            FAKE_COMPONENTS=str(components), PATH=str(work/'bin')+os.pathsep+os.environ['PATH'])
        return work, result, env

    def test_normal_estimate_writer_and_ratio_direction(self):
        work, _, env = self.estimate_fixture()
        subprocess.run(['bash', 'scripts/estimation/run.sh', 'sbd'], cwd=work,
            env=env, capture_output=True, text=True, check=True)
        outputs = list((work/'results').glob('estimate*.json'))
        self.assertEqual([p.name for p in outputs], ['estimate_sbd_result0.json'])
        data = json.loads(outputs[0].read_text())
        self.assertEqual(data['current_system']['fom'], 2)
        self.assertEqual(data['future_system']['fom'], 1.7)
        self.assertEqual(data['performance_ratio'], 1.176)
        self.assertEqual(data['future_system']['model']['projection']['host_wait_added_ns'], 0)
        self.assertEqual(data['estimate_metadata']['source_result_uuid'], '11111111-1111-4111-8111-111111111111')
        self.assertEqual(data['current_system']['benchmark']['uuid'], '11111111-1111-4111-8111-111111111111')
        self.assertEqual(data['estimate_metadata']['app_estimation_method']['version'], '1')
        self.assertEqual(len(data['input_artifacts']), 4)
        self.assertEqual(data['estimate_metadata']['estimation_package'], 'gpu_kernel_lightgbm_v11')
        self.assertEqual(data['estimate_metadata']['estimation_package_version'], '1.1')
        self.assertEqual(data['estimation_timing']['recorded_by'], 'scripts/estimation/run.sh')

    def test_delivery_flag_does_not_change_explicit_estimation_conditions(self):
        work, result, env = self.estimate_fixture()
        outputs = []
        for flag in ('false', 'true', '1'):
            subprocess.run(['bash', 'programs/sbd/estimate.sh', str(result)], cwd=work,
                env=dict(env, BK_SBD_RIKYU_ARTIFACT_ONLY=flag),
                capture_output=True, text=True, check=True)
            data = json.loads((work/'results/estimate_sbd_result0.json').read_text())
            outputs.append({key: data[key] for key in
                ('current_system', 'future_system', 'input_artifacts', 'estimate_metadata')})
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_delivery_flag_does_not_supply_missing_conditions(self):
        work, result, env = self.estimate_fixture()
        for variable in ('BK_GPU_LIGHTGBM_SOURCE_GPU', 'BK_GPU_LIGHTGBM_TARGET_GPU',
                         'BK_ESTIMATION_FUTURE_SYSTEM'):
            missing = dict(env, BK_SBD_RIKYU_ARTIFACT_ONLY='true')
            del missing[variable]
            run = subprocess.run(['bash', 'programs/sbd/estimate.sh', str(result)],
                cwd=work, env=missing, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn(variable, run.stderr)
            self.assertFalse(list((work/'results').glob('estimate*.json')))

    def test_estimate_invalid_inputs_emit_no_json(self):
        work, result, env = self.estimate_fixture()
        original = result.read_bytes()
        for changes in (dict(code='other'), dict(FOM='NaN'), dict(FOM_unit='ns'),
                        dict(FOM_version='other'), dict(numproc_node='2')):
            r = json.loads(original); r.update(changes)
            result.write_text(json.dumps(r))
            run = subprocess.run(['bash', 'programs/sbd/estimate.sh', str(result)], cwd=work,
                env=env, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(run.stdout, '')
            self.assertFalse(list((work/'results').glob('estimate*.json')))

    def test_estimate_requires_exactly_one_result_argument(self):
        work, result, env = self.estimate_fixture()
        for arguments in ([], [str(result), 'extra'],
                          [str(result), str(self.db), 'pred.json', 'samples.json', 'target']):
            run = subprocess.run(['bash', 'programs/sbd/estimate.sh', *arguments], cwd=work,
                env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn('Usage: estimate.sh RESULT', run.stderr)
            self.assertEqual(run.stdout, '')
            self.assertFalse(list((work/'results').glob('estimate*.json')))

    def bundle_fixture(self):
        directory = Path(self.tmp.name)
        self.db.rename(directory / 'discovery.sqlite')
        self.db = directory / 'discovery.sqlite'
        plan = dict(profiles=[dict(name=f'kernel_{i}', kernel_name=n,
            nvtx=dict(range=LABEL, domain='default', style='PushPop'),
            kernel_match=dict(pattern=f'pattern_{i}'), launch_skip=1, launch_count=1)
            for i, n in enumerate(self.names)])
        path = directory / 'plan.json'
        path.write_text(json.dumps(plan))
        for profile in plan['profiles']:
            folder = directory / 'profiles' / profile['name']; folder.mkdir(parents=True)
            meta = dict(profile_name=profile['name'], nsys_discovery_json=json.dumps(profile),
                ncu=dict(kernel_regex=profile['kernel_match']['pattern'], launch_skip=1, launch_count=1))
            (folder/'profile.metadata.json').write_text(json.dumps(meta))
            data = io.StringIO(); writer = csv.writer(data)
            writer.writerow(['ID','Kernel Name'] + ['launch__'+d+'_dim_'+a
                                                    for d in ('grid','block') for a in 'xyz'])
            writer.writerow([0, profile['kernel_name'],10,1,1,64,1,1])
            content = data.getvalue().encode()
            with tarfile.open(folder/'profile.tgz', 'w:gz') as archive:
                member = tarfile.TarInfo('raw/rep1/profile_raw.csv'); member.size=len(content)
                archive.addfile(member, io.BytesIO(content))
        return path, directory/'profiles', directory/'prepared'

    def test_normal_profile_entry_prepares_five_scoped_launches(self):
        plan_path, _, _ = self.bundle_fixture()
        directory = plan_path.parent
        associations = [dict(range=':'+LABEL, style='PushPop', process_id='0',
            thread_id='1', kernel_name=n) for n in self.names]
        (directory/'discovery.json').write_text(json.dumps(dict(nvtx=dict(associations=associations))))
        for filename, header, rows in (
            ('kernel-summary.csv', ['Name','Total Time (ns)','Instances'],
             [[n,100,2] for n in self.names]),
            ('nvtx-summary.csv', ['NVTX Range','Style','PID','TID','Kernel Name','Kern Inst','Total Time (ns)'],
             [[':'+LABEL,'PushPop',0,1,n,2,100] for n in self.names])):
            with (directory/filename).open('w',newline='') as f:
                writer=csv.writer(f); writer.writerow(header); writer.writerows(rows)
        generated=json.loads(Path(sbd.davidson_plan(directory)).read_text())
        for profile in generated['profiles']:
            meta=directory/'profiles'/f"kernel_{self.names.index(profile['kernel_name'])}"/'profile.metadata.json'
            data=json.loads(meta.read_text())
            data.update(profile_name=profile['name'], nsys_discovery_json=json.dumps(profile))
            data['ncu']['kernel_regex']=profile['kernel_match']['pattern']
            meta.write_text(json.dumps(data))
        calls=directory/'calls.log'
        command = """
source scripts/bk_functions.sh
source programs/sbd/profile.sh
bk_discover_ncu_plan() { printf '%s\\n' "$FIXTURE_PLAN"; }
_bk_profile_register() { :; }
bk_acquire_ncu() { printf '%s\\n' "$*" >> "$CALLS"; }
sbd_run_configured_ncu_profiles RIKYU 1 --input unchanged
"""
        environment=dict(os.environ, FIXTURE_PLAN=str(plan_path), CALLS=str(calls),
            BK_SBD_NCU_PROFILE='true', BK_SBD_DAVIDSON_PROFILE='true', PYTHON_BIN=sys.executable,
            BK_RUN_RESULTS_DIR=str(directory), BK_TIMING_OBSERVATIONS_FILE=str(directory/'observations.json'),
            BK_TIMING_OBSERVATION_ITEMS_FILE=str(directory/'observations.jsonl'))
        subprocess.run(['bash','-eu','-c',command], cwd=ROOT,env=environment,
                       capture_output=True,text=True,check=True)
        observed=calls.read_text().splitlines()
        self.assertEqual(len(observed),5)
        self.assertTrue(all('--launch-skip 1 --launch-count 1' in line and '--level detailed' in line for line in observed))
        prepared=json.loads((directory/'davidson-plan.json').read_text())
        self.assertEqual({sbd.family(p['kernel_name']) for p in prepared['profiles']},set(sbd.FAMILIES))
        self.assertTrue(all(p['nvtx']['range']==LABEL and not p['section'] for p in prepared['profiles']))
        manifest=json.loads((directory/'observation-bundle.json').read_text())
        self.assertEqual(len(manifest['files']), 12)
        self.assertTrue((directory/'observation-bundle.tgz').is_file())
        self.assertEqual(json.loads((directory/'observations.json').read_text())['observations'][0]['format'],
                         'benchkit-observation-bundle/v1')
        calls.unlink()
        run=subprocess.run(['bash','-eu','-c',command.replace('RIKYU 1','RIKYU 2')],
            cwd=ROOT,env=environment,capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0)
        self.assertFalse(calls.exists())

    def test_bundle_preparation_and_missing_duplicate_metadata(self):
        plan, profiles, output = self.bundle_fixture()
        sbd.prepare_inputs(plan, profiles, output, 'source', 'target')
        samples = json.loads((output/'samples.json').read_text())
        self.assertEqual(sbd.aggregate(self.trace, self.pred, samples)['time_ratio_predicted_over_source'], .85)
        self.assertEqual(len(json.loads((output/'jobs.json').read_text())), 5)
        meta = profiles/'kernel_0/profile.metadata.json'
        original = meta.read_bytes(); meta.unlink()
        with self.assertRaises(ValueError): sbd.prepare_inputs(plan, profiles, output, 'source', 'target')
        meta.write_bytes(original)
        duplicate = profiles/'duplicate'; duplicate.mkdir()
        (duplicate/'profile.metadata.json').write_bytes(original)
        with self.assertRaises(ValueError): sbd.prepare_inputs(plan, profiles, output, 'source', 'target')

    def test_artifact_estimate_acquires_pinned_model_without_root_configuration(self):
        import shutil
        plan, profiles, _ = self.bundle_fixture()
        directory = plan.parent
        work = directory / 'work'
        work.mkdir()
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        shutil.copytree(ROOT / 'programs/sbd', work / 'programs/sbd')
        model = directory / 'model'
        model.mkdir()
        (model / 'file').write_text('model fixture')
        def git(*args):
            return subprocess.check_output(['git', '-C', str(model), *args], text=True).strip()
        git('init', '-q')
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'fixture')
        commit = git('rev-parse', 'HEAD')
        # Stop at the model boundary: acquisition is real, inference is not run.
        adapter = work / 'scripts/estimation/section_packages/gpu_kernel_lightgbm_v11.sh'
        with adapter.open('a') as handle:
            handle.write('''
bk_section_package_transform_gpu_kernel_lightgbm_v11() {
  [[ -z "${BK_GPU_LIGHTGBM_FETCH_PERFTOOLS+x}" ]] || exit 76
  _bk_gpu_lightgbm_ensure_perftools_root > selected-root || exit 75
  exit 77
}
''')
        result = work / 'result.json'
        result.write_text(json.dumps(dict(code='sbd', Exp='H2O-1em4', system='RIKYU',
            FOM=1, FOM_unit='s', FOM_version='davidson_internal_s',
            node_count=1, numproc_node=1, nthreads=8)))
        env = {k:v for k,v in os.environ.items() if not k.startswith(('BK_GPU_', 'BK_PERFTOOLS_', 'BK_SBD_'))}
        env.update(BK_SBD_RIKYU_ARTIFACT_ONLY='true',
            BK_GPU_LIGHTGBM_SOURCE_GPU='GH200', BK_GPU_LIGHTGBM_TARGET_GPU='A100',
            BK_ESTIMATION_FUTURE_SYSTEM='A100', BK_SBD_DAVIDSON_PLAN=str(plan),
            BK_SBD_DAVIDSON_PROFILES_DIR=str(profiles), BK_GPU_LIGHTGBM_PERFTOOLS_REPO=str(model),
            BK_GPU_LIGHTGBM_PERFTOOLS_COMMIT=commit, BK_PERFTOOLS_CACHE_DIR=str(work / 'cache'),
            BK_ESTIMATION_PYTHON=sys.executable, GIT_ALLOW_PROTOCOL='file')
        run = subprocess.run(['bash', 'programs/sbd/estimate.sh', str(result)],
            cwd=work, env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 77, run.stderr)
        self.assertEqual((work / 'selected-root').read_text().strip(), str(work / 'cache' / commit))
        self.assertEqual(subprocess.check_output(['git', '-C', str(work / 'cache' / commit),
            'rev-parse', 'HEAD'], text=True).strip(), commit)

    def test_plan_rejects_wrong_scope_first_launch_and_missing_family(self):
        plan = dict(profiles=[dict(name=f'k{i}', kernel_name=n,
            nvtx=dict(range=LABEL, domain='default', style='PushPop'), launch_skip=1, launch_count=1)
            for i,n in enumerate(self.names)])
        for changed in ('scope','first','family'):
            candidate = copy.deepcopy(plan)
            if changed == 'scope': candidate['profiles'][0]['nvtx']['range']='other'
            elif changed == 'first': candidate['profiles'][0]['launch_skip']=0
            else: candidate['profiles'].pop()
            with self.assertRaises(ValueError): sbd.make_samples(self.trace,candidate,'source','target')

    def test_bundle_rejects_raw_xyz_mismatch_with_same_product(self):
        plan, profiles, output = self.bundle_fixture()
        archive = profiles/'kernel_0/profile.tgz'
        with tarfile.open(archive) as source:
            content = source.extractfile('raw/rep1/profile_raw.csv').read()
        content = content.replace(b',10,1,1,64,1,1', b',5,2,1,64,1,1')
        with tarfile.open(archive,'w:gz') as target:
            member = tarfile.TarInfo('raw/rep1/profile_raw.csv'); member.size=len(content)
            target.addfile(member,io.BytesIO(content))
        with self.assertRaisesRegex(ValueError,'Grid/Block'): sbd.prepare_inputs(plan,profiles,output,'source','target')

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
