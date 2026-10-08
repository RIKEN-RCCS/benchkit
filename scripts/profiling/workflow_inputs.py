"""Merge execution-scoped input observations into the input metadata contract."""

import json
import os
from pathlib import Path
import sys
import tempfile


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as stream:
            temporary = stream.name
            stream.write(value)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    info_path, items_path = map(Path, sys.argv[1:3])
    exp = sys.argv[3]
    info = json.loads(info_path.read_text()) if info_path.exists() else {"schema_version": 1, "inputs": []}
    for filename in sys.argv[4:]:
        for entry in json.loads(Path(filename).read_text()).get("inputs", []):
            item = dict(entry, result_exp=exp)
            if item not in info["inputs"]:
                info["inputs"].append(item)
    write(info_path, json.dumps(info) + "\n")
    write(items_path, "".join(json.dumps(item) + "\n" for item in info["inputs"]))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError):
        print("Benchkit input: unable to associate input observations", file=sys.stderr)
        sys.exit(1)
