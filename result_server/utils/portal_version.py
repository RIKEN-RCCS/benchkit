"""Portal release/version helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


RELEASE_NOTES = [
    {
        "version": "v2026.08.31",
        "date": "2026-08-31",
        "title": "Initial public CX Portal baseline",
        "summary": (
            "Initial public portal surface with result browsing, comparison, "
            "system information, and release visibility."
        ),
        "changes": [
            "Browse public benchmark results from the portal.",
            "Open public-safe result detail pages.",
            "Compare selected public results.",
            "Browse connected system summaries.",
            "Show the deployed portal version in the shared footer.",
            "Open a public Changes page with broad release notes.",
        ],
    }
]


def _find_git_root(start_path: Path) -> Path | None:
    current = start_path.resolve()
    if current.is_file():
        current = current.parent
    for path in (current, *current.parents):
        if (path / ".git").exists():
            return path
    return None


def _run_git(args: list[str], git_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=git_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def portal_version_info(
    env: dict[str, str] | None = None,
    *,
    start_path: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Return the release label and source commit displayed by the portal."""
    source = env if env is not None else os.environ
    explicit_version = (
        source.get("RESULT_SERVER_VERSION", "").strip()
        or source.get("BENCHKIT_PORTAL_VERSION", "").strip()
    )

    git_root = _find_git_root(Path(start_path or __file__))
    commit = ""
    git_label = ""
    if git_root is not None:
        commit = _run_git(["rev-parse", "--short=12", "HEAD"], git_root)
        git_label = _run_git(["describe", "--tags", "--exact-match", "HEAD"], git_root)
        if not git_label:
            git_label = _run_git(["describe", "--tags", "--always", "--dirty"], git_root)

    if explicit_version:
        label = explicit_version
        source_name = "environment"
    elif git_label:
        label = git_label
        source_name = "git"
    else:
        label = "development"
        source_name = "default"

    return {
        "label": label,
        "commit": commit,
        "source": source_name,
    }


def portal_release_notes() -> list[dict[str, object]]:
    """Return broad-grained release notes for the public changes page."""
    return RELEASE_NOTES
