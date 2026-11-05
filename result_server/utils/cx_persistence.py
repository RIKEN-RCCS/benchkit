"""Explicit, per-instance SQLCipher persistence. No plaintext fallback or auto-init."""

from contextlib import contextmanager, nullcontext
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import time
import tarfile
import uuid
import posixpath

from .encrypted_sqlite import EncryptedSQLite, EncryptedDatabaseError
from .result_catalog import ResultCatalog, CatalogUnavailable
from .profile_storage import _transaction, configured_store, persistence_settings
from .cx_artifact_store import CxArtifactStore, ChunkWriter


SCHEMA_VERSION = 1
CHUNK_SIZE = 1024 * 1024


def catalog_for(path, directory, **kwargs):
    store = configured_store()
    if store:
        if Path(path).absolute() != store.path:
            raise CatalogUnavailable("Encrypted persistence catalog binding mismatch")
        for role, root in [("results", directory),
                           ("estimates", kwargs.get("estimated_directory")),
                           ("artifacts", kwargs.get("artifact_directory"))]:
            if root is not None and str(Path(root).absolute()) != store.sources.get(role):
                raise CatalogUnavailable("Encrypted persistence source binding mismatch")
        return store
    return ResultCatalog(path, directory, **kwargs)


class CxPersistence(ResultCatalog):
    """Atomic metadata/documents with a separately encrypted immutable artifact DB.

    Logical source directories preserve existing URLs and filename semantics;
    encrypted mode never materializes documents or artifacts in those directories.
    Shared Budget/Runner databases remain separately owned stores.
    """

    def __init__(self, path, key_file, *, roots, artifact_path=None):
        self.storage = EncryptedSQLite(path, key_file)
        self.path = self.storage.path
        self.blobs = CxArtifactStore(artifact_path or self.path.with_name(self.path.name + '.artifacts'), key_file)
        if self.blobs.path == self.path:
            raise ValueError('Metadata and artifact databases must be distinct')
        required = {"results", "estimates", "artifacts", "inputs"}
        if not required <= set(roots) or set(roots) - required - {'legacy_inputs'}:
            raise ValueError("Instance-local source bindings are incomplete or unknown")
        if any(not Path(root).is_absolute() or '..' in Path(root).parts for root in roots.values()):
            raise ValueError('Logical source bindings must be absolute and normalized')
        self.roots = {role: str(Path(root).absolute()) for role, root in roots.items()}
        if len(set(self.roots.values())) != len(self.roots):
            raise ValueError("Encrypted persistence requires distinct source bindings")
        paths = [Path(root) for root in self.roots.values()]
        if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(paths) for b in paths[i + 1:]):
            raise ValueError("Encrypted persistence source bindings must not overlap")
        if any(self.path.is_relative_to(root) or self.blobs.path.is_relative_to(root)
               or self.storage.key_file.is_relative_to(root) for root in paths):
            raise ValueError("Keep persistence database and key outside logical sources")
        self.directory = self.roots["results"]
        self.sources = {role: self.roots[role] for role in ("results", "estimates", "artifacts")}

    def initialize(self):
        """Explicit lifecycle operation, never called by a request or app factory."""
        if self.path.exists() or self.blobs.path.exists():
            raise FileExistsError('Persistence creation requires two new files')
        instance_id = str(uuid.uuid4())
        self.blobs.initialize(instance_id)
        with self.storage.connect(create=True) as conn:
            self.initialize_schema(conn)
            conn.executescript("""
                CREATE TABLE cx_state(id INTEGER PRIMARY KEY CHECK(id=1),
                    version INTEGER NOT NULL, roots TEXT NOT NULL, artifact_store_id TEXT NOT NULL);
                CREATE TABLE cx_objects(role TEXT NOT NULL, name TEXT NOT NULL,
                    size INTEGER NOT NULL CHECK(size>=0), sha256 TEXT NOT NULL,
                    generation TEXT NOT NULL,
                    PRIMARY KEY(role,name));
                CREATE TABLE cx_chunks(role TEXT NOT NULL, name TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, data BLOB NOT NULL,
                    PRIMARY KEY(role,name,ordinal),
                    FOREIGN KEY(role,name) REFERENCES cx_objects ON DELETE CASCADE);
                CREATE TABLE cx_values(namespace TEXT NOT NULL, key TEXT NOT NULL,
                    value TEXT NOT NULL, expires REAL,
                    PRIMARY KEY(namespace,key));
                CREATE INDEX cx_expiry ON cx_values(expires);
                CREATE TABLE cx_identities(role TEXT NOT NULL, name TEXT NOT NULL,
                    identifier TEXT NOT NULL, PRIMARY KEY(role,name,identifier),
                    FOREIGN KEY(role,name) REFERENCES cx_objects ON DELETE CASCADE);
                CREATE INDEX cx_identity_lookup ON cx_identities(role,identifier,name DESC);
            """)
            conn.execute("INSERT INTO cx_state VALUES(1,?,?,?)",
                         (SCHEMA_VERSION, json.dumps(self.roots, sort_keys=True), instance_id))
            conn.commit()
        from .execution_profiles import ExecutionProfileStore
        ExecutionProfileStore(self.path, key_file=self.storage.key_file).migrate()
        with self.storage.connect() as conn:
            conn.execute('UPDATE catalog_state SET ready=1')
            conn.commit()
        self.check()

    @contextmanager
    def _connect(self, readonly=False, *, upgrading=False):
        with self.storage.connect(readonly=readonly) as conn:
            state = conn.execute("SELECT * FROM cx_state WHERE id=1").fetchone()
            if (not state or state["version"] != SCHEMA_VERSION
                    or json.loads(state["roots"]) != self.roots):
                raise EncryptedDatabaseError("Persistence schema or instance binding mismatch")
            catalog = conn.execute("SELECT version,directory FROM catalog_state WHERE id=1").fetchone()
            if not catalog or tuple(catalog) != (2, self.directory):
                raise EncryptedDatabaseError("Persistence query schema mismatch")
            yield conn

    @contextmanager
    def transaction(self):
        if _transaction.get() is not None:
            raise EncryptedDatabaseError("Nested persistence transaction is not supported")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute('''DELETE FROM cx_values WHERE (namespace,key) IN
                (SELECT namespace,key FROM cx_values WHERE expires<=? LIMIT 128)''', (time.time(),))
            token = _transaction.set((str(self.path), conn, self.storage.key_file))
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                _transaction.reset(token)

    @staticmethod
    def _object_name(role, name):
        if role not in {"results", "estimates", "artifacts", "inputs", "legacy_inputs", "input_archives"}:
            raise ValueError("Unknown persistence role")
        parts = PurePosixPath(name).parts if isinstance(name, str) else ()
        if (not parts or not name or "\\" in name or "\x00" in name
                or PurePosixPath(name).is_absolute() or any(p in ("", ".", "..") for p in name.split("/"))
                or (role not in ("inputs", "legacy_inputs") and len(parts) != 1)):
            raise ValueError("Unsafe storage identity")
        return name

    def put(self, role, name, stream, *, limit, conn=None):
        """Stream bounded chunks into a transaction; a failed upload rolls back all chunks."""
        self._object_name(role, name)
        if role not in ('results', 'estimates'):
            self._check_artifact_owner()
            info = self.blobs.stage_object(role, name, stream, limit=limit)
            with (self.transaction() if conn is None else nullcontext(conn)) as conn:
                self._publish_blob(conn, role, name, info)
            return info
        if conn is None:
            raise ValueError('Use put_document for a canonical document')
        conn.execute("DELETE FROM cx_objects WHERE role=? AND name=?", (role, name))
        conn.execute("INSERT INTO cx_objects VALUES(?,?,0,'','')", (role, name))
        digest, size, ordinal = hashlib.sha256(), 0, 0
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError("Object exceeds storage limit")
            digest.update(chunk)
            conn.execute("INSERT INTO cx_chunks VALUES(?,?,?,?)", (role, name, ordinal, chunk))
            ordinal += 1
        conn.execute("UPDATE cx_objects SET size=?,sha256=? WHERE role=? AND name=?",
                     (size, digest.hexdigest(), role, name))
        if role in ('results', 'estimates', 'artifacts'):
            conn.execute("UPDATE catalog_state SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        return {"size": size, "sha256": digest.hexdigest()}

    def _publish_blob(self, conn, role, name, info):
        conn.execute('DELETE FROM cx_objects WHERE role=? AND name=?', (role, name))
        conn.execute('INSERT INTO cx_objects VALUES(?,?,?,?,?)',
                     (role, name, info['size'], info['sha256'], info['generation']))
        if role == 'artifacts' and name.endswith('.tgz'):
            self._put_archive(conn, name)
            conn.execute("UPDATE catalog_state SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")

    def _check_artifact_owner(self):
        with self._connect(readonly=True) as conn:
            self.blobs.require_owner(conn.execute('SELECT artifact_store_id FROM cx_state WHERE id=1').fetchone()[0])

    def put_document(self, role, name, raw, *, index_metadata=None, conn=None, update_metadata=True):
        if role not in ("results", "estimates"):
            raise ValueError("Expected a document role")
        self._name(name)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        with (self.transaction() if conn is None else nullcontext(conn)) as conn:
            self.put(role, name, io.BytesIO(raw), limit=len(raw), conn=conn)
            self._put_identities(conn, role, name, payload)
            if role == "results":
                self._put(conn, name, payload)
            else:
                self._put_report(conn, self.roots[role], name, payload)
            from .result_metadata_index import index_result_metadata
            from .environment_snapshots import index_environment_snapshot
            if update_metadata:
                index_result_metadata(db_path=str(self.path), record_type="result" if role == "results" else "estimate",
                                      payload=payload, json_file=name)
            if update_metadata and role == "results":
                index_environment_snapshot(db_path=str(self.path), payload=payload, json_file=name)
            if index_metadata:
                index_metadata()

    @staticmethod
    def _document_identifiers(role, name, payload):
        from .result_file import UUID_PATTERN
        identities = {match.group() for match in UUID_PATTERN.finditer(name)}
        metadata = payload.get('estimate_metadata')
        declared = payload.get('_server_uuid') if role == 'results' else (
            metadata.get('estimation_result_uuid') if isinstance(metadata, dict) else None)
        if isinstance(declared, str) and UUID_PATTERN.fullmatch(declared):
            identities.add(declared)
        return identities

    @classmethod
    def _put_identities(cls, conn, role, name, payload):
        identities = cls._document_identifiers(role, name, payload)
        conn.executemany('INSERT OR IGNORE INTO cx_identities VALUES(?,?,?)',
                         [(role, name, identifier) for identifier in sorted(identities)])

    def find_document(self, role, identifier):
        """Keep newest-filename semantics, including filename-only legacy UUIDs."""
        with self._connect(readonly=True) as conn:
            conn.execute('BEGIN')
            row = conn.execute('SELECT name FROM cx_identities WHERE role=? AND identifier=? ORDER BY name DESC LIMIT 1',
                               (role, identifier)).fetchone()
            if row is None:
                return None, None
            return row[0], json.loads(b''.join(self.chunks(role, row[0], conn=conn)))

    def names(self, role, prefix=""):
        if role not in {*self.roots, "input_archives"}:
            raise ValueError("Unknown persistence role")
        with self._connect(readonly=True) as conn:
            # No LIKE wildcard interpretation of caller-controlled filenames.
            return [row[0] for row in conn.execute(
                "SELECT name FROM cx_objects WHERE role=? ORDER BY name", (role,))
                    if row[0].startswith(prefix)]

    def exists(self, role, name):
        self._object_name(role, name)
        with self._connect(readonly=True) as conn:
            return bool(conn.execute("SELECT 1 FROM cx_objects WHERE role=? AND name=?", (role, name)).fetchone())

    def chunks(self, role, name, *, conn=None):
        """Pin one WAL read snapshot for the entire download, including concurrent replacement."""
        self._object_name(role, name)
        with (self._connect(readonly=True) if conn is None else nullcontext(conn)) as conn:
            if not conn.in_transaction:
                conn.execute("BEGIN")
            info = conn.execute("SELECT size,sha256,generation FROM cx_objects WHERE role=? AND name=?", (role, name)).fetchone()
            if info is None:
                raise FileNotFoundError("Stored object not found")
            if (role in ('results', 'estimates')) != (not info['generation']):
                raise EncryptedDatabaseError('Stored object backend binding is invalid')
            if info['generation']:
                self.blobs.require_owner(conn.execute('SELECT artifact_store_id FROM cx_state WHERE id=1').fetchone()[0])
                yield from self.blobs.chunks(info['generation'], role, name, expected=(info['size'], info['sha256']))
                return
            digest, size = hashlib.sha256(), 0
            for row in conn.execute("SELECT data FROM cx_chunks WHERE role=? AND name=? ORDER BY ordinal", (role, name)):
                data = bytes(row[0])
                size += len(data)
                digest.update(data)
                yield data
            if (size, digest.hexdigest()) != tuple(info)[:2]:
                raise EncryptedDatabaseError("Stored object checksum mismatch")

    def read(self, role, name):
        return b"".join(self.chunks(role, name))

    def replace_inputs(self, stem, stream, *, upload_limit, member_limit, total_limit, count_limit):
        """Stage an entire bundle before atomically switching its visible pointers."""
        self._object_name("input_archives", stem)
        self._check_artifact_owner()
        with self.blobs.stage() as (generation, stage):
            self.blobs.put(generation, 'input_archives', stem, stream, limit=upload_limit, conn=stage)
            chunks = self.blobs.chunks(generation, 'input_archives', stem, conn=stage)
            seen, files, directories, total = set(), set(), [], 0
            with io.BufferedReader(ChunkReader(chunks)) as source, tarfile.open(fileobj=source, mode="r|*") as archive:
                for count, member in enumerate(archive, 1):
                    name = posixpath.normpath(member.name)
                    if (count > count_limit or member.size > member_limit or member.size < 0
                            or not (member.isfile() or member.isdir())):
                        raise ValueError("Unsafe or oversized archive entry")
                    total += member.size
                    if total > total_limit:
                        raise ValueError("Archive extracted size exceeds limit")
                    if name == '.' and member.isdir():
                        continue
                    self._object_name("inputs", name)
                    if name in seen:
                        raise ValueError('Archive contains duplicate normalized paths')
                    if (any(parent.as_posix() in files for parent in PurePosixPath(name).parents)
                            or (member.isfile() and any(item.startswith(name + "/") for item in seen))):
                        raise ValueError("Archive contains conflicting paths")
                    seen.add(name)
                    if member.isdir():
                        directories.append(name)
                    if member.isfile():
                        files.add(name)
                        with archive.extractfile(member) as item:
                            info = self.blobs.put(generation, 'inputs', stem + '/' + name, item,
                                                  limit=member_limit, conn=stage)
                            if info["size"] != member.size:
                                raise ValueError("Incomplete archive entry")
            first = stage.execute("SELECT data FROM chunks WHERE generation=? AND role='input_archives' AND name=? AND ordinal=0", (generation, stem)).fetchone()
            if not first or not bytes(first[0]).startswith(b'\x1f\x8b'):
                stage.execute("DELETE FROM objects WHERE generation=? AND role='input_archives' AND name=?", (generation, stem))
                rows = stage.execute("SELECT name,size FROM objects WHERE generation=? AND role='inputs' ORDER BY name", (generation,)).fetchall()
                entries = ((name, size, self.blobs.chunks(generation, 'inputs', name, conn=stage)) for name, size in rows)
                self._write_input_archive(stage, generation, stem, entries, directories)
            published = [dict(row) for row in stage.execute('SELECT * FROM objects WHERE generation=?', (generation,))]
        with self.transaction() as conn:
            replaced = bool(conn.execute("SELECT 1 FROM cx_objects WHERE role='input_archives' AND name=?", (stem,)).fetchone())
            old = [row[0] for row in conn.execute("SELECT name FROM cx_objects WHERE role='inputs'")
                   if row[0].startswith(stem + "/")]
            conn.executemany("DELETE FROM cx_objects WHERE role='inputs' AND name=?", [(name,) for name in old])
            for item in published:
                self._publish_blob(conn, item['role'], item['name'], item)
            return replaced

    def build_input_archive(self, stem, conn, *, directories=()):
        """Repackage imported legacy inputs directly into encrypted chunks."""
        self._object_name("input_archives", stem)
        self._check_artifact_owner()
        rows = conn.execute("SELECT name,size FROM cx_objects WHERE role='inputs' ORDER BY name").fetchall()
        entries = ((name, size, self.chunks('inputs', name, conn=conn)) for name, size in rows
                   if name.startswith(stem + '/'))
        with self.blobs.stage() as (generation, stage):
            self._write_input_archive(stage, generation, stem, entries, directories)
            info = dict(stage.execute("SELECT * FROM objects WHERE generation=? AND role='input_archives' AND name=?", (generation, stem)).fetchone())
        self._publish_blob(conn, 'input_archives', stem, info)

    @staticmethod
    def _write_input_archive(stage, generation, stem, entries, directories):
        with ChunkWriter(stage, generation, 'input_archives', stem) as output:
            with tarfile.open(fileobj=output, mode="w|gz") as archive:
                for directory in sorted(directories):
                    info = tarfile.TarInfo(directory)
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                for name, size, chunks in entries:
                    info = tarfile.TarInfo(name[len(stem) + 1:])
                    info.size = size
                    with io.BufferedReader(ChunkReader(chunks)) as source:
                        archive.addfile(info, source)

    def writer(self, **kwargs):
        raise EncryptedDatabaseError("Use the canonical persistence transaction, not filesystem callbacks")

    def replace(self, *args, **kwargs):
        raise EncryptedDatabaseError("Use put_document for canonical encrypted storage")

    replace_related = replace
    delete = replace
    delete_related = replace
    upgrade = replace

    def value_get(self, namespace, key):
        with self._connect(readonly=True) as conn:
            row = conn.execute("SELECT value FROM cx_values WHERE namespace=? AND key=? AND (expires IS NULL OR expires>?)",
                               (namespace, key, time.time())).fetchone()
            return json.loads(row[0]) if row else None

    def value_set(self, namespace, key, value, *, ttl=None):
        with self.transaction() as conn:
            conn.execute("INSERT INTO cx_values VALUES(?,?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value,expires=excluded.expires",
                         (namespace, key, json.dumps(value), None if ttl is None else time.time() + ttl))

    def value_delete(self, namespace, key):
        with self.transaction() as conn:
            return conn.execute("DELETE FROM cx_values WHERE namespace=? AND key=?", (namespace, key)).rowcount > 0

    def check(self):
        self.storage.check()
        self.blobs.storage.check()
        with self._connect(readonly=True) as conn:
            conn.execute("BEGIN")
            self.blobs.require_owner(conn.execute('SELECT artifact_store_id FROM cx_state WHERE id=1').fetchone()[0])
            if not conn.execute("SELECT ready FROM catalog_state").fetchone()[0]:
                raise EncryptedDatabaseError("Persistence import is incomplete")
            if conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] != 12:
                raise EncryptedDatabaseError('Unsupported Profile schema')
            objects = [(row[0], row[1]) for row in conn.execute("SELECT role,name FROM cx_objects")]
            documents = {(self.roots[role], name) for role, name in objects if role in ("results", "estimates")}
            facts = {(row[0], row[1]) for row in conn.execute("SELECT directory,filename FROM query_records")}
            if documents != facts:
                raise EncryptedDatabaseError("Canonical documents and query facts disagree")
            if conn.execute("""SELECT 1 FROM candidate_groups g WHERE g.count <>
                (SELECT COUNT(*) FROM result_entries e WHERE e.group_id=g.id) LIMIT 1""").fetchone():
                raise EncryptedDatabaseError("Candidate counts disagree")
            if {name for role, name in objects if role == "results"} != {
                    row[0] for row in conn.execute("SELECT filename FROM result_entries")}:
                raise EncryptedDatabaseError("Canonical results and candidate entries disagree")
            for role, name in objects:
                if role in ("results", "estimates"):
                    from .result_query_records import report_facts
                    payload = json.loads(b''.join(self.chunks(role, name, conn=conn)))
                    expected = report_facts(payload)
                    identities = {row[0] for row in conn.execute('SELECT identifier FROM cx_identities WHERE role=? AND name=?', (role, name))}
                    if identities != self._document_identifiers(role, name, payload):
                        raise EncryptedDatabaseError('Document identity index disagrees with canonical bytes')
                    row = conn.execute("SELECT facts,evidence FROM query_records WHERE directory=? AND filename=?",
                                       (self.roots[role], name)).fetchone()
                    actual = tuple(json.dumps(json.loads(value), sort_keys=True) for value in row)
                    if actual != tuple(json.dumps(value, sort_keys=True) for value in expected):
                        raise EncryptedDatabaseError("Stored report facts disagree with the canonical document")
                    if role == 'results':
                        from .result_file import _extract_confidential_tags
                        tags = sorted(set(_extract_confidential_tags(payload)))
                        row = conn.execute('''SELECT g.system,g.code,g.exp,g.visibility,g.public,g.id
                            FROM candidate_groups g JOIN result_entries e ON g.id=e.group_id WHERE e.filename=?''', (name,)).fetchone()
                        values = tuple(value if isinstance(value, str) else '' for value in
                                       (payload.get('system'), payload.get('code'), payload.get('Exp')))
                        if tuple(row)[:5] != (*values, json.dumps(tags, ensure_ascii=True), int(not tags)):
                            raise EncryptedDatabaseError('Candidate visibility disagrees with canonical Result')
                        if {item[0] for item in conn.execute('SELECT tag FROM group_tags WHERE group_id=?', (row[5],))} != set(tags):
                            raise EncryptedDatabaseError('Candidate permissions disagree with canonical Result')
                else:
                    for _ in self.chunks(role, name, conn=conn):
                        pass

    @classmethod
    def open_existing(cls, path, key_file, *, artifact_path=None):
        """Read logical instance bindings from a copy; never discover filesystem data."""
        storage = EncryptedSQLite(path, key_file)
        with storage.connect(readonly=True) as conn:
            roots = json.loads(conn.execute("SELECT roots FROM cx_state WHERE id=1").fetchone()[0])
        return cls(path, key_file, roots=roots, artifact_path=artifact_path)

    def backup(self, destination):
        """Copy metadata FIRST, then immutable generations, and verify every pointer."""
        artifact_target = Path(destination).with_name(Path(destination).name + '.artifacts')
        if Path(destination).exists() or artifact_target.exists():
            raise FileExistsError('Backup requires two new destination files')
        self.storage.backup(destination)
        self.blobs.storage.backup(artifact_target)
        recovered = CxPersistence(destination, self.storage.key_file, roots=self.roots)
        recovered.check()
        return recovered

    def rebuild(self):
        """Rebuild facts from canonical encrypted bytes, never from stale JSON files."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM result_entries")
            conn.execute("DELETE FROM candidate_groups")
            conn.execute("DELETE FROM query_records")
            conn.execute('DELETE FROM cx_identities')
            conn.execute("DELETE FROM artifact_entries")
            objects = conn.execute("SELECT role,name FROM cx_objects ORDER BY role,name").fetchall()
            for role, name in objects:
                if role in ("results", "estimates"):
                    raw = b"".join(bytes(row[0]) for row in conn.execute(
                        "SELECT data FROM cx_chunks WHERE role=? AND name=? ORDER BY ordinal", (role, name)))
                    payload = json.loads(raw)
                    self._put_identities(conn, role, name, payload)
                    if role == "results":
                        self._put(conn, name, payload)
                    else:
                        self._put_report(conn, self.roots[role], name, payload)
                elif role == "artifacts" and name.endswith('.tgz'):
                    self._put_archive(conn, name)
            conn.execute("UPDATE catalog_state SET rebuilt_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),ready=1")


def configure_persistence(app):
    """Validate an already migrated DB. Incomplete configuration fails closed."""
    db, key, artifact_path = persistence_settings()
    if not db and not key:
        return
    roots = {
        "results": app.config["RECEIVED_DIR"], "estimates": app.config["ESTIMATED_DIR"],
        "artifacts": app.config["RECEIVED_MEASUREMENT_ARTIFACTS_DIR"],
        "inputs": app.config["RECEIVED_ESTIMATION_ARTIFACTS_DIR"],
    }
    if os.environ.get('RESULT_SERVER_LEGACY_INPUTS_DIR'):
        roots['legacy_inputs'] = os.environ['RESULT_SERVER_LEGACY_INPUTS_DIR']
    store = CxPersistence(db, key, roots=roots, artifact_path=artifact_path)
    with store._connect(readonly=True) as conn:
        store.blobs.require_owner(conn.execute('SELECT artifact_store_id FROM cx_state WHERE id=1').fetchone()[0])
        if not conn.execute("SELECT ready FROM catalog_state").fetchone()[0]:
            raise EncryptedDatabaseError("Persistence import is incomplete")
        if conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] != 12:
            raise EncryptedDatabaseError("Profile schema needs explicit migration")
    app.extensions["cx_persistence"] = store
    app.config.update(EXECUTION_PROFILE_DB_PATH=str(store.path), RESULT_CATALOG_PATH=str(store.path))
    from .cx_identity import EncryptedUserStore, EncryptedSessionCache, EncryptedSessionInterface
    app.config["USER_STORE"] = EncryptedUserStore(store)
    from .cx_security_state import EncryptedSecurityState
    app.config["SECURITY_STATE"] = EncryptedSecurityState(store)
    app.config["AUTH_REQUIRES_REDIS"] = True  # Preserve the existing fail-closed policy.
    app.session_interface = EncryptedSessionInterface(app, client=EncryptedSessionCache(store), use_signer=True)
    from .cx_upload import configure_encrypted_uploads
    configure_encrypted_uploads(app, store)

    @app.before_request
    def require_session_storage():
        from flask import session, abort
        if getattr(session, 'storage_unavailable', False):
            abort(503, description='Encrypted session storage is unavailable')

    @app.errorhandler(EncryptedDatabaseError)
    def unavailable(_error):
        from flask import jsonify
        return jsonify(error="Encrypted persistence is unavailable"), 503


class ChunkReader(io.RawIOBase):
    """Bounded read adapter for tarfile; no decrypted temporary files."""

    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.pending = b""

    def readable(self):
        return True

    def readinto(self, buffer):
        if not self.pending:
            self.pending = next(self.chunks, b"")
        count = min(len(buffer), len(self.pending))
        buffer[:count] = self.pending[:count]
        self.pending = self.pending[count:]
        return count
