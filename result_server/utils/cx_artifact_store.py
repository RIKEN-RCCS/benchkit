"""Immutable encrypted artifact generations, published by the CX metadata DB.

Commit bytes before publishing their pointer. Never delete generations in a live
store: a metadata snapshot taken first can then safely back up the artifact DB.
"""

from contextlib import contextmanager, nullcontext
import hashlib
import uuid

from utils.encrypted_sqlite import EncryptedSQLite, EncryptedDatabaseError


CHUNK_SIZE = 1024 * 1024


class CxArtifactStore:
    def __init__(self, path, key_file):
        self.storage = EncryptedSQLite(path, key_file)
        self.path = self.storage.path

    def initialize(self, instance_id):
        with self.storage.connect(create=True) as conn:
            conn.executescript('''
                CREATE TABLE artifact_state(id INTEGER PRIMARY KEY CHECK(id=1),
                    version INTEGER NOT NULL, instance_id TEXT NOT NULL);
                CREATE TABLE objects(generation TEXT NOT NULL, role TEXT NOT NULL,
                    name TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
                    PRIMARY KEY(generation,role,name));
                CREATE TABLE chunks(generation TEXT NOT NULL, role TEXT NOT NULL,
                    name TEXT NOT NULL, ordinal INTEGER NOT NULL, data BLOB NOT NULL,
                    PRIMARY KEY(generation,role,name,ordinal),
                    FOREIGN KEY(generation,role,name) REFERENCES objects ON DELETE CASCADE);
            ''')
            conn.execute('INSERT INTO artifact_state VALUES(1,1,?)', (instance_id,))
            conn.commit()

    @contextmanager
    def connect(self, *, readonly=False):
        with self.storage.connect(readonly=readonly) as conn:
            state = conn.execute('SELECT version FROM artifact_state WHERE id=1').fetchone()
            if not state or state[0] != 1:
                raise EncryptedDatabaseError('Artifact schema mismatch')
            yield conn

    def require_owner(self, instance_id):
        with self.connect(readonly=True) as conn:
            if conn.execute('SELECT instance_id FROM artifact_state WHERE id=1').fetchone()[0] != instance_id:
                raise EncryptedDatabaseError('Artifact database belongs to a different instance')

    @contextmanager
    def stage(self):
        generation = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield generation, conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def put(self, generation, role, name, stream, *, limit, conn):
        conn.execute('INSERT INTO objects VALUES(?,?,?,0,?)', (generation, role, name, ''))
        digest, size, ordinal = hashlib.sha256(), 0, 0
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('Artifact exceeds storage limit')
            digest.update(chunk)
            conn.execute('INSERT INTO chunks VALUES(?,?,?,?,?)', (generation, role, name, ordinal, chunk))
            ordinal += 1
        info = dict(generation=generation, size=size, sha256=digest.hexdigest())
        conn.execute('UPDATE objects SET size=?,sha256=? WHERE generation=? AND role=? AND name=?',
                     (size, info['sha256'], generation, role, name))
        return info

    def stage_object(self, role, name, stream, *, limit):
        with self.stage() as (generation, conn):
            return self.put(generation, role, name, stream, limit=limit, conn=conn)

    def chunks(self, generation, role, name, *, conn=None, expected=None):
        with (self.connect(readonly=True) if conn is None else nullcontext(conn)) as conn:
            if not conn.in_transaction:
                conn.execute('BEGIN')
            info = conn.execute('SELECT size,sha256 FROM objects WHERE generation=? AND role=? AND name=?',
                                (generation, role, name)).fetchone()
            if info is None or (expected is not None and tuple(info) != tuple(expected)):
                raise EncryptedDatabaseError('Published artifact generation is missing or mismatched')
            digest, size = hashlib.sha256(), 0
            for row in conn.execute('SELECT data FROM chunks WHERE generation=? AND role=? AND name=? ORDER BY ordinal',
                                    (generation, role, name)):
                chunk = bytes(row[0])
                digest.update(chunk)
                size += len(chunk)
                yield chunk
            if (size, digest.hexdigest()) != tuple(info):
                raise EncryptedDatabaseError('Artifact checksum mismatch')


class ChunkWriter:
    """tarfile streaming writer for an unpublished immutable generation."""

    def __init__(self, conn, generation, role, name):
        self.conn, self.generation, self.role, self.name = conn, generation, role, name
        self.pending = bytearray()
        self.digest, self.size, self.ordinal = hashlib.sha256(), 0, 0

    def __enter__(self):
        self.conn.execute('INSERT INTO objects VALUES(?,?,?,0,?)',
                          (self.generation, self.role, self.name, ''))
        return self

    def write(self, data):
        self.digest.update(data)
        self.size += len(data)
        self.pending.extend(data)
        while len(self.pending) >= CHUNK_SIZE:
            self._flush(CHUNK_SIZE)
        return len(data)

    def _flush(self, size):
        self.conn.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',
            (self.generation, self.role, self.name, self.ordinal, bytes(self.pending[:size])))
        del self.pending[:size]
        self.ordinal += 1

    def __exit__(self, kind, value, traceback):
        if kind is None:
            if self.pending:
                self._flush(len(self.pending))
            self.conn.execute('UPDATE objects SET size=?,sha256=? WHERE generation=? AND role=? AND name=?',
                (self.size, self.digest.hexdigest(), self.generation, self.role, self.name))
