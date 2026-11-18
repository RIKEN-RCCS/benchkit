"""Read-only public generations and atomic publication from the trusted DB role."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import shutil
import threading
import time
import uuid

from utils.result_catalog import ResultCatalog, CatalogUnavailable


class PublicCatalog(ResultCatalog):
    """A publisher-owned catalog mounted read-only for the public service."""
    def _safe(self, path):
        from flask import current_app
        info = path.lstat()
        if (path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != current_app.config['PUBLIC_EXPORT_OWNER_UID']
                or info.st_mode & 0o027):
            raise CatalogUnavailable('Unsafe public catalog')

    def _parent(self):
        from flask import current_app
        parent = self.path.parent
        info = parent.stat()
        if (parent.resolve() != parent or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != current_app.config['PUBLIC_EXPORT_OWNER_UID']
                or info.st_mode & 0o027):
            raise CatalogUnavailable('Unsafe public catalog directory')

    @contextmanager
    def _connect(self, readonly=False, *, upgrading=False):
        if not readonly or upgrading:
            raise CatalogUnavailable('Public catalog is read-only')
        with super()._connect(readonly=True) as connection:
            connection.execute('PRAGMA query_only=ON')
            yield connection


def grant_reader(path, reader_uid):
    permissions = 'rx' if Path(path).is_dir() else 'r'
    subprocess.run(['/usr/bin/setfacl','-m','u:'+str(reader_uid)+':'+permissions,str(path)],
                   check=True,capture_output=True)


def atomic_json(path, value, reader_uid=None):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output)
            output.flush()
            os.fchmod(output.fileno(), 0o640)
            os.fsync(output.fileno())
        if reader_uid is not None:
            grant_reader(temporary, reader_uid)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def read_current(root, maximum_age=300):
    root = Path(root)
    if (root / 'withdrawn').exists():
        raise ValueError('Publication withdrawn')
    path = root / 'current.json'
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError('Invalid public generation pointer')
    value = json.loads(path.read_text())
    identifier = value['generation']
    if not isinstance(identifier, str) or not re.fullmatch(r'g-[0-9a-f]{32}', identifier):
        raise ValueError('Invalid public generation')
    if time.time() >= value['expires_at']:
        raise ValueError('Publication lease expired')
    age = time.time() - value['checked_at']
    if not -30 <= age <= maximum_age:
        raise ValueError('Public generation expired')
    generation = root / 'generations' / identifier
    if generation.resolve() != generation or not generation.is_dir():
        raise ValueError('Public generation unavailable')
    return generation, value


class PublicApplication:
    """Capture one immutable generation per request, including streaming responses."""
    def __init__(self, root, owner_uid, prefix=""):
        self.prefix = prefix
        from utils.public_projection import validate_public_environment
        validate_public_environment()
        self.root = Path(root).resolve(strict=True)
        self.owner_uid = int(owner_uid)
        self.applications = {}
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        from werkzeug.wrappers import Response
        try:
            generation, pointer = read_current(self.root)
            with self.lock:
                app = self.applications.get(str(generation))
                if app is None:
                    from app import create_app
                    app = create_app(prefix=self.prefix,base_dir=str(generation),public_portal_mode=True,public_export=True)
                    app.config.update(RESULT_CATALOG_PATH=str(generation / 'index/catalog.sqlite3'),
                                      PUBLIC_EXPORT_OWNER_UID=self.owner_uid)
                    self.applications = {str(generation):app}
            environ['cx.public.checked_at'] = pointer['checked_at']
        except (OSError,ValueError,TypeError,KeyError):
            return Response('Public export unavailable',status=503)(environ,start_response)
        iterator = app(environ,start_response)
        def stream():
            try:
                for chunk in iterator:
                    try:
                        current, _ = read_current(self.root)
                    except (OSError, ValueError, KeyError):
                        break
                    if current != generation:
                        break
                    yield chunk
            finally:
                close = getattr(iterator, 'close', None)
                if close:
                    close()
        return stream()


class Publisher:
    """Publish approved content with a trusted reader supervisor.

    control.quiesce(timeout=5) must stop every reader, including children and
    outstanding responses, and return only after that group is empty.
    control.stage(expires_at=...) must supervise the writer independently and
    invoke expiry cleanup even if the writer crashes.
    control.activate(expires_at=...) must bound the lifetime of that group.
    expire() is the companion cleanup operation for that supervised deadline.
    """
    maximum_generations = 2
    maximum_age = 15 * 60
    maximum_bytes = 256 * 1024 * 1024

    def __init__(self, store, root, private_state, reader_uid=None, *, control, policy):
        if reader_uid is None or reader_uid <= 0 or reader_uid == os.geteuid():
            raise ValueError('A distinct reader identity is required')
        self.store = store
        self.root = Path(root)
        self.private_state = Path(private_state)
        self.reader_uid = reader_uid
        if any(not callable(getattr(control, name, None)) for name in ['quiesce','stage','activate']):
            raise ValueError('A reader supervisor is required')
        self.control = control
        self.policy = policy
        self.root.mkdir(mode=0o750, exist_ok=True)
        (self.root / 'generations').mkdir(mode=0o750, exist_ok=True)
        grant_reader(self.root, reader_uid)
        grant_reader(self.root / 'generations', reader_uid)

    def _retire(self):
        for path in list((self.root / 'generations').iterdir()) + list(self.root.glob('.pending-*')):
            if path.is_symlink() or not path.is_dir():
                raise ValueError('Unexpected publication entry')
            for item in [path, *path.rglob('*')]:
                if item.is_symlink():
                    raise ValueError('Unexpected publication link')
                subprocess.run(['/usr/bin/setfacl', '-b', str(item)], check=True, capture_output=True)
                item.chmod(0o700 if item.is_dir() else 0o600)
            shutil.rmtree(path)

    def _withdraw(self):
        atomic_json(self.root / 'withdrawn', {'withdrawn': True})
        started = time.monotonic()
        self.control.quiesce(timeout=5)
        if time.monotonic() - started > 5:
            raise RuntimeError('Reader shutdown deadline exceeded')
        (self.root / 'current.json').unlink(missing_ok=True)
        self._retire()

    def expire(self):
        """Trusted supervisor cleanup at the lease deadline, even without updates."""
        self.private_state.parent.mkdir(parents=True, exist_ok=True)
        with self.private_state.with_suffix('.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._withdraw()

    def update(self, fault=None, *, change=None):
        from utils.public_projection import export_public
        self.private_state.parent.mkdir(parents=True, exist_ok=True)
        with self.private_state.with_suffix('.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status': 'busy'}
            # Reclassification must use change(), so old readers are withdrawn
            # before the source transaction is committed. Failure never restores
            # an earlier pointer or resumes a reader against withdrawn content.
            self._withdraw()
            identifier = 'g-' + uuid.uuid4().hex
            pending = self.root / ('.pending-' + identifier)
            destination = self.root / 'generations' / identifier
            expiry = time.time() + self.maximum_age
            self.control.stage(expires_at=expiry)
            try:
                if change is not None:
                    change()
                manifest = export_public(self.store, pending, policy=self.policy,
                                         maximum_bytes=self.maximum_bytes, published_path=destination)
                if fault:
                    fault('after_export')
                for path in [pending, *pending.rglob('*')]:
                    if path.is_symlink():
                        raise ValueError('Publication link rejected')
                    path.chmod(0o750 if path.is_dir() else 0o640)
                    grant_reader(path, self.reader_uid)
                    if path.is_file():
                        with path.open('rb') as stream:
                            os.fsync(stream.fileno())
                os.replace(pending, destination)
                if time.time() >= expiry:
                    raise RuntimeError('Publication lease expired during generation')
                size = sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())
                if size > self.maximum_bytes:
                    raise ValueError('Publication exceeds capacity')
                atomic_json(self.root / 'current.json',
                            {'generation': identifier, 'checked_at': time.time(), 'expires_at': expiry}, self.reader_uid)
                if fault:
                    fault('before_activate')
                self.root.joinpath('withdrawn').unlink()
                self.control.activate(expires_at=expiry)
                atomic_json(self.private_state, {'generation': identifier})
                complete = getattr(self.control, 'complete', None)
                if complete is not None:
                    complete()
                return {'status': 'published', 'results': manifest['results'], 'archives': manifest['archives']}
            except BaseException:
                # Keep fail-closed state until a complete rebuild from current
                # approvals succeeds. No fallback to a stale successful export.
                self._withdraw()
                raise
