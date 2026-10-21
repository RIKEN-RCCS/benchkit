#!/usr/bin/env python3
"""Record external inference inputs without loading model serialization formats."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def git(root, *args):
    top = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(root).resolve():
        return None
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def public_repo(value):
    if not value:
        return None
    if '://' in value:
        url = urlsplit(value)
        host = url.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        if url.port:
            host += ':' + str(url.port)
        return urlunsplit((url.scheme, host, url.path, '', ''))
    if value.startswith('git@'):
        return value.split('@', 1)[1].replace(':', '/', 1)
    return None  # Local paths and arbitrary user strings are not published.


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def record_files(root, patterns):
    files = []
    missing = []
    for pattern in patterns:
        matches = sorted(p for p in root.glob(pattern) if p.is_file())
        if not matches:
            missing.append(pattern)
        for path in matches:
            files.append({'path': str(path.relative_to(root)), 'sha256': digest(path)})
    return files, missing


def make_manifest(root, version, predictor, mode, input_csv, prediction_csv, requested_ref, pin, source_gpu="", target_gpu="", row="all", model_version="1.0"):
    repo_root = Path(root) if root else None
    data = {'schema_version': 1, 'input_mode': mode, 'external_inference': None,
            'preprocessing': None, 'inputs': []}
    if mode != 'precomputed_prediction':
        data['inference_parameters'] = ({'source_gpu': source_gpu or None, 'target_gpu': target_gpu or None}
                                        if version in ('lightgbm', 'mlp455', 'pinn325') else {'row': row})
    for role, value in [('input_csv', input_csv), ('prediction_csv', prediction_csv)]:
        if value and Path(value).is_file():
            data['inputs'].append({'role': role, 'sha256': digest(Path(value))})
    if mode != 'precomputed_prediction' and repo_root:
        if version == 'lightgbm':
            patterns = [f'LightGBM_model/{model_version}/AI_model/run_inference.py',
                        f'LightGBM_model/{model_version}/extract_features.py',
                        f'LightGBM_model/{model_version}/AI_model/model/lgbm_*.txt',
                        f'LightGBM_model/{model_version}/AI_model/model/feature_names.pkl',
                        f'LightGBM_model/{model_version}/AI_model/model/clean_map.pkl']
            # Include the actual hardware table selected by the upstream entrypoint.
            patterns += ['data/gpu_microarch_specs.csv']
        elif version in ('mlp455', 'pinn325'):
            family, release, core = ('MLP_NN', 'v4.55', 'mlpnn_core.py') if version == 'mlp455' else ('PINN', 'v3.25', 'pinn_core.py')
            patterns = [f'{family}/{predictor}', f'{family}/network.py', f'{family}/{core}',
                        f'{family}/data_pipeline_v2.py',
                        f'{family}/{release}/meta.pkl', f'{family}/{release}/runtime_inputs_training.csv',
                        'examples/kernel_inputs/prepare_data.py', 'data/v4/gpu_microarch_specs.csv']
            patterns += [f'{family}/{release}/model_seed{i}.pt' for i in range(5 if version == 'mlp455' else 3)]
            if version == 'pinn325':
                patterns += ['PINN/v3.25/trust_anchor.json']
        else:
            patterns = [f'MLP_NN/{version}/{predictor}', 'MLP_NN/v1.5/v15_core.py']
            if version == 'v4.1':
                patterns += ['MLP_NN/v4.1/v40_core.py', 'MLP_NN/v4.1/v41_artifact/*']
            else:
                patterns += ['MLP_NN/v1.5/v15_artifact/*']
        if mode == 'ncu_archive' and version not in ('lightgbm', 'mlp455', 'pinn325'):
            patterns += ['MLP_NN/examples/prepare_data.py', 'data/gpu_microarch_specs.csv']
        files, missing = record_files(repo_root, patterns)
        dirty = git(repo_root, 'status', '--porcelain', '--untracked-files=all')
        commit = git(repo_root, 'rev-parse', 'HEAD')
        if pin and (dirty is None or dirty or not commit or commit.lower() != pin.lower()):
            raise SystemExit('Pinned PerfTools checkout changed during inference')
        if version in ('mlp455', 'pinn325') and missing:
            raise ValueError('Current PerfTools model dependencies are missing: ' + ', '.join(missing))
        data['external_inference'] = {
            'repository': public_repo(git(repo_root, 'remote', 'get-url', 'origin')),
            'requested_ref': requested_ref, 'resolved_commit': commit,
            'requested_commit': pin or None, 'dirty': None if dirty is None else bool(dirty),
            'files': files, 'missing_files': missing,
            'file_scope': 'inference dependency bundle; may include unused GPU weights',
        }
    if version == 'lightgbm' and model_version == '1.1' and mode != 'precomputed_prediction':
        adapter = Path('scripts/estimation/run_gpu_lightgbm_v11.py')
        data['adapter'] = {'path': str(adapter), 'sha256': digest(adapter), 'group_by_config': True,
                           'aggregation': 'representative_sample_time_ratio'}
        validation_path = Path(prediction_csv + '.validation.json')
        if validation_path.is_file():
            validation = json.loads(validation_path.read_text())
            data['adapter']['sampling'] = validation.get('sampling')
        for suffix, role in [('.features.csv', 'inference_features'), ('.input.csv', 'normalized_input'), ('.validation.json', 'feature_validation')]:
            path = Path(prediction_csv + suffix)
            if path.is_file():
                data['inputs'].append({'role': role, 'sha256': digest(path)})
    if version in ('mlp455', 'pinn325'):
        dependencies = ['scripts/estimation/' + name for name in
                        ['run_gpu_neural.py', 'run_gpu_lightgbm_v11.py', 'prepare_gpu_lightgbm_ncu_input.py',
                         'prepare_gpu_mlp_ncu_input.py', 'perftools_provenance.py']]
        data['preprocessing'] = {'benchkit_commit': git(Path('.'), 'rev-parse', 'HEAD'),
                                 'spec_supplements': [],
                                 'spec_policy': 'upstream input generator representatives and release runtime inputs',
                                 'files': record_files(Path('.'), dependencies)[0]}
    elif mode == 'ncu_archive':
        script = 'prepare_gpu_lightgbm_ncu_input.py' if version == 'lightgbm' else 'prepare_gpu_mlp_ncu_input.py'
        path = Path('scripts/estimation') / script
        data['preprocessing'] = {'benchkit_commit': git(Path('.'), 'rev-parse', 'HEAD'),
                                 'path': str(path), 'sha256': digest(path),
                                 'spec_supplements': [] if version == 'lightgbm' else None}
        dependencies = [str(path)]
        if version == 'lightgbm':
            dependencies.append('scripts/estimation/prepare_gpu_mlp_ncu_input.py')
        data['preprocessing']['files'], _ = record_files(Path('.'), dependencies)
        sidecar = Path(input_csv + '.preprocessing.json')
        if sidecar.is_file():
            data['preprocessing']['spec_supplements'] = json.loads(sidecar.read_text())
    return data


def main():
    parser = argparse.ArgumentParser()
    for name in ['root', 'version', 'predictor', 'mode', 'input-csv', 'prediction-csv', 'requested-ref', 'pin', 'output', 'source-gpu', 'target-gpu', 'row']:
        parser.add_argument('--' + name, default='')
    parser.add_argument("--model-version", choices=["1.0", "1.1"], default="1.0")
    args = parser.parse_args()
    manifest = make_manifest(args.root, args.version, args.predictor, args.mode,
                             args.input_csv, args.prediction_csv, args.requested_ref, args.pin, args.source_gpu, args.target_gpu, args.row or "all", args.model_version)
    contents = json.dumps(manifest, sort_keys=True, indent=2) + '\n'
    manifest_sha = hashlib.sha256(contents.encode()).hexdigest()
    target = Path(args.output)
    path = target.with_name(target.stem + '.' + manifest_sha + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    print(json.dumps({'manifest': str(path), 'sha256': digest(path),
                      'input_mode': args.mode, 'external_commit':
                      (manifest['external_inference'] or {}).get('resolved_commit')}))


if __name__ == '__main__':
    main()
