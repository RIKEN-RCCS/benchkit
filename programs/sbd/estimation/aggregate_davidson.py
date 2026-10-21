#!/usr/bin/env python3
"""Conditional SBD Davidson projection from NSYS weights and sampled predictions.

Offline, explicit opt-in: never launches profilers or changes a benchmark Result.
Python 3.11+; standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

FAMILIES = ("MultAlphaBeta", "MultUnified<0,1>", "MultUnified<1,1>",
            "MultUnified<1,0>", "MultUnified<0,0>")


def family(name):
    # Match the observed fully qualified/unqualified SBD demangler forms only.
    text = re.sub(r"\s+", "", name)
    prefix = r"(?:void)?(?:sbd::)?tpb_for_each_n_kernel<(?:sbd::)?"
    if re.fullmatch(prefix + r"MultAlphaBeta<double>>\(.+\)", text):
        return FAMILIES[0]
    match = re.fullmatch(prefix + r"MultUnified<double,(?:\(int\))?([01]),"
                         r"(?:\(int\))?([01])>>\(.+\)", text)
    return f"MultUnified<{match[1]},{match[2]}>" if match else None


def kernel_signature(name):
    # Normalize only the observed SBD wrapper and its two boolean int arguments.
    # Preserve the complete function argument list and all other type spelling.
    text = re.sub(r"\s+", "", name)
    match = re.fullmatch(
        r"(?:void)?(?:sbd::)?tpb_for_each_n_kernel<(?:sbd::)?"
        r"(MultAlphaBeta<double>|MultUnified<double,(?:\(int\))?[01],"
        r"(?:\(int\))?[01]>)>\((.+)\)", text)
    if match is None:
        return None
    return re.sub(r"\(int\)", "", match[1]), match[2]


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
        rows = [dict(r) for r in db.execute("SELECT * FROM NVTX_EVENTS")]
        ranges = [r for r in rows if r['domainId'] == 0 and r['end'] is not None
                  and (r['text'] if r['text'] is not None else strings.get(r['textId'])) == label]
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
    weights = {}
    for k in trace['kernels']:
        f = family(k['name'])
        if f:
            weights.setdefault(f, []).append(k)
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
        if family(row['name']) != f or kernel_signature(row['name']) != kernel_signature(name):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nsys-sqlite', required=True, type=Path)
    parser.add_argument('--nvtx-range', required=True)
    parser.add_argument('--predictions', required=True, type=Path,
                        help='Parsed LightGBM 1.1 JSON containing metrics.kernels')
    parser.add_argument('--samples', required=True, type=Path,
                        help='Explicit association of NCU samples with this NSYS scope')
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'sbdiag\.h:\d+ \[diag\] : Davidson', args.nvtx_range):
            raise ValueError('Require the raw Davidson NVTX range, excluding post-Davidson mult')
        trace = load_trace(args.nsys_sqlite, args.nvtx_range)
        result = aggregate(trace, json.loads(args.predictions.read_text()),
                           json.loads(args.samples.read_text()))
        result['input_sha256'] = {key: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for key, p in (('predictions', args.predictions),
                                                 ('samples', args.samples))}
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, KeyError, TypeError, IndexError, sqlite3.Error, OSError) as exc:
        parser.exit(2, f'SBD Davidson projection unavailable: {exc}\n')


if __name__ == '__main__':
    main()
