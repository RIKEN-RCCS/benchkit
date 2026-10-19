#!/usr/bin/env python3
"""Manually review an application method version; never run estimation."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


APP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
MAX_BYTES = 2 * 1024 * 1024


def git(repository, *args, missing_ok=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")
    result = subprocess.run(
        ["git", "--no-pager", "--no-replace-objects", "--literal-pathspecs",
         "-C", str(repository), *args], env=env, capture_output=True, timeout=10,
    )
    if result.returncode and not (missing_ok and result.returncode == 1):
        raise ValueError("comparison data is not available in the local Git repository")
    return result.stdout


def committed_file(repository, commit, path):
    tree = git(repository, "ls-tree", "-z", commit, "--", path)
    if not tree:
        raise ValueError("file is missing")
    entry, name = tree.split(b"\t", 1)
    mode, kind, oid = entry.split()
    if mode not in (b"100644", b"100755") or kind != b"blob" or name != path.encode() + b"\0":
        raise ValueError("expected a regular file")
    if int(git(repository, "cat-file", "-s", oid.decode())) > MAX_BYTES:
        raise ValueError("file is too large")
    return git(repository, "cat-file", "blob", oid.decode())


def working_file(repository, path):
    target = repository / path
    if target.is_symlink() or not target.resolve().is_relative_to(repository):
        raise ValueError("expected a regular file inside the repository")
    if not target.is_file():
        raise ValueError("file is missing or is not a regular file")
    if target.stat().st_size > MAX_BYTES:
        raise ValueError("file is too large")
    return target.read_bytes()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def version(contents):
    data = json.loads(contents, object_pairs_hook=unique_object)
    value = data.get("version") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("version must be a nonempty string")
    return value


def compare(repository, app, base="HEAD"):
    """Compare one local commit with working files, including unstaged edits."""
    if not isinstance(app, str) or not APP_NAME.fullmatch(app):
        raise ValueError("invalid application name")
    repository = Path(repository).resolve()
    script = f"programs/{app}/estimate.sh"
    metadata = f"programs/{app}/estimate.metadata.json"
    # Refuse partial clones even when a Git version ignores GIT_NO_LAZY_FETCH.
    if git(repository, "config", "--local", "--get-regexp",
           r"^(extensions\.partialclone|remote\..*\.promisor)$", missing_ok=True):
        raise ValueError("partial clones are not supported; no objects will be fetched")
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
    result = {"base_commit": commit, "script_changed": None,
              "base_version": None, "working_version": None, "problems": []}
    scripts = []
    for label, read in (("base", lambda p: committed_file(repository, commit, p)),
                        ("working", lambda p: working_file(repository, p))):
        try:
            scripts.append(read(script))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["problems"].append(f"{label} estimate.sh: {exc}")
        try:
            result[label + "_version"] = version(read(metadata))
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
            result["problems"].append(f"{label} estimate.metadata.json: {exc}")
    if len(scripts) == 2:
        result["script_changed"] = scripts[0] != scripts[1]
    if result["problems"]:
        result["status"] = "unknown"
    elif result["base_version"] != result["working_version"]:
        result["status"] = "version_changed"
    elif result["script_changed"]:
        result["status"] = "review"
    else:
        result["status"] = "unchanged"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="application directory name under programs/")
    parser.add_argument("--base", default="HEAD", help="existing local comparison commit/ref (default: HEAD)")
    args = parser.parse_args()
    try:
        result = compare(Path(__file__).resolve().parents[1], args.app, args.base)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"Cannot compare application files: {exc}\n")
    if result["status"] == "review":
        print(f"{args.app}: estimate.sh changed, but method version remains {result['working_version']!r}. "
              "Check whether a version update is needed; comments/formatting may not require one.")
    elif result["status"] == "version_changed":
        print(f"{args.app}: method version changed from {result['base_version']!r} "
              f"to {result['working_version']!r}; no version-update reminder.")
    elif result["status"] == "unknown":
        print(f"{args.app}: cannot check the method version: " + "; ".join(result["problems"]))
    else:
        print(f"{args.app}: estimate.sh and the method version are unchanged; no version-update reminder.")
    # Review/unknown are informational: this tool never enforces a version bump.


if __name__ == "__main__":
    main()
