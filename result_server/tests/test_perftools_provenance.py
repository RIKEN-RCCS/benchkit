"""External inference provenance and checkout tests use local repositories only."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'scripts/estimation/perftools_provenance.py'
spec = importlib.util.spec_from_file_location('perftools_provenance', MODULE)
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)


def run_git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    run_git(root, 'init', '-q')
    (root / 'file').write_text('first')
    run_git(root, 'add', '.')
    run_git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'initial')
    return root


def ensure(source, ref='main', pin='', cache=None, extra_env=None):
    env = dict(os.environ, BK_PERFTOOLS_CACHE_DIR=str(cache or source.parent / 'cache'))
    env.update(extra_env or {})
    return subprocess.run(['bash', '-c', 'source "$1"; bk_perftools_ensure_root "$2" "$3" "$4"',
                           'fixture', str(ROOT / 'scripts/estimation/section_packages/perftools_common.sh'),
                           str(source), ref, pin],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_checkout_fixed_and_dirty_rejected(repo):
    sha = run_git(repo, 'rev-parse', 'HEAD')
    result = ensure(repo, 'not-the-current-ref', sha)
    assert result.returncode == 0, result.stderr
    checkout = Path(result.stdout.strip())
    assert checkout != repo
    assert run_git(checkout, 'rev-parse', 'HEAD') == sha
    assert run_git(checkout, 'status', '--porcelain') == ''
    assert ensure(repo, pin='0' * 40).returncode != 0
    (checkout / 'file').write_text('changed')
    assert ensure(repo, pin=sha).returncode != 0
    assert (checkout / 'file').read_text() == 'changed'
    assert ensure(repo, pin='short-sha').returncode != 0


def test_local_ref_resolution_commit_cache_and_failure(repo):
    branch = run_git(repo, 'symbolic-ref', '--short', 'HEAD')
    sha = run_git(repo, 'rev-parse', 'HEAD')
    result = ensure(repo, 'refs/heads/' + branch)
    assert result.returncode == 0, result.stderr
    checkout = Path(result.stdout.strip())
    assert checkout.name == sha
    assert run_git(checkout, 'rev-parse', 'HEAD') == sha
    assert ensure(repo, 'missing-ref').returncode != 0
    assert ensure(repo, branch, pin='0' * 40).returncode != 0
    assert ensure(repo, pin=sha.upper()).stdout.strip() == str(checkout)
    (checkout / 'file').write_text('cache modified')
    assert ensure(repo, branch).returncode != 0


def test_commit_cache_reuse_needs_no_repository_connection(repo):
    sha = run_git(repo, 'rev-parse', 'HEAD')
    first = ensure(repo, pin=sha)
    assert first.returncode == 0, first.stderr
    unavailable = repo.parent / 'unavailable'
    second = ensure(unavailable, pin=sha)
    assert second.returncode == 0, second.stderr
    assert second.stdout == first.stdout


def test_wrong_commit_in_cache_fails_without_switching_it(repo):
    sha = run_git(repo, 'rev-parse', 'HEAD')
    result = ensure(repo, pin=sha)
    assert result.returncode == 0, result.stderr
    checkout = Path(result.stdout.strip())
    (repo / 'file').write_text('second')
    run_git(repo, 'add', '.')
    run_git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'second')
    other = run_git(repo, 'rev-parse', 'HEAD')
    run_git(checkout, 'fetch', '-q', str(repo), other)
    run_git(checkout, 'checkout', '--detach', other)
    failed = ensure(repo, pin=sha)
    assert failed.returncode != 0
    assert 'does not match the resolved clean commit' in failed.stderr
    assert run_git(checkout, 'rev-parse', 'HEAD') == other


def test_ref_updates_select_separate_commits_and_preserve_old_checkout(repo):
    branch = run_git(repo, 'symbolic-ref', '--short', 'HEAD')
    old_sha = run_git(repo, 'rev-parse', 'HEAD')
    first = ensure(repo, branch)
    (repo / 'file').write_text('second')
    run_git(repo, 'add', '.')
    run_git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'second')
    second = ensure(repo, branch)
    assert second.returncode == 0, second.stderr
    assert second.stdout != first.stdout
    assert run_git(Path(first.stdout.strip()), 'rev-parse', 'HEAD') == old_sha
    assert ensure(repo, pin=old_sha).stdout == first.stdout


@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink'])
def test_invalid_cache_is_not_repaired(repo, kind):
    sha = run_git(repo, 'rev-parse', 'HEAD')
    entry = repo.parent / 'cache' / sha
    entry.parent.mkdir()
    if kind == 'file':
        entry.write_text('preserve')
    elif kind == 'directory':
        entry.mkdir()
        (entry / 'file').write_text('preserve')
    else:
        entry.symlink_to(repo, target_is_directory=True)
    assert ensure(repo, pin=sha).returncode != 0
    assert (entry if kind == 'file' else entry / 'file').read_text() in ('preserve', 'first')


@pytest.mark.parametrize('script,function', [
    ('gpu_kernel_lightgbm_v10.sh', '_bk_gpu_lightgbm_ensure_perftools_root'),
    ('gpu_kernel_lightgbm_v11.sh', '_bk_gpu_lightgbm_ensure_perftools_root'),
    ('gpu_kernel_mlp_v15.sh', '_bk_gpu_mlp_ensure_perftools_root'),
    ('gpu_kernel_mlp_v21.sh', '_bk_gpu_mlp_ensure_perftools_root'),
    ('gpu_kernel_mlp_v41.sh', '_bk_gpu_mlp_ensure_perftools_root'),
    ('gpu_kernel_neural_common.sh', '_bk_gpu_neural_root'),
])
def test_model_adapters_use_common_commit_checkout(repo, script, function):
    sha = run_git(repo, 'rev-parse', 'HEAD')
    env = dict(os.environ, BK_PERFTOOLS_REPO=str(repo), BK_PERFTOOLS_COMMIT=sha,
               BK_PERFTOOLS_CACHE_DIR=str(repo.parent / 'cache'))
    # Obsolete deployment variables cannot select code or prohibit acquisition.
    for name in ('BK_PERFTOOLS_ROOT', 'BK_GPU_LIGHTGBM_PERFTOOLS_ROOT',
                 'BK_GPU_MLP_PERFTOOLS_ROOT', 'BK_GPU_NEURAL_PERFTOOLS_ROOT'):
        env[name] = str(repo.parent / 'not-a-model')
    for family in ('LIGHTGBM', 'MLP', 'NEURAL'):
        env[f'BK_GPU_{family}_FETCH_PERFTOOLS'] = 'false'
    result = subprocess.run(['bash', '-c', 'source scripts/estimation/section_packages/gpu_kernel_mlp_v15.sh; source "$1"; "$2"', 'fixture',
                             str(ROOT / 'scripts/estimation/section_packages' / script), function],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == repo.parent / 'cache' / sha


def test_precomputed_prediction_has_no_local_model_identity(tmp_path):
    csv = tmp_path / 'prediction.csv'
    csv.write_text('time\n1\n')
    data = provenance.make_manifest('/unused/private/checkout', 'v2.1', 'predict_v21.py',
                                    'precomputed_prediction', '', str(csv), 'main', '')
    assert data['external_inference'] is None
    assert data['preprocessing'] is None
    assert data['inputs'][0]['sha256'] == provenance.digest(csv)
    assert '/unused' not in json.dumps(data)


def test_v21_shared_weights_and_preprocessing_supplements(repo, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    for name in ['MLP_NN/v2.1/predict_v21.py', 'MLP_NN/v1.5/v15_core.py',
                 'MLP_NN/v1.5/v15_artifact/model_h100.pt',
                 'MLP_NN/examples/prepare_data.py', 'data/gpu_microarch_specs.csv']:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    run_git(repo, 'remote', 'add', 'origin', 'https://user:private@example.invalid/tool.git?secret=value')
    csv = tmp_path / 'input.csv'
    csv.write_text('value\n1\n')
    supplements = {'spec_supplements': [{'gpu': 'H100', 'column': 'SRC warps', 'value': 16}]}
    Path(str(csv) + '.preprocessing.json').write_text(json.dumps(supplements))
    data = provenance.make_manifest(str(repo), 'v2.1', 'predict_v21.py', 'ncu_archive', str(csv), '', 'main', '')
    external = data['external_inference']
    assert external['repository'] == 'https://example.invalid/tool.git'
    assert external['resolved_commit'] == run_git(repo, 'rev-parse', 'HEAD')
    assert external['dirty'] is True
    files = {f['path']: f['sha256'] for f in external['files']}
    assert 'MLP_NN/v1.5/v15_artifact/model_h100.pt' in files
    assert not any('v2.1/v21_artifact' in f for f in files)
    assert data['preprocessing']['spec_supplements'] == supplements
    before = files['MLP_NN/v1.5/v15_core.py']
    (repo / 'MLP_NN/v1.5/v15_core.py').write_text('modified')
    after = provenance.make_manifest(str(repo), 'v2.1', 'predict_v21.py', 'prepared_csv', str(csv), '', 'main', '')
    assert after['preprocessing'] is None
    assert next(f['sha256'] for f in after['external_inference']['files'] if f['path'].endswith('v15_core.py')) != before
    assert 'private' not in json.dumps(data)


@pytest.mark.parametrize('version,predictor,expected', [
    ('v1.5', 'predict_v15.py', 'MLP_NN/v1.5/v15_artifact/model_h100.pt'),
    ('v4.1', 'predict_v41.py', 'MLP_NN/v4.1/v41_artifact/model_seed0.pt'),
    ('lightgbm', 'run_inference.py', 'LightGBM_model/1.0/AI_model/model/lgbm_Execution_Time.txt'),
])
def test_model_bundle_selection(repo, version, predictor, expected):
    path = repo / expected
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('fixture weights; never deserialize')
    data = provenance.make_manifest(str(repo), version, predictor, 'prepared_csv', '', '', 'main', '')
    external = data['external_inference']
    assert expected in [f['path'] for f in external['files']]
    assert external['missing_files']  # Missing parts are explicit rather than claimed complete.


def test_spec_supplements_record_only_missing_values(monkeypatch):
    # Only the dataframe boundary is mocked; exercise the real supplement function.
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    monkeypatch.setitem(sys.modules, 'pandas', SimpleNamespace())
    source = ROOT / 'scripts/estimation/prepare_gpu_mlp_ncu_input.py'
    module_spec = importlib.util.spec_from_file_location('mlp_prepare', source)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    column = 'TGT GPU Maximum Warps Per Scheduler [warp]'
    frame = MagicMock()
    frame.columns = ['tgt_gpu', column]
    frame.__getitem__.return_value.astype.return_value.items.return_value = [(0, 'H100'), (1, 'A100')]
    frame.at = {(0, column): float('nan'), (1, column): 7}
    applied = module.fill_spec_defaults(frame)
    assert applied == [{'row': 0, 'gpu': 'H100', 'column': column, 'value': 16}]
    assert frame.at[(0, column)] == 16
    assert frame.at[(1, column)] == 7
    assert module.fill_spec_defaults(frame) == []


def test_pin_failure_does_not_turn_into_identity_fallback(repo):
    predictor = repo / 'MLP_NN/v1.5/predict_v15.py'
    predictor.parent.mkdir(parents=True)
    predictor.write_text('fixture')
    csv = repo.parent / 'input.csv'
    csv.write_text('fixture')
    import sys
    env = dict(os.environ, BK_GPU_MLP_PYTHON=sys.executable,
               BK_GPU_MLP_PERFTOOLS_REPO=str(repo), BK_GPU_MLP_PERFTOOLS_COMMIT='0' * 40,
               BK_PERFTOOLS_CACHE_DIR=str(repo.parent / 'cache'),
               BK_GPU_MLP_INPUT_CSV=str(csv), BK_GPU_MLP_ARTIFACT_MODE='input')
    result = subprocess.run(['bash', '-c', '''source scripts/estimation/packages/top_level_package_common.sh
bk_top_level_dispatch_bound_item '{"name":"gpu","time":1,"estimation_package":"gpu_kernel_mlp_v15"}' 1 1 1 section ""
'''], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'commit fetch failed' in result.stderr
    assert not result.stdout.strip()


def test_annotated_tag_resolves_to_commit(repo):
    run_git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'tag', '-a', 'release', '-m', 'release')
    result = ensure(repo, 'refs/tags/release')
    assert result.returncode == 0, result.stderr
    assert run_git(Path(result.stdout.strip()), 'rev-parse', 'HEAD') == run_git(repo, 'rev-parse', 'HEAD')


def test_ncu_preparation_supplements_and_shared_lightgbm_bridge(tmp_path):
    pytest.importorskip('pandas', reason='NCU preparation uses the optional inference dependency')
    import sys
    raw = tmp_path / 'raw.csv'
    raw.write_text('"ID","Process ID","Kernel Name","gpu__time_duration.sum","launch__block_size","dram__bytes.sum.per_second","GPU Maximum Warps Per Scheduler [warp]"\n0,1,"fixture",1000,128,1000000,12\n')
    tool = tmp_path / 'tool/MLP_NN/examples'
    tool.mkdir(parents=True)
    (tool / 'prepare_data.py').write_text(
        'import sys,csv\np=sys.argv[sys.argv.index("--out")+1]\n'
        'with open(p,"w") as f:\n w=csv.writer(f);'
        'w.writerow(["src_gpu","tgt_gpu","SRC GPU Maximum Warps Per Scheduler [warp]",'
        '"TGT Shared Memory Configuration Size [byte]"]);w.writerow(["H100","A100",12,7])\n')
    output = tmp_path / 'input.csv'
    subprocess.run([sys.executable, str(ROOT / 'scripts/estimation/prepare_gpu_mlp_ncu_input.py'),
                    '--raw-csv', str(raw), '--perftools-root', str(tmp_path / 'tool'),
                    '--out-csv', str(output), '--target-gpu', 'A100'], check=True)
    details = json.loads(Path(str(output) + '.preprocessing.json').read_text())
    assert details['spec_supplements'] == []
    assert details['parameters']['target_gpu'] == 'A100'
    subprocess.run([sys.executable, str(ROOT / 'scripts/estimation/prepare_gpu_lightgbm_ncu_input.py'),
                    '--raw-csv', str(raw), '--out-csv', str(tmp_path / 'light.csv')], check=True)
    assert (tmp_path / 'light.csv').is_file()


def test_manifest_rechecks_pin_after_inference(repo):
    sha = run_git(repo, 'rev-parse', 'HEAD')
    (repo / 'file').write_text('changed during inference')
    with pytest.raises(SystemExit, match='changed during inference'):
        provenance.make_manifest(str(repo), 'v1.5', 'predict_v15.py', 'prepared_csv', '', '', 'main', sha)


def test_manifests_remain_addressable_across_results(tmp_path):
    import sys
    csv = tmp_path / 'prediction.csv'
    output = tmp_path / 'provenance.json'
    csv.write_text('time\n1\n')
    command = [sys.executable, str(MODULE), '--mode', 'precomputed_prediction',
               '--prediction-csv', str(csv), '--output', str(output)]
    first = json.loads(subprocess.check_output(command, text=True))
    csv.write_text('time\n2\n')
    second = json.loads(subprocess.check_output(command, text=True))
    assert first['manifest'] != second['manifest']
    assert provenance.digest(Path(first['manifest'])) == first['sha256']
    assert provenance.digest(Path(second['manifest'])) == second['sha256']


def test_ncu_source_spec_values_and_missing_observations(tmp_path):
    pd = pytest.importorskip('pandas')
    import runpy
    bridge = runpy.run_path(str(ROOT / 'scripts/estimation/prepare_gpu_mlp_ncu_input.py'))
    raw = pd.DataFrame({
        'device__attribute_max_warps_per_scheduler': [12, 12],
        'sm__maximum_warps_avg_per_active_cycle': [32, 16],
        'smsp__maximum_warps_avg_per_active_cycle': [8, 4],
        'launch__shared_mem_config_size': [65536, 32768],
        'launch__occupancy_limit_warps': [8, 4],
    })
    path = tmp_path / 'wide.csv'
    bridge['build_wide_ncu_csv'](raw, path, 'GB200')
    wide = pd.read_csv(path)
    expected = {
        'GPU Maximum Warps Per Scheduler [warp]': [12, 12],
        'Theoretical Active Warps per SM [warp]': [32, 16],
        'Theoretical Active Warps Per Scheduler [warp]': [8, 4],
        'Shared Memory Configuration Size [byte]': [65536, 32768],
        'Block Limit Warps [block]': [8, 4],
    }
    for column, values in expected.items():
        assert wide[column].tolist() == values
    # The shared bridge also accepts exported display names unchanged.
    bridge['build_wide_ncu_csv'](pd.DataFrame(expected), path, 'GB200')
    wide = pd.read_csv(path)
    for column, values in expected.items():
        assert wide[column].tolist() == values
    bridge['build_wide_ncu_csv'](pd.DataFrame({'Kernel Name': ['missing']}), path, 'GB200')
    missing = pd.read_csv(path)
    assert missing[list(expected)].isna().all().all()
    prepared = pd.DataFrame({'src_gpu': ['GB200'], 'tgt_gpu': ['H100'],
                             'SRC Theoretical Active Warps per SM [warp]': [float('nan')],
                             'TGT Theoretical Active Warps per SM [warp]': [float('nan')]})
    applied = bridge['fill_spec_defaults'](prepared)
    assert pd.isna(prepared.iloc[0]['SRC Theoretical Active Warps per SM [warp]'])
    assert all(item['column'].startswith('TGT ') for item in applied)


def test_final_src_features_keep_kernel_values_and_missing_fails(tmp_path):
    pd = pytest.importorskip('pandas')
    import runpy
    bridge = runpy.run_path(str(ROOT / 'scripts/estimation/prepare_gpu_mlp_ncu_input.py'))
    columns = list(bridge['SPEC_DEFAULTS']['H100'])
    source = pd.DataFrame({
        'Kernel Name': ['a', 'b'], 'Duration [ns]': [100, 200],
        'Block Size': [128, 256], 'Memory Throughput [byte/s]': [1000, 2000],
        **{column: [i + 1, i + 11] for i, column in enumerate(columns)},
    })
    prepared = pd.DataFrame({'Kernel Name': ['a', 'b'], 'src_gpu': ['GB200', 'GB200'],
                             'tgt_gpu': ['A100', 'H100'],
                             **{'SRC ' + c: [99, 99] for c in columns}})
    path = tmp_path / 'prepared.csv'
    prepared.to_csv(path, index=False)
    output = tmp_path / 'final.csv'
    bridge['finalize_prepared_input'](path, pd.DataFrame(), output, set(), 'H100', source)
    result = pd.read_csv(output)
    for i, column in enumerate(columns):
        assert result.iloc[0]['SRC ' + column] == i + 11
    assert json.loads(Path(str(output) + '.preprocessing.json').read_text())['spec_supplements'] == []
    source.loc[1, columns[0]] = float('nan')
    with pytest.raises(SystemExit, match='unexpected NaN'):
        bridge['finalize_prepared_input'](path, pd.DataFrame(), output, set(), 'H100', source)
    source.loc[1, 'Kernel Name'] = 'wrong'
    with pytest.raises(SystemExit, match='kernel order'):
        bridge['finalize_prepared_input'](path, pd.DataFrame(), output, set(), 'H100', source)


def test_partial_display_names_use_raw_values_per_row(tmp_path):
    pd = pytest.importorskip('pandas')
    import runpy
    bridge = runpy.run_path(str(ROOT / 'scripts/estimation/prepare_gpu_mlp_ncu_input.py'))
    pairs = {
        'GPU Maximum Warps Per Scheduler [warp]': 'device__attribute_max_warps_per_scheduler',
        'Theoretical Active Warps per SM [warp]': 'sm__maximum_warps_avg_per_active_cycle',
        'Theoretical Active Warps Per Scheduler [warp]': 'smsp__maximum_warps_avg_per_active_cycle',
        'Shared Memory Configuration Size [byte]': 'launch__shared_mem_config_size',
        'Block Limit Warps [block]': 'launch__occupancy_limit_warps',
    }
    raw = pd.DataFrame({**{label: [32, None, 7, None] for label in pairs},
                        **{metric: [99, 16, 99, None] for metric in pairs.values()}})
    path = tmp_path / 'wide.csv'
    bridge['build_wide_ncu_csv'](raw, path, 'GB200')
    output = pd.read_csv(path)
    for column in pairs:
        assert output[column].iloc[:3].tolist() == [32, 16, 7]
        assert pd.isna(output[column].iloc[3])


@pytest.mark.parametrize('target', ['', 'H100'])
def test_incomplete_rows_and_target_filter_align_src_and_ipc(tmp_path, target):
    pd = pytest.importorskip('pandas')
    import runpy
    bridge = runpy.run_path(str(ROOT / 'scripts/estimation/prepare_gpu_mlp_ncu_input.py'))
    columns = bridge['SOURCE_SPEC_COLUMNS']
    source = pd.DataFrame({
        'Kernel Name': ['same'] * 4, 'Duration [ns]': [100] * 4,
        'Block Size': [128] * 4,
        'Memory Throughput [byte/s]': [None, 1000, 'invalid', 2000],
        **{column: [1, 2, 3, 4] for column in columns},
    })
    prepared = pd.DataFrame({'Kernel Name': ['same'] * 2, 'src_gpu': ['GB200'] * 2,
                             'tgt_gpu': ['A100', 'H100'],
                             'Executed Ipc Active [inst/cycle]': [99, 99],
                             **{'SRC ' + c: [99, 99] for c in columns}})
    path = tmp_path / 'prepared.csv'
    prepared.to_csv(path, index=False)
    raw = pd.DataFrame({'sm__inst_executed.avg.per_cycle_active': [10, None, 30, 40],
                        'TPC.TriageCompute.sm__inst_executed_realtime.avg.per_cycle_active': [99, 20, 99, 99]})
    output = tmp_path / 'final.csv'
    bridge['finalize_prepared_input'](path, raw, output, set(), target, source)
    result = pd.read_csv(output)
    expected = [4] if target else [2, 4]
    for column in columns:
        assert result['SRC ' + column].tolist() == expected
    assert result['Executed Ipc Active [inst/cycle]'].tolist() == [v * 10 for v in expected]


def test_lightgbm_names_preserve_observations_and_convert_instruction_counts(tmp_path):
    pd = pytest.importorskip('pandas')
    import csv
    import sys
    raw = pd.DataFrame({
        'ID': range(4), 'Process ID': [1] * 4, 'Kernel Name': ['a', 'b', 'c', 'd'],
        'Achieved Occupancy': [7, None, None, None],
        'sm__warps_active.avg.pct_of_peak_sustained_active': [99, 12, None, None],
        'Executed Ipc Active [inst/cycle]': [3, None, None, None],
        'sm__inst_executed.avg.per_cycle_active': [99, 4, None, None],
        'Max Cluster Size [block]': [2, None, None, None],
        'launch__cluster_max_potential_size': [99, 8, None, None],
        'Block Limit Barriers [block]': [16, None, None, None],
        'launch__occupancy_limit_barriers': [99, 32, None, None],
        'Warp Cycles Per Executed Instruction [cycle/inst]': [5, None, None, None],
        'smsp__average_warp_latency_per_inst_issued.ratio': [99, 10, 10, 10],
        'smsp__inst_issued.sum': [100, 120, 100, None],
        'smsp__inst_executed.sum': [100, 100, 0, 100],
    })
    path = tmp_path / 'raw.csv'
    raw.to_csv(path, index=False, quoting=csv.QUOTE_ALL)
    out = tmp_path / 'wide.csv'
    subprocess.run([sys.executable, str(ROOT / 'scripts/estimation/prepare_gpu_lightgbm_ncu_input.py'),
                    '--raw-csv', str(path), '--out-csv', str(out)], check=True)
    wide = pd.read_csv(out)
    for column, expected in {
        'Achieved Occupancy': [7, 12],
        'Executed Ipc Active [inst/cycle]': [3, 4],
        'Max Cluster Size [block]': [2, 8],
        'Block Limit Barriers [block]': [16, 32],
        'Warp Cycles Per Executed Instruction [cycle/inst]': [5, 12],
    }.items():
        assert wide[column].iloc[:2].tolist() == expected
        assert wide[column].iloc[2:].isna().all()
    assert wide['Kernel Name'].tolist() == ['a', 'b', 'c', 'd']
    assert wide['smsp__average_warp_latency_per_inst_issued.ratio'].tolist() == [99, 10, 10, 10]


def test_lightgbm_v11_records_actual_bundle_adapter_and_evidence(repo, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    names = ['LightGBM_model/1.1/AI_model/run_inference.py',
             'LightGBM_model/1.1/extract_features.py',
             'LightGBM_model/1.1/AI_model/model/lgbm_Execution_Time.txt',
             'LightGBM_model/1.1/AI_model/model/feature_names.pkl',
             'LightGBM_model/1.1/AI_model/model/clean_map.pkl', 'data/gpu_microarch_specs.csv']
    for name in names:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    prediction = tmp_path / 'prediction.csv'
    prediction.write_text('prediction')
    for suffix in ['.input.csv', '.features.csv', '.validation.json']:
        Path(str(prediction) + suffix).write_text('{}' if suffix == '.validation.json' else suffix)
    data = provenance.make_manifest(str(repo), 'lightgbm', 'run_inference.py',
                                    'prepared_csv', '', str(prediction), 'main', '',
                                    'GB200', 'H100', model_version='1.1')
    assert set(names) == {f['path'] for f in data['external_inference']['files']}
    assert data['external_inference']['missing_files'] == []
    assert data['adapter']['group_by_config'] is True
    assert data['adapter']['sha256'] == provenance.digest(ROOT / data['adapter']['path'])
    assert {i['role'] for i in data['inputs']} == {
        'prediction_csv', 'normalized_input', 'inference_features', 'feature_validation'}
