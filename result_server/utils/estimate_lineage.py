"""Read-only navigation between stored Results and their Estimate records."""

from collections import defaultdict
from pathlib import Path
from uuid import UUID

from flask import current_app, session, url_for
from werkzeug.exceptions import Forbidden

from utils.result_file import check_file_permission
from utils.result_records import load_result_json


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return str(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _uuid(value):
    try:
        return str(UUID(value)) if isinstance(value, str) else ""
    except ValueError:
        return ""


def _references(values):
    present = [value for value in values if value not in (None, "")]
    valid = {_uuid(value) for value in present}
    if "" in valid or len(valid) > 1:
        return "", True
    return next(iter(valid), ""), False


def _identity(payload, filename, *, estimate=False):
    metadata = _mapping(payload.get("estimate_metadata"))
    declared = metadata.get("estimation_result_uuid") if estimate else payload.get("_server_uuid")
    # Older records have a server-assigned UUID only in the stored filename.
    return _uuid(declared) if declared else _uuid(Path(filename).stem.rsplit("_", 1)[-1])


def _records(directory):
    records = []
    unavailable = False
    if not directory:
        return records, True
    try:
        paths = sorted(Path(directory).iterdir())
    except OSError:
        return records, True
    for path in paths:
        if path.suffix != ".json" or path.is_symlink() or not path.is_file():
            continue
        try:
            check_file_permission(path.name, directory)
        except Forbidden:
            continue
        payload = load_result_json(path.name, directory)
        if not isinstance(payload, dict):
            unavailable = True
            continue
        records.append((path.name, payload))
    return records, unavailable


def _estimate_record(filename, payload):
    metadata = _mapping(payload.get("estimate_metadata"))
    context = _mapping(payload.get("reestimation"))
    source, source_conflict = _references([
        metadata.get("source_result_uuid"),
        _mapping(metadata.get("source_result")).get("uuid"),
        context.get("source_result_uuid"),
        _mapping(context.get("source_result")).get("uuid"),
    ])
    parent, parent_conflict = _references([
        context.get("previous_estimation_result_uuid"),
        context.get("source_estimate_result_uuid"),
        _mapping(context.get("source_estimate")).get("uuid"),
    ])
    return {
        "filename": filename, "payload": payload, "metadata": metadata,
        "uuid": _identity(payload, filename, estimate=True), "source": source,
        "source_conflict": source_conflict, "parent": parent,
        "parent_conflict": parent_conflict,
    }


def build_estimate_lineage(result, filename, *, estimate=False):
    """Build permission-filtered links without changing files, indexes, or schemas."""
    if current_app.config.get("PUBLIC_PORTAL_MODE") or not session.get("authenticated"):
        return None
    selected = _estimate_record(filename, result) if estimate else None
    source = selected["source"] if selected else _identity(result, filename)
    if not source:
        return {"rows": [], "source_link": "", "source_uuid": "",
                "notice": "Source Result reference is missing or inconsistent."}

    stored, unavailable = _records(current_app.config.get("ESTIMATED_DIR"))
    records = [_estimate_record(name, payload) for name, payload in stored]
    by_uuid = defaultdict(list)
    for record in records:
        if record["uuid"]:
            by_uuid[record["uuid"]].append(record)
    related = [record for record in records if record["source"] == source]

    def parent_record(record):
        candidates = by_uuid.get(record["parent"], [])
        if record["parent_conflict"] or len(candidates) != 1:
            return None
        parent = candidates[0]
        return parent if parent["source"] == source else None

    def parent_state(record):
        if record["parent_conflict"]:
            return None, "Conflicting parent references"
        if not record["parent"]:
            return None, "No parent recorded"
        parent = parent_record(record)
        if parent is None:
            return None, "Parent unavailable or ambiguous"
        seen = {record["uuid"]}
        cursor = parent
        while cursor:
            if cursor["uuid"] in seen:
                return None, "Cyclic parent references"
            seen.add(cursor["uuid"])
            cursor = parent_record(cursor)
        return parent, ""

    rows = []
    for record in sorted(related, key=lambda item: (
        _text(item["metadata"].get("estimation_result_timestamp")), item["filename"],
    )):
        payload, metadata = record["payload"], record["metadata"]
        parent, parent_note = parent_state(record)
        duplicate = not record["uuid"] or len(by_uuid[record["uuid"]]) != 1
        sides = []
        for side in ("current_system", "future_system"):
            system = _mapping(payload.get(side))
            sides.append(f"{_text(system.get('system')) or 'Unknown'} / nodes {_text(system.get('target_nodes')) or 'Unknown'}")
        changes = _mapping(_mapping(payload.get("reestimation")).get("resolved_request"))
        rows.append({
            "uuid": record["uuid"] or "Unknown UUID",
            "link": "" if duplicate else url_for("estimated.estimated_detail", filename=record["filename"]),
            "selected": estimate and filename == record["filename"],
            "timestamp": _text(metadata.get("estimation_result_timestamp")) or "Unknown",
            "parent_uuid": parent["uuid"] if parent else "",
            "parent_link": url_for("estimated.estimated_detail", filename=parent["filename"]) if parent else "",
            "parent_note": "Estimate UUID unavailable or ambiguous" if duplicate else parent_note,
            "package": _text(metadata.get("estimation_package")) or "Unknown",
            "package_version": _text(metadata.get("estimation_package_version")) or "Unknown",
            "method_version": _text(_mapping(metadata.get("app_estimation_method")).get("version")) or "Unknown",
            "status": _text(_mapping(payload.get("applicability")).get("status")) or "Unknown",
            "conditions": " -> ".join(sides),
            "changes": "Recorded explicit overrides" if _mapping(changes.get("explicit_changes")) else "",
        })

    source_link = ""
    if estimate:
        results, source_unavailable = _records(current_app.config.get("RECEIVED_DIR"))
        matches = [name for name, payload in results if _identity(payload, name) == source]
        if len(matches) == 1:
            source_link = url_for("results.result_detail", filename=matches[0])
        unavailable = unavailable or source_unavailable
    return {"rows": rows, "source_uuid": source, "source_link": source_link,
            "source_unavailable": estimate and not source_link,
            "notice": "Some stored records could not be read; this history may be incomplete." if unavailable else ""}
