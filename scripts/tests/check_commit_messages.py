#!/usr/bin/env python3
"""Reject commit messages that expose known Claude session metadata."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ZERO_SHA = "0" * 40
DISALLOWED_PATTERNS = (
    (re.compile(r"(?im)^Claude-Session\s*:"), "Claude-Session trailer"),
    (re.compile(r"(?i)\b(?:https?://)?claude\.ai/code/session[^\s]*"), "claude.ai session URL"),
)


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def git_fetch(*refspecs: str) -> None:
    subprocess.run(["git", "fetch", "--no-tags", "origin", *refspecs], check=True)


def event_payload() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    with Path(event_path).open(encoding="utf-8") as handle:
        return json.load(handle)


def changed_commits() -> list[str]:
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    event = event_payload()

    if event_name == "pull_request":
        pull_request = event.get("pull_request") or {}
        number = pull_request.get("number")
        base = pull_request.get("base") or {}
        base_ref = base.get("ref")
        base_sha = base.get("sha")
        if not number or not base_ref or not base_sha:
            raise RuntimeError("pull_request.number, base.ref, or base.sha is missing")

        head_ref = f"refs/remotes/origin/pr/{number}/head"
        git_fetch(
            f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}",
            f"+refs/pull/{number}/head:{head_ref}",
        )
        revspec = f"{base_sha}..{head_ref}"
        return run_git("rev-list", "--reverse", revspec).splitlines()

    if event_name == "push":
        before = event.get("before")
        after = event.get("after")
        if not after or after == ZERO_SHA:
            return []
        if not before or before == ZERO_SHA:
            return [after]
        return run_git("rev-list", "--reverse", f"{before}..{after}").splitlines()

    return [run_git("rev-parse", "HEAD")]


def disallowed_metadata(message: str) -> list[str]:
    labels: list[str] = []
    for pattern, label in DISALLOWED_PATTERNS:
        if pattern.search(message):
            labels.append(label)
    return labels


def main() -> int:
    try:
        commits = changed_commits()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Could not determine commits to check: {exc}", file=sys.stderr)
        return 1

    violations: list[tuple[str, str]] = []
    for commit in commits:
        message = run_git("log", "-1", "--format=%B", commit)
        for label in disallowed_metadata(message):
            violations.append((commit, label))

    if violations:
        print("Disallowed commit metadata detected:", file=sys.stderr)
        for commit, label in violations:
            print(f"  - {commit[:12]}: {label}", file=sys.stderr)
        print(
            "Remove Claude-Session trailers or claude.ai/code/session URLs "
            "from commit messages before merging.",
            file=sys.stderr,
        )
        return 1

    print(f"Checked {len(commits)} commit message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
