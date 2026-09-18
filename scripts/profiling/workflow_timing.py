"""Persist common execution stages and expose scoped timing observations."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
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
    parser.add_argument("--results-dir", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--session", required=True)
    start.add_argument("--exp", default="")
    start.add_argument("--stage", required=True)
    start.add_argument("--tool", default="none")
    start.add_argument("--profile", default="")
    finish = commands.add_parser("finish")
    finish.add_argument("token")
    finish.add_argument("exit_code", type=int)
    context = commands.add_parser("context")
    context.add_argument("--session", required=True)
    commands.add_parser("manifest")
    args = parser.parse_args()

    if args.command == "manifest" and not args.results_dir.exists():
        print(json.dumps({"schema_version": 1, "observations": []}))
        return
    args.results_dir.mkdir(parents=True, exist_ok=True)
    # A scope may be entered from command substitution, pipelines or concurrent workers.
    with (args.results_dir / ".workflow_timing.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "manifest":
            print(json.dumps(collect_manifest(args.results_dir)))
            return
        if args.command == "context":
            write_document(args.results_dir / ".workflow_session.json", {"session_id": args.session})
            return
        update_stage(args)


def update_stage(args):
    if args.command == "start":
        scope = hashlib.sha256(args.exp.encode("utf-8")).hexdigest()
        path = args.results_dir / f"workflow_timing_{scope}.json"
        document = {}
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                document = json.load(handle)
        if document.get("session_id") != args.session:
            document = {
                "schema_version": 1,
                "kind": "workflow_stage_timing",
                "producer": "benchkit",
                "session_id": args.session,
                "exp": args.exp,
                "elapsed_clock": "monotonic",
                "stages": [],
            }
        record = {
            "id": uuid.uuid4().hex,
            "stage": args.stage,
            "tool": args.tool,
            "profile": args.profile,
            "started_at": timestamp(),
            "started_monotonic_ns": time.monotonic_ns(),
            "status": "running",
        }
        document["stages"].append(record)
    else:
        filename, record_id = args.token.split(":", 1)
        if not re.fullmatch(r"workflow_timing_[0-9a-f]{64}\.json", filename):
            raise ValueError("invalid stage token")
        path = args.results_dir / filename
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
        record = next(item for item in document["stages"] if item["id"] == record_id)
        if record["status"] != "running":
            raise ValueError("stage has already finished")
        elapsed = (time.monotonic_ns() - record.pop("started_monotonic_ns")) / 1e9
        record.update({
            "finished_at": timestamp(),
            "elapsed_seconds": elapsed,
            "exit_code": args.exit_code,
            "status": "completed" if args.exit_code == 0 else "failed",
        })
    write_document(path, document)
    if args.command == "start":
        write_document(args.results_dir / ".workflow_session.json", {"session_id": args.session})
    label = record["stage"]
    label += " tool=" + record["tool"]
    if record["profile"]:
        label += " profile=" + record["profile"]
    if args.command == "start":
        print(f"Benchkit timing: stage={label} started_at={record['started_at']}", file=sys.stderr)
        print(f"{path.name}:{record['id']}")
    else:
        print(
            f"Benchkit timing: stage={label} finished_at={record['finished_at']} "
            f"elapsed_seconds={elapsed:.3f} status={record['status']} "
            f"exit_code={args.exit_code}", file=sys.stderr,
        )


def collect_manifest(results_dir):
    manifest = {"schema_version": 1, "observations": []}
    session_path = results_dir / ".workflow_session.json"
    if not session_path.exists():
        return manifest
    with session_path.open(encoding="utf-8") as handle:
        session = json.load(handle)["session_id"]
    for path in sorted(results_dir.glob("workflow_timing_*.json")):
        if path.is_symlink() or not re.fullmatch(r"workflow_timing_[0-9a-f]{64}\.json", path.name):
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                document = json.load(handle)
            if document.get("session_id") != session:
                continue
            if document.get("kind") != "workflow_stage_timing" or document.get("schema_version") != 1:
                continue
            stages = document["stages"]
            statuses = [stage["status"] for stage in stages]
            observation = {
                "id": path.stem,
                "kind": "workflow-stage-timing",
                "producer": "benchkit",
                "format": "workflow_stage_timing/v1",
                "artifact": {"type": "file_reference", "path": f"results/{path.name}"},
                "summary": {
                    "stage_count": len(stages),
                    "completed_count": statuses.count("completed"),
                    "failed_count": statuses.count("failed"),
                    "unfinished_count": statuses.count("running"),
                },
            }
            if document.get("exp"):
                observation["result_exp"] = document["exp"]
            manifest["observations"].append(observation)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            print("Benchkit timing: skipped invalid stage artifact", file=sys.stderr)
    return manifest


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, StopIteration, TypeError, AttributeError):
        print("Benchkit timing: unable to access stage artifact", file=sys.stderr)
        sys.exit(1)
