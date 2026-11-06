"""Offline import and recovery of an explicitly prepared CX snapshot, not live data.

No Redis discovery, service control, key generation or source mutation lives here.
The caller must freeze writers and prepare independently verified source copies.
"""

from collections import Counter
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import pickle
import struct
import time
import math

from .cx_persistence import CxPersistence
from .encrypted_sqlite import EncryptedDatabaseError
from .execution_profiles import ExecutionProfileStore


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _matching_profile_columns(source, destination, table):
    quoted = _identifier(table)
    before = source.execute(f"PRAGMA table_info({quoted})").fetchall()
    after = destination.execute(f"PRAGMA table_info({quoted})").fetchall()
    # cid is physical position, not part of a named column's definition.
    source_definition = {row[1]: tuple(row[2:]) for row in before}
    destination_definition = {row[1]: tuple(row[2:]) for row in after}
    if not before or source_definition != destination_definition:
        raise ValueError("Unsupported Profile snapshot table or columns")
    return tuple(row[1] for row in before)


def verify_profile_rows(source, destination):
    """Compare same-version Profile schemas/rows by name using existing connections.

    Extra destination tables belong to persistence and are not Profile data.
    Connections must be stable snapshots; this function performs only reads and
    never exposes row values in exceptions or its count-only result.
    """
    tables = [row[0] for row in source.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    total = 0
    for table in tables:
        columns = _matching_profile_columns(source, destination, table)
        selected = ','.join(_identifier(column) for column in columns)
        statement = f"SELECT {selected} FROM {_identifier(table)}"
        expected = Counter(tuple(row) for row in source.execute(statement))
        observed = Counter(tuple(row) for row in destination.execute(statement))
        if expected != observed:
            raise ValueError("Profile snapshot rows differ")
        total += sum(expected.values())
    if source.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
        if not destination.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            raise ValueError("Profile snapshot sequences differ")
        expected = dict(source.execute('SELECT name,seq FROM sqlite_sequence'))
        observed = dict(destination.execute('SELECT name,seq FROM sqlite_sequence'))
        if any(expected.get(table) != observed.get(table) for table in tables):
            raise ValueError("Profile snapshot sequences differ")
    return {'tables': len(tables), 'rows': total}


def _regular(path):
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Snapshot contains an unsafe file")
    return info


def _snapshot_files(roots):
    result = {}
    for role, root in roots.items():
        paths = root.rglob('*') if role in ('inputs', 'legacy_inputs') else root.iterdir()
        for path in paths:
            if path.is_dir() and not path.is_symlink() and role in ('inputs', 'legacy_inputs'):
                continue
            info = _regular(path)
            result[(role, path.relative_to(root).as_posix())] = (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return result


def _copy_profile(source, conn):
    """Migrate the readonly snapshot in memory, then copy rows without new IDs."""
    _regular(source)
    if any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Profile migration requires a standalone consistent snapshot')
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True)) as original, closing(sqlite3.connect(":memory:")) as memory:
        memory.row_factory = sqlite3.Row
        memory.execute('PRAGMA temp_store=MEMORY')
        original.execute("PRAGMA query_only=ON")
        original.backup(memory)
        version = memory.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        if version not in (11, 12):
            raise ValueError('Unsupported Profile snapshot version')
        if memory.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Profile snapshot integrity failed")

        class MemoryProfile(ExecutionProfileStore):
            def connect(self):
                return memory

            def _key(self):
                return None

        MemoryProfile(":memory:").migrate()
        if memory.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Profile snapshot contains orphan references")
        names = [row[0] for row in memory.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in names:
            quoted = _identifier(table)
            matched = _matching_profile_columns(memory, conn, table)
            conn.execute(f"DELETE FROM {quoted}")
            columns = ",".join(_identifier(column) for column in matched)
            marks = ",".join("?" for _ in matched)
            conn.executemany(f"INSERT INTO {quoted}({columns}) VALUES({marks})",
                             memory.execute(f"SELECT {columns} FROM {quoted}"))
        if memory.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            for name, seq in memory.execute("SELECT name,seq FROM sqlite_sequence"):
                conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (name,))
                conn.execute("INSERT INTO sqlite_sequence VALUES(?,?)", (name, seq))


def import_snapshot(destination, *, profile_copy, source_roots, identity=None, sessions=None,
                    session_copy=None, max_file_bytes=1024 ** 3, max_total_bytes=10 * 1024 ** 3,
                    preserve_legacy_files=False):
    """Import into a NEW destination, publish readiness only after complete checks.

    Identity and sessions are explicit in-memory exports, never a command that
    silently contacts Redis or deserializes arbitrary filesystem pickle files.
    ``sessions`` entries carry original absolute expiry and tagged JSON text.
    """
    if type(preserve_legacy_files) is not bool:
        raise ValueError('Explicit legacy preservation flag is required')
    if destination.path.exists():
        raise FileExistsError("Migration destination must not exist")
    roots = {role: Path(path).absolute() for role, path in source_roots.items()}
    if set(roots) != set(destination.roots):
        raise ValueError("Snapshot roots must match the destination bindings")
    for root in roots.values():
        if root.resolve() != root or not root.is_dir():
            raise ValueError("Snapshot requires canonical directories")
        if destination.path.is_relative_to(root):
            raise ValueError("Destination must be outside the snapshot")
    files_before = _snapshot_files(roots)
    profile_source = Path(profile_copy).absolute()
    profile_before = _regular(profile_source)
    if profile_before.st_size > min(max_file_bytes, 256 * 1024 * 1024):
        raise ValueError('Profile snapshot exceeds the in-memory migration limit')
    destination.initialize()
    # Mark even an interrupted, empty import unusable by the app factory.
    with destination._connect() as conn:
        conn.execute("UPDATE catalog_state SET ready=0")
        conn.commit()
    counts = {role: 0 for role in roots}
    retained = 0
    total = profile_before.st_size
    with destination._connect() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        # The same context used by receipt also keeps metadata updates atomic.
        from .cx_persistence import _transaction
        token = _transaction.set((str(destination.path), conn, destination.storage.key_file))
        try:
            _copy_profile(profile_source, conn)
            for role, root in roots.items():
                paths = sorted(root.rglob("*")) if role in ("inputs", "legacy_inputs") else sorted(root.iterdir())
                for path in paths:
                    if path.is_dir() and not path.is_symlink() and role in ("inputs", "legacy_inputs"):
                        continue
                    before = _regular(path)
                    name = path.relative_to(root).as_posix()
                    if before.st_size > max_file_bytes:
                        raise ValueError("Snapshot file exceeds configured limit")
                    total += before.st_size
                    if total > max_total_bytes:
                        raise ValueError("Snapshot exceeds configured total limit")
                    with path.open("rb") as source:
                        if role in ("results", "estimates"):
                            from .legacy_files import document_file_identity
                            if preserve_legacy_files and document_file_identity(role, name) is None:
                                destination.put(destination.LEGACY_FILES_ROLE, role + '/' + name,
                                                source, limit=max_file_bytes, conn=conn)
                                retained += 1
                                continue
                            if path.suffix != ".json":
                                raise ValueError("Unexpected non-JSON document in snapshot")
                            destination.put_document(role, name, source.read(), conn=conn, update_metadata=False)
                        else:
                            destination.put(role, name, source, limit=max_file_bytes, conn=conn)
                    after = _regular(path)
                    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                        raise ValueError("Snapshot changed while reading")
                    counts[role] += 1
            stems = {row[0].split("/", 1)[0] for row in conn.execute("SELECT name FROM cx_objects WHERE role='inputs'") if '/' in row[0]}
            stems.update(path.name for path in roots['inputs'].iterdir() if path.is_dir() and not path.is_symlink())
            for stem in sorted(stems):
                directories = [path.relative_to(roots['inputs'] / stem).as_posix()
                               for path in (roots['inputs'] / stem).rglob('*')
                               if path.is_dir() and not path.is_symlink()]
                destination.build_input_archive(stem, conn, directories=directories)
            exports = dict(identity or {})
            if set(exports) - {"users", "invitations", "guards"}:
                raise ValueError("Unknown identity namespace")
            exports["sessions"] = sessions or {}
            if session_copy is not None:
                exports["legacy_sessions"] = read_session_snapshot(session_copy)
            for namespace, records in exports.items():
                for key, record in records.items():
                    value, expires = record["value"], record.get("expires")
                    if (not isinstance(key, str) or not key or set(record) - {'value', 'expires'}
                            or (expires is not None and (type(expires) not in (int, float) or not math.isfinite(expires)))):
                        raise ValueError('Invalid identity/session snapshot envelope')
                    if namespace in ('users', 'invitations'):
                        if (not isinstance(value, dict) or not isinstance(value.get('email'), str)
                                or not isinstance(value.get('affiliations'), list)
                                or any(not isinstance(item, str) for item in value['affiliations'])):
                            raise ValueError('Invalid identity snapshot')
                        if namespace == 'users' and (value['email'] != key or not isinstance(value.get('totp_secret'), str)):
                            raise ValueError('Invalid user snapshot')
                    elif namespace in ('sessions', 'legacy_sessions'):
                        from flask.json.tag import TaggedJSONSerializer
                        if not isinstance(value, str) or not isinstance(TaggedJSONSerializer().loads(value), dict):
                            raise ValueError('Invalid session snapshot')
                    elif namespace == 'guards' and (type(value) is not int or value < 0 or expires is None):
                        raise ValueError('Invalid authentication guard snapshot')
                    conn.execute("INSERT INTO cx_values VALUES(?,?,?,?)", (namespace, key, json.dumps(value), expires))
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Migrated snapshot reference integrity failed")
            profile_after = _regular(profile_source)
            if (_snapshot_files(roots) != files_before or
                    (profile_before.st_dev, profile_before.st_ino, profile_before.st_size, profile_before.st_mtime_ns) !=
                    (profile_after.st_dev, profile_after.st_ino, profile_after.st_size, profile_after.st_mtime_ns)):
                raise ValueError('Source snapshot changed during import')
            conn.execute("UPDATE catalog_state SET ready=1,rebuilt_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            _transaction.reset(token)
    destination.check()
    return {"objects": counts, "legacy_files_preserved": retained, "bytes": total, "source_modified": False,
            "source_is_snapshot": True, "cross_store_atomic": False}


class _SessionUnpickler(pickle.Unpickler):
    """Decode a trusted legacy cache copy without allowing executable globals."""

    def find_class(self, module, name):
        import datetime
        import uuid
        from markupsafe import Markup
        allowed = {('datetime', 'datetime'): datetime.datetime,
                   ('datetime', 'timezone'): datetime.timezone,
                   ('datetime', 'timedelta'): datetime.timedelta,
                   ('uuid', 'UUID'): uuid.UUID, ('markupsafe', 'Markup'): Markup}
        if (module, name) not in allowed:
            raise ValueError("Unsupported legacy session value")
        return allowed[(module, name)]


def read_session_snapshot(directory):
    """Import MD5/SHA256-addressed legacy sessions without discovering SIDs."""
    import re
    from flask.json.tag import TaggedJSONSerializer
    root = Path(directory).absolute()
    if root.resolve() != root or not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError("Unsafe session snapshot directory")
    from .cx_identity import legacy_session_keys
    management = legacy_session_keys('__wz_cache_count')
    result = {}
    for path in sorted(root.iterdir()):
        info = _regular(path)
        if info.st_mode & 0o077 or info.st_size > 1024 * 1024 or not re.fullmatch('(?:[0-9a-f]{32}|[0-9a-f]{64})', path.name):
            raise ValueError("Unsupported session snapshot file")
        if path.name in management:
            continue
        raw = path.read_bytes()
        if len(raw) < 4:
            raise ValueError("Truncated session snapshot")
        expires = struct.unpack('I', raw[:4])[0]
        if expires and expires <= time.time():
            continue
        value = _SessionUnpickler(io.BytesIO(raw[4:])).load()
        if not isinstance(value, dict):
            raise ValueError("Unsupported session payload")
        result[path.name] = {'value': TaggedJSONSerializer().dumps(value), 'expires': expires or None}
    return result


def export_identity(user_store):
    """Read only the caller-supplied, frozen Redis user namespace into memory.

    This helper does not discover credentials or open a connection. Its returned
    object contains secrets and must never be logged. Runtime cutover must freeze
    auth writers as well as result/trigger writers before calling this function.
    """
    if not user_store.prefix or any(char in user_store.prefix for char in '*?[]\r\n\x00'):
        raise ValueError('An explicit identity namespace is required')
    users = {user['email']: {'value': user, 'expires': None} for user in user_store.list_users()}
    invitations = {}
    prefix = user_store._invitation_key('')
    for key in user_store.r.scan_iter(match=prefix + '*'):
        token = key[len(prefix):]
        started = time.time()
        value = user_store.get_invitation(token)
        ttl = user_store.r.ttl(key)
        if ttl == -1:
            raise ValueError("Invitation snapshot lacks an expiry")
        if value is not None and ttl > 0:
            invitations[token] = {'value': value, 'expires': started + ttl}
    guards = {}
    for suffix in ('totp_used:*', 'login_attempts:*', 'rate:*'):
        for key in user_store.r.scan_iter(match=user_store.prefix + suffix):
            started = time.time()
            value = user_store.r.get(key)
            ttl = user_store.r.ttl(key)
            if ttl == -1:
                raise ValueError('Authentication guard snapshot lacks an expiry')
            if value is not None and ttl > 0:
                guards[key] = {'value': int(value), 'expires': started + ttl}
    return {'users': users, 'invitations': invitations, 'guards': guards}


def recover_copy(source, destination):
    """Restore encrypted DB to a new path; never overwrite a DB or copy its key."""
    return source.backup(destination)
