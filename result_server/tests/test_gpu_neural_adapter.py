"""Current neural estimator boundaries; no GPU, weights or network needed."""
import csv
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts/estimation'


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('gpu_neural_adapter', SCRIPTS / 'run_gpu_neural.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ratio_uses_sums_and_preserves_self_error(adapter):
    rows = [{'source_time_ns': 100, 'self_predicted_time_ns': 200, 'predicted_time_ns': 100},
            {'source_time_ns': 300, 'self_predicted_time_ns': 100, 'predicted_time_ns': 200}]
    summary = adapter.aggregate(rows)
    assert summary['time_ratio_predicted_over_source'] == 1
    assert summary['time_ratio_predicted_over_observed_source'] == .75
    assert summary['self_prediction_over_observed_source'] == .75
    assert summary['self_prediction_error_percent'] == -25
    assert summary['time_ratio_basis'] == 'predicted_target_over_predicted_source'
    # Averaging per-launch ratios would give 1.25, a different result.


def test_self_ratio_is_one_even_when_absolute_prediction_is_wrong(adapter):
    result = adapter.aggregate([{'source_time_ns': 100, 'self_predicted_time_ns': 180,
                                 'predicted_time_ns': 180}])
    assert result['time_ratio_predicted_over_source'] == 1
    assert result['self_prediction_error_percent'] == 80


@pytest.mark.parametrize('bad', [0, -1, float('nan'), float('inf')])
def test_nonpositive_or_nonfinite_time_is_rejected(adapter, bad):
    with pytest.raises(ValueError):
        adapter.positive(bad, 'self prediction')


def test_prediction_identity_matching_does_not_use_row_order(adapter):
    rows = [{'kernel_name': 'k', 'src_gpu': 'S', 'tgt_gpu': 'T', 'time': 20},
            {'kernel_name': 'k', 'src_gpu': 'S', 'tgt_gpu': 'S', 'time': 10}]
    assert adapter.prediction_pair(rows[::-1], 'k', 'S', 'T')['T']['time'] == 20
    for invalid in [rows[:1], rows + rows[:1], [rows[0], rows[0]],
                    [rows[0], dict(rows[1], src_gpu='wrong')],
                    [rows[0], dict(rows[1], kernel_name='wrong')]]:
        with pytest.raises(ValueError):
            adapter.prediction_pair(invalid, 'k', 'S', 'T')
    assert len(adapter.prediction_pair([rows[1]], 'k', 'S', 'S')) == 1


def test_normalization_preserves_canonical_values_and_fills_observed_aliases(adapter):
    pd = pytest.importorskip('pandas')
    frame = pd.DataFrame({'Achieved Occupancy': [7, None], 'Achieved Occupancy [%]': [99, 12],
                          'smsp__inst_issued.sum': [120, 80], 'smsp__inst_executed.sum': [100, 0],
                          'smsp__average_warp_latency_per_inst_issued.ratio': [10, 5],
                          'l1tex__t_sector_hit_rate.pct': [40, 50], 'lts__t_sector_hit_rate.pct': [60, 70]})
    wide = adapter.normalize(frame)
    assert wide['Achieved Occupancy'].tolist() == [7, 12]
    assert 'Achieved Occupancy [%]' not in wide
    assert wide['Warp Cycles Per Executed Instruction [cycle/inst]'][0] == 12
    assert pd.isna(wide['Warp Cycles Per Executed Instruction [cycle/inst]'][1])
    assert wide['L1/TEX Hit Rate [%]'].tolist() == [40, 50]
    assert wide['Issued Instructions [inst]'].tolist() == [120, 80]


def test_explicit_process_and_configurations_are_preserved(adapter):
    pd = pytest.importorskip('pandas')
    from run_gpu_lightgbm_v11 import select_process
    frame = pd.DataFrame({'Process ID': [10, 10, 20], 'Kernel Name': ['k', 'k', 'k'],
                          'Grid Size': [100, 101, 100], 'Block Size': [128] * 3})
    with pytest.raises(ValueError, match='representative'):
        select_process(frame)
    selected, sampling = select_process(frame, '10')
    selected = adapter.choose_kernels(selected, {'kernel_name': 'k'})
    assert selected['Grid Size'].tolist() == [100, 101]
    assert sampling['mpi_rank'] is None
    assert sampling['available_process_ids'] == ['10', '20']
    with pytest.raises(ValueError):
        adapter.choose_kernels(selected, {'kernel_name': 'absent'})


@pytest.mark.parametrize('model,family,release,entry,seeds', [
    ('mlp455', 'MLP_NN', 'v4.55', 'mlp-nn.py', 5),
    ('pinn325', 'PINN', 'v3.25', 'pinn.py', 3),
])
def test_current_release_manifest_hashes_all_model_files(adapter, tmp_path, monkeypatch, model, family, release, entry, seeds):
    monkeypatch.chdir(ROOT)
    root = tmp_path / 'tool'
    names = [f'{family}/{entry}', f'{family}/network.py', f'{family}/data_pipeline_v2.py',
             f'{family}/' + ('mlpnn_core.py' if model == 'mlp455' else 'pinn_core.py'),
             f'{family}/{release}/meta.pkl', f'{family}/{release}/runtime_inputs_training.csv',
             'examples/kernel_inputs/prepare_data.py', 'data/v4/gpu_microarch_specs.csv']
    names += [f'{family}/{release}/model_seed{i}.pt' for i in range(seeds)]
    if model == 'pinn325':
        names.append('PINN/v3.25/trust_anchor.json')
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture data, not a real model: ' + name)
    manifest = adapter.make_manifest(str(root), model, entry, 'wide_ncu_csv', '', '', 'ref', '')
    assert set(names) == {f['path'] for f in manifest['external_inference']['files']}
    assert manifest['external_inference']['missing_files'] == []
    assert manifest['preprocessing']['spec_supplements'] == []
    seed = root / f'{family}/{release}/model_seed0.pt'
    seed.unlink()
    with pytest.raises(ValueError, match='dependencies are missing'):
        adapter.make_manifest(str(root), model, entry, 'wide_ncu_csv', '', '', 'ref', '')


@pytest.mark.parametrize('model', ['mlp455', 'pinn325'])
def test_launch_preparation_projection_and_provenance(adapter, tmp_path, monkeypatch, model):
    pd = pytest.importorskip('pandas')
    from argparse import Namespace
    monkeypatch.chdir(ROOT)
    family, entry, release, package, _ = adapter.MODELS[model]
    tool = tmp_path / 'tool'
    names = [f'{family}/{entry}', f'{family}/network.py', f'{family}/data_pipeline_v2.py',
             f'{family}/' + ('mlpnn_core.py' if model == 'mlp455' else 'pinn_core.py'),
             f'{family}/{release}/meta.pkl', f'{family}/{release}/runtime_inputs_training.csv',
             'examples/kernel_inputs/prepare_data.py', 'data/v4/gpu_microarch_specs.csv']
    names += [f'{family}/{release}/model_seed{i}.pt' for i in range(5 if model == 'mlp455' else 3)]
    if model == 'pinn325':
        names.append('PINN/v3.25/trust_anchor.json')
    for name in names:
        path = tool / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('opaque fixture: ' + name)
    observed = tmp_path / 'wide.csv'
    pd.DataFrame({'Process ID': [10, 10, 20], 'ID': [0, 1, 0], 'Kernel Name': ['k'] * 3,
                  'Grid Size': [1, 2, 1], 'Block Size': [128] * 3,
                  'Duration [ns]': [100, 300, 999]}).to_csv(observed, index=False)
    calls = []

    def invoke(argv, root, env, log):
        argv = list(map(str, argv))
        calls.append(argv)
        output = Path(argv[argv.index('--out') + 1])
        if argv[0].endswith('prepare_data.py'):
            frame = pd.read_csv(argv[argv.index('--ncu') + 1])
            assert len(frame) == 1  # No kernel-name deduplication can lose configurations.
            row = frame.iloc[0].to_dict()
            rows = [dict(row, src_gpu='S', tgt_gpu=t, **{'Execution Time': row['Duration [ns]']})
                    for t in argv[argv.index('--tgt') + 1].split(',')]
        else:
            assert argv[argv.index('--artifact') + 1] == str(tool / family / release)
            frame = pd.read_csv(argv[argv.index('--csv') + 1])
            rows = [{'kernel_name': r['Kernel Name'], 'src_gpu': 'S', 'tgt_gpu': r['tgt_gpu'],
                     'Execution Time [ns]': (100 if r['Grid Size'] == 1 else 300)
                     * (1 if r['tgt_gpu'] == 'S' else (0.5 if r['Grid Size'] == 1 else 2))}
                    for _, r in frame.iterrows()]
            rows.reverse()
        pd.DataFrame(rows).to_csv(output, index=False)
        log.write_text('fixture invocations only')

    monkeypatch.setattr(adapter, 'invoke', invoke)
    monkeypatch.setattr(adapter, 'distribution_version', lambda name: 'fixture')
    args = Namespace(model=model, root=str(tool), output_dir=str(tmp_path / 'outputs'), padata=None,
                     wide_csv=str(observed), source_gpu='S', target_gpu='T', profile_process_id='10',
                     kernel_name='', kernel_regex='', requested_ref='fixture', pin='')
    item = adapter.run(args, {'name': 'gpu', 'time': 8, 'fallback_used': 'identity'})
    assert len(calls) == 4 and 'fallback_used' not in item
    assert item['estimation_package'] == package
    assert item['time'] == 13  # 8 * (50 + 600) / (100 + 300)
    assert item['metrics']['configuration_count'] == 2
    assert item['metrics']['sampling']['selected_rows'] == 2
    assert item['model']['requested_version'] == item['model']['applied_version'] == release
    path = Path(item['model']['provenance']['manifest'])
    manifest = json.loads(path.read_text())
    assert adapter.digest(path) == item['model']['provenance']['sha256']
    assert manifest['model']['weights_directory'] == f'{family}/{release}'
    assert manifest['external_inference']['resolved_commit'] is None  # Not a fabricated commit.
    assert len([f for f in manifest['inputs'] if f['role'] == 'prepared_input']) == 2
    # Repeating an attempt cannot overwrite earlier provenance or input artifacts.
    repeated = adapter.run(args, {'name': 'gpu', 'time': 8})
    assert repeated['model']['provenance']['manifest'] != str(path)
    assert adapter.digest(path) == item['model']['provenance']['sha256']


def test_current_package_registration_and_legacy_availability():
    package_dir = SCRIPTS / 'section_packages'
    supported = json.loads((SCRIPTS / 'packages/instrumented_app_sections_dummy.metadata.json').read_text())
    for name in ['gpu_kernel_mlp_v455', 'gpu_kernel_pinn_v325', 'gpu_kernel_mlp_v15']:
        assert name in supported['supported_section_packages']
        metadata = json.loads((package_dir / f'{name}.metadata.json').read_text())
        assert metadata['version']
    result = subprocess.check_output(['bash', '-c', '''
source scripts/estimation/section_packages/gpu_kernel_ensemble_average.sh
_bk_gpu_kernel_ensemble_packages '{}'
'''], cwd=ROOT, text=True).splitlines()
    assert result == ['gpu_kernel_lightgbm_v11', 'gpu_kernel_mlp_v455', 'gpu_kernel_pinn_v325']


def test_configuration_means_reconstruct_identical_weighted_totals(adapter):
    rows = []
    for grid, observed, self_time, target in [(2, 100, 200, 300), (1, 200, 400, 800), (2, 300, 600, 900)]:
        rows.append({'name': 'k', 'configuration': {'grid_size': grid, 'block_size': 128},
                     'source_time_ns': observed, 'self_predicted_time_ns': self_time, 'predicted_time_ns': target,
                     'source_gpu': 'S', 'target_gpu': 'T', 'profile_process_id': '10', 'metrics': {}})
    groups = adapter.group_samples(rows)
    assert [g['sample_count'] for g in groups] == [1, 2]
    for key, total in [('source_time_ns', 'total_source_time_ns'),
                       ('self_predicted_time_ns', 'total_self_predicted_time_ns'),
                       ('predicted_time_ns', 'total_predicted_time_ns')]:
        assert sum(g[key] * g['sample_count'] for g in groups) == adapter.aggregate(rows)[total]


@pytest.mark.parametrize('package', ['gpu_kernel_mlp_v455', 'gpu_kernel_pinn_v325'])
def test_pinned_neural_checkout_failure_is_not_identity(adapter, tmp_path, package):
    import os
    repo = tmp_path / 'tool'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'file').write_text('fixture')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-qm', 'fixture'], check=True)
    # Isolate checkout validation from the optional Python/torch readiness probe.
    python = tmp_path / 'python-probe'
    python.write_text('#!/bin/sh\nexit 0\n')
    python.chmod(0o755)
    csv_path = tmp_path / 'input.csv'
    csv_path.write_text('fixture')
    env = dict(os.environ, BK_GPU_NEURAL_PYTHON=str(python), BK_GPU_NEURAL_PERFTOOLS_REPO=str(repo),
               BK_PERFTOOLS_CACHE_DIR=str(tmp_path / 'cache'),
               BK_GPU_NEURAL_PERFTOOLS_COMMIT='0' * 40, BK_GPU_NEURAL_INPUT_CSV=str(csv_path),
               BK_GPU_NEURAL_SOURCE_GPU='S', BK_GPU_NEURAL_TARGET_GPU='T')
    item = json.dumps({'name': 'gpu', 'time': 1, 'estimation_package': package})
    result = subprocess.run(['bash', '-c', '''
source scripts/estimation/packages/top_level_package_common.sh
bk_top_level_dispatch_bound_item "$1" 1 1 1 section ''
''', 'fixture', item], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not result.stdout.strip()
    assert 'commit fetch failed' in result.stderr


def test_missing_neural_runtime_records_requested_and_fallback_versions(tmp_path):
    import os
    python = tmp_path / 'unavailable-python'
    python.write_text('#!/bin/sh\nexit 1\n')
    python.chmod(0o755)
    result = subprocess.check_output(['bash', '-c', '''
source scripts/estimation/packages/top_level_package_common.sh
bk_top_level_dispatch_bound_item '{"name":"gpu","time":8,"estimation_package":"gpu_kernel_mlp_v455"}' 1 1 1 section ''
'''], cwd=ROOT, env=dict(os.environ, BK_GPU_NEURAL_PYTHON=str(python)), text=True)
    item = json.loads(result)
    assert item['estimation_package'] == 'identity'
    assert item['requested_estimation_package'] == 'gpu_kernel_mlp_v455'
    assert item['estimation_package_version'] == item['requested_estimation_package_version'] == '0.1'
    assert item['package_applicability']['status'] == 'fallback'
    assert 'model' not in item
