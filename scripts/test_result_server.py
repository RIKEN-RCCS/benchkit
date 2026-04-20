#!/usr/bin/env python3
"""Run the result_server pytest suite through a stable repo-local entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    suite_path = repo_root / "result_server" / "tests"

    if len(argv) > 1:
        args = [str(suite_path), *argv[1:]]
    else:
        args = [str(suite_path), "-q"]

    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
