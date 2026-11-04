"""Shared lifecycle with a third method, variable job counts and isolated Results."""
import json
import importlib.util
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(REPO / 'scripts', self.root / 'scripts')
        (self.root / 'results').mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('BK_', '_BK_', 'RESULT_SERVER'))}

    def shell(self, command):
        return subprocess.run(['bash', '-eu', '-c', command], cwd=self.root,
                              env=self.env, text=True, capture_output=True)

    def test_third_package_variable_batches_and_failure(self):
        adapter = self.root / 'scripts/estimation/section_packages/fixture.sh'
        adapter.write_text('''bk_section_package_run_job_fixture() {
          local job="$1" work="$2"
          [[ $(jq -r .fail <<< "$job") != true ]] || return 17
          jq -c --arg work "$work" '. + {work:$work}' <<< "$job"
        }\n''')
        for count in (1, 3, 7):
            (self.root / 'jobs.json').write_text(json.dumps([dict(value=i) for i in range(count)]))
            result = self.shell(f'source scripts/estimation/common.sh; bk_estimation_run_jobs fixture jobs.json results/jobs_{count}')
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = sorted((self.root / 'results' / f'jobs_{count}').glob('kernel_*.json'))
            self.assertEqual(len(outputs), count)
            self.assertEqual({json.loads(p.read_text())['value'] for p in outputs}, set(range(count)))
        (self.root / 'jobs.json').write_text('[{"value":0},{"fail":true},{"value":2}]')
        result = self.shell('source scripts/estimation/common.sh; bk_estimation_run_jobs fixture jobs.json results/jobs_3')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'results/jobs_3/kernel_1.json').exists())
        self.assertFalse((self.root / 'results/jobs_3/kernel_2.json').exists())

    def test_third_app_projection_preserves_source_links(self):
        app = self.root / 'programs/third'
        app.mkdir(parents=True)
        (app / 'estimate.metadata.json').write_text('{"version":"test"}')
        projection = dict(schema_version=1, method='fixture-ratio', time_ratio_predicted_over_source=.5,
                          prediction_package='fixture', prediction_model=dict(version='1'),
                          assumptions=['fixture'], status='conditional', limitations=[])
        (self.root / 'projection.json').write_text(json.dumps(projection))
        for i in range(2):
            source = dict(code='third', Exp='case'+str(i), system='source', FOM=10+i,
                          node_count=1, numproc_node=1,
                          _server_uuid=f'11111111-1111-4111-8111-{i:012d}',
                          _server_timestamp='2026-01-01 00:00:00')
            result_path = self.root / f'results/result{i}.json'
            result_path.write_text(json.dumps(source))
            result = self.shell(f'''source scripts/estimation/common.sh
              export BK_ESTIMATION_FUTURE_SYSTEM=target
              bk_estimation_write_projection results/result{i}.json "$(cat projection.json)" '{{}}' results/estimate_{i}.json
            ''')
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads((self.root / f'results/estimate_{i}.json').read_text())
            self.assertEqual(output['future_system']['fom'], (10+i)*.5)
            self.assertEqual(output['current_system']['benchmark']['uuid'], source['_server_uuid'])
            self.assertEqual(output['future_system']['benchmark']['uuid'], source['_server_uuid'])
            self.assertEqual(json.loads(result_path.read_text()), source)
            self.assertEqual(output['input_artifacts'][0]['sha256'], hashlib.sha256(result_path.read_bytes()).hexdigest())
            self.assertNotIn('RESULT_SERVER', output['estimate_metadata']['execution_conditions'])
            spec = importlib.util.spec_from_file_location('conditions', self.root / 'scripts/estimation/reestimation_conditions.py')
            conditions = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(conditions)
            settings, request = conditions.resolve_conditions(output, {'source_result_uuid': source['_server_uuid']}, {})
            self.assertEqual(settings['BK_ESTIMATION_FUTURE_SYSTEM'], 'target')
            self.assertEqual(settings['BK_ESTIMATION_FUTURE_PACKAGE'], 'fixture')
            self.assertEqual(request['explicit_changes'], {})
            changed, request = conditions.resolve_conditions(output, {'source_result_uuid': source['_server_uuid']}, {'BK_ESTIMATION_FUTURE_SYSTEM': 'other'})
            self.assertEqual(changed['BK_ESTIMATION_FUTURE_SYSTEM'], 'other')
            self.assertEqual(request['explicit_changes']['BK_ESTIMATION_FUTURE_SYSTEM'], dict(recorded='target', requested='other'))



if __name__ == '__main__':
    unittest.main()
