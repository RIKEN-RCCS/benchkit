#!/usr/bin/env python3
"""Run the result_server pytest suite through a stable repo-local entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest


def split_test_files(suite_path: Path, count: int = 2) -> tuple[list[Path], ...]:
    """Balance file sizes without splitting file-scoped fixtures across jobs."""
    files = {path for pattern in ("test_*.py", "*_test.py")
             for path in suite_path.rglob(pattern) if path.is_file()}
    if count not in (2, 4):
        raise ValueError("Expected two or four test shards")
    groups = tuple([] for _ in range(count))
    sizes = [0] * count
    for path in sorted(files, key=lambda p: (-p.stat().st_size, p.relative_to(suite_path).as_posix())):
        shard = min(range(count), key=lambda index: sizes[index])
        groups[shard].append(path)
        sizes[shard] += path.stat().st_size
    return tuple(sorted(group) for group in groups)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--shard", type=int, choices=(0, 1, 2, 3))
    parser.add_argument("--shard-count", type=int, choices=(2, 4), default=2)
    options, pytest_args = parser.parse_known_args(argv[1:])
    if options.shard is not None and options.shard >= options.shard_count:
        parser.error("Shard index must be smaller than shard count")
    repo_root = Path(__file__).resolve().parents[2]
    suite_path = repo_root / "result_server" / "tests"
    if options.shard is None:
        paths = [suite_path]
    else:
        paths = split_test_files(suite_path, options.shard_count)[options.shard]
        if not paths:
            print("No test files selected for shard", file=sys.stderr)
            return 2
    return pytest.main([*(str(path) for path in paths), *(pytest_args or ["-q"])])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
