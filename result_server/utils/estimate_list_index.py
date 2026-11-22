"""Optional, rebuildable Estimate selection index; canonical bytes remain authoritative."""
import json

from .result_catalog import CatalogUnavailable
from .result_file import _extract_confidential_tags
from .table_filters import get_nested_field
from .table_pagination import normalize_per_page

FIELDS = {'system': 'current_system.system', 'code': 'code', 'exp': 'exp'}


def exists(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name='estimate_list_state' AND type='table'").fetchone() is not None


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS estimate_list_state (
        id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,ready INTEGER NOT NULL)''')
    conn.execute('INSERT OR IGNORE INTO estimate_list_state VALUES(1,1,0)')
    conn.execute('''CREATE TABLE IF NOT EXISTS estimate_list_entries (
        name TEXT PRIMARY KEY,role TEXT NOT NULL DEFAULT 'estimates' CHECK(role='estimates'),
        source_sha TEXT NOT NULL,system TEXT NOT NULL,code TEXT NOT NULL,exp TEXT NOT NULL,
        public INTEGER NOT NULL,FOREIGN KEY(role,name) REFERENCES cx_objects(role,name) ON DELETE CASCADE)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS estimate_list_tags (
        name TEXT NOT NULL REFERENCES estimate_list_entries(name) ON DELETE CASCADE,
        tag TEXT NOT NULL,PRIMARY KEY(name,tag))''')
    conn.execute('CREATE INDEX IF NOT EXISTS estimate_list_selection ON estimate_list_entries(system,code,exp,name DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS estimate_list_tag_lookup ON estimate_list_tags(tag,name)')


def put(conn, name, payload):
    if not name.endswith('.json') or not exists(conn):
        return
    tags = sorted(set(_extract_confidential_tags(payload)))
    checksum = conn.execute("SELECT sha256 FROM cx_objects WHERE role='estimates' AND name=?", (name,)).fetchone()[0]
    conn.execute('DELETE FROM estimate_list_entries WHERE name=?', (name,))
    conn.execute('''INSERT INTO estimate_list_entries(name,source_sha,system,code,exp,public)
        VALUES(?,?,?,?,?,?)''', (name, checksum,
        *(json.dumps(get_nested_field(payload, path), ensure_ascii=True) for path in FIELDS.values()), int(not tags)))
    conn.executemany('INSERT INTO estimate_list_tags VALUES(?,?)', [(name, tag) for tag in tags])


def verify_document(conn, name, payload):
    """Full integrity checks compare derived fields against canonical JSON."""
    tags = set(_extract_confidential_tags(payload))
    row = conn.execute('''SELECT e.source_sha,e.system,e.code,e.exp,e.public,o.sha256
        FROM estimate_list_entries e JOIN cx_objects o ON o.role=e.role AND o.name=e.name
        WHERE e.name=?''', (name,)).fetchone()
    actual_tags = {row[0] for row in conn.execute(
        'SELECT tag FROM estimate_list_tags WHERE name=?', (name,))}
    expected = tuple(json.dumps(get_nested_field(payload, path), ensure_ascii=True)
                     for path in FIELDS.values()) + (int(not tags),)
    if not row or row[0] != row[5] or tuple(row[1:5]) != expected or actual_tags != tags:
        raise CatalogUnavailable('Estimate list projection disagrees with canonical bytes')


def select(conn, *, public_only, authenticated, affiliations, page, per_page, filters):
    state = conn.execute('SELECT version,ready FROM estimate_list_state WHERE id=1').fetchone()
    if not state or tuple(state) != (1, 1):
        raise CatalogUnavailable('Estimate list index needs rebuilding')
    count = conn.execute('SELECT count(*) FROM estimate_list_entries').fetchone()[0]
    canonical = conn.execute("SELECT count(*) FROM cx_objects WHERE role='estimates' AND substr(name,-5)='.json'").fetchone()[0]
    stale = conn.execute('''SELECT 1 FROM estimate_list_entries e LEFT JOIN cx_objects o
        ON o.role=e.role AND o.name=e.name WHERE o.name IS NULL OR o.sha256<>e.source_sha LIMIT 1''').fetchone()
    if count != canonical or stale:
        raise CatalogUnavailable('Estimate list index differs from canonical documents')
    clauses, args = [], []
    if public_only or not authenticated:
        clauses.append('e.public=1')
    elif 'admin' not in affiliations:
        tags = sorted(set(affiliations))
        permission = 'e.public=1'
        if tags:
            permission += ' OR EXISTS(SELECT 1 FROM estimate_list_tags t WHERE t.name=e.name AND t.tag IN (' + ','.join('?' for _ in tags) + '))'
            args.extend(tags)
        clauses.append('(' + permission + ')')
    visibility = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    options = {}
    for field, plural in [('system', 'systems'), ('code', 'codes'), ('exp', 'exps')]:
        values = [json.loads(row[0]) for row in conn.execute('SELECT DISTINCT e.'+field+' FROM estimate_list_entries e'+visibility, args)]
        options[plural] = sorted({value for value in values if value and value != 'N/A'})
    for field, value in filters.items():
        if value is not None:
            clauses.append('e.' + field + '=?')
            args.append(json.dumps(value, ensure_ascii=True))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    total = conn.execute('SELECT count(*) FROM estimate_list_entries e'+where, args).fetchone()[0]
    per_page = normalize_per_page(per_page)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    names = [row[0] for row in conn.execute('SELECT e.name FROM estimate_list_entries e'+where+
        ' ORDER BY e.name DESC LIMIT ? OFFSET ?', [*args, per_page, (page-1)*per_page])]
    return names, {'page':page,'per_page':per_page,'total':total,'total_pages':pages}, options
