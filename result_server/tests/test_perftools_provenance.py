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


def ensure(root, source, ref, pin='', fetch=False, cache=None):
    env = dict(os.environ, BK_PERFTOOLS_CACHE_DIR=str(cache or source.parent / 'cache'))
    return subprocess.run(['bash', '-c', 'source "$1"; bk_perftools_ensure_root "$2" "$3" "$4" "$5" "$6"',
                           'fixture', str(ROOT / 'scripts/estimation/section_packages/perftools_common.sh'),
                           str(root) if root else '', str(source), ref, pin, str(fetch).lower()],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_checkout_fixed_and_dirty_rejected(repo):
    sha = run_git(repo, 'rev-parse', 'HEAD')
    assert ensure(repo, repo, 'not-the-current-ref', sha).returncode == 0
    assert ensure(repo, repo, 'main', '0' * 40).returncode != 0
    (repo / 'file').write_text('changed')
    assert ensure(repo, repo, 'main', sha).returncode != 0
    assert ensure(repo, repo, 'main').returncode == 0  # Record-only use remains supported.
    assert ensure(repo, repo, 'main', 'short-sha').returncode != 0


def test_local_ref_resolution_commit_cache_and_failure(repo):
    branch = run_git(repo, 'symbolic-ref', '--short', 'HEAD')
    sha = run_git(repo, 'rev-parse', 'HEAD')
    result = ensure(None, repo, 'refs/heads/' + branch, fetch=True)
    assert result.returncode == 0, result.stderr
    checkout = Path(result.stdout.strip())
    assert checkout.name == sha
    assert run_git(checkout, 'rev-parse', 'HEAD') == sha
    assert ensure(None, repo, 'missing-ref', fetch=True).returncode != 0
    assert ensure(None, repo, branch, pin='0' * 40, fetch=True).returncode != 0
    assert ensure(None, repo, branch, pin=sha, fetch=False).returncode != 0
    (checkout / 'file').write_text('cache modified')
    assert ensure(None, repo, branch, fetch=True).returncode != 0


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
    column = 'SRC GPU Maximum Warps Per Scheduler [warp]'
    frame = MagicMock()
    frame.columns = ['src_gpu', column]
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
               BK_GPU_MLP_PERFTOOLS_ROOT=str(repo), BK_GPU_MLP_PERFTOOLS_COMMIT='0' * 40,
               BK_GPU_MLP_INPUT_CSV=str(csv), BK_GPU_MLP_ARTIFACT_MODE='input')
    result = subprocess.run(['bash', '-c', '''source scripts/estimation/packages/top_level_package_common.sh
bk_top_level_dispatch_bound_item '{"name":"gpu","time":1,"estimation_package":"gpu_kernel_mlp_v15"}' 1 1 1 section ""
'''], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'checkout does not match' in result.stderr
    assert not result.stdout.strip()


def test_annotated_tag_resolves_to_commit(repo):
    run_git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'tag', '-a', 'release', '-m', 'release')
    result = ensure(None, repo, 'refs/tags/release', fetch=True)
    assert result.returncode == 0, result.stderr
    assert run_git(Path(result.stdout.strip()), 'rev-parse', 'HEAD') == run_git(repo, 'rev-parse', 'HEAD')


def test_ncu_preparation_supplements_and_shared_lightgbm_bridge(tmp_path):
    pytest.importorskip('pandas', reason='NCU preparation uses the optional inference dependency')
    import sys
    raw = tmp_path / 'raw.csv'
    raw.write_text('"ID","Process ID","Kernel Name","gpu__time_duration.sum"\n0,1,"fixture",1000\n')
    tool = tmp_path / 'tool/MLP_NN/examples'
    tool.mkdir(parents=True)
    (tool / 'prepare_data.py').write_text(
        'import sys,csv\np=sys.argv[sys.argv.index("--out")+1]\n'
        'with open(p,"w") as f:\n w=csv.writer(f);'
        'w.writerow(["src_gpu","tgt_gpu","SRC GPU Maximum Warps Per Scheduler [warp]",'
        '"TGT Shared Memory Configuration Size [byte]"]);w.writerow(["H100","A100","",7])\n')
    output = tmp_path / 'input.csv'
    subprocess.run([sys.executable, str(ROOT / 'scripts/estimation/prepare_gpu_mlp_ncu_input.py'),
                    '--raw-csv', str(raw), '--perftools-root', str(tmp_path / 'tool'),
                    '--out-csv', str(output), '--target-gpu', 'A100'], check=True)
    details = json.loads(Path(str(output) + '.preprocessing.json').read_text())
    assert details['spec_supplements'] == [
        {'row': 0, 'gpu': 'H100', 'column': 'SRC GPU Maximum Warps Per Scheduler [warp]', 'value': 16}]
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
