"""Recorded conditions for selected results, without scientific equivalence claims."""
from itertools import combinations
import json

from utils.result_records import input_info_items_for_result


def _state(values):
    known = [value for value in values if value not in (None, '', (), [])]
    different = known and any(value != known[0] for value in known)
    if different:
        return 'recorded difference' if len(known) == len(values) else 'recorded difference (incomplete evidence)'
    if len(known) != len(values):
        return 'insufficient evidence'
    return 'recorded match'


def _arguments(data):
    items = input_info_items_for_result(data)
    # A partial set of observed inputs cannot establish an input relationship.
    if not items or any(not isinstance(item, dict) or item.get('collection_status') == 'unavailable'
                        for item in items):
        return None
    signatures = []
    for item in items:
        args = item.get('arguments')
        if (item.get('kind') != 'runtime-parameters' or not isinstance(args, list) or not args
                or any(not isinstance(arg, (str, int)) or isinstance(arg, bool)
                       or not str(arg).strip() or '$' in str(arg) for arg in args)):
            return None
        # Dataset and parameter-set names differ across producers. Compare the
        # recorded argument content only; this is a candidate, not input identity.
        signatures.append(tuple(str(arg) for arg in args))
    return tuple(sorted(signatures))


def build_condition_evidence(results):
    data = [row.get('data') or {} for row in results]
    if len(data) < 2:
        return {'conditions': [], 'relationships': []}
    fields = [('Code', 'code'), ('System', 'system'), ('Nodes', 'node_count'), ('MPI ranks per node', 'numproc_node'),
              ('Threads per rank', 'nthreads'), ('FOM definition', 'FOM_version'), ('FOM unit', 'FOM_unit')]
    conditions = []
    for label, key in fields:
        values = [str(d.get(key)).strip() if d.get(key) not in (None, '') else None for d in data]
        # The legacy generic FOM label does not identify a measurement interval.
        if key == 'FOM_version':
            values = [None if v and ('figure of merit' in v.lower() or v.lower() == 'fom') else v for v in values]
        conditions.append({'label': label, 'status': _state(values),
                           'values': [v or 'not recorded' for v in values]})
    sources = [d.get('source_info') if isinstance(d.get('source_info'), dict) else {} for d in data]
    commits = [s.get('resolved_commit') or s.get('commit_hash') for s in sources]
    conditions.append({'label': 'Source commit', 'status': _state(commits),
                       'values': [c or 'not recorded' for c in commits]})
    builds = [json.dumps(d.get('build'), sort_keys=True) if isinstance(d.get('build'), dict) and d['build'] else None for d in data]
    conditions.append({'label': 'Build record', 'status': _state(builds),
                       'values': ['recorded' if v else 'not recorded' for v in builds]})
    relationships = []
    for a, b in combinations(range(len(data)), 2):
        left, right = data[a], data[b]
        args = [_arguments(left), _arguments(right)]
        same_context = (left.get('code') and left.get('system')
                        and left.get('code') == right.get('code') and left.get('system') == right.get('system'))
        state = _state(args)
        if not same_context:
            state = ('different code/system' if all(d.get('code') and d.get('system') for d in (left, right))
                     else 'insufficient evidence')
        relationships.append({'left': a + 1, 'right': b + 1,
            'left_exp': left.get('Exp') or 'not recorded', 'right_exp': right.get('Exp') or 'not recorded',
            'status': 'related input candidate' if state == 'recorded match' else state})
    return {'conditions': conditions, 'relationships': relationships}


def find_related_candidates(selected, records):
    """Suggest cross-name records with observed input arguments, never rewrite them."""
    candidates = []
    insufficient = 0
    different = 0
    selected_names = {r.get('filename') for r in selected}
    seen = set()
    for other in records:
        if other.get('filename') in selected_names:
            continue
        for row in selected:
            left, right = row.get('data') or {}, other.get('data') or {}
            if (not left.get('code') or not left.get('system')
                    or left.get('code') != right.get('code') or left.get('system') != right.get('system')
                    or not left.get('Exp') or not right.get('Exp') or left['Exp'] == right['Exp']):
                continue
            state = _state([_arguments(left), _arguments(right)])
            if state == 'recorded match' and other['filename'] not in seen:
                seen.add(other['filename'])
                candidates.append({'filename': other['filename'], 'exp': right['Exp'],
                    'selected_filename': row['filename'], 'timestamp': other.get('timestamp') or other['filename'],
                    'status': 'related input candidate'})
            elif state == 'insufficient evidence':
                insufficient += 1
            elif state == 'recorded difference':
                different += 1
    return {'candidates': candidates[:20], 'candidate_count': len(candidates),
            'insufficient_pairs': insufficient, 'different_pairs': different}
