"""Operation-scoped encrypted document reads; never cache authorization decisions."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
from uuid import UUID


_active = ContextVar('cx_document_snapshot', default=None)


def current_snapshot(store):
    active = _active.get()
    return active if active is not None and active.store is store else None


class DocumentSnapshot:
    def __init__(self, store, conn, *, cache_documents=True):
        self.store, self.conn = store, conn
        self._documents = {} if cache_documents else None
        self._exceptions = None

    def names(self, role, prefix=''):
        return [row[0] for row in self.conn.execute(
            'SELECT name FROM cx_objects WHERE role=? ORDER BY name', (role,))
            if row[0].startswith(prefix)]

    def exists(self, role, name):
        self.store._object_name(role, name)
        return bool(self.conn.execute(
            'SELECT 1 FROM cx_objects WHERE role=? AND name=?', (role, name)).fetchone())

    def read_json(self, role, name):
        if self._documents is None:
            return json.loads(b''.join(self.store.chunks(role, name, conn=self.conn)))
        key = role, name
        if key not in self._documents:
            self._documents[key] = b''.join(self.store.chunks(role, name, conn=self.conn))
        # A fresh JSON value prevents caller mutations from affecting subsequent
        # permission/payload reads, without Python-level deep copies of large records.
        return json.loads(self._documents[key])

    def source_names(self, identifier):
        # The persisted index also contains filename identities. Callers must
        # recheck the declared identity and permissions, including duplicates.
        names = {row[0] for row in self.conn.execute(
            'SELECT name FROM cx_identities WHERE role=? AND identifier=?',
            ('results', identifier))}
        if self._exceptions is None:
            self._exceptions = set()
            # Older indexes do not normalize UUIDs. Inspect only the declaration
            # projection, not every complete Result through the document API.
            # Multi-chunk/invalid JSON falls back to the verified document reader.
            for row in self.conn.execute('''SELECT c.name,
                CASE WHEN json_valid(CAST(c.data AS TEXT))
                     THEN json_extract(CAST(c.data AS TEXT),'$._server_uuid') END AS declared,
                CASE WHEN json_valid(CAST(c.data AS TEXT))
                     THEN json_type(CAST(c.data AS TEXT)) END AS kind,
                json_valid(CAST(c.data AS TEXT)) AS valid,
                EXISTS(SELECT 1 FROM cx_chunks x WHERE x.role=c.role AND x.name=c.name AND x.ordinal>0) AS multiple
                FROM cx_chunks c WHERE c.role='results' AND c.ordinal=0'''):
                declared = row['declared']
                if row['multiple'] or not row['valid'] or row['kind'] != 'object':
                    self._exceptions.add(row['name'])
                elif isinstance(declared, str):
                    try:
                        normalized = str(UUID(declared))
                    except ValueError:
                        continue
                    if normalized != declared:
                        self._exceptions.add(row['name'])
            self._exceptions.update(row[0] for row in self.conn.execute('''
                SELECT o.name FROM cx_objects o WHERE o.role='results'
                AND NOT EXISTS(SELECT 1 FROM cx_chunks c
                    WHERE c.role=o.role AND c.name=o.name AND c.ordinal=0)'''))
            for row in self.conn.execute(
                    "SELECT name,identifier FROM cx_identities WHERE role='results'"):
                if row['identifier'] != row['identifier'].lower():
                    self._exceptions.add(row['name'])
        return sorted(names | self._exceptions)


@contextmanager
def document_snapshot(store=None, *, conn=None, cache_documents=True):
    if store is None:
        from .profile_storage import configured_store
        store = configured_store()
    if store is None:
        yield None
        return
    active = current_snapshot(store)
    if active is not None:
        if conn is not None and conn is not active.conn:
            raise RuntimeError('Conflicting document snapshots')
        yield active
        return
    if conn is None:
        with store._connect(readonly=True) as connection:
            connection.execute('BEGIN')
            # Establish the WAL snapshot before any nested reads.
            connection.execute('SELECT ready FROM catalog_state').fetchone()
            with document_snapshot(store, conn=connection, cache_documents=cache_documents) as snapshot:
                yield snapshot
        return
    token = _active.set(DocumentSnapshot(store, conn, cache_documents=cache_documents))
    try:
        yield _active.get()
    finally:
        _active.reset(token)


def snapshot_reads(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with document_snapshot():
            return function(*args, **kwargs)
    return wrapped
