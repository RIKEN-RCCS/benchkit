"""Explicit, single-instance migrations for encrypted SQLite backends.

This runner does not discover databases or define their sharing boundaries.
Other storage engines can implement the CLI contract with their own lifecycle.
"""

from dataclasses import dataclass
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any


class MigrationError(ValueError):
    """Value-free migration error suitable for CLI output."""


@dataclass(frozen=True)
class Migration:
    id: str
    source: int
    target: int
    apply: Callable[[Any], None]


class EncryptedSQLiteMigrator:
    """Coordinate one backend, one explicitly supplied DB, one transaction."""

    def __init__(self, backend):
        self.backend = backend

    def _state(self, conn):
        path = self.backend.storage.path
        info = path.stat()
        identity = f"{self.backend.kind}\0{path}\0{info.st_dev}\0{info.st_ino}"
        return {**self.backend.status(conn), "instance_id": sha256(identity.encode()).hexdigest()}

    def status(self):
        with self.backend.storage.connect(readonly=True) as conn:
            conn.execute("BEGIN")
            return self._state(conn)

    def _plan(self, conn):
        state = self._state(conn)
        steps = []
        version = state["schema_version"]
        seen = set()
        while version != self.backend.target_version:
            step = next((item for item in self.backend.migrations if item.source == version), None)
            if step is None or version in seen or step.target <= version:
                raise MigrationError("No supported forward migration path")
            seen.add(version)
            steps.append(step)
            version = step.target
        self.backend.preflight(conn)
        return state, steps

    def plan(self):
        with self.backend.storage.connect(readonly=True) as conn:
            conn.execute("BEGIN")
            state, steps = self._plan(conn)
            return {**state, "target_version": self.backend.target_version,
                    "steps": [dict(id=step.id, source=step.source, target=step.target) for step in steps],
                    "requires_compatible_clients": bool(steps), "exclusive_writes": bool(steps),
                    "backup_required": bool(steps)}

    def verify(self):
        with self.backend.storage.connect(readonly=True) as conn:
            conn.execute("BEGIN")
            self.backend.verify(conn)
            return {**self._state(conn), "verified": True}

    def _apply(self, conn, steps):
        if steps:
            conn.execute("""CREATE TABLE IF NOT EXISTS db_migration_history (
                id TEXT PRIMARY KEY, source_version INTEGER NOT NULL,
                target_version INTEGER NOT NULL, applied_at TEXT NOT NULL)""")
        for step in steps:
            step.apply(conn)
            if self.backend.status(conn)["schema_version"] != step.target:
                raise MigrationError("Migration did not reach its declared version")
            conn.execute("INSERT INTO db_migration_history VALUES (?, ?, ?, ?)",
                         (step.id, step.source, step.target, datetime.now(UTC).isoformat()))
        self.backend.verify(conn)
        return {**self._state(conn), "applied": [step.id for step in steps], "verified": True}

    def migrate(self, *, backup, expected_version, expected_revision, expected_instance):
        with self.backend.storage.connect() as conn:
            with conn:
                # No DB write precedes the backup. A second, read-only connection
                # copies the committed state while this lock excludes all writers.
                conn.execute("BEGIN IMMEDIATE")
                state, steps = self._plan(conn)
                if (type(expected_version) is not int or type(expected_revision) is not int
                        or state["schema_version"] != expected_version or state["revision"] != expected_revision
                        or state["instance_id"] != expected_instance):
                    raise MigrationError("Database changed; inspect and plan again")
                if steps:
                    self.backend.storage.backup(backup)
                return self._apply(conn, steps)

    def rehearse(self, *, destination):
        # The backup API creates a new encrypted file and refuses all overwrites.
        # The source is read-only; all schema changes and history go into the copy.
        self.plan()
        self.backend.storage.backup(destination)
        copy = self.backend.copy_at(destination)
        runner = EncryptedSQLiteMigrator(copy)
        with copy.storage.connect() as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                state, steps = runner._plan(conn)
                result = runner._apply(conn, steps)
        return {**result, "rehearsal": True, "source_version": state["schema_version"]}
