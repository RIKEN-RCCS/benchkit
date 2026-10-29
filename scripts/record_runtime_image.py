"""Observe an image and atomically supplement an existing run snapshot.

Usage: python3 scripts/record_runtime_image.py IMAGE SNAPSHOT [UNAVAILABLE_REASON]
The caller selects the image, snapshot, timing, and process time limit. An
explicit unavailable reason skips image reads and clears any previous digest.
Only toolchain.container is replaced; other snapshot evidence is preserved.
This records file identity, not publisher verification or container execution.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def observe(image):
    record = {"image_path": str(image), "image_sha256sum": "",
              "observation_status": "unavailable"}
    try:
        fd = os.open(str(image), os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("not a regular image")
            digest = hashlib.sha256()
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
            after = os.fstat(handle.fileno())
        current = image.stat()
        if identity(before) != identity(after) or identity(after) != identity(current):
            record["observation_status"] = "changed"
        else:
            record.update(image_sha256sum=digest.hexdigest(), observation_status="observed")
    except FileNotFoundError:
        record["observation_status"] = "missing"
    except (OSError, ValueError):
        pass
    return record


def record_image(image, snapshot, unavailable=None):
    data = json.loads(snapshot.read_text()) if snapshot.exists() else {"schema_version": 1}
    if not isinstance(data, dict) or not isinstance(data.get("toolchain", {}), dict):
        raise ValueError("invalid runtime snapshot")
    data.setdefault("toolchain", {})["container"] = (
        {"image_path": str(image), "image_sha256sum": "", "observation_status": unavailable}
        if unavailable else observe(Path(image)))
    fd, name = tempfile.mkstemp(prefix=".sif-observation-", dir=str(snapshot.parent))
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, sort_keys=True)
            output.write("\n")
        os.replace(name, str(snapshot))
    finally:
        if os.path.exists(name):
            os.unlink(name)


if __name__ == "__main__":
    try:
        record_image(sys.argv[1], Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else None)
    except (OSError, ValueError, IndexError):
        print("Benchkit: runtime image observation could not be stored", file=sys.stderr)
        sys.exit(1)
