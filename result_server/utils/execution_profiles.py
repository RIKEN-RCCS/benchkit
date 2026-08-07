"""SQLite-backed execution profile registry for CX Portal admin views."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
TRIGGER_TYPES = {"manual_button", "scheduled", "watch_event"}
MATCH_MODES = {"any", "all"}
SCHEMA_VERSION = 6


@dataclass(frozen=True)
class ExecutionProfileLoadResult:
    """Normalized execution profile load result."""

    path: str
    exists: bool
    profiles: list[dict[str, Any]]
    errors: list[str]

    @property
    def enabled_count(self) -> int:
        return sum(1 for profile in self.profiles if profile.get("enabled", True))

    @property
    def disabled_count(self) -> int:
        return len(self.profiles) - self.enabled_count

    @property
    def approved_count(self) -> int:
        return sum(1 for profile in self.profiles if profile.get("status") == "approved")

    @property
    def inactive_count(self) -> int:
        inactive_statuses = {"paused", "retired"}
        return sum(
            1
            for profile in self.profiles
            if not profile.get("enabled", True)
            or profile.get("status") in inactive_statuses
        )

    @property
    def expired_count(self) -> int:
        today = datetime.now(UTC).date().isoformat()
        return sum(
            1
            for profile in self.profiles
            if profile.get("valid_until") and profile.get("valid_until") < today
        )


@dataclass(frozen=True)
class ExecutionProfileResolveResult:
    """Result of resolving a runnable execution profile for a target scope."""

    profile: dict[str, Any] | None
    errors: list[str]

    @property
    def scheduler_extra_args(self) -> str:
        if not self.profile:
            return ""
        return str(self.profile.get("scheduler_extra_args", ""))

    @property
    def allocation_project_id(self) -> str:
        if not self.profile:
            return ""
        return str(self.profile.get("allocation_project_id", ""))


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        items = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def _json_dump(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_dump_list(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False, sort_keys=True)


def _as_watch_targets(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                return _as_text_list(decoded)
        return _split_text_block(stripped)
    return _as_text_list(value)


def _split_text_block(value: str) -> list[str]:
    items = []
    for chunk in value.replace("\n", ",").split(","):
        text = chunk.strip()
        if text:
            items.append(text)
    return items


def _scope_matches(scope_values: list[str], target: str) -> bool:
    return not scope_values or not target or target in scope_values


def _scope_score(profile: dict[str, Any]) -> int:
    return sum(1 for key in ("code", "system", "exp") if profile.get(key))


def normalize_profile(raw_profile: Any, index: int = 0) -> tuple[dict[str, Any] | None, list[str]]:
    """Normalize a profile from JSON/form input and return validation errors."""
    errors: list[str] = []
    if not isinstance(raw_profile, dict):
        return None, [f"profile[{index}] must be an object"]

    profile_id = str(raw_profile.get("id", "")).strip()
    if not profile_id:
        errors.append(f"profile[{index}] is missing id")
    elif not PROFILE_ID_RE.match(profile_id):
        errors.append(f"profile[{index}] has invalid id: {profile_id}")

    enabled = raw_profile.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append(f"profile[{index}] enabled must be boolean")
        enabled = bool(enabled)

    display_name = str(raw_profile.get("display_name") or profile_id).strip()
    metadata = raw_profile.get("metadata_json", raw_profile.get("metadata", {}))
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        errors.append(f"profile[{index}] metadata_json must be an object")
        metadata = {}

    normalized = {
        "id": profile_id,
        "display_name": display_name,
        "enabled": enabled,
        "status": str(raw_profile.get("status") or "draft").strip(),
        "owner": str(raw_profile.get("owner", "")).strip(),
        "purpose": str(raw_profile.get("purpose", "")).strip(),
        "activity": str(raw_profile.get("activity", "")).strip(),
        "code": _as_text_list(raw_profile.get("code")),
        "system": _as_text_list(raw_profile.get("system")),
        "exp": _as_text_list(raw_profile.get("exp")),
        "allocation_project_id": str(raw_profile.get("allocation_project_id", "")).strip(),
        "scheduler_extra_args": str(raw_profile.get("scheduler_extra_args", "")).strip(),
        "visibility": str(raw_profile.get("visibility", "")).strip(),
        "valid_from": str(raw_profile.get("valid_from", "")).strip(),
        "valid_until": str(raw_profile.get("valid_until", "")).strip(),
        "created_by": str(raw_profile.get("created_by", "")).strip(),
        "approved_by": str(raw_profile.get("approved_by", "")).strip(),
        "approved_at": str(raw_profile.get("approved_at", "")).strip(),
        "metadata_json": metadata,
    }
    return normalized, errors


def normalize_trigger_definition(
    raw_trigger: Any,
    index: int = 0,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Normalize a trigger definition from form input and return validation errors."""
    errors: list[str] = []
    if not isinstance(raw_trigger, dict):
        return None, [f"trigger[{index}] must be an object"]

    trigger_id = str(raw_trigger.get("id", "")).strip()
    if not trigger_id:
        errors.append(f"trigger[{index}] is missing id")
    elif not PROFILE_ID_RE.match(trigger_id):
        errors.append(f"trigger[{index}] has invalid id: {trigger_id}")

    profile_id = str(raw_trigger.get("profile_id", "")).strip()
    if not profile_id:
        errors.append(f"trigger[{index}] profile_id is required")

    trigger_type = str(raw_trigger.get("trigger_type") or "scheduled").strip()
    if trigger_type not in TRIGGER_TYPES:
        errors.append(f"trigger[{index}] trigger_type must be one of {sorted(TRIGGER_TYPES)}")

    enabled = raw_trigger.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append(f"trigger[{index}] enabled must be boolean")
        enabled = bool(enabled)

    match_mode = str(raw_trigger.get("match_mode") or "any").strip()
    if match_mode not in MATCH_MODES:
        errors.append(f"trigger[{index}] match_mode must be one of {sorted(MATCH_MODES)}")

    cron_expr = str(raw_trigger.get("cron_expr", "")).strip()
    timezone = str(raw_trigger.get("timezone", "")).strip() or "Asia/Tokyo"
    watch_kind = str(raw_trigger.get("watch_kind", "")).strip()
    watch_targets = _as_watch_targets(
        raw_trigger.get("watch_targets", raw_trigger.get("watch_targets_json", []))
    )

    if trigger_type == "scheduled" and not cron_expr:
        errors.append(f"trigger[{index}] cron_expr is required for scheduled triggers")
    if trigger_type == "watch_event":
        if not watch_kind:
            errors.append(f"trigger[{index}] watch_kind is required for watch_event triggers")
        if not watch_targets:
            errors.append(f"trigger[{index}] watch_targets is required for watch_event triggers")

    normalized = {
        "id": trigger_id,
        "name": str(raw_trigger.get("name") or trigger_id).strip(),
        "trigger_type": trigger_type,
        "profile_id": profile_id,
        "enabled": enabled,
        "gitlab_target": str(raw_trigger.get("gitlab_target", "")).strip(),
        "target_ref": str(raw_trigger.get("target_ref", "")).strip(),
        "cron_expr": cron_expr,
        "timezone": timezone,
        "watch_kind": watch_kind,
        "watch_targets": watch_targets,
        "match_mode": match_mode,
        "last_seen_fingerprint": str(raw_trigger.get("last_seen_fingerprint", "")).strip(),
        "last_seen_at": str(raw_trigger.get("last_seen_at", "")).strip(),
        "next_due_at": str(raw_trigger.get("next_due_at", "")).strip(),
        "last_submitted_at": str(raw_trigger.get("last_submitted_at", "")).strip(),
        "created_by": str(raw_trigger.get("created_by", "")).strip(),
    }
    return normalized, errors


class ExecutionProfileStore:
    """Persist execution profiles in a small site-local SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = os.path.normpath(db_path)

    def connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                """
            )
            current = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()["version"]
            if current < 1:
                self._apply_v1(conn)
                current = 1
            if current < 2:
                self._apply_v2(conn)
                current = 2
            if current < 3:
                self._apply_v3(conn)
                current = 3
            if current < 4:
                self._apply_v4(conn)
                current = 4
            if current < 5:
                self._apply_v5(conn)
                current = 5
            if current < 6:
                self._apply_v6(conn)

    def _apply_v1(self, conn: sqlite3.Connection) -> None:
        now = _utc_now_iso()
        conn.executescript(
            """
            CREATE TABLE execution_profiles (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'draft',
                activity TEXT NOT NULL DEFAULT '',
                owner TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT '',
                allocation_project_id TEXT NOT NULL DEFAULT '',
                scheduler_extra_args TEXT NOT NULL DEFAULT '',
                valid_from TEXT NOT NULL DEFAULT '',
                valid_until TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE execution_profile_scopes (
                profile_id TEXT NOT NULL REFERENCES execution_profiles(id) ON DELETE CASCADE,
                scope_type TEXT NOT NULL CHECK(scope_type IN ('code', 'system', 'exp')),
                value TEXT NOT NULL,
                PRIMARY KEY (profile_id, scope_type, value)
            );

            CREATE TABLE execution_profile_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (1, now),
        )

    def _apply_v2(self, conn: sqlite3.Connection) -> None:
        now = _utc_now_iso()
        conn.executescript(
            """
            CREATE TABLE execution_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_type TEXT NOT NULL,
                status TEXT NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 1,
                profile_id TEXT NOT NULL DEFAULT '',
                target_ref TEXT NOT NULL DEFAULT '',
                code TEXT NOT NULL DEFAULT '',
                system TEXT NOT NULL DEFAULT '',
                exp TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                errors_json TEXT NOT NULL DEFAULT '[]',
                actor TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (2, now),
        )

    def _apply_v3(self, conn: sqlite3.Connection) -> None:
        now = _utc_now_iso()
        conn.executescript(
            """
            CREATE TABLE result_metadata_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL CHECK(record_type IN ('result', 'estimate')),
                result_uuid TEXT NOT NULL,
                server_timestamp TEXT NOT NULL DEFAULT '',
                json_file TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                system TEXT NOT NULL DEFAULT '',
                exp TEXT NOT NULL DEFAULT '',
                ci_trigger TEXT NOT NULL DEFAULT '',
                pipeline_id TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                source_ref TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(record_type, result_uuid),
                UNIQUE(record_type, json_file)
            );

            CREATE INDEX idx_result_metadata_index_scope
                ON result_metadata_index(record_type, code, system, exp);
            CREATE INDEX idx_result_metadata_index_timestamp
                ON result_metadata_index(record_type, server_timestamp);
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (3, now),
        )

    def _apply_v4(self, conn: sqlite3.Connection) -> None:
        now = _utc_now_iso()
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(execution_profiles)").fetchall()
        }
        if "allocation_project_id" not in columns:
            conn.execute(
                """
                ALTER TABLE execution_profiles
                ADD COLUMN allocation_project_id TEXT NOT NULL DEFAULT ''
                """
            )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (4, now),
        )

    def _apply_v5(self, conn: sqlite3.Connection) -> None:
        now = _utc_now_iso()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trigger_definitions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                trigger_type TEXT NOT NULL CHECK(
                    trigger_type IN ('manual_button', 'scheduled', 'watch_event')
                ),
                profile_id TEXT NOT NULL REFERENCES execution_profiles(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL DEFAULT 1,
                gitlab_target TEXT NOT NULL DEFAULT '',
                target_ref TEXT NOT NULL DEFAULT '',
                cron_expr TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT '',
                watch_kind TEXT NOT NULL DEFAULT '',
                watch_targets_json TEXT NOT NULL DEFAULT '[]',
                match_mode TEXT NOT NULL DEFAULT 'any' CHECK(match_mode IN ('any', 'all')),
                last_seen_fingerprint TEXT NOT NULL DEFAULT '',
                last_seen_at TEXT NOT NULL DEFAULT '',
                next_due_at TEXT NOT NULL DEFAULT '',
                last_submitted_at TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trigger_definitions_profile
                ON trigger_definitions(profile_id, enabled, trigger_type);
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (5, now),
        )

    def _apply_v6(self, conn: sqlite3.Connection) -> None:
        now = _utc_now_iso()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trigger_runner_lock (
                name TEXT PRIMARY KEY,
                owner TEXT NOT NULL DEFAULT '',
                locked_until TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trigger_observations (
                trigger_id TEXT NOT NULL REFERENCES trigger_definitions(id) ON DELETE CASCADE,
                target TEXT NOT NULL,
                fingerprint TEXT NOT NULL DEFAULT '',
                observed_at TEXT NOT NULL,
                PRIMARY KEY (trigger_id, target)
            );

            CREATE TABLE IF NOT EXISTS trigger_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 1,
                reason TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                errors_json TEXT NOT NULL DEFAULT '[]',
                actor TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trigger_runs_trigger
                ON trigger_runs(trigger_id, created_at);
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (6, now),
        )

    def upsert_profile(self, profile: dict[str, Any], *, actor: str = "") -> None:
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, status, approved_by, approved_at, created_at
                FROM execution_profiles
                WHERE id = ?
                """,
                (profile["id"],),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            approved_by = ""
            approved_at = ""
            if profile["status"] == "approved":
                if (
                    existing
                    and existing["status"] == "approved"
                    and existing["approved_by"]
                    and existing["approved_at"]
                ):
                    approved_by = existing["approved_by"]
                    approved_at = existing["approved_at"]
                else:
                    approved_by = actor
                    approved_at = now
            elif existing:
                approved_by = existing["approved_by"]
                approved_at = existing["approved_at"]
            conn.execute(
                """
                INSERT INTO execution_profiles (
                    id, display_name, enabled, status, activity, owner, purpose,
                    visibility, allocation_project_id, scheduler_extra_args,
                    valid_from, valid_until, created_by, approved_by, approved_at,
                    metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name=excluded.display_name,
                    enabled=excluded.enabled,
                    status=excluded.status,
                    activity=excluded.activity,
                    owner=excluded.owner,
                    purpose=excluded.purpose,
                    visibility=excluded.visibility,
                    allocation_project_id=excluded.allocation_project_id,
                    scheduler_extra_args=excluded.scheduler_extra_args,
                    valid_from=excluded.valid_from,
                    valid_until=excluded.valid_until,
                    created_by=excluded.created_by,
                    approved_by=excluded.approved_by,
                    approved_at=excluded.approved_at,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    profile["id"],
                    profile["display_name"],
                    1 if profile["enabled"] else 0,
                    profile["status"],
                    profile["activity"],
                    profile["owner"],
                    profile["purpose"],
                    profile["visibility"],
                    profile["allocation_project_id"],
                    profile["scheduler_extra_args"],
                    profile["valid_from"],
                    profile["valid_until"],
                    profile["created_by"],
                    approved_by,
                    approved_at,
                    _json_dump(profile["metadata_json"]),
                    created_at,
                    now,
                ),
            )
            conn.execute(
                "DELETE FROM execution_profile_scopes WHERE profile_id = ?",
                (profile["id"],),
            )
            for scope_type in ("code", "system", "exp"):
                conn.executemany(
                    """
                    INSERT INTO execution_profile_scopes(profile_id, scope_type, value)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (profile["id"], scope_type, value)
                        for value in profile.get(scope_type, [])
                    ],
                )
            conn.execute(
                """
                INSERT INTO execution_profile_events(
                    profile_id, actor, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    profile["id"],
                    actor,
                    "profile_upserted" if existing else "profile_created",
                    _json_dump({"source": "admin_or_seed"}),
                    now,
                ),
            )

    def upsert_trigger_definition(self, trigger: dict[str, Any], *, actor: str = "") -> None:
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, created_at, created_by
                FROM trigger_definitions
                WHERE id = ?
                """,
                (trigger["id"],),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            created_by = (
                existing["created_by"]
                if existing and existing["created_by"]
                else trigger.get("created_by") or actor
            )
            conn.execute(
                """
                INSERT INTO trigger_definitions (
                    id, name, trigger_type, profile_id, enabled, gitlab_target,
                    target_ref, cron_expr, timezone, watch_kind, watch_targets_json,
                    match_mode, last_seen_fingerprint, last_seen_at, next_due_at,
                    last_submitted_at, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    trigger_type=excluded.trigger_type,
                    profile_id=excluded.profile_id,
                    enabled=excluded.enabled,
                    gitlab_target=excluded.gitlab_target,
                    target_ref=excluded.target_ref,
                    cron_expr=excluded.cron_expr,
                    timezone=excluded.timezone,
                    watch_kind=excluded.watch_kind,
                    watch_targets_json=excluded.watch_targets_json,
                    match_mode=excluded.match_mode,
                    last_seen_fingerprint=excluded.last_seen_fingerprint,
                    last_seen_at=excluded.last_seen_at,
                    next_due_at=excluded.next_due_at,
                    last_submitted_at=excluded.last_submitted_at,
                    updated_at=excluded.updated_at
                """,
                (
                    trigger["id"],
                    trigger["name"],
                    trigger["trigger_type"],
                    trigger["profile_id"],
                    1 if trigger["enabled"] else 0,
                    trigger["gitlab_target"],
                    trigger["target_ref"],
                    trigger["cron_expr"],
                    trigger["timezone"],
                    trigger["watch_kind"],
                    _json_dump_list(trigger["watch_targets"]),
                    trigger["match_mode"],
                    trigger["last_seen_fingerprint"],
                    trigger["last_seen_at"],
                    trigger["next_due_at"],
                    trigger["last_submitted_at"],
                    created_by,
                    created_at,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO execution_profile_events(
                    profile_id, actor, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    trigger["profile_id"],
                    actor,
                    "trigger_definition_upserted" if existing else "trigger_definition_created",
                    _json_dump(
                        {
                            "trigger_id": trigger["id"],
                            "trigger_type": trigger["trigger_type"],
                        }
                    ),
                    now,
                ),
            )

    def set_trigger_definition_enabled(
        self,
        trigger_id: str,
        enabled: bool,
        *,
        actor: str = "",
    ) -> bool:
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, profile_id
                FROM trigger_definitions
                WHERE id = ?
                """,
                (trigger_id,),
            ).fetchone()
            if not existing:
                return False
            conn.execute(
                """
                UPDATE trigger_definitions
                SET enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if enabled else 0, now, trigger_id),
            )
            conn.execute(
                """
                INSERT INTO execution_profile_events(
                    profile_id, actor, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    existing["profile_id"],
                    actor,
                    "trigger_definition_resumed"
                    if enabled
                    else "trigger_definition_paused",
                    _json_dump({"trigger_id": trigger_id}),
                    now,
                ),
            )
        return True

    def delete_trigger_definition(self, trigger_id: str, *, actor: str = "") -> bool:
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, profile_id
                FROM trigger_definitions
                WHERE id = ?
                """,
                (trigger_id,),
            ).fetchone()
            if not existing:
                return False
            conn.execute("DELETE FROM trigger_definitions WHERE id = ?", (trigger_id,))
            conn.execute(
                """
                INSERT INTO execution_profile_events(
                    profile_id, actor, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    existing["profile_id"],
                    actor,
                    "trigger_definition_deleted",
                    _json_dump({"trigger_id": trigger_id}),
                    now,
                ),
            )
        return True

    def list_trigger_definitions(self) -> list[dict[str, Any]]:
        self.migrate()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM trigger_definitions
                ORDER BY enabled DESC, trigger_type, id COLLATE NOCASE
                """
            ).fetchall()

        triggers = []
        for row in rows:
            try:
                watch_targets = json.loads(row["watch_targets_json"] or "[]")
            except json.JSONDecodeError:
                watch_targets = []
            if not isinstance(watch_targets, list):
                watch_targets = []
            triggers.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "trigger_type": row["trigger_type"],
                    "profile_id": row["profile_id"],
                    "enabled": bool(row["enabled"]),
                    "gitlab_target": row["gitlab_target"],
                    "target_ref": row["target_ref"],
                    "cron_expr": row["cron_expr"],
                    "timezone": row["timezone"],
                    "watch_kind": row["watch_kind"],
                    "watch_targets": _as_text_list(watch_targets),
                    "match_mode": row["match_mode"],
                    "last_seen_fingerprint": row["last_seen_fingerprint"],
                    "last_seen_at": row["last_seen_at"],
                    "next_due_at": row["next_due_at"],
                    "last_submitted_at": row["last_submitted_at"],
                    "created_by": row["created_by"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return triggers

    def acquire_trigger_runner_lock(
        self,
        name: str,
        *,
        owner: str,
        ttl_seconds: int = 300,
        now: str | None = None,
    ) -> bool:
        self.migrate()
        current = now or _utc_now_iso()
        locked_until = (
            datetime.fromisoformat(current.replace("Z", "+00:00"))
            + timedelta(seconds=ttl_seconds)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT owner, locked_until
                FROM trigger_runner_lock
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
            if row and row["locked_until"] > current:
                return False
            conn.execute(
                """
                INSERT INTO trigger_runner_lock(name, owner, locked_until, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    owner=excluded.owner,
                    locked_until=excluded.locked_until,
                    updated_at=excluded.updated_at
                """,
                (name, owner, locked_until, current),
            )
        return True

    def release_trigger_runner_lock(
        self,
        name: str,
        *,
        owner: str,
        now: str | None = None,
    ) -> bool:
        self.migrate()
        current = now or _utc_now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE trigger_runner_lock
                SET locked_until = ?, updated_at = ?
                WHERE name = ? AND owner = ?
                """,
                (current, current, name, owner),
            )
        return cur.rowcount > 0

    def list_trigger_observations(
        self,
        trigger_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.migrate()
        query = """
            SELECT trigger_id, target, fingerprint, observed_at
            FROM trigger_observations
        """
        params: tuple[Any, ...] = ()
        if trigger_id:
            query += " WHERE trigger_id = ?"
            params = (trigger_id,)
        query += " ORDER BY trigger_id COLLATE NOCASE, target COLLATE NOCASE"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "trigger_id": row["trigger_id"],
                "target": row["target"],
                "fingerprint": row["fingerprint"],
                "observed_at": row["observed_at"],
            }
            for row in rows
        ]

    def get_trigger_observation(
        self,
        trigger_id: str,
        target: str,
    ) -> dict[str, Any] | None:
        self.migrate()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT trigger_id, target, fingerprint, observed_at
                FROM trigger_observations
                WHERE trigger_id = ? AND target = ?
                """,
                (trigger_id, target),
            ).fetchone()
        if not row:
            return None
        return {
            "trigger_id": row["trigger_id"],
            "target": row["target"],
            "fingerprint": row["fingerprint"],
            "observed_at": row["observed_at"],
        }

    def upsert_trigger_observation(
        self,
        trigger_id: str,
        target: str,
        fingerprint: str,
        *,
        observed_at: str | None = None,
    ) -> None:
        self.migrate()
        observed = observed_at or _utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trigger_observations(
                    trigger_id, target, fingerprint, observed_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(trigger_id, target) DO UPDATE SET
                    fingerprint=excluded.fingerprint,
                    observed_at=excluded.observed_at
                """,
                (trigger_id, target, fingerprint, observed),
            )

    def create_trigger_run(
        self,
        *,
        trigger_id: str,
        trigger_type: str,
        status: str,
        dry_run: bool,
        reason: str = "",
        payload: dict[str, Any] | None = None,
        errors: list[str] | None = None,
        actor: str = "",
    ) -> int:
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO trigger_runs (
                    trigger_id, trigger_type, status, dry_run, reason,
                    payload_json, errors_json, actor, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trigger_id,
                    trigger_type,
                    status,
                    1 if dry_run else 0,
                    reason,
                    _json_dump(payload or {}),
                    json.dumps(errors or [], ensure_ascii=False),
                    actor,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def list_trigger_runs(
        self,
        trigger_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.migrate()
        query = """
            SELECT *
            FROM trigger_runs
        """
        params: list[Any] = []
        if trigger_id:
            query += " WHERE trigger_id = ?"
            params.append(trigger_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        runs = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {"_invalid_payload_json": row["payload_json"]}
            try:
                errors = json.loads(row["errors_json"] or "[]")
            except json.JSONDecodeError:
                errors = [row["errors_json"]]
            runs.append(
                {
                    "id": row["id"],
                    "trigger_id": row["trigger_id"],
                    "trigger_type": row["trigger_type"],
                    "status": row["status"],
                    "dry_run": bool(row["dry_run"]),
                    "reason": row["reason"],
                    "payload_json": payload,
                    "errors": errors,
                    "actor": row["actor"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return runs

    def has_trigger_run(
        self,
        *,
        trigger_id: str,
        status: str,
        reason: str,
        created_at_since: str = "",
    ) -> bool:
        self.migrate()
        params: list[Any] = [trigger_id, status, reason]
        query = """
            SELECT 1
            FROM trigger_runs
            WHERE trigger_id = ? AND status = ? AND reason = ?
        """
        if created_at_since:
            query += " AND created_at >= ?"
            params.append(created_at_since)
        query += " LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return row is not None

    def list_profiles(self) -> list[dict[str, Any]]:
        self.migrate()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM execution_profiles
                ORDER BY enabled DESC, id COLLATE NOCASE
                """
            ).fetchall()
            scope_rows = conn.execute(
                """
                SELECT profile_id, scope_type, value
                FROM execution_profile_scopes
                ORDER BY scope_type, value COLLATE NOCASE
                """
            ).fetchall()

        scopes: dict[str, dict[str, list[str]]] = {}
        for row in scope_rows:
            item = scopes.setdefault(
                row["profile_id"],
                {"code": [], "system": [], "exp": []},
            )
            item[row["scope_type"]].append(row["value"])

        profiles = []
        for row in rows:
            metadata = {}
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {"_invalid_metadata_json": row["metadata_json"]}
            profile_scopes = scopes.get(row["id"], {"code": [], "system": [], "exp": []})
            profiles.append(
                {
                    "id": row["id"],
                    "display_name": row["display_name"],
                    "enabled": bool(row["enabled"]),
                    "status": row["status"],
                    "owner": row["owner"],
                    "purpose": row["purpose"],
                    "activity": row["activity"],
                    "code": profile_scopes["code"],
                    "system": profile_scopes["system"],
                    "exp": profile_scopes["exp"],
                    "allocation_project_id": row["allocation_project_id"],
                    "scheduler_extra_args": row["scheduler_extra_args"],
                    "visibility": row["visibility"],
                    "valid_from": row["valid_from"],
                    "valid_until": row["valid_until"],
                    "created_by": row["created_by"],
                    "approved_by": row["approved_by"],
                    "approved_at": row["approved_at"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "metadata_json": metadata,
                }
            )
        return profiles

    def delete_profile(self, profile_id: str, *, actor: str = "") -> bool:
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM execution_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
            if not existing:
                return False
            conn.execute(
                """
                INSERT INTO execution_profile_events(
                    profile_id, actor, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    actor,
                    "profile_deleted",
                    _json_dump({"profile_id": profile_id}),
                    now,
                ),
            )
            conn.execute("DELETE FROM execution_profiles WHERE id = ?", (profile_id,))
        return True

    def resolve_profile(
        self,
        *,
        profile_id: str = "",
        code: str = "",
        system: str = "",
        exp: str = "",
    ) -> ExecutionProfileResolveResult:
        """Resolve one enabled and approved profile for a target execution."""
        target_id = profile_id.strip()
        profiles = [
            profile
            for profile in self.list_profiles()
            if profile.get("enabled", True) and profile.get("status") == "approved"
        ]
        if target_id:
            matches = [
                profile
                for profile in profiles
                if profile.get("id") == target_id
                and _scope_matches(profile.get("code", []), code)
                and _scope_matches(profile.get("system", []), system)
                and _scope_matches(profile.get("exp", []), exp)
            ]
            if not matches:
                return ExecutionProfileResolveResult(
                    profile=None,
                    errors=[f"execution profile is not approved for target: {target_id}"],
                )
            return ExecutionProfileResolveResult(profile=matches[0], errors=[])

        matches = [
            profile
            for profile in profiles
            if _scope_matches(profile.get("code", []), code)
            and _scope_matches(profile.get("system", []), system)
            and _scope_matches(profile.get("exp", []), exp)
        ]
        if not matches:
            return ExecutionProfileResolveResult(
                profile=None,
                errors=["no approved execution profile matches target"],
            )

        matches.sort(key=lambda profile: (-_scope_score(profile), profile.get("id", "")))
        best_score = _scope_score(matches[0])
        best = [profile for profile in matches if _scope_score(profile) == best_score]
        if len(best) > 1:
            ids = ", ".join(profile.get("id", "") for profile in best)
            return ExecutionProfileResolveResult(
                profile=None,
                errors=[f"multiple execution profiles match target: {ids}"],
            )
        return ExecutionProfileResolveResult(profile=matches[0], errors=[])

    def create_execution_request(
        self,
        *,
        request_type: str,
        status: str,
        dry_run: bool,
        profile_id: str = "",
        target_ref: str = "",
        code: str = "",
        system: str = "",
        exp: str = "",
        payload: dict[str, Any] | None = None,
        errors: list[str] | None = None,
        actor: str = "",
    ) -> int:
        """Record a Portal-triggered execution request or dry-run preview."""
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO execution_requests (
                    request_type, status, dry_run, profile_id, target_ref,
                    code, system, exp, payload_json, errors_json, actor,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_type,
                    status,
                    1 if dry_run else 0,
                    profile_id,
                    target_ref,
                    code,
                    system,
                    exp,
                    _json_dump(payload or {}),
                    json.dumps(errors or [], ensure_ascii=False),
                    actor,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)


def load_execution_profiles(db_path: str | None) -> ExecutionProfileLoadResult:
    """Load execution profiles from the site-local SQLite registry."""
    normalized_path = os.path.normpath(db_path or "")
    if not normalized_path:
        return ExecutionProfileLoadResult(path="", exists=False, profiles=[], errors=[])

    existed = os.path.exists(normalized_path)
    store = ExecutionProfileStore(normalized_path)
    try:
        profiles = store.list_profiles()
    except sqlite3.Error as exc:
        return ExecutionProfileLoadResult(
            path=normalized_path,
            exists=os.path.exists(normalized_path),
            profiles=[],
            errors=[f"failed to read execution profile database: {exc}"],
        )
    return ExecutionProfileLoadResult(
        path=normalized_path,
        exists=existed or os.path.exists(normalized_path),
        profiles=profiles,
        errors=[],
    )


def import_execution_profiles_json(
    json_path: str,
    db_path: str,
    *,
    actor: str = "seed",
) -> list[str]:
    """Import execution profiles from a JSON seed file into SQLite."""
    errors: list[str] = []
    try:
        with open(json_path, encoding="utf-8") as f:
            raw_data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"failed to read execution profile seed: {exc}"]

    raw_profiles = raw_data.get("profiles") if isinstance(raw_data, dict) else raw_data
    if not isinstance(raw_profiles, list):
        return ["execution profile seed must contain a profiles array"]

    seen_ids: set[str] = set()
    normalized_profiles: list[dict[str, Any]] = []
    for index, raw_profile in enumerate(raw_profiles):
        profile, profile_errors = normalize_profile(raw_profile, index)
        errors.extend(profile_errors)
        if profile is None:
            continue
        profile_id = profile.get("id", "")
        if profile_id:
            if profile_id in seen_ids:
                errors.append(f"profile[{index}] duplicates id: {profile_id}")
            seen_ids.add(profile_id)
        normalized_profiles.append(profile)

    if errors:
        return errors

    store = ExecutionProfileStore(db_path)
    for profile in normalized_profiles:
        store.upsert_profile(profile, actor=actor)
    return []
