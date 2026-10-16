#!/usr/bin/env python3
"""Run the complete SQLCipher test selection, optionally split across two jobs."""
from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys

import pytest


# The two route suites dominate this selection's measured test time.
# Keep all selected files here, once, including the default unsharded selection.
TEST_GROUPS = (
    ("test_budget_routes.py", "test_budget_group_routes.py"),
    ("test_budget_registry.py", "test_budget_groups.py", "test_db_migrations.py",
     "test_runner_observations.py", "test_runner_observation_ingest_storage.py",
     "test_runner_observation_handoff.py", "test_budget_profile_preview.py",
     "test_budget_pipeline.py", "test_budget_profile_binding.py",
     "test_sqlcipher_runtime_report.py"),
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--shard", type=int, choices=(0, 1))
    options, pytest_args = parser.parse_known_args(argv[1:])
    try:
        importlib.import_module("sqlcipher3.dbapi2")
    except ImportError:
        print("SQLCipher is required for encrypted database tests", file=sys.stderr)
        return 2
    names = (sum(TEST_GROUPS, ()) if options.shard is None else TEST_GROUPS[options.shard])
    if not names or len(names) != len(set(names)):
        print("Encrypted database test selection is empty or duplicated", file=sys.stderr)
        return 2
    directory = Path(__file__).resolve().parent
    paths = [directory / name for name in names]
    if not all(path.is_file() for path in paths):
        print("An encrypted database test file is missing", file=sys.stderr)
        return 2
    return pytest.main([*(str(path) for path in paths), *(pytest_args or ["-q"])])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
