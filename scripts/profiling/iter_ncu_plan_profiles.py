#!/usr/bin/env python3
"""Emit NCU plan profiles as tab-separated rows for shell wrappers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _profile_section(profile: dict[str, Any]) -> str:
    section = profile.get("section")
    if section:
        return str(section)
    return ""


def _profile_pattern(profile: dict[str, Any]) -> str:
    match = profile.get("kernel_match")
    if isinstance(match, dict):
        pattern = match.get("pattern")
        if pattern:
            return str(pattern)
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path, help="input ncu_plan.json")
    args = parser.parse_args(argv)

    with args.plan.open(encoding="utf-8") as handle:
        plan = json.load(handle)

    profiles = plan.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        print(f"{args.plan} has no profiles", file=sys.stderr)
        return 1

    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        name = str(profile.get("name") or "").strip()
        pattern = _profile_pattern(profile)
        if not name or not pattern:
            continue
        section = _profile_section(profile)
        kernel_name = str(profile.get("kernel_name") or "")
        launch_skip = int(profile.get("launch_skip") or 0)
        launch_count = int(profile.get("launch_count") or 1)
        print("\t".join([name, section, pattern, str(launch_skip), str(launch_count), kernel_name]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
