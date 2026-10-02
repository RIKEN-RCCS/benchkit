"""Persist common execution stages and expose scoped timing observations."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
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
    start.add_argument("--output", default="")
    start.add_argument("--inputs", type=Path)
    finish = commands.add_parser("finish")
    finish.add_argument("token")
    finish.add_argument("exit_code", type=int)
    finish.add_argument("--print-elapsed", action="store_true")
    context = commands.add_parser("context")
    context.add_argument("--session", required=True)
    bind = commands.add_parser("bind")
    bind.add_argument("--session", required=True)
    bind.add_argument("--exp", required=True)
    bind.add_argument("--output", action="append", required=True)
    bind.add_argument("--input-info", type=Path)
    bind.add_argument("--input-items", type=Path)
    for name in ("workspace", "register"):
        command = commands.add_parser(name)
        command.add_argument("--session", required=True)
        command.add_argument("--output", default="")
        command.add_argument("--exp", default="")
        if name == "register":
            command.add_argument("--section", default="")
            command.add_argument("--artifact", type=Path, action="append", required=True)
    publish = commands.add_parser("publish-primary")
    publish.add_argument("--exp", required=True)
    publish.add_argument("--destination", required=True)
    commands.add_parser("has-profiles")
    enrich = commands.add_parser("enrich-sections")
    enrich.add_argument("--exp", required=True)
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
        if args.command == "bind":
            bind_outputs(args)
            return
        if args.command in ("workspace", "register", "publish-primary", "has-profiles", "enrich-sections"):
            manage_artifacts(args)
            return
        update_stage(args)


def output_key(path):
    return hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()


def output_index(args):
    path = args.results_dir / ".workflow_outputs.json"
    document = json.loads(path.read_text()) if path.exists() else {}
    if document.get("session_id") != args.session:
        document = {"session_id": args.session, "outputs": {}}
    if not isinstance(document.get("outputs"), dict) or any(
        not re.fullmatch(r"[0-9a-f]{64}", key)
        or not isinstance(value, str)
        or not re.fullmatch(r"workflow_timing_[0-9a-f]{64}\.json", value)
        for key, value in document["outputs"].items()
    ):
        raise ValueError("invalid output index")
    return path, document


def bind_outputs(args):
    if not args.exp:
        raise ValueError("output association requires an experiment")
    _, index = output_index(args)
    documents = {}
    for output in args.output:
        filename = index["outputs"].get(output_key(output))
        if not filename:
            raise ValueError("output has no current execution")
        path = args.results_dir / filename
        document = json.loads(path.read_text())
        if document["session_id"] != args.session or document.get("exp") not in ("", args.exp):
            raise ValueError("output is already associated with another experiment")
        document["exp"] = args.exp
        documents[path] = document
    for path, document in documents.items():
        write_document(path, document)
    inputs = [dict(item, result_exp=args.exp) for document in documents.values()
              for item in document.get("inputs", [])]
    if inputs:
        info_path = args.input_info or args.results_dir / "input_info.json"
        info = json.loads(info_path.read_text()) if info_path.exists() else {"schema_version": 1, "inputs": []}
        for item in inputs:
            if item not in info["inputs"]:
                info["inputs"].append(item)
        write_document(info_path, info)
        items_path = args.input_items or args.results_dir / ".input_info_items.jsonl"
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items_path.write_text(
            "".join(json.dumps(item) + "\n" for item in info["inputs"]), encoding="utf-8")


def scoped_documents(results_dir, session, exp):
    if not exp:
        return
    for path in results_dir.glob("workflow_timing_*.json"):
        if path.is_symlink() or not re.fullmatch(r"workflow_timing_[0-9a-f]{64}\.json", path.name):
            continue
        document = json.loads(path.read_text())
        if document.get("session_id") == session and document.get("exp") == exp:
            yield document


def safe_artifact(results_dir, path):
    root = results_dir.resolve()
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(root)
    if not resolved.is_file() or resolved.suffix not in (".json", ".tgz"):
        raise ValueError("unsupported artifact")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in relative.parts):
        raise ValueError("unsafe artifact name")
    return "results/" + relative.as_posix()


def manage_artifacts(args):
    if args.command == "enrich-sections":
        sections = json.load(sys.stdin)
        marker = args.results_dir / ".workflow_session.json"
        session = json.loads(marker.read_text())["session_id"] if marker.exists() else ""
        documents = list(scoped_documents(args.results_dir, session, args.exp))
        for section in sections:
            managed = [item for document in documents
                       for item in document.get("section_artifacts", {}).get(section["name"], [])]
            for item in sorted(managed, key=lambda item: not item.endswith(".tgz")):
                safe = safe_artifact(args.results_dir, args.results_dir / item.removeprefix("results/"))
                references = section.setdefault("artifacts", [])
                if not any(reference.get("path") == safe for reference in references):
                    references.append({"type": "file_reference", "path": safe})
        print(json.dumps(sections))
        return
    if args.command == "has-profiles":
        documents = [json.loads((args.results_dir / Path(item["artifact"]["path"]).name).read_text())
                     for item in collect_manifest(args.results_dir)["observations"]]
        if any(item.get("output_scoped") for item in documents):
            print("true" if any(stage["stage"] == "collect" for item in documents
                                for stage in item["stages"]) else "false")
        return
    if args.command in ("workspace", "register"):
        if args.output:
            _, index = output_index(args)
            filename = index["outputs"][output_key(args.output)]
        elif args.exp:
            filename = "workflow_timing_" + hashlib.sha256(args.exp.encode()).hexdigest() + ".json"
        else:
            raise ValueError("profile requires an execution")
        path = args.results_dir / filename
        document = json.loads(path.read_text())
        if document.get("session_id") != args.session:
            raise ValueError("profile requires a current execution")
        if args.command == "workspace":
            directory = args.results_dir / ("profile_" + uuid.uuid4().hex)
            directory.mkdir()
            print(directory.absolute())
        else:
            additions = [safe_artifact(args.results_dir, item) for item in args.artifact]
            if args.section:
                additions = [item for item in document.get("section_artifacts", {}).get("", [])
                             if item.endswith(".json")] + additions
            items = document.setdefault("section_artifacts", {}).setdefault(args.section, [])
            for item in additions:
                if item not in items:
                    items.append(item)
            write_document(path, document)
        return
    if not re.fullmatch(r"padata[0-9]+\.tgz", args.destination):
        raise ValueError("invalid compatibility archive name")
    marker = args.results_dir / ".workflow_session.json"
    if not marker.exists():
        return
    session = json.loads(marker.read_text())["session_id"]
    documents = list(scoped_documents(args.results_dir, session, args.exp))
    if not any(document.get("output_scoped") for document in documents):
        return
    destination = args.results_dir / args.destination
    destination.unlink(missing_ok=True)
    archives = [item for document in documents
                for item in document.get("section_artifacts", {}).get("", []) if item.endswith(".tgz")]
    # The legacy primary archive is singular; section profiles remain separate.
    if len(archives) == 1:
        source = args.results_dir / archives[0].removeprefix("results/")
        safe_artifact(args.results_dir, source)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=args.results_dir, delete=False) as output:
                temporary = output.name
                with source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output)
            os.replace(temporary, destination)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    elif archives:
        print("Benchkit profile: multiple primary archives; use named sections", file=sys.stderr)


def update_stage(args):
    if args.command == "start":
        scope = hashlib.sha256(args.exp.encode("utf-8")).hexdigest()
        path = args.results_dir / f"workflow_timing_{scope}.json"
        index_path = None
        if args.output:
            index_path, index = output_index(args)
            key = output_key(args.output)
            if args.stage == "benchmark":
                scope = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                index["outputs"][key] = f"workflow_timing_{scope}.json"
            if key not in index["outputs"]:
                raise ValueError("profile output has no current benchmark")
            path = args.results_dir / index["outputs"][key]
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
        if args.output:
            document["output_scoped"] = True
        if args.inputs:
            document["inputs"] = json.loads(args.inputs.read_text())["inputs"]
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
        if index_path:
            write_document(index_path, index)
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
        if args.print_elapsed:
            print(f"{elapsed:.9f}")


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
            if document.get("output_scoped") and not document.get("exp"):
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
