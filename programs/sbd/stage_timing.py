"""Persist sequential SBD workflow timings independently of application FOM."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_document(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            json.dump(document, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--exp", default="")
    start = commands.add_parser("start")
    start.add_argument("stage")
    start.add_argument("--profile", default="")
    finish = commands.add_parser("finish")
    finish.add_argument("id")
    finish.add_argument("exit_code", type=int)
    args = parser.parse_args()

    if args.command == "init":
        write_document(args.path, {
            "schema_version": 1,
            "kind": "sbd_stage_timing",
            "producer": "sbd",
            "exp": args.exp,
            "elapsed_clock": "monotonic",
            "stages": [],
        })
        return

    with args.path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if args.command == "start":
        record = {
            "id": uuid.uuid4().hex,
            "stage": args.stage,
            "profile": args.profile,
            "started_at": timestamp(),
            "started_monotonic_ns": time.monotonic_ns(),
            "status": "running",
        }
        document["stages"].append(record)
    else:
        record = next(item for item in document["stages"] if item["id"] == args.id)
        if record["status"] != "running":
            raise ValueError("stage has already finished")
        elapsed = (time.monotonic_ns() - record.pop("started_monotonic_ns")) / 1e9
        record.update({
            "finished_at": timestamp(),
            "elapsed_seconds": elapsed,
            "exit_code": args.exit_code,
            "status": "completed" if args.exit_code == 0 else "failed",
        })
    write_document(args.path, document)
    label = record["stage"]
    if record["profile"]:
        label += " profile=" + record["profile"]
    if args.command == "start":
        print(f"SBD timing: stage={label} started_at={record['started_at']}", file=sys.stderr)
        print(record["id"])
    else:
        print(
            f"SBD timing: stage={label} finished_at={record['finished_at']} "
            f"elapsed_seconds={elapsed:.3f} status={record['status']} "
            f"exit_code={args.exit_code}", file=sys.stderr,
        )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, StopIteration):
        print("SBD timing: unable to update stage artifact", file=sys.stderr)
        sys.exit(1)
