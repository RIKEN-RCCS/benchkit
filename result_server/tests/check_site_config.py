#!/usr/bin/env python3
"""Fail CI when public portal systems are not runnable site definitions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_site_diagnostics():
    repo_root = _repo_root()
    sys.path.insert(0, str(repo_root / "result_server"))

    from utils.site_diagnostics import (  # pylint: disable=import-outside-toplevel
        build_site_config_preflight_failures,
        build_site_diagnostics,
    )

    return build_site_diagnostics, build_site_config_preflight_failures


def parse_args(argv: list[str]) -> argparse.Namespace:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Validate public site configuration. Systems listed in "
            "config/system_info.csv are visible to portal users and must also "
            "exist in config/system.csv with a queue defined in config/queue.csv."
        )
    )
    parser.add_argument(
        "--system-csv",
        default=str(repo_root / "config" / "system.csv"),
        help="Path to system.csv.",
    )
    parser.add_argument(
        "--queue-csv",
        default=str(repo_root / "config" / "queue.csv"),
        help="Path to queue.csv.",
    )
    parser.add_argument(
        "--system-info-csv",
        default=str(repo_root / "config" / "system_info.csv"),
        help="Path to system_info.csv.",
    )
    parser.add_argument(
        "--programs-dir",
        default=str(repo_root / "programs"),
        help="Path to programs directory for shared diagnostics.",
    )
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_site_diagnostics, build_site_config_preflight_failures = _load_site_diagnostics()

    diagnostics = build_site_diagnostics(
        system_csv_path=args.system_csv,
        queue_csv_path=args.queue_csv,
        system_info_csv_path=args.system_info_csv,
        programs_dir=args.programs_dir,
    )
    failures = build_site_config_preflight_failures(diagnostics)

    if failures:
        print("Site configuration preflight failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        "Site configuration preflight passed: every public system_info.csv "
        "system is registered in system.csv and has a queue defined in queue.csv."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
