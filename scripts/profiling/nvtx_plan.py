"""Optional NVTX scope support for NCU plans (standard library only)."""
import csv
import math
import re
from pathlib import Path


def ncu_nvtx_args(profile):
    scope = profile.get('nvtx')
    if scope is None:
        return []
    if not isinstance(scope, dict):
        raise ValueError('Invalid NVTX scope')
    if scope.get('domain', 'default') != 'default':
        raise ValueError('Only the default NVTX domain is supported')
    name = scope.get('range')
    style = scope.get('style')
    if not isinstance(name, str) or not name or any(ord(c) < 32 for c in name):
        raise ValueError('NVTX range must be nonempty and contain no control characters')
    if style not in ('PushPop', 'StartEnd') or name.startswith('regex:'):
        raise ValueError('Unsupported NVTX range style or literal name')
    # NCU expressions have their own metacharacters, independent of shell quoting.
    expression = ''.join('\\' + c if c in '\\/@[]*+' else c for c in name)
    if style == 'PushPop':
        expression += '/'
    return ['--nvtx', '--nvtx-include', expression]


def read_nvtx_summary(path):
    """Read NVIDIA nvtx_kern_sum CSV; do not sum nested range rows."""
    with path.open(newline='', encoding='utf-8-sig') as handle:
        lines = list(handle)
    normalize = lambda x: re.sub(r'[^a-z0-9]+', '_', x.lower()).strip('_')
    header = None
    for i, line in enumerate(lines):
        keys = {normalize(x) for x in next(csv.reader([line]))}
        if {'nvtx_range', 'kernel_name', 'style', 'pid', 'tid', 'kern_inst'} <= keys:
            header = i
            break
    if header is None:
        raise ValueError('NVTX CSV must be an nvtx_kern_sum report with PID/TID/style')
    result = []
    for raw in csv.DictReader(lines[header:]):
        row = {normalize(k): v for k, v in raw.items() if k is not None}
        if not any(row.values()):
            continue
        def number(key):
            value = float(row[key].replace(',', ''))
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid NVTX numeric value')
            return value
        style = {'PushPop': 'PushPop', 'StartEnd': 'StartEnd',
                 'Push/Pop': 'PushPop', 'Start/End': 'StartEnd'}.get(row['style'])
        if style is None:
            raise ValueError('Unsupported NVTX range style')
        unit = next((k for k in row if k.startswith('total_time')), None)
        scale = {'total_time_ns': 1, 'total_time': 1, 'total_time_us': 1000,
                 'total_time_ms': 1000000}.get(unit)
        if scale is None:
            raise ValueError('Unsupported NVTX time unit')
        count = number('kern_inst')
        if count < 1 or count != int(count):
            raise ValueError('Invalid NVTX kernel count')
        item = {'range': row['nvtx_range'], 'style': style,
                'process_id': row['pid'], 'thread_id': row['tid'],
                'kernel_name': row['kernel_name'], 'instances': int(count),
                'total_time_ns': number(unit) * scale}
        ncu_nvtx_args({'nvtx': item})
        result.append(item)
    return result


def resolve_nsys_nvtx_scope(scope, sqlite_path):
    """Resolve a domain-prefixed NSYS display label using raw default-domain data.

    Do not strip a colon from arbitrary literal labels. With no SQLite proof,
    callers must retain the existing literal-name path instead.
    """
    import sqlite3

    display = scope['range']
    uri = Path(sqlite_path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as database:
        rows = database.execute(
            'SELECT DISTINCT COALESCE(n.text, s.value) '
            'FROM NVTX_EVENTS n LEFT JOIN StringIds s ON s.id = n.textId '
            'WHERE n.domainId = 0')
        names = {name for (name,) in rows if name and ':' + name == display}
    if len(names) != 1:
        raise ValueError('NSYS display range has no unique raw name in the default domain')
    result = dict(scope, range=next(iter(names)), display_range=display, domain='default')
    ncu_nvtx_args({'nvtx': result})
    return result
