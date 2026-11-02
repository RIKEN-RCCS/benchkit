"""Rebuildable Result candidates, search and report facts, never a source of truth."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat

from utils.result_file import _extract_confidential_tags, UUID_PATTERN
from utils.node_hours import extract_timestamp_from_filename
from utils.result_query_records import report_facts


class CatalogUnavailable(RuntimeError):
    """The derived catalog cannot currently provide trustworthy candidates."""


class ResultCatalog:
    """Private derived SQLite store; creation/rebuild is explicit, not on GET.

    One file is one stored Result, just as in the existing list loader. All
    participating writers serialize JSON replacement and index publication.
    A committed dirty flag bridges the filesystem/SQLite transaction boundary.
    """

    def __init__(self, path, directory, *, estimated_directory=None, artifact_directory=None):
        self.path = Path(path).absolute()
        self.directory = str(Path(directory).resolve(strict=True))
        self.sources = {'results': self.directory}
        for role, root in [('estimates', estimated_directory), ('artifacts', artifact_directory)]:
            if root is not None:
                self.sources[role] = str(Path(root).resolve(strict=True))

    def _safe(self, path):
        info = path.lstat()
        if (path.resolve() != path or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise CatalogUnavailable("Unsafe catalog file")

    def _parent(self):
        parent = self.path.parent
        info = parent.stat()
        if (parent.resolve() != parent or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or any(parent == Path(root) or Path(root) in parent.parents for root in self.sources.values())):
            raise CatalogUnavailable("Catalog requires a separate private directory")

    @contextmanager
    def _lock(self):
        self._parent()
        lock = Path(str(self.path) + ".lock")
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            self._safe(lock)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CatalogUnavailable("Catalog writer is busy") from None
            yield
        finally:
            os.close(fd)

    @contextmanager
    def _connect(self, readonly=False, *, upgrading=False):
        self._parent()
        self._safe(self.path)
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                self._safe(sidecar)
        conn = sqlite3.connect(self.path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                               uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA temp_store=MEMORY")
            state = conn.execute("SELECT * FROM catalog_state WHERE id=1").fetchone()
            if not state or state["version"] not in ((1, 2) if upgrading else (2,)) or state["directory"] != self.directory:
                raise CatalogUnavailable("Catalog source or schema mismatch")
            yield conn
        finally:
            conn.close()

    def initialize(self):
        with self._lock():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with sqlite3.connect(self.path) as conn:
                conn.executescript("""
                    CREATE TABLE catalog_state (
                        id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
                        directory TEXT NOT NULL, ready INTEGER NOT NULL,
                        rebuilt_at TEXT, updated_at TEXT);
                    CREATE TABLE candidate_groups (
                        id INTEGER PRIMARY KEY, system TEXT NOT NULL, code TEXT NOT NULL,
                        exp TEXT NOT NULL, visibility TEXT NOT NULL,
                        public INTEGER NOT NULL, count INTEGER NOT NULL CHECK(count>=0),
                        UNIQUE(system,code,exp,visibility));
                    CREATE TABLE group_tags (
                        group_id INTEGER REFERENCES candidate_groups(id) ON DELETE CASCADE,
                        tag TEXT NOT NULL, PRIMARY KEY(group_id,tag));
                    CREATE INDEX tags_lookup ON group_tags(tag,group_id);
                    CREATE TABLE result_entries (
                        filename TEXT PRIMARY KEY,
                        group_id INTEGER NOT NULL REFERENCES candidate_groups(id));
                """)
                conn.execute("INSERT INTO catalog_state VALUES(1,2,?,0,NULL,NULL)",
                             (self.directory,))
                self._create_query_schema(conn)

    def _create_query_schema(self, conn):
        conn.executescript('''BEGIN IMMEDIATE;
            CREATE TABLE catalog_sources(role TEXT PRIMARY KEY, directory TEXT NOT NULL);
            CREATE TABLE query_records(
                directory TEXT NOT NULL, filename TEXT NOT NULL, timestamp TEXT,
                code TEXT, system TEXT, selected_system TEXT,
                facts TEXT NOT NULL, evidence TEXT NOT NULL,
                PRIMARY KEY(directory,filename));
            CREATE INDEX query_scope ON query_records(directory,code,selected_system,timestamp);
            CREATE INDEX query_code_time ON query_records(directory,code,timestamp);
            CREATE INDEX query_system ON query_records(directory,selected_system,timestamp);
            CREATE INDEX query_time ON query_records(directory,timestamp);
            CREATE INDEX result_group_files ON result_entries(group_id,filename DESC);
            CREATE TABLE artifact_entries(filename TEXT PRIMARY KEY);
            CREATE TABLE artifact_uuids(filename TEXT NOT NULL REFERENCES artifact_entries(filename) ON DELETE CASCADE,
                result_uuid TEXT NOT NULL, PRIMARY KEY(filename,result_uuid));
            CREATE INDEX artifact_uuid ON artifact_uuids(result_uuid,filename);
        ''')
        conn.executemany('INSERT INTO catalog_sources VALUES(?,?)', self.sources.items())

    def upgrade(self):
        """Explicit derived-v1 upgrade; never performed by a reader or receipt."""
        with self._lock(), self._connect(upgrading=True) as conn:
            version = conn.execute('SELECT version FROM catalog_state').fetchone()[0]
            if version != 1:
                raise CatalogUnavailable('Expected a version 1 catalog')
            conn.execute('UPDATE catalog_state SET ready=0')
            conn.commit()
            self._create_query_schema(conn)
            conn.execute('UPDATE catalog_state SET version=2')
            conn.commit()

    @staticmethod
    def _name(filename):
        if (not filename or Path(filename).name != filename or "\\" in filename
                or not filename.endswith(".json")):
            raise ValueError("Expected a Result JSON basename")

    def _put(self, conn, filename, payload):
        self._name(filename)
        if not isinstance(payload, dict):
            raise ValueError("Expected a Result object")
        self._remove(conn, filename)
        # Use exactly the same confidentiality normalization as the Result loader.
        tags = sorted(set(_extract_confidential_tags(payload)))
        values = tuple(value if isinstance(value, str) else "" for value in
                       (payload.get("system"), payload.get("code"), payload.get("Exp")))
        visibility = json.dumps(tags, ensure_ascii=True)
        conn.execute("""INSERT INTO candidate_groups(system,code,exp,visibility,public,count)
                        VALUES(?,?,?,?,?,0) ON CONFLICT DO NOTHING""",
                     (*values, visibility, int(not tags)))
        group = conn.execute("""SELECT id FROM candidate_groups
                                WHERE system=? AND code=? AND exp=? AND visibility=?""",
                             (*values, visibility)).fetchone()[0]
        conn.executemany("INSERT OR IGNORE INTO group_tags VALUES(?,?)", [(group, tag) for tag in tags])
        conn.execute("INSERT INTO result_entries VALUES(?,?)", (filename, group))
        conn.execute("UPDATE candidate_groups SET count=count+1 WHERE id=?", (group,))
        self._put_report(conn, self.directory, filename, payload)

    @staticmethod
    def _put_report(conn, directory, filename, payload):
        facts, evidence = report_facts(payload)
        timestamp = extract_timestamp_from_filename(filename)
        current = payload.get('current_system')
        selected_system = current.get('system') if isinstance(current, dict) else payload.get('system')
        def text(value):
            return value if isinstance(value, str) else None
        conn.execute('''INSERT INTO query_records VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(directory,filename) DO UPDATE SET timestamp=excluded.timestamp,
            code=excluded.code,system=excluded.system,selected_system=excluded.selected_system,
            facts=excluded.facts,evidence=excluded.evidence''', (
                directory, filename, timestamp.isoformat() if timestamp else None,
                text(payload.get('code')), text(payload.get('system')), text(selected_system),
                json.dumps(facts), json.dumps(evidence)))

    @staticmethod
    def _remove(conn, filename):
        previous = conn.execute("SELECT group_id FROM result_entries WHERE filename=?", (filename,)).fetchone()
        if previous:
            conn.execute("DELETE FROM result_entries WHERE filename=?", (filename,))
            conn.execute("UPDATE candidate_groups SET count=count-1 WHERE id=?", (previous[0],))
            conn.execute("DELETE FROM candidate_groups WHERE id=? AND count=0", (previous[0],))

    @contextmanager
    def writer(self, *, complete=False):
        """Invalidate BEFORE changing JSON; leave invalid on any failed publication."""
        with self._lock(), self._connect() as conn:
            ready = conn.execute("SELECT ready FROM catalog_state WHERE id=1").fetchone()[0]
            if not complete:
                self._require_sources(conn)
            conn.execute("UPDATE catalog_state SET ready=0 WHERE id=1")
            conn.commit()
            try:
                yield conn
                conn.execute("""UPDATE catalog_state SET ready=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                                WHERE id=1""", (1 if complete else ready,))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def rebuild(self):
        """Explicit operator operation. Do not call from request rendering."""
        with self.writer(complete=True) as conn:
            conn.execute("DELETE FROM result_entries")
            conn.execute("DELETE FROM candidate_groups")
            conn.execute('DELETE FROM query_records')
            conn.execute('DELETE FROM artifact_entries')
            conn.execute('DELETE FROM catalog_sources')
            conn.executemany('INSERT INTO catalog_sources VALUES(?,?)', self.sources.items())
            for path in sorted(Path(self.directory).iterdir()):
                if not path.name.endswith(".json"):
                    continue
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Result rebuild does not follow links")
                with path.open(encoding="utf-8") as handle:
                    self._put(conn, path.name, json.load(handle))
            for role in ('estimates', 'artifacts'):
                root = self.sources.get(role)
                if not root:
                    continue
                for path in sorted(Path(root).iterdir()):
                    suffix = '.json' if role == 'estimates' else '.tgz'
                    if not path.name.endswith(suffix):
                        continue
                    if not stat.S_ISREG(path.lstat().st_mode):
                        raise ValueError('Catalog rebuild does not follow links')
                    if role == 'artifacts':
                        self._put_archive(conn, path.name)
                    else:
                        with path.open(encoding='utf-8') as handle:
                            payload = json.load(handle)
                        if not isinstance(payload, dict):
                            raise ValueError('Expected a Result object')
                        self._put_report(conn, root, path.name, payload)
            conn.execute("""UPDATE catalog_state SET rebuilt_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=1""")

    def replace(self, filename, payload, write_json):
        """Publish one replacement; callback must atomically save that filename."""
        self._name(filename)
        with self.writer() as conn:
            write_json()
            self._sync_directory()
            self._put(conn, filename, payload)

    def delete(self, filename, delete_json):
        """Internal lifecycle hook, not a new deletion endpoint or watcher."""
        self._name(filename)
        with self.writer() as conn:
            delete_json()
            self._sync_directory()
            self._remove(conn, filename)
            conn.execute('DELETE FROM query_records WHERE directory=? AND filename=?', (self.directory, filename))

    def replace_related(self, role, filename, payload, write_file):
        """Publish Estimate/report facts or archive names with the same dirty guard."""
        if role not in ('estimates', 'artifacts') or role not in self.sources:
            raise CatalogUnavailable('Catalog source is not configured')
        if Path(filename).name != filename or '\\' in filename:
            raise ValueError('Expected a basename')
        if role == 'estimates':
            self._name(filename)
            if not isinstance(payload, dict):
                raise ValueError('Expected an Estimate object')
        elif not filename.endswith('.tgz'):
            raise ValueError('Expected an archive basename')
        with self.writer() as conn:
            stored_name = write_file()
            fd = os.open(self.sources[role], os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if role == 'artifacts':
                if isinstance(stored_name, str):
                    if (Path(stored_name).name != stored_name or '\\' in stored_name
                            or not stored_name.endswith('.tgz')):
                        raise ValueError('Expected an archive basename')
                    filename = stored_name
                self._put_archive(conn, filename)
            elif self.sources[role] == self.directory:
                self._put(conn, filename, payload)
            else:
                self._put_report(conn, self.sources[role], filename, payload)

    def delete_related(self, role, filename, delete_file):
        if role not in ('estimates', 'artifacts') or role not in self.sources:
            raise CatalogUnavailable('Catalog source is not configured')
        if not filename or Path(filename).name != filename or '\\' in filename:
            raise ValueError('Expected a basename')
        with self.writer() as conn:
            delete_file()
            fd = os.open(self.sources[role], os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if role == 'artifacts':
                conn.execute('DELETE FROM artifact_entries WHERE filename=?', (filename,))
            else:
                conn.execute('DELETE FROM query_records WHERE directory=? AND filename=?',
                             (self.sources[role], filename))
                if self.sources[role] == self.directory:
                    self._remove(conn, filename)

    @staticmethod
    def _put_archive(conn, filename):
        conn.execute('INSERT OR IGNORE INTO artifact_entries VALUES(?)', (filename,))
        conn.execute('DELETE FROM artifact_uuids WHERE filename=?', (filename,))
        conn.executemany('INSERT OR IGNORE INTO artifact_uuids VALUES(?,?)',
                         ((filename, match.group()) for match in UUID_PATTERN.finditer(filename)))

    def _require_sources(self, conn):
        sources = dict(conn.execute('SELECT role,directory FROM catalog_sources'))
        if any(sources.get(role) != root for role, root in self.sources.items()):
            raise CatalogUnavailable('Catalog source binding needs rebuilding')

    @contextmanager
    def snapshot(self):
        from utils.result_query_reader import ResultQueryReader
        with self._connect(readonly=True) as conn:
            conn.execute('BEGIN')
            if not conn.execute('SELECT ready FROM catalog_state').fetchone()[0]:
                raise CatalogUnavailable('Catalog needs rebuilding')
            self._require_sources(conn)
            yield ResultQueryReader(conn, self.sources)

    def _sync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def candidates(self, *, public_only=True, authenticated=False, affiliations=(),
                   system=None, code=None, exp=None, page=1, page_size=50):
        page_size = min(100, max(1, int(page_size)))
        filters = {"system": system, "code": code, "exp": exp}
        visibility, params = "g.public=1", []
        if not public_only and authenticated:
            if "admin" in affiliations:
                visibility = "1=1"
            elif affiliations:
                unique = sorted(set(affiliations))
                visibility += " OR EXISTS(SELECT 1 FROM group_tags t WHERE t.group_id=g.id AND t.tag IN (" + ",".join("?" for _ in unique) + "))"
                params = unique
        def where(exclude=None):
            clauses, args = ["(" + visibility + ")"], list(params)
            for key, value in filters.items():
                if key != exclude and value:
                    clauses.append("g." + key + "=?")
                    args.append(value)
            return " AND ".join(clauses), args
        with self._connect(readonly=True) as conn:
            conn.execute("BEGIN")
            state = dict(conn.execute("SELECT * FROM catalog_state WHERE id=1").fetchone())
            if not state["ready"]:
                raise CatalogUnavailable("Catalog needs rebuilding")
            options = {}
            for field in filters:
                condition, args = where(field)
                options[field] = [dict(row) for row in conn.execute(
                    "SELECT g." + field + " AS value,SUM(g.count) AS count FROM candidate_groups g WHERE "
                    + condition + " AND g." + field + "<>'' GROUP BY g." + field + " ORDER BY g." + field, args)]
            condition, args = where()
            grouped = " FROM candidate_groups g WHERE " + condition + " GROUP BY g.system,g.code,g.exp"
            combinations = conn.execute("SELECT COUNT(*) FROM (SELECT 1" + grouped + ")", args).fetchone()[0]
            pages = max(1, (combinations + page_size - 1) // page_size)
            page = max(1, min(int(page), pages))
            rows = [dict(row) for row in conn.execute(
                "SELECT g.system,g.code,g.exp,SUM(g.count) AS count" + grouped
                + " ORDER BY g.system,g.code,g.exp LIMIT ? OFFSET ?", [*args, page_size, (page-1)*page_size])]
            total = conn.execute("SELECT COALESCE(SUM(g.count),0) FROM candidate_groups g WHERE " + condition, args).fetchone()[0]
            return {"options": options, "rows": rows, "total": total, "page": page,
                    "pages": pages, "updated_at": state["updated_at"], "rebuilt_at": state["rebuilt_at"]}
