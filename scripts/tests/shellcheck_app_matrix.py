#!/usr/bin/env python3
"""Group NUL-delimited changed application paths for ShellCheck jobs."""

import json
import os
from pathlib import Path, PurePosixPath
import sys


def app_matrix(paths):
    apps = {}
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        path = os.fsdecode(raw)
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or parts[0] != "programs" or not path.endswith(".sh"):
            raise ValueError("Unexpected application shell path")
        apps.setdefault(parts[1], set()).add(path)
    return {"include": [{"app": app, "files": sorted(files)}
                        for app, files in sorted(apps.items())]}


if __name__ == "__main__":
    matrix = app_matrix(sys.stdin.buffer.read())
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("matrix=" + json.dumps(matrix) + "\n")
        output.write("has_changes=" + ("true" if matrix["include"] else "false") + "\n")
