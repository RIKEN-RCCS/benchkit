#!/usr/bin/env python3
"""Fail pull-request policy checks when the tested base SHA is stale."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        print("Not a pull_request event; PR base freshness check skipped.")
        return 0

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("GITHUB_EVENT_PATH is not set", file=sys.stderr)
        return 1

    with Path(event_path).open(encoding="utf-8") as handle:
        event = json.load(handle)

    pull_request = event.get("pull_request") or {}
    base = pull_request.get("base") or {}
    base_ref = base.get("ref")
    tested_base_sha = base.get("sha")
    if not base_ref or not tested_base_sha:
        print("pull_request.base.ref or pull_request.base.sha is missing", file=sys.stderr)
        return 1

    subprocess.run(
        [
            "git",
            "fetch",
            "--no-tags",
            "--depth=1",
            "origin",
            f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}",
        ],
        check=True,
    )
    current_base_sha = run_git("rev-parse", f"refs/remotes/origin/{base_ref}")

    if current_base_sha != tested_base_sha:
        print(
            f"PR base is stale: this run tested {base_ref} at {tested_base_sha}, "
            f"but origin/{base_ref} is now {current_base_sha}.",
            file=sys.stderr,
        )
        print("Update/rebase the PR branch or rerun CI after refreshing the base.", file=sys.stderr)
        return 1

    print(f"PR base is current: {base_ref} {tested_base_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
