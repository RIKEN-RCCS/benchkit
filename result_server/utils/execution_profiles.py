"""SQLite-backed execution profile registry for CX Portal admin views."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SCHEMA_VERSION = 1


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
            (SCHEMA_VERSION, now),
        )

    def upsert_profile(self, profile: dict[str, Any], *, actor: str = "") -> None:
        self.migrate()
        now = _utc_now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id, created_at FROM execution_profiles WHERE id = ?",
                (profile["id"],),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO execution_profiles (
                    id, display_name, enabled, status, activity, owner, purpose,
                    visibility, scheduler_extra_args, valid_from, valid_until,
                    created_by, approved_by, approved_at, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name=excluded.display_name,
                    enabled=excluded.enabled,
                    status=excluded.status,
                    activity=excluded.activity,
                    owner=excluded.owner,
                    purpose=excluded.purpose,
                    visibility=excluded.visibility,
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
                    profile["scheduler_extra_args"],
                    profile["valid_from"],
                    profile["valid_until"],
                    profile["created_by"],
                    profile["approved_by"],
                    profile["approved_at"],
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
