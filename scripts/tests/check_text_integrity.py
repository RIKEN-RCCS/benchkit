#!/usr/bin/env python3
"""Check tracked text files for UTF-8 decode errors and replacement chars."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def tracked_text_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = []
    for raw_name in proc.stdout.split(b"\0"):
        if not raw_name:
            continue
        path = Path(raw_name.decode("utf-8", errors="surrogateescape"))
        if path.suffix.lower() in TEXT_SUFFIXES:
            paths.append(path)
    return paths


def main() -> int:
    failures: list[str] = []
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{path}: invalid UTF-8 at byte {exc.start}")
            continue
        except OSError as exc:
            failures.append(f"{path}: cannot read file: {exc}")
            continue

        if "\ufffd" in text:
            line = text.count("\n", 0, text.index("\ufffd")) + 1
            failures.append(f"{path}: contains U+FFFD replacement character at line {line}")

    if failures:
        print("Text integrity check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"Checked {len(tracked_text_files())} tracked text files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
