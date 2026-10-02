"""Initialize common metadata once per run, including across child shells."""

import argparse
import fcntl
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--kind", choices=("input", "timing"), required=True)
    parser.add_argument("--info", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    args = parser.parse_args()
    args.info.parent.mkdir(parents=True, exist_ok=True)
    state = args.info.with_name(f".{args.info.name}.session")
    with state.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        previous = handle.read()
        current = json.dumps([args.session, str(args.items.absolute())])
        if previous == current:
            return
        args.info.unlink(missing_ok=True)
        args.items.unlink(missing_ok=True)
        if args.kind == "timing":
            (args.info.parent / ".workflow_session.json").unlink(missing_ok=True)
        handle.seek(0)
        handle.truncate()
        handle.write(current)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print("Benchkit metadata: unable to initialize run records", file=sys.stderr)
        sys.exit(1)
