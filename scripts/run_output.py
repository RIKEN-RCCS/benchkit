"""Collect invocation-local rank-zero MPI output without scanning application data."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


MAX_ENTRIES = 10000
MAX_BYTES = 256 * 1024 * 1024
RANK_LOG = re.compile(r"(?:stdout|stderr)\.[0-9]+\.0$")


def identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def candidates(root):
    """Only conventional MPI output trees and top-level per-rank logs are eligible."""
    remaining = MAX_ENTRIES

    def visit(directory, depth):
        nonlocal remaining
        with os.scandir(directory) as entries:
            for entry in entries:
                remaining -= 1
                if remaining < 0:
                    raise ValueError("too many output entries")
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False) and RANK_LOG.fullmatch(entry.name):
                    yield Path(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    if depth == 0 and not entry.name.startswith("output."):
                        continue
                    if depth < 5:
                        yield from visit(entry.path, depth + 1)

    return sorted(visit(root, 0))


def read_log(path, remaining):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > remaining:
            raise ValueError("invalid or oversized rank output")
        data = handle.read(remaining + 1)
        if len(data) > remaining or identity(before) != identity(os.fstat(handle.fileno())):
            raise ValueError("rank output changed while collecting")
    return data, identity(before)


def snapshot(root, log):
    files = {}
    remaining = MAX_BYTES
    for path in candidates(root):
        if path.absolute() == log.absolute():
            continue
        data, info = read_log(path, remaining)
        remaining -= len(data)
        files[str(path.relative_to(root))] = {
            "identity": info, "sha256": hashlib.sha256(data).hexdigest(),
            "ends_line": not data or data.endswith(b"\n"),
        }
    return {"root": str(root), "files": files}


def collect(state, log):
    root = Path(state["root"])
    remaining = MAX_BYTES
    chunks = []
    for path in candidates(root):
        if path.absolute() == log.absolute():
            continue
        previous = state["files"].get(str(path.relative_to(root)))
        data, info = read_log(path, remaining)
        remaining -= len(data)
        if previous and info == previous["identity"] and hashlib.sha256(data).hexdigest() == previous["sha256"]:
            continue
        if previous and info[:2] == previous["identity"][:2]:
            old_size = previous["identity"][2]
            # Preserve only new bytes when a launcher appends to an existing log.
            if len(data) > old_size and hashlib.sha256(data[:old_size]).hexdigest() == previous["sha256"]:
                data = data[old_size:]
                if not previous["ends_line"]:
                    data = data.partition(b"\n")[2]
        if data:
            chunks.append(data)
    # Publish only after every selected file has been read successfully.
    with log.open("ab") as output:
        for data in chunks:
            output.write(b"\n")
            output.write(data)
            if not data.endswith(b"\n"):
                output.write(b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "collect"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "snapshot":
        args.state.write_text(json.dumps(snapshot(Path.cwd(), args.log)), encoding="utf-8")
    else:
        collect(json.loads(args.state.read_text(encoding="utf-8")), args.log)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError):
        print("Benchkit output: unable to collect invocation output", file=sys.stderr)
        sys.exit(1)
