#!/usr/bin/env python3
"""Render a BenchKit NCU plan into concrete ``bk_profiler ncu`` commands.

This helper is deliberately dry-run friendly.  It does not run Nsight Compute;
it translates ``ncu_plan.json`` profiles into the environment variables and
``bk_profiler`` command lines that a site/app wrapper can execute on a GPU
node.  Keeping this step inspectable makes the automatic discovery flow safer
before we connect it to real runners.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any


def _shell_join(args: list[str]) -> str:
    return " ".join(shlex.quote(str(item)) for item in args)


def _profiler_args_env(args: list[str]) -> str:
    return " ".join(str(item) for item in args)


def _truth(value: Any) -> str:
    return "true" if bool(value) else "false"


def _profile_args(profile: dict[str, Any]) -> list[str]:
    match = profile.get("kernel_match") if isinstance(profile.get("kernel_match"), dict) else {}
    name_base = str(match.get("name_base") or "demangled")
    pattern = str(match.get("pattern") or "")
    if not pattern:
        raise ValueError(f"profile {profile.get('name')!r} is missing kernel_match.pattern")

    args = [
        "--kernel-name-base",
        name_base,
        "--kernel-name",
        pattern,
        "--launch-skip",
        str(int(profile.get("launch_skip") or 0)),
        "--launch-count",
        str(int(profile.get("launch_count") or 1)),
    ]
    return args


def _command_record(
    profile: dict[str, Any],
    *,
    level: str,
    archive_dir: Path,
    raw_dir_prefix: str,
    command: list[str],
) -> dict[str, Any]:
    name = str(profile.get("name") or "profile")
    archive = archive_dir / f"padata_{name}.tgz"
    raw_dir = f"{raw_dir_prefix}_{name}"
    profiler_args = _profile_args(profile)
    archive_report = bool(profile.get("archive_ncu_report", False))

    env = {
        "BK_PROFILER_ARGS": _profiler_args_env(profiler_args),
        "BK_PROFILER_NCU_RAW_CSV": "true",
        "BK_PROFILER_ARCHIVE_NCU_REPORT": _truth(archive_report),
    }
    argv = [
        "bk_profiler",
        "ncu",
        "--level",
        level,
        "--archive",
        str(archive),
        "--raw-dir",
        raw_dir,
        "--",
        *command,
    ]
    return {
        "name": name,
        "kernel_name": profile.get("kernel_name"),
        "section": profile.get("section"),
        "metric_set": profile.get("metric_set"),
        "archive": str(archive),
        "raw_dir": raw_dir,
        "env": env,
        "bk_profiler_args": profiler_args,
        "argv": argv,
        "selection": profile.get("selection") if isinstance(profile.get("selection"), dict) else {},
    }


def build_command_manifest(
    plan: dict[str, Any],
    *,
    level: str,
    archive_dir: Path,
    raw_dir_prefix: str,
    command: list[str],
) -> dict[str, Any]:
    profiles = plan.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("ncu plan has no profiles")

    commands = [
        _command_record(
            profile,
            level=level,
            archive_dir=archive_dir,
            raw_dir_prefix=raw_dir_prefix,
            command=command,
        )
        for profile in profiles
        if isinstance(profile, dict)
    ]
    return {
        "schema_version": 1,
        "source": {
            "plan_schema_version": plan.get("schema_version"),
            "plan_source": plan.get("source"),
        },
        "execution": {
            "tool": "bk_profiler",
            "profiler": "ncu",
            "level": level,
            "command": command,
        },
        "commands": commands,
    }


def print_shell(manifest: dict[str, Any]) -> None:
    for record in manifest["commands"]:
        for key, value in record["env"].items():
            print(f"export {key}={shlex.quote(str(value))}")
        print(_shell_join(record["argv"]))
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path, help="input ncu_plan.json")
    parser.add_argument("--out", type=Path, help="write command manifest JSON")
    parser.add_argument("--format", choices=["json", "shell"], default="shell", help="stdout format")
    parser.add_argument("--level", default="detailed", help="bk_profiler ncu level")
    parser.add_argument("--archive-dir", type=Path, default=Path("results"), help="archive directory")
    parser.add_argument("--raw-dir-prefix", default="ncu_plan", help="raw-dir prefix")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="profiled command after --")
    args = parser.parse_args(argv)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("profiled command is required after --")

    with args.plan.open(encoding="utf-8") as handle:
        plan = json.load(handle)

    manifest = build_command_manifest(
        plan,
        level=args.level,
        archive_dir=args.archive_dir,
        raw_dir_prefix=args.raw_dir_prefix,
        command=command,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print_shell(manifest)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
