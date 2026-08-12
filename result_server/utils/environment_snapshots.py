"""Environment snapshot storage helpers for received benchmark results."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from utils.execution_profiles import ExecutionProfileStore


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _json_dump(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_load(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def extract_environment_snapshot_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return normalized snapshot fields from a Result JSON payload."""
    snapshot = payload.get("environment_snapshot")
    if not isinstance(snapshot, dict):
        return None

    snapshot_hash = _as_text(snapshot.get("hash"))
    if not snapshot_hash:
        return None

    summary = snapshot.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    snapshot_payload = snapshot.get("payload")
    snapshot_payload = snapshot_payload if isinstance(snapshot_payload, dict) else snapshot

    return {
        "snapshot_hash": snapshot_hash,
        "schema_version": int(snapshot.get("schema_version") or snapshot_payload.get("schema_version") or 1),
        "summary_json": _json_dump(summary),
        "payload_json": _json_dump(snapshot_payload),
        "result_uuid": _as_text(payload.get("_server_uuid")),
        "json_file": "",
        "code": _as_text(payload.get("code")),
        "system": _as_text(payload.get("system")),
        "exp": _as_text(payload.get("Exp")),
        "pipeline_id": _as_text(payload.get("pipeline_id")),
    }


def index_environment_snapshot(
    *,
    db_path: str | None,
    payload: dict[str, Any],
    json_file: str,
) -> bool:
    """Upsert environment snapshot payload and link it to a received result."""
    if not db_path:
        return False

    record = extract_environment_snapshot_record(payload)
    if record is None:
        return False

    record["json_file"] = json_file
    store = ExecutionProfileStore(db_path)
    store.migrate()
    now = _utc_now_iso()
    with store.connect() as conn:
        existing = conn.execute(
            """
            SELECT first_seen_at, result_count FROM environment_snapshots
            WHERE snapshot_hash = ?
            """,
            (record["snapshot_hash"],),
        ).fetchone()
        first_seen_at = existing["first_seen_at"] if existing else now
        result_count = int(existing["result_count"]) if existing else 0
        conn.execute(
            """
            INSERT INTO environment_snapshots (
                snapshot_hash, schema_version, summary_json, payload_json,
                first_seen_at, last_seen_at, result_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_hash) DO UPDATE SET
                schema_version=excluded.schema_version,
                summary_json=excluded.summary_json,
                payload_json=excluded.payload_json,
                last_seen_at=excluded.last_seen_at
            """,
            (
                record["snapshot_hash"],
                record["schema_version"],
                record["summary_json"],
                record["payload_json"],
                first_seen_at,
                now,
                result_count,
            ),
        )

        linked_existing = conn.execute(
            """
            SELECT snapshot_hash FROM environment_snapshot_results
            WHERE result_uuid = ?
            """,
            (record["result_uuid"],),
        ).fetchone() if record["result_uuid"] else None
        if record["result_uuid"]:
            conn.execute(
                """
                INSERT INTO environment_snapshot_results (
                    result_uuid, snapshot_hash, json_file, code, system, exp,
                    pipeline_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(result_uuid) DO UPDATE SET
                    snapshot_hash=excluded.snapshot_hash,
                    json_file=excluded.json_file,
                    code=excluded.code,
                    system=excluded.system,
                    exp=excluded.exp,
                    pipeline_id=excluded.pipeline_id,
                    updated_at=excluded.updated_at
                """,
                (
                    record["result_uuid"],
                    record["snapshot_hash"],
                    record["json_file"],
                    record["code"],
                    record["system"],
                    record["exp"],
                    record["pipeline_id"],
                    now,
                    now,
                ),
            )
            if not linked_existing:
                conn.execute(
                    """
                    UPDATE environment_snapshots
                    SET result_count = result_count + 1
                    WHERE snapshot_hash = ?
                    """,
                    (record["snapshot_hash"],),
                )
            elif linked_existing["snapshot_hash"] != record["snapshot_hash"]:
                conn.execute(
                    """
                    UPDATE environment_snapshots
                    SET result_count = MAX(result_count - 1, 0)
                    WHERE snapshot_hash = ?
                    """,
                    (linked_existing["snapshot_hash"],),
                )
                conn.execute(
                    """
                    UPDATE environment_snapshots
                    SET result_count = result_count + 1
                    WHERE snapshot_hash = ?
                    """,
                    (record["snapshot_hash"],),
                )
    return True


def list_environment_snapshots(db_path: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Return snapshot rows ordered by latest observation."""
    store = ExecutionProfileStore(db_path)
    store.migrate()
    with store.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM environment_snapshots
                ORDER BY last_seen_at DESC, snapshot_hash DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]


def get_environment_snapshot(db_path: str, snapshot_hash: str) -> dict[str, Any] | None:
    """Return one environment snapshot row with decoded summary and payload."""
    if not db_path or not snapshot_hash:
        return None

    store = ExecutionProfileStore(db_path)
    store.migrate()
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM environment_snapshots
            WHERE snapshot_hash = ?
            """,
            (snapshot_hash,),
        ).fetchone()
    if row is None:
        return None

    snapshot = dict(row)
    snapshot["summary"] = _json_load(snapshot.get("summary_json"))
    snapshot["payload"] = _json_load(snapshot.get("payload_json"))
    return snapshot


def list_environment_snapshot_results(
    db_path: str,
    snapshot_hash: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return result links for one environment snapshot, newest first."""
    if not db_path or not snapshot_hash:
        return []

    store = ExecutionProfileStore(db_path)
    store.migrate()
    with store.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM environment_snapshot_results
                WHERE snapshot_hash = ?
                ORDER BY updated_at DESC, json_file DESC
                LIMIT ?
                """,
                (snapshot_hash, limit),
            ).fetchall()
        ]
