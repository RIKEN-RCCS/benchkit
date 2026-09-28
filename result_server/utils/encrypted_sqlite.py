"""SQLCipher-only storage primitives. Never fall back to unencrypted SQLite."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import stat


class EncryptedDatabaseError(RuntimeError):
    """A deliberately value-free storage error suitable for an operator report."""


def _private_parent(path: Path) -> None:
    parent = path.parent
    info = parent.stat()
    if (path != path.resolve() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o077):
        raise EncryptedDatabaseError("Storage requires a private, non-symlink directory")


def _check_file(info) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o077):
        raise EncryptedDatabaseError("Storage file permissions or type are unsafe")


def generate_key(path: str | Path) -> None:
    """Create a random 256-bit key, without displaying it or replacing a key."""
    path = Path(path).absolute()
    try:
        _private_parent(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(secrets.token_bytes(32))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise EncryptedDatabaseError("Could not create a new key file") from None


def _read_key(path: Path) -> bytes:
    try:
        _private_parent(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            _check_file(os.fstat(handle.fileno()))
            key = handle.read(33)
        if len(key) != 32:
            raise EncryptedDatabaseError("Key file must contain exactly 32 random bytes")
        return key
    except OSError:
        raise EncryptedDatabaseError("Encryption key is unavailable") from None


def _driver():
    try:
        from sqlcipher3 import dbapi2
    except (ImportError, OSError):
        raise EncryptedDatabaseError("SQLCipher driver is required") from None
    return dbapi2


class EncryptedSQLite:
    """Open an existing encrypted database; creation is always explicit.

    Parent directories must already exist with private permissions. Callers own
    schema lifecycle and authorization. No keys or open connections are cached.
    """

    def __init__(self, path: str | Path, key_file: str | Path):
        self.path = Path(path).absolute()
        self.key_file = Path(key_file).absolute()
        if self.path.parent == self.key_file.parent:
            raise EncryptedDatabaseError("Keep the key outside the database directory")

    @contextmanager
    def connect(self, *, create: bool = False, readonly: bool = False):
        if create and readonly:
            raise EncryptedDatabaseError("Cannot create a read-only database")
        db = _driver()
        key = _read_key(self.key_file)
        conn = None
        try:
            _private_parent(self.path)
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if create:
                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            fd = os.open(self.path, flags, 0o600)
            with os.fdopen(fd, "rb") as handle:
                _check_file(os.fstat(handle.fileno()))
                if not create and os.fstat(handle.fileno()).st_size == 0:
                    raise EncryptedDatabaseError("Database is not initialized")
                if handle.read(16) == b"SQLite format 3\x00":
                    raise EncryptedDatabaseError("Plaintext databases are not accepted")
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    if sidecar.is_symlink():
                        raise EncryptedDatabaseError("Database sidecar must not be a symlink")
                    _check_file(sidecar.stat())
            mode = "ro" if readonly else "rw"
            conn = db.connect(self.path.as_uri() + "?mode=" + mode, uri=True, timeout=5)
            # PRAGMA does not support placeholders. Only encoded random bytes
            # enter this statement, never user text or a passphrase.
            conn.execute(f'''PRAGMA key = "x'{key.hex()}'"''')
            key = b""
            version = conn.execute("PRAGMA cipher_version").fetchone()
            match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(version[0])) if version else None
            numbers = tuple(map(int, match.groups())) if match else ()
            if not numbers or numbers[0] != 4 or numbers < (4, 5, 1):
                raise EncryptedDatabaseError("SQLCipher 4.5.1 or newer within version 4 is required")
            conn.execute("PRAGMA cipher_log_level = NONE")
            conn.execute("PRAGMA cipher_compatibility = 4")
            conn.execute("PRAGMA cipher_plaintext_header_size = 0")
            conn.execute("PRAGMA cipher_memory_security = ON")
            conn.execute("PRAGMA temp_store = MEMORY")
            options = {row[0] for row in conn.execute("PRAGMA compile_options")}
            if not options.intersection({"TEMP_STORE=2", "TEMP_STORE=3"}):
                raise EncryptedDatabaseError("SQLCipher must use memory-backed temporary storage")
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            conn.row_factory = db.Row
            conn.execute("PRAGMA foreign_keys = ON")
            if create:
                if conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] != "wal":
                    raise EncryptedDatabaseError("Could not enable the database journal")
            conn.execute("PRAGMA synchronous = FULL")
            if readonly:
                conn.execute("PRAGMA query_only = ON")
            yield conn
        except (OSError, db.Error):
            raise EncryptedDatabaseError("Encrypted database operation failed") from None
        finally:
            key = b""
            if conn is not None:
                conn.close()

    def check(self) -> None:
        """Verify both encrypted page authentication and logical consistency."""
        with self.connect(readonly=True) as conn:
            self._check_connection(conn)

    @staticmethod
    def _check_connection(conn) -> None:
        if conn.execute("PRAGMA cipher_integrity_check").fetchall():
            raise EncryptedDatabaseError("Encrypted page integrity check failed")
        if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
            raise EncryptedDatabaseError("Database integrity check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise EncryptedDatabaseError("Database reference integrity check failed")

    def backup(self, destination: str | Path) -> None:
        """Take a consistent encrypted backup; key material is never copied."""
        target = EncryptedSQLite(destination, self.key_file)
        with self.connect(readonly=True) as source:
            with target.connect(create=True) as output:
                source.backup(output)
                self._check_connection(output)
