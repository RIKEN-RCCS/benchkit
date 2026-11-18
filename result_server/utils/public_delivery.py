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
    path = root / 'current.json'
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError('Invalid public generation pointer')
    value = json.loads(path.read_text())
    identifier = value['generation']
    if not isinstance(identifier, str) or not re.fullmatch(r'g-[0-9a-f]{32}', identifier):
        raise ValueError('Invalid public generation')
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
        return app(environ,start_response)


class Publisher:
    def __init__(self, store, root, private_state, reader_uid=None):
        self.store = store
        self.reader_uid = reader_uid
        self.root = Path(root)
        self.private_state = Path(private_state)
        self.root.mkdir(mode=0o750, exist_ok=True)
        (self.root / 'generations').mkdir(mode=0o750, exist_ok=True)
        self.root.chmod(0o750)
        (self.root / 'generations').chmod(0o750)
        if reader_uid is not None:
            grant_reader(self.root, reader_uid)
            grant_reader(self.root / 'generations', reader_uid)

    def update(self, fault=None):
        from utils.document_snapshot import document_snapshot
        from utils.public_projection import export_public
        self.private_state.parent.mkdir(mode=0o700, exist_ok=True)
        lock_path = self.private_state.with_suffix('.lock')
        with lock_path.open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status': 'busy'}
            with document_snapshot(self.store) as snapshot:
                rows = [tuple(row) for row in snapshot.conn.execute(
                    'SELECT role,name,sha256,generation FROM cx_objects ORDER BY role,name')]
                revision = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
                previous = json.loads(self.private_state.read_text()) if self.private_state.exists() else {}
                if previous.get('revision') == revision:
                    try:
                        generation, _ = read_current(self.root, maximum_age=float('inf'))
                        if not (generation / 'manifest.json').is_file():
                            raise ValueError('Public generation incomplete')
                        with sqlite3.connect((generation / 'index/catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as index:
                            if index.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                                raise ValueError('Public index failed verification')
                        if generation.name == previous.get('generation'):
                            atomic_json(self.root / 'current.json', {'generation': generation.name, 'checked_at': time.time()},self.reader_uid)
                            return {'status': 'unchanged'}
                    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
                        pass
                identifier = 'g-' + uuid.uuid4().hex
                pending = self.root / ('.pending-' + identifier)
                destination = self.root / 'generations' / identifier
                manifest = export_public(self.store, pending)
                if fault:
                    fault('after_export')
                # Only the derived public index contains these source bindings.
                with sqlite3.connect(pending / 'index/catalog.sqlite3') as connection:
                    for table in ('catalog_state', 'catalog_sources', 'query_records'):
                        connection.execute('UPDATE ' + table + ' SET directory=replace(directory,?,?)',
                                           (str(pending), str(destination)))
                for path in [pending, *pending.rglob('*')]:
                    if path.is_symlink():
                        raise ValueError('Public publication refuses symbolic links')
                    path.chmod(0o750 if path.is_dir() else 0o640)
                    if self.reader_uid is not None:
                        grant_reader(path,self.reader_uid)
                    if path.is_file():
                        with path.open('rb') as data:
                            os.fsync(data.fileno())
                os.replace(pending, destination)
                directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                if fault:
                    fault('before_pointer')
                atomic_json(self.root / 'current.json', {'generation': identifier, 'checked_at': time.time()},self.reader_uid)
                atomic_json(self.private_state, {'generation': identifier, 'revision': revision})
                self.private_state.chmod(0o600)
                return {'status': 'published', 'results': manifest['results'], 'archives': manifest['archives']}
