#!/usr/bin/env python3
"""Collect content identity without exporting input locations."""

import argparse
import hashlib
from itertools import islice
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time


MAX_ENTRIES = 10000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


class InputError(ValueError):
    pass


class DestinationError(InputError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def inventory(source, kind):
    root = source.resolve(strict=True)
    nodes = {}
    files = []

    def visit(path, relative, ancestors):
        if len(nodes) >= MAX_ENTRIES or len(ancestors) > 64:
            raise InputError("input tree exceeds collection limits")
        resolved = path.resolve(strict=True)
        if kind == "directory" and resolved != root and root not in resolved.parents:
            raise InputError("input tree contains an external symbolic link")
        info = resolved.stat()
        nodes[relative] = (str(resolved), fingerprint(path.lstat()), fingerprint(info))
        if stat.S_ISREG(info.st_mode):
            files.append((relative, resolved, fingerprint(info)))
        elif stat.S_ISDIR(info.st_mode) and kind == "directory":
            identity = (info.st_dev, info.st_ino)
            if identity in ancestors:
                raise InputError("input tree contains a directory cycle")
            remaining = MAX_ENTRIES - len(nodes)
            children = list(islice(path.iterdir(), remaining + 1))
            if len(children) > remaining:
                raise InputError("input tree exceeds collection limits")
            for child in sorted(children, key=lambda item: item.name):
                child_relative = child.name if relative == "" else relative + "/" + child.name
                visit(child, child_relative, ancestors + (identity,))
        else:
            raise InputError("input contains a non-regular file")

    if kind == "directory" and not root.is_dir():
        raise InputError("directory input is not a directory")
    visit(source, "" if kind == "directory" else "input", ())
    if not files:
        raise InputError("input contains no regular files")
    return nodes, sorted(files)


def hash_file(path, expected_fingerprint):
    # Nonblocking open avoids hanging if a regular file is replaced by a FIFO.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or fingerprint(before) != expected_fingerprint:
            raise InputError("input changed during collection")
        digest = hashlib.sha256()
        count = 0
        while True:
            chunk = stream.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            count += len(chunk)
        if fingerprint(os.fstat(stream.fileno())) != expected_fingerprint or count != before.st_size:
            raise InputError("input changed during collection")
    return count, digest.hexdigest()


def _expected_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise InputError("expected manifest contains a duplicate JSON key")
        value[key] = item
    return value


def load_expected(path, kind):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise InputError("expected manifest must be a regular file")
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise InputError("expected manifest exceeds collection limits")
    value = json.loads(raw, object_pairs_hook=_expected_object)
    if not isinstance(value, dict) or set(value) != {"schema_version", "kind", "files"}:
        raise InputError("invalid expected manifest")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != kind:
        raise InputError("expected manifest schema or kind mismatch")
    files = value["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_ENTRIES:
        raise InputError("invalid expected file list")
    names = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
            raise InputError("invalid expected file entry")
        name = item["path"]
        if (not isinstance(name, str) or not name
                or PurePosixPath(name).is_absolute() or any(part in {"", ".", ".."} for part in name.split("/"))
                or name in names):
            raise InputError("invalid expected relative file name")
        names.add(name)
        if type(item["size_bytes"]) is not int or item["size_bytes"] < 0:
            raise InputError("invalid expected byte count")
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise InputError("invalid expected SHA-256")
    if kind == "file" and names != {"input"}:
        raise InputError("single-file manifest must contain only the entry named input")
    return {**value, "files": sorted(files, key=lambda item: item["path"])}


def collect(source, kind, expected=None):
    started = time.monotonic()
    before, files = inventory(source, kind)
    print("bk_record_input: hashing {} input file(s)".format(len(files)), file=sys.stderr)
    entries = []
    for relative, path, identity in files:
        size, digest = hash_file(path, identity)
        entries.append({"path": relative, "size_bytes": size, "sha256": digest})
    after, _ = inventory(source, kind)
    if before != after:
        raise InputError("input changed during collection")
    manifest = {"schema_version": 1, "kind": kind, "files": entries}
    encoded = canonical_json(manifest)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise InputError("input manifest exceeds collection limits")
    manifest_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
    result = {
        "manifest": manifest,
        "manifest_digest": manifest_digest,
        "content_digest": "sha256:" + entries[0]["sha256"] if kind == "file" else manifest_digest,
        "size_bytes": sum(entry["size_bytes"] for entry in entries),
        "file_count": len(entries),
        "verification_status": ("verified" if manifest == expected else "mismatch") if expected is not None else "declared",
        "collection_status": "recorded",
        "collection_elapsed_seconds": round(time.monotonic() - started, 6),
    }
    if kind == "file":
        result["sha256"] = entries[0]["sha256"]
    if expected is not None:
        result["reference_manifest_digest"] = "sha256:" + hashlib.sha256(canonical_json(expected)).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--directory", type=Path)
    parser.add_argument("--expected-manifest", type=Path)
    parser.add_argument("--metadata-output", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        item = json.load(sys.stdin)
        if not isinstance(item, dict):
            raise InputError("input metadata must be an object")
        kind = "file" if args.file is not None else "directory"
        source_path = args.file if kind == "file" else args.directory
        root = source_path.resolve()
        for output in args.metadata_output:
            resolved = output.resolve()
            if resolved == root or (kind == "directory" and root in resolved.parents):
                raise DestinationError("metadata output must be outside the input")
        expected = None
        reference_unavailable = False
        if args.expected_manifest is not None:
            try:
                resolved = args.expected_manifest.resolve(strict=True)
                if kind == "directory" and (resolved == root or root in resolved.parents):
                    raise InputError("reference is inside input directory")
                expected = load_expected(args.expected_manifest, kind)
            except (OSError, ValueError, RuntimeError):
                reference_unavailable = True
        try:
            observed = collect(source_path, kind, expected)
        except (OSError, ValueError, RuntimeError):
            observed = {"collection_status": "unavailable", "collection_error": "collection_failed",
                        "verification_status": "unavailable"}
        if reference_unavailable:
            observed["verification_status"] = "unavailable"
            observed["reference_error"] = "invalid_or_unavailable"
        for field in ("manifest", "manifest_digest", "content_digest", "sha256", "size_bytes", "file_count",
                      "collection_elapsed_seconds", "collection_error", "reference_error", "reference_manifest_digest"):
            item.pop(field, None)
        item.update(observed)
        if not item.get("dataset_version") and observed.get("content_digest"):
            item["dataset_version"] = observed["content_digest"]
        if observed["verification_status"] in {"mismatch", "unavailable"}:
            print("bk_record_input: input observation is " + observed["verification_status"], file=sys.stderr)
        print(canonical_json(item).decode("ascii"))
        return 0
    except DestinationError:
        print("bk_record_input: metadata output must be outside the input", file=sys.stderr)
        return 2
    except InputError as exc:
        print("bk_record_input: " + str(exc), file=sys.stderr)
    except (OSError, ValueError, RuntimeError):
        # Exception text may contain absolute paths or fragments of input data.
        print("bk_record_input: input collection failed; check readability and manifest format", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
