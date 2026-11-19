"""Regression tests for SQLite removing a sidecar during validation."""
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.encrypted_sqlite import EncryptedSQLite, SidecarValidationError
from utils.shared_db_access import SharedAccess


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    path.touch(mode=0o600)
    store = EncryptedSQLite(path, tmp_path / "keys" / "test")
    info = path.stat()
    return store, (info.st_dev, info.st_ino)


@pytest.mark.parametrize("suffix", ["-shm", "-wal"])
@pytest.mark.parametrize("replacement", ["absent", "valid", "unsafe", "symlink", "lost_again"])
def test_disappearance_during_validation(database, monkeypatch, suffix, replacement):
    store, identity = database
    sidecar = Path(str(store.path) + suffix)
    sidecar.touch(mode=0o600)
    original = store._validate_data
    checks = []

    def validate(path, info=None, **kwargs):
        if path == sidecar:
            checks.append(path)
            if len(checks) == 1 or replacement == "lost_again":
                path.unlink()
                if replacement == "symlink":
                    path.symlink_to(store.path)
                elif replacement != "absent":
                    path.touch(mode=0o600)
                    if replacement == "unsafe":
                        path.chmod(0o666)
                raise FileNotFoundError(errno.ENOENT, "missing", str(path))
        return original(path, info, **kwargs)

    monkeypatch.setattr(store, "_validate_data", validate)
    if replacement in ("absent", "valid"):
        store._validate_sidecar(suffix, identity)
    else:
        with pytest.raises(SidecarValidationError):
            store._validate_sidecar(suffix, identity)
    assert len(checks) == (1 if replacement in ("absent", "symlink") else 2)


@pytest.mark.parametrize("failure", ["other_path", "permission", "journal"])
def test_other_failures_do_not_retry(database, monkeypatch, failure):
    store, identity = database
    suffix = "-journal" if failure == "journal" else "-shm"
    sidecar = Path(str(store.path) + suffix)
    sidecar.touch(mode=0o600)
    checks = []

    def fail(path, *args, **kwargs):
        checks.append(path)
        if failure == "permission":
            raise PermissionError(errno.EACCES, "denied", str(path))
        missing = str(store.path.parent / "policy") if failure == "other_path" else str(path)
        raise FileNotFoundError(errno.ENOENT, "missing", missing)

    monkeypatch.setattr(store, "_validate_data", fail)
    with pytest.raises(SidecarValidationError):
        store._validate_sidecar(suffix, identity)
    assert checks == [sidecar]


@pytest.mark.skipif(not shutil.which("setfacl") or not Path("/usr/bin/getfacl").exists(),
                    reason="requires POSIX ACL tools")
def test_shared_sidecar_acl(database, monkeypatch):
    store, identity = database
    sidecar = Path(str(store.path) + "-wal")
    sidecar.touch(mode=0o600)
    uid = os.geteuid()
    access = SharedAccess(store.path, [uid])
    monkeypatch.setenv("RESULT_SERVER_SHARED_DB_POLICY", "test")
    monkeypatch.setattr("utils.shared_db_access.configured_access", lambda _: access)
    subprocess.run(["setfacl", "-m", f"u:{uid}:rw", sidecar], check=True)
    store._validate_sidecar("-wal", identity)
    subprocess.run(["setfacl", "-m", f"u:{uid}:r", sidecar], check=True)
    with pytest.raises(SidecarValidationError, match="acl_mismatch"):
        store._validate_sidecar("-wal", identity)
