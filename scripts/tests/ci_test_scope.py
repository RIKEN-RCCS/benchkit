#!/usr/bin/env python3
"""Select the lightweight CI path only for demonstrably non-executable edits."""

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


MAX_BLOB_BYTES = 2 * 1024 * 1024


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def without_header(data):
    """Ignore only initial // lines; line splicing must never hide source code."""
    text = data.decode("utf-8")
    if "\x00" in text or "\r" in text:
        raise ValueError("unsupported source encoding")
    lines = text.splitlines(keepends=True)
    count = 0
    for line in lines:
        if not line.startswith("//"):
            break
        if not line.endswith("\n") or line.rstrip().endswith(("\\", "??/")):
            raise ValueError("possible line continuation")
        count += 1
    if count == 0 or count == len(lines):
        raise ValueError("missing source header or body")
    return "".join(lines[count:])


def lightweight_edit(path, old, new):
    name = PurePosixPath(path)
    if (name.suffix == ".md" and (
        len(name.parts) == 1 or name.parts[0] == "docs"
        or (len(name.parts) == 3 and name.parts[0] == "programs" and name.name == "README.md")
    )) or path == "LICENSE":
        return True
    if name.suffix not in {".c", ".cc", ".cpp", ".h", ".hpp"}:
        return False
    # Removing header lines changes __LINE__; retain the original body location.
    if old.count(b"\n") != new.count(b"\n"):
        return False
    return without_header(old) == without_header(new)


def blob(oid):
    if int(git("cat-file", "-s", oid)) > MAX_BLOB_BYTES:
        raise ValueError("large file")
    return git("cat-file", "blob", oid)


def full_tests(base, head):
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha or "") for sha in (base, head)):
        return True
    try:
        # Missing history, rewritten history and empty changes all run the suite.
        git("merge-base", "--is-ancestor", base, head)
        changes = git("diff", "--raw", "-z", "--no-renames", "--abbrev=40", base, head).split(b"\0")
        if changes == [b""]:
            return True
        for i in range(0, len(changes) - 1, 2):
            old_mode, new_mode, old_oid, new_oid, status = changes[i].decode("ascii").split()
            path = changes[i + 1].decode("utf-8")
            if (old_mode, new_mode, status) != (":100644", "100644", "M"):
                return True
            if not lightweight_edit(path, blob(old_oid), blob(new_oid)):
                return True
        return False
    except (subprocess.CalledProcessError, ValueError, IndexError, OSError):
        return True


def select_scope(event_name, event, head):
    if not isinstance(event, dict):
        return True
    if event_name == "pull_request":
        base = event["pull_request"]["base"]["sha"]
    elif event_name == "push":
        if event.get("forced") or event.get("deleted"):
            return True
        base = event["before"]
        if event.get("after") != head:
            return True
    else:
        return True
    return full_tests(base, head)


def main():
    full = True
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        head = git("rev-parse", "HEAD").decode().strip()
        full = select_scope(os.environ.get("GITHUB_EVENT_NAME"), event, head)
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError):
        pass
    result = f"full={'true' if full else 'false'}\n"
    print(result.strip())
    print("Full suite selected" if full else "Documentation or same-line-count source header edits only")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(result)


if __name__ == "__main__":
    main()
