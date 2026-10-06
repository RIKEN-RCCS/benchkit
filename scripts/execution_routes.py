#!/usr/bin/env python3
"""Compatibility entry points for the shell/jq execution route validator."""

import csv
import json
import os
from pathlib import Path
import subprocess
import sys


class RouteError(ValueError):
    pass


def _validate(raw, systems, env, *, source="file", selected=""):
    if len(raw.encode("utf-8")) > 1024 * 1024:
        raise RouteError("execution route configuration is too large")
    try:
        result = subprocess.run(
            ["jq", "-nce", "--stream", "--arg", "systems_json", json.dumps(systems),
             "--arg", "systems_csv", "", "--arg", "source", source, "--arg", "selected", selected,
             "-f", str(Path(__file__).with_suffix(".jq"))],
            input=raw, text=True, capture_output=True,
            env={**os.environ, "CI_SERVER_URL": env.get("CI_SERVER_URL", ""),
                 "CI_PROJECT_PATH": env.get("CI_PROJECT_PATH", "")},
        )
        if result.returncode:
            raise RouteError("Execution route configuration is invalid")
        resolved = json.loads(result.stdout)
    except (OSError, ValueError):
        raise RouteError("Execution route configuration is invalid") from None
    if "error" in resolved:
        raise RouteError(resolved["error"])
    return resolved["resolved"]


def resolve_routes(config, systems, env):
    return _validate(json.dumps(config), systems, env)


def _systems(system_file):
    with open(system_file, newline="", encoding="utf-8") as handle:
        return {row["system"]: row["mode"] for row in csv.DictReader(handle)}


def load_routes(path, system_file, env):
    with open(path, encoding="utf-8") as handle:
        raw = handle.read(1024 * 1024 + 1)
    return _validate(raw, _systems(system_file), env)


def load_snapshot(raw, system_file, env, selected_system):
    return _validate(raw, _systems(system_file), env, source="snapshot", selected=selected_system)


def main():
    try:
        return subprocess.call(["bash", str(Path(__file__).with_suffix(".sh")), *sys.argv[1:]])
    except OSError:
        print("Execution route validator is unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
