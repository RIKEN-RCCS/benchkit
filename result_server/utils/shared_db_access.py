"""Opt-in ACL checks for exact shared DB paths. Private DB/key checks stay strict."""
import json
import os
from pathlib import Path
import stat
import subprocess


class SharedAccess:
    def __init__(self, database, writers):
        self.database = Path(database)
        self.writers = set(writers)

    def validate(self, path, info, *, directory=False):
        from .encrypted_sqlite import EncryptedDatabaseError
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if (not expected(info.st_mode) or info.st_uid not in self.writers or info.st_mode & 0o007
                or (not directory and info.st_nlink != 1) or path.resolve() != path):
            raise EncryptedDatabaseError('Unsafe shared database ownership or type')
        # Inspect the observed inode, even when SQLite unlinks its name concurrently.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            current = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                error = EncryptedDatabaseError('Shared database identity changed')
                error.reason = 'identity_changed'
                raise error
            try:
                result = subprocess.run(
                    ['/usr/bin/getfacl', '--absolute-names', '--omit-header', '--numeric',
                     '/proc/self/fd/' + str(descriptor)], pass_fds=(descriptor,),
                    capture_output=True, text=True)
            except OSError:
                error = EncryptedDatabaseError('Unable to run shared database ACL inspection')
                error.reason = 'acl_inspection_failed'
                raise error from None
            if result.returncode:
                error = EncryptedDatabaseError('Unable to inspect shared database ACL')
                error.reason = 'acl_inspection_failed'
                raise error
        finally:
            os.close(descriptor)
        entries = {}
        for line in result.stdout.splitlines():
            line = line.split('#',1)[0].strip()
            if line and not line.startswith('default:'):
                name, permission = line.rsplit(':',1)
                entries[name] = permission
        mask = entries.get('mask:','---')
        for name, permission in list(entries.items()):
            if name.startswith('user:') and name != 'user:':
                entries[name] = ''.join(letter if letter in permission and letter in mask else '-' for letter in 'rwx')
        permissions = 'rwx' if directory else 'rw-'
        expected_entries = {'user:':permissions,'group:':'---','other:':'---','mask:':permissions}
        expected_entries.update({'user:'+str(uid):permissions for uid in self.writers})
        if entries != expected_entries:
            error = EncryptedDatabaseError('Shared database ACL differs from explicit policy')
            error.reason = 'acl_mismatch'
            raise error
        if directory:
            defaults = {}
            for line in result.stdout.splitlines():
                line = line.split('#',1)[0].strip()
                if line.startswith('default:'):
                    name, permission = line[len('default:'):].rsplit(':',1)
                    defaults[name] = permission
            if defaults != expected_entries:
                raise EncryptedDatabaseError('Shared database default ACL is incomplete')


def configured_access(database):
    from .encrypted_sqlite import EncryptedDatabaseError
    configured = os.environ.get('RESULT_SERVER_SHARED_DB_POLICY')
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute() or path.resolve() != path:
        raise EncryptedDatabaseError('Shared database policy path is unsafe')
    for parent in path.parents:
        info = parent.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise EncryptedDatabaseError('Shared database policy requires root-controlled parents')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1:
        raise EncryptedDatabaseError('Shared database policy must be root controlled')
    value = json.loads(path.read_text())
    if value.get('version') != 1:
        raise EncryptedDatabaseError('Unsupported shared database policy')
    entry = value.get('databases',{}).get(str(database))
    if entry is None:
        return None
    writers = entry.get('writers')
    if (not isinstance(writers,list) or not writers or
            any(type(uid) is not int or uid <= 0 for uid in writers) or os.geteuid() not in writers):
        raise EncryptedDatabaseError('Shared database caller is outside explicit policy')
    return SharedAccess(database,writers)
