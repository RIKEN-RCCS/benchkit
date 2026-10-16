"""One private pending batch, protected by a process lock and durable replaces."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid

from utils.runner_observation_protocol import MAX_BYTES, ProtocolError, validate_batch
from .errors import DeliveryError


MAX_STATE_BYTES = 6 * MAX_BYTES + 65536


def _check(info, mode, *, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != mode or (not directory and info.st_nlink != 1)):
        raise DeliveryError("unsafe_private_file")


@contextmanager
def private_directory(path):
    path = Path(path)
    if not path.is_absolute() or path != path.resolve():
        raise DeliveryError("unsafe_private_directory")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _check(os.fstat(fd), 0o700, directory=True)
        yield fd
    finally:
        os.close(fd)


def _read(directory, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as handle:
        _check(os.fstat(handle.fileno()), 0o600)
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise DeliveryError("private_file_too_large")
    return data


def read_delivery_key(path):
    try:
        path = Path(path)
        with private_directory(path.parent) as directory:
            key = _read(directory, path.name, 257).decode("ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", key):
            raise ValueError
        return key
    except (OSError, ValueError, UnicodeError, DeliveryError):
        raise DeliveryError("delivery_credential_unavailable") from None


def binding(policy, endpoint):
    return {"endpoint": endpoint, "collector_id": policy.collector_id,
            "source_id": policy.source_id, "generation": policy.generation,
            "targets": sorted([{"target_id": t.target_id, "server_id": t.server_id,
                                 **t.identity()} for t in policy.targets], key=lambda t: t["target_id"])}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class DeliveryState:
    def __init__(self, directory, policy, endpoint):
        self.directory = Path(directory)
        self.policy = policy
        self.binding = binding(policy, endpoint)

    @contextmanager
    def locked(self):
        try:
            with private_directory(self.directory) as directory:
                fd = os.open("delivery.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                             0o600, dir_fd=directory)
                with os.fdopen(fd, "rb") as lock:
                    _check(os.fstat(lock.fileno()), 0o600)
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise DeliveryError("delivery_busy") from None
                    yield directory
        except OSError:
            raise DeliveryError("delivery_state_unavailable") from None

    def initialize(self):
        """Explicit first-time initialization only; never reset missing state on run."""
        with self.locked() as directory:
            self.save(directory, {"schema_version": 1, "binding": self.binding,
                                  "next_sequence": 1, "pending": None}, create=True)

    def load(self, directory, *, now):
        try:
            value = json.loads(_read(directory, "delivery.json", MAX_STATE_BYTES), object_pairs_hook=_object)
            if (not isinstance(value, dict)
                    or set(value) != {"schema_version", "binding", "next_sequence", "pending"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1
                    or value["binding"] != self.binding
                    or type(value["next_sequence"]) is not int
                    or not 1 <= value["next_sequence"] <= 2**53 - 1):
                raise ValueError
            if value["pending"] is not None:
                pending = value["pending"]
                if not isinstance(pending, str):
                    raise ValueError
                batch = validate_batch(pending.encode("utf-8"), self.policy, received_at=now)
                if batch["sequence"] != value["next_sequence"]:
                    raise ValueError
            return value
        except (OSError, ValueError, UnicodeError, RecursionError, ProtocolError):
            raise DeliveryError("delivery_state_invalid") from None

    def save(self, directory, value, *, create=False):
        data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
        if len(data) > MAX_STATE_BYTES:
            raise DeliveryError("delivery_state_too_large")
        name = ".delivery-" + uuid.uuid4().hex
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if create:
                # Publish without replacing any state created by another invocation.
                os.link(name, "delivery.json", src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False)
                os.unlink(name, dir_fd=directory)
            else:
                self._read_current_before_replace(directory)
                os.replace(name, "delivery.json", src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass

    @staticmethod
    def _read_current_before_replace(directory):
        _read(directory, "delivery.json", MAX_STATE_BYTES)
