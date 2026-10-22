#!/usr/bin/env python3
"""Conditional SBD Davidson projection from NSYS weights and sampled predictions.

Offline, explicit opt-in: never launches profilers or changes a benchmark Result.
Python 3.11+; standard library only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import tarfile

FAMILIES = ("MultAlphaBeta", "MultUnified<0,1>", "MultUnified<1,1>",
            "MultUnified<1,0>", "MultUnified<0,0>")


def kernel_signature(name):
    # Only known SBD namespace/cast spellings; keep the complete argument list.
    match = re.fullmatch(
        r"(?:void)?(?:sbd::)?tpb_for_each_n_kernel<(?:sbd::)?"
        r"(?:MultAlphaBeta<double>|MultUnified<double,(?:\(int\))?([01]),"
        r"(?:\(int\))?([01])>)>\((.+)\)", re.sub(r"\s+", "", name))
    if match is None:
        return None
    family = f"MultUnified<{match[1]},{match[2]}>" if match[1] else FAMILIES[0]
    return family, match[3]


def family(name):
    signature = kernel_signature(name)
    return signature[0] if signature else None


def union_time(spans):
    total = 0
    end = None
    for a, b in sorted(spans):
        if b <= a:
            raise ValueError("Invalid event interval")
        total += max(0, b - max(a, end if end is not None else a))
        end = max(b, end if end is not None else b)
    return total


def positive(value, label, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Missing numeric {label}")
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"Invalid {label}")
    return value


def load_trace(path, label):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        strings = dict(db.execute("SELECT id,value FROM StringIds"))
        ranges = db.execute(
            "SELECT n.start, n.end, n.globalTid FROM NVTX_EVENTS n "
            "LEFT JOIN StringIds s ON s.id = n.textId "
            "WHERE n.domainId = 0 AND n.end IS NOT NULL "
            "AND COALESCE(n.text, s.value) = ?", (label,)).fetchall()
        if len(ranges) != 1:
            raise ValueError("Require exactly one default-domain Davidson range")
        scope = ranges[0]
        a, b, tid = scope['start'], scope['end'], scope['globalTid']
        if b <= a:
            raise ValueError("Invalid Davidson interval")
        kernels = [dict(r) for r in db.execute("SELECT * FROM CUPTI_ACTIVITY_KIND_KERNEL")]
        apis = {}
        for row in db.execute("SELECT * FROM CUPTI_ACTIVITY_KIND_RUNTIME"):
            apis.setdefault(row['correlationId'], []).append(dict(row))
        pids = {r['globalPid'] for r in kernels}
        if len(pids) != 1 or next(iter(pids)) != ((tid >> 24) << 24):
            raise ValueError("Require a single profiled process matching the NVTX thread")
        inside = []
        for k in kernels:
            matches = apis.get(k['correlationId'], [])
            if len(matches) != 1:
                raise ValueError("Ambiguous or missing kernel launch origin")
            api = matches[0]
            launched_inside = (api['globalTid'] == tid and a <= api['start']
                               and api['end'] <= b)
            overlaps = k['start'] < b and k['end'] > a
            if launched_inside and not (a <= k['start'] < k['end'] <= b):
                raise ValueError("Kernel crosses Davidson boundary")
            if overlaps and not launched_inside:
                raise ValueError("External kernel overlaps Davidson")
            if launched_inside:
                k['name'] = strings[k['demangledName']]
                inside.append(k)
        if len({k['deviceId'] for k in inside}) != 1:
            raise ValueError('Require one profiled GPU inside Davidson')
        spans = [(k['start'], k['end']) for k in inside]
        kernel_sum = sum(y-x for x, y in spans)
        if union_time(spans) != kernel_sum:
            raise ValueError("Overlapping kernels need a different projection model")
        memory = []
        for table in ('CUPTI_ACTIVITY_KIND_MEMCPY', 'CUPTI_ACTIVITY_KIND_MEMSET'):
            for row in db.execute('SELECT * FROM ' + table):
                if row['globalPid'] != next(iter(pids)):
                    raise ValueError("Mixed-process memory events")
                x, y = max(a, row['start']), min(b, row['end'])
                if y > x:
                    memory.append((x, y))
        mem_union = union_time(memory)
        gpu_union = union_time(spans + memory)
        if gpu_union != kernel_sum + mem_union:
            raise ValueError("Kernel/transfer overlap needs a different projection model")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("SQLite changed during analysis")
    return dict(sha256=digest, label=label, start_ns=a, end_ns=b,
                wall_ns=b-a, kernels=inside, kernel_ns=kernel_sum,
                memory_union_ns=mem_union, gpu_union_ns=gpu_union)


def aggregate(trace, predictions, samples):
    scope = samples['scope']
    if (scope.get('nsys_sha256') != trace['sha256']
            or scope.get('nvtx_range') != trace['label']
            or type(scope.get('mpi_size')) is not int or scope['mpi_size'] != 1
            or type(scope.get('mpi_rank')) is not int or scope['mpi_rank'] != 0):
        raise ValueError("Sampling scope must match this SQLite and the one-rank Davidson range")
    # Source/target are required to avoid silently mixing different prediction pairs.
    source_gpu, target_gpu = samples['source_gpu'], samples['target_gpu']
    if not isinstance(source_gpu, str) or not source_gpu.strip() or not isinstance(target_gpu, str) or not target_gpu.strip():
        raise ValueError("Require source and target GPU names")
    rows = predictions['metrics']['kernels']
    signatures = {name: kernel_signature(name) for name in {k['name'] for k in trace['kernels']}}
    weights = {}
    for k in trace['kernels']:
        signature = signatures[k['name']]
        if signature:
            weights.setdefault(signature[0], []).append(k)
    if set(weights) != set(FAMILIES):
        raise ValueError("All five Davidson kernel families are required")
    plans = samples['samples']
    if len(plans) != 5 or {p['family'] for p in plans} != set(FAMILIES):
        raise ValueError("Require one representative sample for each of the five families")
    if len({p['prediction_index'] for p in plans}) != 5:
        raise ValueError("Prediction rows must not be reused")
    terms = []
    for plan in plans:
        f = plan['family']
        launches = sorted(weights[f], key=lambda k: k['start'])
        configs = {(k['name'], tuple(k[x] for x in ('gridX','gridY','gridZ')),
                    tuple(k[x] for x in ('blockX','blockY','blockZ'))) for k in launches}
        if len(configs) != 1:
            raise ValueError("Multiple signatures or Grid/Block configurations need separate samples")
        name, grid, block = next(iter(configs))
        index = plan['launch_index']
        if type(index) is not int or not 1 <= index < len(launches):
            raise ValueError("Select an available non-first launch (zero-based launch_index)")
        if tuple(plan['grid']) != grid or tuple(plan['block']) != block or plan['kernel_name'] != name:
            raise ValueError("Sample signature or Grid/Block does not match NSYS")
        row_index = plan['prediction_index']
        if type(row_index) is not int or not 0 <= row_index < len(rows):
            raise ValueError("Invalid prediction row index")
        row = rows[row_index]
        if kernel_signature(row['name']) != signatures[name]:
            raise ValueError("Prediction kernel signature mismatch")
        config = row['configuration']
        if config.get('grid_size') != math.prod(grid) or config.get('block_size') != math.prod(block):
            raise ValueError("Prediction execution configuration mismatch")
        if row.get('source_gpu') != source_gpu or row.get('target_gpu') != target_gpu:
            raise ValueError("Prediction GPU pair mismatch")
        if row.get('sample_count') != 1:
            raise ValueError("This minimal model requires one NCU launch per family")
        src = positive(row.get('source_time_ns'), 'source time')
        dst = positive(row.get('predicted_time_ns'), 'predicted time', zero=True)
        ratio = dst / src
        if 'time_ratio_predicted_over_source' in row and not math.isclose(
                ratio, positive(row['time_ratio_predicted_over_source'], 'ratio', zero=True), rel_tol=1e-9):
            raise ValueError("Prediction ratio disagrees with aligned source/target times")
        weight = sum(k['end'] - k['start'] for k in launches)
        terms.append(dict(family=f, kernel_name=name, grid=list(grid), block=list(block),
                          nsys_launch_count=len(launches), sample_count=1, launch_index=index,
                          prediction_index=row_index, source_kernel_time_ns=src,
                          predicted_kernel_time_ns=dst, ratio_predicted_over_source=ratio,
                          nsys_weight_ns=weight, predicted_weight_ns=weight*ratio))
    selected = sum(t['nsys_weight_ns'] for t in terms)
    residual = trace['wall_ns'] - selected
    if residual < 0:
        raise ValueError("Negative residual")
    projected = residual + sum(t['predicted_weight_ns'] for t in terms)
    return dict(schema_version=1, method='sbd-davidson-nsys-weighted-v1',
                status='conditional_projection', scope=scope, source_gpu=source_gpu,
                target_gpu=target_gpu, prediction_model=predictions.get('model'),
                prediction_package=predictions.get('estimation_package'),
                source_scope_interval_ns=[trace['start_ns'], trace['end_ns']],
                source_wall_time_ns=trace['wall_ns'],
                predicted_wall_time_ns=projected,
                time_ratio_predicted_over_source=projected/trace['wall_ns'],
                selected_kernel_time_ns=selected, residual_unchanged_ns=residual,
                selected_wall_coverage=selected/trace['wall_ns'],
                residual_components_ns=dict(unselected_kernels=trace['kernel_ns']-selected,
                    memory_event_union=trace['memory_union_ns'],
                    gpu_event_gaps=trace['wall_ns']-trace['gpu_union_ns']),
                host_wait_added_ns=0, terms=terms,
                assumptions=['Residual time unchanged on target',
                    'Representative launch ratio applies to all launches of its configuration',
                    'Execution structure and non-overlap preserved on target'],
                limitations=['One-rank observation; no MPI/other-rank prediction',
                    'Sample association is explicitly declared, not verified from raw NCU reports',
                    'No prediction accuracy or cross-system overlap validation'])



def davidson_plan(directory):
    # Reuse common display/raw-name resolution and plan generation.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/profiling'))
    from nvtx_plan import resolve_nsys_nvtx_scope
    from generate_ncu_plan import main as generate_plan
    discovery = json.loads((directory / 'discovery.json').read_text())
    scopes = {(r['range'], r['style'], r['process_id'], r['thread_id'])
              for r in discovery.get('nvtx', {}).get('associations', [])
              if re.fullmatch(r':?sbdiag\.h:\d+ \[diag\] : Davidson', r['range'])}
    if len(scopes) != 1:
        raise ValueError('Require one outer Davidson NVTX scope')
    label, style, pid, tid = next(iter(scopes))
    sqlite = directory / 'discovery.sqlite'
    scope = resolve_nsys_nvtx_scope(dict(range=label, style=style, process_id=pid,
                                        thread_id=tid), sqlite)
    trace = load_trace(sqlite, scope['range'])
    output = directory / 'davidson-plan.json'
    status = generate_plan(['--nsys-csv', str(directory / 'kernel-summary.csv'),
        '--nvtx-csv', str(directory / 'nvtx-summary.csv'), '--nvtx-sqlite', str(sqlite),
        '--nvtx-range', label, '--nvtx-process-id', pid, '--nvtx-thread-id', tid,
        '--top-k', '0', '--launch-count', '1', '--max-launch-skip', '1',
        '--out-plan', str(output)])
    if status:
        raise ValueError('Davidson plan generation failed')
    plan = json.loads(output.read_text())
    plan['profiles'] = [p for p in plan['profiles'] if family(p['kernel_name'])]
    # Check all families/configurations before spending time on NCU.
    make_samples(trace, plan, 'source', 'target')
    output.write_text(json.dumps(plan, indent=2) + '\n')
    return str(output)


def make_samples(trace, plan, source_gpu, target_gpu):
    profiles = plan['profiles']
    samples = dict(scope=dict(nsys_sha256=trace['sha256'], nvtx_range=trace['label'],
                             mpi_rank=0, mpi_size=1), source_gpu=source_gpu,
                   target_gpu=target_gpu, samples=[])
    rows = []
    for i, profile in enumerate(profiles):
        if (profile['nvtx']['range'] != trace['label']
                or profile['nvtx'].get('domain', 'default') != 'default'
                or profile['nvtx']['style'] != 'PushPop'
                or profile['launch_skip'] != 1 or profile['launch_count'] != 1):
            raise ValueError('Require Davidson-scoped second-launch samples')
        launches = [k for k in trace['kernels'] if k['name'] == profile['kernel_name']]
        if not launches:
            raise ValueError('Plan kernel missing from Davidson')
        k = launches[0]
        grid, block = ([k[prefix+a] for a in 'XYZ'] for prefix in ('grid', 'block'))
        samples['samples'].append(dict(family=family(k['name']), kernel_name=k['name'],
            grid=grid, block=block, launch_index=1, prediction_index=i))
        rows.append(dict(name=k['name'], configuration=dict(grid_size=math.prod(grid),
            block_size=math.prod(block)), source_gpu=source_gpu, target_gpu=target_gpu,
            sample_count=1, source_time_ns=1, predicted_time_ns=1))
    aggregate(trace, dict(metrics=dict(kernels=rows)), samples)
    return samples


def prepare_inputs(plan_path, profiles_dir, output, source_gpu, target_gpu):
    plan = json.loads(plan_path.read_text())
    trace = load_trace(plan_path.parent / 'discovery.sqlite', plan['profiles'][0]['nvtx']['range'])
    samples = make_samples(trace, plan, source_gpu, target_gpu)
    metadata = [(p, json.loads(p.read_text())) for p in profiles_dir.rglob('profile.metadata.json')]
    jobs = []
    for i, profile in enumerate(plan['profiles']):
        matches = [(p, m) for p, m in metadata if m.get('profile_name') == profile['name']]
        if len(matches) != 1:
            raise ValueError('Missing or duplicate NCU profile')
        path, meta = matches[0]
        selected = json.loads(meta['nsys_discovery_json'])
        if (selected['nvtx'] != profile['nvtx'] or selected['kernel_name'] != profile['kernel_name']
                or meta['ncu']['launch_skip'] != 1 or meta['ncu']['launch_count'] != 1
                or meta['ncu']['kernel_regex'] != profile['kernel_match']['pattern']):
            raise ValueError('NCU metadata does not match plan')
        archive = path.with_name('profile.tgz')
        # Inspect without extraction; validate full XYZ, not just the product.
        with tarfile.open(archive) as tar:
            members = [m for m in tar if m.isfile() and m.name.endswith('/profile_raw.csv')]
            if len(members) != 1:
                raise ValueError('Require one raw NCU CSV')
            lines = tar.extractfile(members[0]).read().decode('utf-8-sig').splitlines()
        header = next(j for j, line in enumerate(lines)
                      if {'ID', 'Kernel Name'} <= set(next(csv.reader([line]))))
        rows = [r for r in csv.DictReader(lines[header:]) if r.get('ID')]
        if len(rows) != 1 or kernel_signature(rows[0]['Kernel Name']) != kernel_signature(profile['kernel_name']):
            raise ValueError('Require one matching NCU launch')
        row = rows[0]
        for dimension in ('grid', 'block'):
            if [float(row['launch__'+dimension+'_dim_'+a].replace(',', '')) for a in 'xyz'] != samples['samples'][i][dimension]:
                raise ValueError('NCU Grid/Block mismatch')
        samples['samples'][i]['ncu_artifact'] = dict(
            path=str(archive.resolve()), sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            metadata_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        jobs.append(dict(archive=str(archive.resolve()), metadata=str(path.resolve()),
            item=dict(name='davidson_kernel_'+str(i), kernel_name=row['Kernel Name'],
                time=sum(k['end']-k['start'] for k in trace['kernels']
                         if k['name'] == profile['kernel_name']) / 1e9)))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'samples.json').write_text(json.dumps(samples, indent=2) + '\n')
    (output / 'jobs.json').write_text(json.dumps(jobs, indent=2) + '\n')


def combine_predictions(directory):
    results = [json.loads((directory / f'kernel_{i}.json').read_text()) for i in range(5)]
    if any(r['package_applicability']['status'] != 'applicable'
           or r['model']['version'] != '1.1' or len(r['metrics']['kernels']) != 1 for r in results):
        raise ValueError('Require five applicable LightGBM 1.1 predictions')
    commits = {r['model']['provenance']['external_commit'] for r in results}
    if len(commits) != 1 or not re.fullmatch(r'[0-9a-f]{40}', next(iter(commits))):
        raise ValueError('Require one resolved PerfTools commit across all five predictions')
    for r in results:
        provenance = r['model']['provenance']
        if hashlib.sha256(Path(provenance['manifest']).read_bytes()).hexdigest() != provenance['sha256']:
            raise ValueError('Prediction provenance manifest changed')
    return dict(estimation_package='gpu_kernel_lightgbm_v11',
        model=dict(name='PerfTools LightGBM_model/1.1', version='1.1', external_commit=next(iter(commits)),
                   component_provenance=[r['model']['provenance'] for r in results]),
        component_results=[dict(path=str(directory / f'kernel_{i}.json'),
            sha256=hashlib.sha256((directory / f'kernel_{i}.json').read_bytes()).hexdigest())
            for i in range(5)],
        metrics=dict(kernels=[r['metrics']['kernels'][0] for r in results]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-plan', type=Path)
    parser.add_argument('--prepare-inputs', type=Path)
    parser.add_argument('--profiles-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--source-gpu')
    parser.add_argument('--target-gpu')
    parser.add_argument('--combine', type=Path)
    parser.add_argument('--nsys-sqlite', type=Path)
    parser.add_argument('--nvtx-range')
    parser.add_argument('--predictions', type=Path,
                        help='Parsed LightGBM 1.1 JSON containing metrics.kernels')
    parser.add_argument('--samples', type=Path,
                        help='Explicit association of NCU samples with this NSYS scope')
    args = parser.parse_args()
    try:
        if args.prepare_plan:
            print(davidson_plan(args.prepare_plan))
            return
        if args.prepare_inputs:
            if not all((args.profiles_dir, args.output_dir, args.source_gpu, args.target_gpu)):
                raise ValueError('Require profiles directory, output directory and explicit GPU pair')
            prepare_inputs(args.prepare_inputs, args.profiles_dir, args.output_dir, args.source_gpu, args.target_gpu)
            return
        if args.combine:
            print(json.dumps(combine_predictions(args.combine), indent=2, allow_nan=False))
            return
        if not all((args.nsys_sqlite, args.nvtx_range, args.predictions, args.samples)):
            raise ValueError('Require SQLite, raw NVTX range, predictions and samples')
        if not re.fullmatch(r'sbdiag\.h:\d+ \[diag\] : Davidson', args.nvtx_range):
            raise ValueError('Require the raw Davidson NVTX range, excluding post-Davidson mult')
        trace = load_trace(args.nsys_sqlite, args.nvtx_range)
        result = aggregate(trace, json.loads(args.predictions.read_text()),
                           json.loads(args.samples.read_text()))
        result['input_sha256'] = {key: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for key, p in (('predictions', args.predictions),
                                                 ('samples', args.samples))}
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, KeyError, TypeError, IndexError, sqlite3.Error, OSError, StopIteration, tarfile.TarError) as exc:
        parser.exit(2, f'SBD Davidson projection unavailable: {exc}\n')


if __name__ == '__main__':
    main()
