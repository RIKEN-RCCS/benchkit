"""Prepare SBD-specific values for the common Estimate writer; Python 3.11+."""
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

from aggregate_davidson import aggregate, load_trace


def prepare(result_path, sqlite_path, predictions_path, samples_path, target_system):
    paths = dict(result=result_path, nsys=sqlite_path, predictions=predictions_path,
                 samples=samples_path)
    digests = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}
    result = json.loads(result_path.read_text())
    samples = json.loads(samples_path.read_text())
    predictions = json.loads(predictions_path.read_text())
    if str(result.get('code', '')).lower() != 'sbd':
        raise ValueError('Require an SBD Result')
    if result.get('FOM_unit') != 's' or result.get('FOM_version') != 'davidson_internal_s':
        raise ValueError('Require the internal Davidson seconds FOM')
    fom = float(result['FOM'])
    if not math.isfinite(fom) or fom <= 0:
        raise ValueError('Invalid Result FOM')
    if str(result.get('node_count')) != '1' or str(result.get('numproc_node')) != '1':
        raise ValueError('Only a one-node, one-rank Result is supported')
    if not result.get('system') or not result.get('Exp') or not target_system.strip():
        raise ValueError('Require source system, experiment and target system')
    if samples['scope'].get('source_result_sha256') != digests['result']:
        raise ValueError('Declare the corresponding Result digest in sample scope')
    label = samples['scope']['nvtx_range']
    if not re.fullmatch(r'sbdiag\.h:\d+ \[diag\] : Davidson', label):
        raise ValueError('Require the raw outer Davidson NVTX range')
    trace = load_trace(sqlite_path, label)
    projection = aggregate(trace, predictions, samples)
    projection['input_sha256'] = digests
    projected_fom = fom * projection['time_ratio_predicted_over_source']
    if not math.isfinite(projected_fom) or projected_fom <= 0:
        raise ValueError('Invalid projected Result FOM')
    if not predictions.get('model') or not predictions.get('estimation_package'):
        raise ValueError('Require recorded prediction model and package provenance')
    model = dict(type='cross_system_projection_model', name=projection['method'],
                 version='1', projection=projection)
    state = dict(est_current_system=result['system'], est_future_system=target_system,
                 est_current_fom=fom, est_future_fom=projected_fom,
                 est_current_target_nodes='1', est_future_target_nodes='1',
                 est_current_scaling_method='identity',
                 est_future_scaling_method=projection['method'],
                 est_future_model_json=model,
                 est_estimation_package='sbd_davidson_nsys_weighted',
                 est_estimation_package_version='1',
                 est_requested_estimation_package='sbd_davidson_nsys_weighted',
                 est_requested_estimation_package_version='1',
                 est_current_estimation_package='identity',
                 est_requested_current_estimation_package='identity',
                 est_method_class='cross_system_projection', est_detail_level='section',
                 est_measurement_json=dict(result_fom_seconds=fom,
                     nsys_davidson_wall_seconds=trace['wall_ns']/1e9,
                     source_gpu=samples['source_gpu'], target_gpu=samples['target_gpu']),
                 est_input_artifacts_json=[dict(kind=k, path=str(p), sha256=digests[k])
                                           for k, p in paths.items()],
                 est_applicability_json=dict(status='applicable', missing_inputs=[]),
                 est_assumptions_json=projection['assumptions'] + [
                     'NSYS Davidson ratio applies to the corresponding internal Davidson FOM',
                     'Source Result association is explicitly declared by the caller'],
                 est_notes_json=dict(status='conditional_projection',
                     limitations=projection['limitations'], accuracy_verified=False))
    for side in ('current', 'future'):
        for key, value in dict(system=result['system'], fom=fom, nodes='1',
                               numproc_node='1', timestamp='', uuid='').items():
            state[f'est_{side}_bench_{key}'] = value
    # The common writer resolves genuine server identity from the Result; never invent it.
    for key, p in paths.items():
        if hashlib.sha256(p.read_bytes()).hexdigest() != digests[key]:
            raise ValueError('Input changed while preparing Estimate')
    return state


if __name__ == '__main__':
    try:
        if len(sys.argv) != 6:
            raise ValueError('Expected Result, SQLite, predictions, samples and target system')
        state = prepare(*(Path(p) for p in sys.argv[1:5]), sys.argv[5])
        print(json.dumps(state, allow_nan=False))
    except (ValueError, KeyError, TypeError, IndexError, OSError, sqlite3.Error) as exc:
        sys.exit(f'SBD Estimate unavailable: {exc}')
