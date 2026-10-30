"""Rebuildable, permission-filtered candidates, never a Result source of truth."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat

from utils.result_file import _extract_confidential_tags


class CatalogUnavailable(RuntimeError):
    """The derived catalog cannot currently provide trustworthy candidates."""


class ResultCatalog:
    """Private derived SQLite store; creation/rebuild is explicit, not on GET.

    One file is one stored Result, just as in the existing list loader. All
    participating writers serialize JSON replacement and index publication.
    A committed dirty flag bridges the filesystem/SQLite transaction boundary.
    """

    def __init__(self, path, directory):
        self.path = Path(path).absolute()
        self.directory = str(Path(directory).resolve(strict=True))

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
                or parent == Path(self.directory)):
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
    def _connect(self, readonly=False):
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
            if not state or state["version"] != 1 or state["directory"] != self.directory:
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
                conn.execute("INSERT INTO catalog_state VALUES(1,1,?,0,NULL,NULL)",
                             (self.directory,))

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
            for path in sorted(Path(self.directory).iterdir()):
                if not path.name.endswith(".json"):
                    continue
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Result rebuild does not follow links")
                with path.open(encoding="utf-8") as handle:
                    self._put(conn, path.name, json.load(handle))
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
