"""SQLite metadata index for received benchmark and estimate JSON files."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from typing import Any

from utils.execution_profiles import ExecutionProfileStore


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _nested_text(data: dict[str, Any], *keys: str) -> str:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return _as_text(current)


def _source_ref(source_info: dict[str, Any]) -> str:
    if not isinstance(source_info, dict):
        return ""
    for key in (
        "resolved_commit",
        "commit_hash",
        "sha256sum",
        "md5sum",
        "ref_name",
        "branch",
        "file_path",
        "repo_url",
    ):
        value = _as_text(source_info.get(key))
        if value:
            return value
    return ""


def _metadata_for_result(payload: dict[str, Any]) -> dict[str, Any]:
    source_info = payload.get("source_info")
    source_info = source_info if isinstance(source_info, dict) else {}
    return {
        "fom": payload.get("FOM"),
        "fom_unit": payload.get("FOM_unit"),
        "fom_version": payload.get("FOM_version"),
        "nodes": payload.get("nodes"),
        "numproc_node": payload.get("numproc_node"),
        "nthreads": payload.get("nthreads"),
        "source_info": {
            key: source_info.get(key)
            for key in (
                "source_type",
                "repo_url",
                "branch",
                "commit_hash",
                "ref_name",
                "ref_kind",
                "resolved_commit",
                "file_path",
                "md5sum",
                "sha256sum",
            )
            if source_info.get(key)
        },
    }


def _metadata_for_estimate(payload: dict[str, Any]) -> dict[str, Any]:
    estimate_meta = payload.get("estimate_metadata")
    estimate_meta = estimate_meta if isinstance(estimate_meta, dict) else {}
    applicability = payload.get("applicability")
    applicability = applicability if isinstance(applicability, dict) else {}
    return {
        "performance_ratio": payload.get("performance_ratio"),
        "applicability_status": applicability.get("status"),
        "estimation_package": estimate_meta.get("estimation_package"),
        "requested_estimation_package": estimate_meta.get("requested_estimation_package"),
        "source_result_uuid": estimate_meta.get("source_result_uuid"),
        "source_result_timestamp": estimate_meta.get("source_result_timestamp"),
        "current_system": payload.get("current_system", {}).get("system")
        if isinstance(payload.get("current_system"), dict)
        else None,
        "future_system": payload.get("future_system", {}).get("system")
        if isinstance(payload.get("future_system"), dict)
        else None,
    }


def extract_result_index_record(
    *,
    record_type: str,
    payload: dict[str, Any],
    json_file: str,
    fallback_uuid: str = "",
    fallback_timestamp: str = "",
) -> dict[str, Any]:
    """Return a normalized result_metadata_index row from a stored JSON payload."""
    if record_type not in {"result", "estimate"}:
        raise ValueError(f"unsupported record_type: {record_type}")

    if record_type == "estimate":
        estimate_meta = payload.get("estimate_metadata")
        estimate_meta = estimate_meta if isinstance(estimate_meta, dict) else {}
        result_uuid = _as_text(estimate_meta.get("estimation_result_uuid")) or fallback_uuid
        server_timestamp = (
            _as_text(estimate_meta.get("estimation_result_timestamp"))
            or fallback_timestamp
        )
        system = _nested_text(payload, "current_system", "system")
        metadata = _metadata_for_estimate(payload)
    else:
        result_uuid = _as_text(payload.get("_server_uuid")) or fallback_uuid
        server_timestamp = _as_text(payload.get("_server_timestamp")) or fallback_timestamp
        system = _as_text(payload.get("system"))
        metadata = _metadata_for_result(payload)

    source_info = payload.get("source_info")
    source_info = source_info if isinstance(source_info, dict) else {}
    return {
        "record_type": record_type,
        "result_uuid": result_uuid,
        "server_timestamp": server_timestamp,
        "json_file": os.path.basename(json_file),
        "code": _as_text(payload.get("code")),
        "system": system,
        "exp": _as_text(payload.get("Exp") if record_type == "result" else payload.get("exp")),
        "ci_trigger": _as_text(payload.get("ci_trigger")),
        "pipeline_id": _as_text(payload.get("pipeline_id")),
        "source_type": _as_text(source_info.get("source_type")),
        "source_ref": _source_ref(source_info),
        "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    }


def index_result_metadata(
    *,
    db_path: str | None,
    record_type: str,
    payload: dict[str, Any],
    json_file: str,
    fallback_uuid: str = "",
    fallback_timestamp: str = "",
) -> bool:
    """Upsert a stored result or estimate JSON into the Portal SQLite index."""
    if not db_path:
        return False

    record = extract_result_index_record(
        record_type=record_type,
        payload=payload,
        json_file=json_file,
        fallback_uuid=fallback_uuid,
        fallback_timestamp=fallback_timestamp,
    )
    if not record["result_uuid"]:
        return False

    store = ExecutionProfileStore(db_path)
    store.migrate()
    now = _utc_now_iso()
    with store.connect() as conn:
        existing = conn.execute(
            """
            SELECT created_at FROM result_metadata_index
            WHERE record_type = ? AND result_uuid = ?
            """,
            (record["record_type"], record["result_uuid"]),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO result_metadata_index (
                record_type, result_uuid, server_timestamp, json_file,
                code, system, exp, ci_trigger, pipeline_id,
                source_type, source_ref, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_type, result_uuid) DO UPDATE SET
                server_timestamp=excluded.server_timestamp,
                json_file=excluded.json_file,
                code=excluded.code,
                system=excluded.system,
                exp=excluded.exp,
                ci_trigger=excluded.ci_trigger,
                pipeline_id=excluded.pipeline_id,
                source_type=excluded.source_type,
                source_ref=excluded.source_ref,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                record["record_type"],
                record["result_uuid"],
                record["server_timestamp"],
                record["json_file"],
                record["code"],
                record["system"],
                record["exp"],
                record["ci_trigger"],
                record["pipeline_id"],
                record["source_type"],
                record["source_ref"],
                record["metadata_json"],
                created_at,
                now,
            ),
        )
        return True


def list_indexed_results(db_path: str, *, record_type: str | None = None) -> list[dict[str, Any]]:
    """Return indexed metadata rows, newest first."""
    store = ExecutionProfileStore(db_path)
    store.migrate()
    query = "SELECT * FROM result_metadata_index"
    params: tuple[str, ...] = ()
    if record_type:
        query += " WHERE record_type = ?"
        params = (record_type,)
    query += " ORDER BY server_timestamp DESC, id DESC"
    with store.connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
