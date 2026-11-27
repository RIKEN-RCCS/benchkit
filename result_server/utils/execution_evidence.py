"""Explicit, offline execution observations bound to recorded submissions."""

import json
import re
from datetime import datetime, timezone

from .execution_history import list_execution_history, summarize_execution_history
from .execution_profiles import ExecutionProfileStore

MAX_BYTES = 1024 * 1024
STATUSES = frozenset(('created', 'waiting_for_resource', 'preparing', 'pending',
    'running', 'success', 'failed', 'canceled', 'skipped', 'manual', 'scheduled'))
COMPUTE_STATUSES = frozenset(('unknown', 'queued', 'running', 'completed',
    'failed', 'canceled', 'timeout'))
PHASES = frozenset(('unknown', 'generation', 'build', 'submission', 'queue', 'compute', 'delivery'))
CURRENT = 'execution_evidence_current'
HISTORY = 'execution_evidence_history'


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('Invalid evidence fields')


def _text(value, limit=160):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid evidence text')
    return value


def _id(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError('Invalid evidence identifier')
    return value


def _time(value):
    _text(value, 40)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')
    except (ValueError, OverflowError):
        raise ValueError('Invalid observation time') from None


def _project(value):
    _text(value, 512)
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?(?:/[A-Za-z0-9_.-]+){2,}', value):
        raise ValueError('Host-qualified project required')
    if any(part in ('.', '..') for part in value.split('/')):
        raise ValueError('Invalid project')
    return value


def _choice(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError('Invalid evidence state')


def parse_evidence(raw):
    """Reject duplicate keys and unrestricted log/credential payloads."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError('Evidence exceeds input limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate evidence key')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        return validate_evidence(value)
    except (UnicodeError, RecursionError):
        raise ValueError('Invalid evidence document') from None


def validate_evidence(value):
    _fields(value, ('version', 'source', 'record_id', 'project', 'pipeline_id', 'observed_at', 'pipelines', 'jobs'))
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Unsupported evidence version')
    _choice(value['source'], ('manual', 'runner'))
    _id(value['record_id'])
    root = (_project(value['project']), _id(value['pipeline_id']))
    observed = _time(value['observed_at'])
    if not isinstance(value['pipelines'], list) or not 1 <= len(value['pipelines']) <= 128:
        raise ValueError('Invalid pipeline count')
    if not isinstance(value['jobs'], list) or len(value['jobs']) > 1024:
        raise ValueError('Invalid job count')
    graph = {}
    for pipeline in value['pipelines']:
        _fields(pipeline, ('project', 'id', 'parent', 'status'))
        key = (_project(pipeline['project']), _id(pipeline['id']))
        _choice(pipeline['status'], STATUSES)
        parent = pipeline['parent']
        if parent is not None:
            _fields(parent, ('project', 'id'))
            parent = (_project(parent['project']), _id(parent['id']))
        if key in graph:
            raise ValueError('Duplicate pipeline')
        graph[key] = parent
    if root not in graph or graph[root] is not None:
        raise ValueError('Submission root missing')
    for key in graph:
        seen = set()
        while key != root:
            if key in seen or key not in graph or graph[key] is None:
                raise ValueError('Unlinked pipeline')
            seen.add(key)
            key = graph[key]
    jobs = set()
    for job in value['jobs']:
        _fields(job, ('project', 'pipeline_id', 'id', 'name', 'stage', 'phase', 'status', 'compute'))
        project = _project(job['project'])
        key = (project, _id(job['id']))
        if key in jobs or (project, _id(job['pipeline_id'])) not in graph:
            raise ValueError('Duplicate or unlinked job')
        jobs.add(key)
        _text(job['name'])
        _text(job['stage'])
        _choice(job['phase'], PHASES)
        _choice(job['status'], STATUSES)
        compute = job['compute']
        if compute is not None:
            _fields(compute, ('scheduler', 'job_id', 'started', 'status', 'exit_code', 'source', 'observed_at'))
            _text(compute['scheduler'], 64)
            _text(compute['job_id'], 128)
            if compute['started'] is not None and type(compute['started']) is not bool:
                raise ValueError('Invalid start evidence')
            _choice(compute['status'], COMPUTE_STATUSES)
            if compute['exit_code'] is not None and (type(compute['exit_code']) is not int or not -(2**31) <= compute['exit_code'] < 2**31):
                raise ValueError('Invalid exit evidence')
            _choice(compute['source'], ('execution_record', 'runner_record', 'scheduler_record'))
            if _time(compute['observed_at']) > observed:
                raise ValueError('Compute observation follows snapshot')
            if compute['started'] is False and compute['status'] in ('running', 'completed'):
                raise ValueError('Contradictory start evidence')
            if compute['status'] in ('running', 'completed') and compute['started'] is not True:
                raise ValueError('Start evidence required')
            if compute['exit_code'] is not None and compute['started'] is not True:
                raise ValueError('Exit evidence requires a recorded start')
    # Copy the input: callers cannot mutate the stored observation through aliases.
    normalized = json.loads(json.dumps(value, allow_nan=False))
    normalized['observed_at'] = observed
    for job in normalized['jobs']:
        if job['compute'] is not None:
            job['compute']['observed_at'] = _time(job['compute']['observed_at'])
    normalized['pipelines'].sort(key=lambda item: (item['project'], item['id']))
    normalized['jobs'].sort(key=lambda item: (item['project'], item['id']))
    if len(json.dumps(normalized).encode()) > MAX_BYTES:
        raise ValueError('Evidence exceeds input limit')
    return normalized


def _key(source, record_id):
    _choice(source, ('manual', 'runner'))
    return f'{source}:{_id(record_id)}'


def matches(evidence, summary):
    return (summary['status'] == 'submitted' and not summary['dry_run']
        and evidence['source'] == summary['source']
        and evidence['record_id'] == summary['record_id']
        and evidence['project'] == str(summary['gitlab_project']).removesuffix('.git')
        and str(evidence['pipeline_id']) == str(summary['pipeline_id']))


def _envelope(raw):
    value = json.loads(raw)
    _fields(value, ('observation', 'imported_at'))
    return {'observation': validate_evidence(value['observation']),
            'imported_at': _time(value['imported_at'])}


class ExecutionEvidenceStore:
    """Store immutable observations in existing encrypted metadata namespaces."""

    def __init__(self, persistence):
        from .cx_persistence import CxPersistence
        if not isinstance(persistence, CxPersistence):
            raise ValueError('Encrypted persistence required')
        self.persistence = persistence

    def import_observation(self, value):
        evidence = validate_evidence(value)
        key = _key(evidence['source'], evidence['record_id'])
        history_key = key + ':' + evidence['observed_at']
        with self.persistence.transaction() as conn:
            profiles = ExecutionProfileStore(str(self.persistence.path), key_file=self.persistence.storage.key_file)
            runs = list_execution_history(profiles, source=evidence['source'], record_id=evidence['record_id'], limit=1)
            if not runs or not matches(evidence, summarize_execution_history(runs[0])):
                raise ValueError('Evidence does not match a recorded submission')
            prior = conn.execute('SELECT value FROM cx_values WHERE namespace=? AND key=?', (HISTORY, history_key)).fetchone()
            if prior:
                if _envelope(prior[0])['observation'] != evidence:
                    raise ValueError('Conflicting observation at the same time')
                return False
            envelope = json.dumps({'observation': evidence, 'imported_at': datetime.now(timezone.utc).isoformat()}, sort_keys=True)
            conn.execute('INSERT INTO cx_values(namespace,key,value) VALUES(?,?,?)', (HISTORY, history_key, envelope))
            current = conn.execute('SELECT value FROM cx_values WHERE namespace=? AND key=?', (CURRENT, key)).fetchone()
            if not current or _envelope(current[0])['observation']['observed_at'] < evidence['observed_at']:
                conn.execute('INSERT INTO cx_values(namespace,key,value) VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value', (CURRENT, key, envelope))
        return True

    def current(self, summaries):
        if not summaries:
            return {}
        if len(summaries) > 80:
            raise ValueError('Evidence page exceeds limit')
        keys = [_key(item['source'], item['record_id']) for item in summaries]
        with self.persistence._connect(readonly=True) as conn:
            rows = conn.execute('SELECT key,value FROM cx_values WHERE namespace=? AND key IN (' + ','.join('?' for _ in keys) + ')', (CURRENT, *keys)).fetchall()
        values = {row[0]: _envelope(row[1]) for row in rows}
        result = {}
        for summary, key in zip(summaries, keys):
            if key not in values:
                continue
            envelope = values[key]
            evidence = envelope['observation']
            if not matches(evidence, summary):
                raise ValueError('Stored evidence binding differs')
            result[key] = envelope
        return result

    def observations(self, summary, *, limit=20):
        if type(limit) is not int or not 1 <= limit <= 80:
            raise ValueError('Invalid observation limit')
        prefix = _key(summary['source'], summary['record_id']) + ':'
        with self.persistence._connect(readonly=True) as conn:
            rows = conn.execute('SELECT value FROM cx_values WHERE namespace=? AND key>=? AND key<? ORDER BY key DESC LIMIT ?',
                (HISTORY, prefix, prefix + '\uffff', limit)).fetchall()
        result = []
        for row in rows:
            envelope = _envelope(row[0])
            if not matches(envelope['observation'], summary):
                raise ValueError('Stored evidence binding differs')
            result.append(presentation(envelope))
        return result


def presentation(envelope):
    """Report observed states, not an inferred computation or delivery outcome."""
    evidence = envelope['observation']
    root = next(p for p in evidence['pipelines'] if (p['project'], p['id']) == (evidence['project'], evidence['pipeline_id']))
    outstanding = [j for j in evidence['jobs'] if j['status'] not in ('success', 'skipped')]
    stages = list(dict.fromkeys(f"{j['stage']}: {j['status']}" for j in outstanding))
    stage_label = ', '.join(stages[:3]) or ('No unfinished job recorded' if evidence['jobs'] else 'Job stages unknown')
    if len(stages) > 3:
        stage_label += f' (+{len(stages) - 3} stages)'
    child_states = [f"#{p['id']}: {p['status']}" for p in evidence['pipelines']
        if (p['project'], p['id']) != (root['project'], root['id']) and p['status'] not in ('success', 'skipped')]
    return {
        'status': root['status'], 'observed_at': evidence['observed_at'],
        'stages': stage_label,
        'children': ', '.join(child_states[:3]) + (f' (+{len(child_states) - 3})' if len(child_states) > 3 else ''),
        'observation': evidence, 'imported_at': envelope['imported_at'],
    }
