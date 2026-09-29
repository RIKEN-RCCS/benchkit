"""Shared encrypted budget registry, independent of application profile databases."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
import re
from urllib.parse import urlsplit

from .encrypted_sqlite import EncryptedSQLite
from .gitlab_pipeline import configured_gitlab_targets


SCHEMA_VERSION = 4
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class RegistryError(ValueError):
    """Invalid registry configuration or unavailable destination."""


class RegistryConflict(RegistryError):
    """The revision changed after the caller loaded the registry."""


class RegistryPermissionError(RegistryError):
    """The authenticated principal cannot perform this operation."""


@dataclass(frozen=True)
class RegistryActor:
    """Trusted caller identity, never populated directly from submitted fields."""

    principal: str
    is_admin: bool = False


def _text(value, *, optional=False):
    if (not isinstance(value, str) or len(value) > 256
            or any(ord(c) < 32 for c in value) or (not value.strip() and not optional)):
        raise RegistryError("Invalid registry text field")
    return value.strip()


def _id(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise RegistryError("Invalid registry identifier")
    return value


def _dates(start, end):
    try:
        for value in (start, end):
            if not isinstance(value, str):
                raise ValueError
            if value and date.fromisoformat(value).isoformat() != value:
                raise ValueError
        if start and end and start > end:
            raise ValueError
    except (ValueError, TypeError):
        raise RegistryError("Invalid budget validity interval") from None


class BudgetRegistry:
    """Storage service for budget management and atomic destination resolution.

    A global revision provides optimistic concurrency across Portal instances.
    Schema creation is an explicit operator action, never a side effect of reads.
    """

    def __init__(self, db_path, key_file):
        self.storage = EncryptedSQLite(db_path, key_file)

    def initialize(self):
        with self.storage.connect(create=True) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""CREATE TABLE registry_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL
                )""")
                conn.execute("INSERT INTO registry_meta VALUES (1, ?, 0)", (SCHEMA_VERSION,))
                conn.execute("""CREATE TABLE budgets (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    system TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    valid_from TEXT NOT NULL,
                    valid_until TEXT NOT NULL
                )""")
                conn.execute("""CREATE TABLE budget_managers (
                    budget_id TEXT NOT NULL REFERENCES budgets(id),
                    principal TEXT NOT NULL,
                    PRIMARY KEY(budget_id, principal)
                )""")
                conn.execute("""CREATE TABLE connections (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    server_url TEXT NOT NULL,
                    project_path TEXT NOT NULL,
                    token_env TEXT NOT NULL,
                    target_id TEXT NOT NULL DEFAULT ''
                )""")
                conn.execute("""CREATE TABLE execution_accounts (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    system TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    connection_id TEXT NOT NULL REFERENCES connections(id),
                    build_tag TEXT NOT NULL,
                    run_tag TEXT NOT NULL,
                    id_token_audience TEXT NOT NULL
                )""")
                conn.execute("""CREATE TABLE destinations (
                    id TEXT PRIMARY KEY,
                    budget_id TEXT NOT NULL REFERENCES budgets(id),
                    system TEXT NOT NULL,
                    account_id TEXT NOT NULL REFERENCES execution_accounts(id),
                    allocation_project_id TEXT NOT NULL,
                    UNIQUE(budget_id, system)
                )""")
                conn.execute("""CREATE TABLE budget_defaults (
                    id TEXT PRIMARY KEY REFERENCES budgets(id),
                    account_id TEXT NOT NULL REFERENCES execution_accounts(id),
                    allocation_project_id TEXT NOT NULL
                )""")
                conn.execute("""CREATE TABLE registry_history (
                    revision INTEGER PRIMARY KEY,
                    actor TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL
                )""")

    def migrate_empty(self):
        """Explicitly upgrade an unused prototype without losing data.

        Populated registries need a separately reviewed migration; never infer
        which system, manager assignments, or enabled state should survive.
        """
        with self.storage.connect() as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                self._migrate_empty_to_three(conn)
                self._migrate_targets(conn)

    @staticmethod
    def _migrate_empty_to_three(conn):
        row = conn.execute("SELECT schema_version, revision FROM registry_meta WHERE singleton=1").fetchone()
        if row is None or row["schema_version"] not in (1, 2) or row["revision"] != 0:
            raise RegistryError("Only an unused version-1 or version-2 registry can be migrated")
        managers = "budget_members" if row["schema_version"] == 1 else "budget_managers"
        for table in ("budgets", managers, "connections", "execution_accounts", "destinations", "registry_history"):
            if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                raise RegistryError("Populated registries require a reviewed migration")
        if row["schema_version"] == 1:
            conn.execute("ALTER TABLE budgets ADD COLUMN system TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE budget_members RENAME TO budget_managers")
            conn.execute("ALTER TABLE budget_managers DROP COLUMN role")
            conn.execute("ALTER TABLE destinations DROP COLUMN enabled")
            conn.execute("CREATE UNIQUE INDEX destinations_budget ON destinations(budget_id)")
        conn.execute("ALTER TABLE connections ADD COLUMN target_id TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE registry_meta SET schema_version=3 WHERE singleton=1")

    def migrate_targets(self):
        """Explicitly preserve populated version-3 registries as singleton groups."""
        with self.storage.connect() as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                self._migrate_targets(conn)

    @staticmethod
    def _migrate_targets(conn):
        if BudgetRegistry._schema(conn) != 3:
            raise RegistryError("Execution-target migration requires a version-3 registry")
        if conn.execute("""SELECT 1 FROM destinations d
                JOIN budgets b ON b.id=d.budget_id
                JOIN execution_accounts a ON a.id=d.account_id
                WHERE d.system<>b.system OR d.system<>a.system LIMIT 1""").fetchone():
            raise RegistryError("Existing destination systems are inconsistent")
        EncryptedSQLite._check_connection(conn)
        conn.execute("""CREATE TABLE destinations_next (
            id TEXT PRIMARY KEY, budget_id TEXT NOT NULL REFERENCES budgets(id),
            system TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES execution_accounts(id),
            allocation_project_id TEXT NOT NULL, UNIQUE(budget_id, system))""")
        conn.execute("INSERT INTO destinations_next SELECT * FROM destinations")
        conn.execute("DROP TABLE destinations")
        conn.execute("ALTER TABLE destinations_next RENAME TO destinations")
        conn.execute("""CREATE TABLE budget_defaults (
            id TEXT PRIMARY KEY REFERENCES budgets(id), account_id TEXT NOT NULL REFERENCES execution_accounts(id),
            allocation_project_id TEXT NOT NULL)""")
        conn.execute("UPDATE registry_meta SET schema_version=? WHERE singleton=1", (SCHEMA_VERSION,))

    @staticmethod
    def _schema(conn):
        row = conn.execute("SELECT schema_version FROM registry_meta WHERE singleton=1").fetchone()
        if row is None or row["schema_version"] not in (3, SCHEMA_VERSION):
            raise RegistryError("Unsupported budget registry schema; explicit migration required")
        return row["schema_version"]

    @staticmethod
    def _revision(conn):
        row = conn.execute("SELECT schema_version, revision FROM registry_meta WHERE singleton=1").fetchone()
        if row is None or row["schema_version"] not in (3, SCHEMA_VERSION):
            raise RegistryError("Unsupported budget registry schema; explicit migration required")
        return row["revision"]

    @staticmethod
    def _authorize(conn, actor, budget_id=None):
        if (not isinstance(actor, RegistryActor) or not isinstance(actor.principal, str)
                or not actor.principal.strip() or type(actor.is_admin) is not bool):
            raise RegistryPermissionError("Authenticated registry identity is required")
        if actor.is_admin:
            return
        row = None
        if budget_id:
            row = conn.execute("SELECT 1 FROM budget_managers WHERE budget_id=? AND principal=?",
                               (budget_id, actor.principal)).fetchone()
        if row is None:
            raise RegistryPermissionError("Budget access is not permitted")

    @contextmanager
    def _edit(self, actor, expected_revision, *, budget_id=None, preview=False):
        if type(expected_revision) is not int or expected_revision < 0:
            raise RegistryConflict("A valid registry revision is required")
        with self.storage.connect() as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                revision = self._revision(conn)
                self._authorize(conn, actor, budget_id)
                if revision != expected_revision:
                    raise RegistryConflict("Registry changed; reload before saving")
                yield conn
                if preview:
                    conn.rollback()

    @staticmethod
    def _record(conn, actor, table, entity_id, before, after):
        conn.execute("UPDATE registry_meta SET revision=revision+1 WHERE singleton=1")
        revision = conn.execute("SELECT revision FROM registry_meta WHERE singleton=1").fetchone()[0]
        conn.execute("INSERT INTO registry_history VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (revision, actor.principal, datetime.now(UTC).isoformat(), table, entity_id,
                      json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True)))
        return revision

    def _save(self, conn, actor, table, values, *, skip_unchanged=False):
        # Table and column names are exclusively supplied by the typed methods
        # below; all submitted values remain SQL parameters.
        before = conn.execute(f"SELECT * FROM {table} WHERE id=?", (values["id"],)).fetchone()
        if skip_unchanged and before and dict(before) == values:
            return self._revision(conn)
        columns = list(values)
        assignments = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "id")
        placeholders = ",".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {assignments}", tuple(values.values()),
        )
        return self._record(conn, actor, table, values["id"], dict(before) if before else None, values)

    def save_budget(self, actor, expected_revision, *, id, label, system, enabled=False,
                    valid_from="", valid_until="", preview=False):
        with self._edit(actor, expected_revision, budget_id=id, preview=preview) as conn:
            return self._save_budget(conn, actor, id=id, label=label, system=system, enabled=enabled,
                                     valid_from=valid_from, valid_until=valid_until)

    def _save_budget(self, conn, actor, *, id, label, system, enabled, valid_from, valid_until):
        _dates(valid_from, valid_until)
        if type(enabled) is not bool:
            raise RegistryError("Budget enabled state must be boolean")
        system = _id(system) if self._schema(conn) == 3 else _text(system)
        values = dict(id=_id(id), label=_text(label), system=system, enabled=int(enabled),
                      valid_from=valid_from, valid_until=valid_until)
        before = conn.execute("SELECT system FROM budgets WHERE id=?", (id,)).fetchone()
        if before and before["system"] != system:
            raise RegistryError("A budget cannot change system; create a separate budget")
        return self._save(conn, actor, "budgets", values)

    def set_manager(self, actor, expected_revision, *, budget_id, principal, assigned, preview=False):
        _id(budget_id)
        principal = _text(principal)
        if type(assigned) is not bool:
            raise RegistryError("Manager assignment must be boolean")
        with self._edit(actor, expected_revision, preview=preview) as conn:
            if conn.execute("SELECT 1 FROM budgets WHERE id=?", (budget_id,)).fetchone() is None:
                raise RegistryError("Budget does not exist")
            before = conn.execute("SELECT * FROM budget_managers WHERE budget_id=? AND principal=?", (budget_id, principal)).fetchone()
            if not assigned:
                conn.execute("DELETE FROM budget_managers WHERE budget_id=? AND principal=?", (budget_id, principal))
            else:
                conn.execute("INSERT INTO budget_managers VALUES (?, ?) ON CONFLICT DO NOTHING", (budget_id, principal))
            return self._record(conn, actor, "budget_managers", budget_id,
                                dict(before) if before else None, dict(principal=principal, assigned=assigned))

    def save_connection(self, actor, expected_revision, *, id, label, server_url,
                        project_path, token_env, preview=False):
        with self._edit(actor, expected_revision, preview=preview) as conn:
            return self._save_connection(conn, actor, id=id, label=label, server_url=server_url,
                                         project_path=project_path, token_env=token_env)

    def _save_connection(self, conn, actor, *, id, label, server_url, project_path, token_env,
                         skip_unchanged=False):
        if _id(id).startswith("gitlab:"):
            raise RegistryError("Configured GitLab targets are managed in server configuration")
        values = dict(id=_id(id), label=_text(label), target_id="",
                      **self._connection_fields(server_url, project_path, token_env))
        return self._save(conn, actor, "connections", values, skip_unchanged=skip_unchanged)

    @staticmethod
    def _connection_fields(server_url, project_path, token_env):
        server_url = _text(server_url)
        project_path = _text(project_path)
        token_env = _text(token_env)
        try:
            parsed = urlsplit(server_url)
            valid_url = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                         and not parsed.password and parsed.path in ("", "/")
                         and not parsed.query and not parsed.fragment)
            parsed.port
        except (TypeError, ValueError):
            valid_url = False
        if (not valid_url or any(c.isspace() for c in server_url)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", project_path)
                or not re.fullmatch(r"RESULT_SERVER_GITLAB_TRIGGER_TOKEN(?:_[A-Z0-9_]+)?", token_env)):
            raise RegistryError("Invalid connection or credential reference")
        return dict(server_url=server_url.rstrip("/"), project_path=project_path, token_env=token_env)

    def _connections(self, conn):
        targets, errors = configured_gitlab_targets()
        if errors:
            raise RegistryError("GitLab target configuration is invalid")
        configured = {}
        for target in targets:
            try:
                parsed = urlsplit("https://" + target.repo.removesuffix(".git"))
                if parsed.query or parsed.fragment:
                    raise RegistryError("Invalid GitLab target")
                fields = self._connection_fields("https://" + parsed.netloc, parsed.path.lstrip("/"), target.token_env)
            except (ValueError, RegistryError):
                raise RegistryError("GitLab target configuration is invalid") from None
            configured["gitlab:" + target.id] = dict(id="gitlab:" + target.id, label=target.id,
                                                    target_id=target.id, available=True, **fields)
        records = []
        for row in conn.execute("SELECT * FROM connections"):
            record = dict(row)
            if record["target_id"]:
                resolved = configured.pop(record["id"], None)
                if resolved and resolved["target_id"] == record["target_id"]:
                    record = resolved
                else:
                    record.update(available=False, server_url="", project_path="", token_env="")
            else:
                record["available"] = True
            records.append(record)
        return records + list(configured.values())

    def _ensure_connection(self, conn, actor, id, expected=None):
        record = next((row for row in self._connections(conn) if row["id"] == id), None)
        if not record or not record["available"]:
            raise RegistryError("Select an available GitLab connection")
        if expected is not None and record != expected:
            raise RegistryConflict("GitLab connection changed; review the change again")
        if record["target_id"] and not conn.execute("SELECT 1 FROM connections WHERE id=?", (id,)).fetchone():
            # Store the target reference, never a second copy of server settings.
            self._save(conn, actor, "connections", dict(id=id, label=record["label"], target_id=record["target_id"],
                                                       server_url="", project_path="", token_env=""))
        return record

    def save_account(self, actor, expected_revision, *, id, label, system,
                     connection_id, build_tag, run_tag, id_token_audience="", expected_connection=None, preview=False):
        with self._edit(actor, expected_revision, preview=preview) as conn:
            self._ensure_connection(conn, actor, connection_id, expected_connection)
            return self._save_account(conn, actor, id=id, label=label, system=system,
                                      connection_id=connection_id,
                                      build_tag=build_tag, run_tag=run_tag, id_token_audience=id_token_audience)

    def _save_account(self, conn, actor, *, id, label, system, connection_id,
                      build_tag, run_tag, id_token_audience, skip_unchanged=False):
        # Preserve retired metadata in existing databases without accepting new
        # account names or including them in execution settings.
        legacy = conn.execute("SELECT account_name FROM execution_accounts WHERE id=?", (_id(id),)).fetchone()
        system = _id(system) if self._schema(conn) == 3 else _text(system)
        values = dict(id=_id(id), label=_text(label), system=system,
                      account_name=legacy["account_name"] if legacy else "",
                      connection_id=_id(connection_id), build_tag=_id(build_tag) if build_tag else "",
                      run_tag=_id(run_tag), id_token_audience=id_token_audience)
        if (not isinstance(id_token_audience, str)
                or (id_token_audience and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}", id_token_audience))):
            raise RegistryError("Invalid ID token audience")
        if conn.execute("""SELECT 1 FROM destinations d JOIN budgets b ON b.id=d.budget_id
                          WHERE d.account_id=? AND b.system<>?""", (id, system)).fetchone():
            raise RegistryError("An assigned account cannot change system")
        if self._schema(conn) >= 4 and conn.execute("""SELECT 1 FROM budget_defaults d JOIN budgets b ON b.id=d.id
                WHERE d.account_id=? AND b.system<>?""", (id, system)).fetchone():
            raise RegistryError("Assigned common settings cannot change managed system")
        return self._save(conn, actor, "execution_accounts", values, skip_unchanged=skip_unchanged)

    def save_destination(self, actor, expected_revision, *, id, budget_id, system,
                         account_id, allocation_project_id, preview=False):
        with self._edit(actor, expected_revision, preview=preview) as conn:
            return self._save_destination(conn, actor, id=id, budget_id=budget_id, system=system,
                                          account_id=account_id, allocation_project_id=allocation_project_id)

    def _save_destination(self, conn, actor, *, id, budget_id, system, account_id,
                          allocation_project_id, group_update=False):
        values = dict(id=_id(id), budget_id=_id(budget_id), system=_id(system),
                      account_id=_id(account_id),
                      allocation_project_id="" if allocation_project_id == "" else _id(allocation_project_id))
        account = conn.execute("SELECT system FROM execution_accounts WHERE id=?", (account_id,)).fetchone()
        budget = conn.execute("SELECT system FROM budgets WHERE id=?", (budget_id,)).fetchone()
        if not budget or not account or account["system"] != budget["system"]:
            raise RegistryError("Execution settings must use the budget's managed system")
        if self._schema(conn) == 3 and budget["system"] != system:
            raise RegistryError("Destination must use the budget's system")
        before = conn.execute("SELECT budget_id, system FROM destinations WHERE id=?", (id,)).fetchone()
        if before and (before["budget_id"] != budget_id or before["system"] != system):
            raise RegistryError("Destination identity cannot change budget or system")
        duplicate = conn.execute("SELECT id FROM destinations WHERE budget_id=? AND id<>? AND (?=3 OR system=?)",
                                 (budget_id, id, self._schema(conn), system)).fetchone()
        if duplicate:
            raise RegistryError("This budget already has an execution destination")
        if not group_update and conn.execute(
                "SELECT 1 FROM destinations WHERE budget_id=? AND id<>? AND allocation_project_id<>?",
                (budget_id, id, values["allocation_project_id"])).fetchone():
            raise RegistryError("Change the allocation for all execution targets in the Budget editor")
        if not group_update and self._schema(conn) >= 4 and conn.execute(
                "SELECT 1 FROM budget_defaults WHERE id=? AND allocation_project_id<>?",
                (budget_id, values["allocation_project_id"])).fetchone():
            raise RegistryError("Change the allocation in the grouped Budget editor")
        return self._save(conn, actor, "destinations", values)

    @staticmethod
    def _single_target(conn, budget_id, system):
        if conn.execute("SELECT 1 FROM destinations WHERE budget_id=? AND system<>?",
                        (budget_id, system)).fetchone():
            raise RegistryError("Use the grouped Budget editor for multiple execution targets")
        if BudgetRegistry._schema(conn) >= 4 and conn.execute(
                "SELECT 1 FROM budget_defaults WHERE id=?", (budget_id,)).fetchone():
            raise RegistryError("Use the grouped Budget editor for common execution settings")

    def save_budget_system(self, actor, expected_revision, *, budget_id, destination_id,
                           label, valid_from, valid_until, system,
                           account_id, allocation_project_id, enabled, preview=False):
        """Apply the budget and its destination atomically after one review.

        Both history records are in the same transaction; failed destination
        validation must not leave a budget edit or new empty budget behind.
        """
        with self._edit(actor, expected_revision, preview=preview) as conn:
            self._single_target(conn, budget_id, system)
            self._save_budget(conn, actor, id=budget_id, label=label, system=system, enabled=enabled,
                              valid_from=valid_from, valid_until=valid_until)
            return self._save_destination(conn, actor, id=destination_id, budget_id=budget_id,
                                          system=system, account_id=account_id,
                                          allocation_project_id=allocation_project_id)

    def save_budget_setup(self, actor, expected_revision, *, budget_id, destination_id,
                          label, enabled, valid_from, valid_until, system, allocation_project_id,
                          account_id, build_tag, run_tag, connection_id,
                          new_account, expected_connection=None, preview=False):
        """Save a budget and runner tags without editing connection credentials."""
        with self._edit(actor, expected_revision, preview=preview) as conn:
            self._single_target(conn, budget_id, system)
            account = conn.execute("SELECT * FROM execution_accounts WHERE id=?", (_id(account_id),)).fetchone()
            if type(new_account) is not bool or bool(account) == new_account:
                raise RegistryError("Selected execution settings are unavailable")
            if account and account["system"] != system:
                raise RegistryError("Selected execution settings do not match the system")
            self._ensure_connection(conn, actor, connection_id, expected_connection)
            if account and account["connection_id"] != connection_id and account["id_token_audience"]:
                raise RegistryError("Change the connection and custom audience in Execution settings")
            self._save_account(conn, actor, id=account_id, label=account["label"] if account else "Execution settings",
                               system=system, connection_id=connection_id,
                               build_tag=build_tag, run_tag=run_tag,
                               id_token_audience=account["id_token_audience"] if account else "",
                               skip_unchanged=True)
            self._save_budget(conn, actor, id=budget_id, label=label, system=system, enabled=enabled,
                              valid_from=valid_from, valid_until=valid_until)
            return self._save_destination(conn, actor, id=destination_id, budget_id=budget_id, system=system,
                                          account_id=account_id, allocation_project_id=allocation_project_id)

    def save_budget_group(self, actor, expected_revision, *, budget_id, label, system, enabled,
                          valid_from, valid_until, allocation_project_id, targets,
                          account_id, connection_id, build_tag, run_tag, new_account,
                          expected_connection=None, expected_target_connections=None, preview=False):
        """Review one managed system and its explicit execution targets atomically.

        An empty target account reference inherits the common settings. Other
        references select settings in the same managed system, never by tag
        similarity. Removing a target revokes resolution of its destination ID.
        """
        if not isinstance(targets, list) or not 1 <= len(targets) <= 64:
            raise RegistryError("Select between 1 and 64 execution targets")
        with self._edit(actor, expected_revision, preview=preview) as conn:
            if self._schema(conn) != SCHEMA_VERSION:
                raise RegistryError("Execution groups require an explicit database migration")
            seen_ids, seen_systems = set(), set()
            for target in targets:
                if not isinstance(target, dict) or set(target) != {"id", "system", "account_id"}:
                    raise RegistryError("Invalid execution target")
                target_id, target_system = _id(target["id"]), _id(target["system"])
                if target_id in seen_ids or target_system in seen_systems:
                    raise RegistryError("Duplicate execution target")
                seen_ids.add(target_id)
                seen_systems.add(target_system)
                if target["account_id"]:
                    _id(target["account_id"])
                elif target["account_id"] != "":
                    raise RegistryError("Invalid execution settings reference")
            account = conn.execute("SELECT * FROM execution_accounts WHERE id=?", (_id(account_id),)).fetchone()
            if type(new_account) is not bool or bool(account) == new_account:
                raise RegistryError("Selected execution settings are unavailable")
            if account and account["system"] != system:
                raise RegistryError("Selected execution settings do not match the managed system")
            self._ensure_connection(conn, actor, connection_id, expected_connection)
            if account and account["connection_id"] != connection_id and account["id_token_audience"]:
                raise RegistryError("Change the connection and custom audience in Execution settings")
            self._save_account(conn, actor, id=account_id, label=account["label"] if account else "Execution settings",
                               system=system, connection_id=connection_id, build_tag=build_tag, run_tag=run_tag,
                               id_token_audience=account["id_token_audience"] if account else "", skip_unchanged=True)
            self._save_budget(conn, actor, id=budget_id, label=label, system=system, enabled=enabled,
                              valid_from=valid_from, valid_until=valid_until)
            self._save(conn, actor, "budget_defaults", dict(id=budget_id, account_id=account_id,
                       allocation_project_id="" if allocation_project_id == "" else _id(allocation_project_id)),
                       skip_unchanged=True)
            previous = conn.execute("SELECT * FROM destinations WHERE budget_id=?", (budget_id,)).fetchall()
            for target in targets:
                selected_account = target["account_id"] or account_id
                other = conn.execute("SELECT connection_id FROM execution_accounts WHERE id=?", (selected_account,)).fetchone()
                if not other:
                    raise RegistryError("Selected execution settings are unavailable")
                expected = (expected_target_connections or {}).get(other["connection_id"])
                self._ensure_connection(conn, actor, other["connection_id"], expected)
                self._save_destination(conn, actor, id=target["id"], budget_id=budget_id, system=target["system"],
                                       account_id=selected_account, allocation_project_id=allocation_project_id,
                                       group_update=True)
            for old in previous:
                if old["id"] not in seen_ids:
                    conn.execute("DELETE FROM destinations WHERE id=?", (old["id"],))
                    self._record(conn, actor, "destinations", old["id"], dict(old), None)
            return self._revision(conn)

    def create_budget_batch(self, actor, expected_revision, *, entries, connection_id,
                            build_tag, run_tag, allocation_project_id, enabled,
                            expected_connection=None, preview=False):
        """Create independent budgets in one transaction, never replace a system."""
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise RegistryError("Select between 1 and 64 systems")
        fields = {"budget_id", "destination_id", "account_id", "system", "label"}
        with self._edit(actor, expected_revision, preview=preview) as conn:
            self._ensure_connection(conn, actor, connection_id, expected_connection)
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != fields:
                    raise RegistryError("Invalid batch entry")
                if conn.execute("SELECT 1 FROM budgets WHERE system=?", (_id(entry["system"]),)).fetchone():
                    raise RegistryError("A selected system already has a budget; edit it individually")
                for table, key in (("budgets", "budget_id"), ("destinations", "destination_id"),
                                   ("execution_accounts", "account_id")):
                    if conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (_id(entry[key]),)).fetchone():
                        raise RegistryError("Batch identifiers must be new")
                self._save_account(conn, actor, id=entry["account_id"], label="Execution settings",
                                   system=entry["system"], connection_id=connection_id,
                                   build_tag=build_tag, run_tag=run_tag, id_token_audience="")
                self._save_budget(conn, actor, id=entry["budget_id"], label=entry["label"],
                                  system=entry["system"], enabled=enabled, valid_from="", valid_until="")
                self._save_destination(conn, actor, id=entry["destination_id"], budget_id=entry["budget_id"],
                                       system=entry["system"], account_id=entry["account_id"],
                                       allocation_project_id=allocation_project_id)
            return self._revision(conn)

    def catalog(self, actor):
        """Return one consistent catalog for authorized administrative editing."""
        with self.storage.connect(readonly=True) as conn:
            conn.execute("BEGIN")
            self._authorize(conn, actor)
            catalog = {"revision": self._revision(conn), "schema_version": self._schema(conn)}
            for table in ("budgets", "budget_managers", "connections", "execution_accounts", "destinations"):
                catalog[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            catalog["budget_defaults"] = ([dict(row) for row in conn.execute("SELECT * FROM budget_defaults")]
                                          if self._schema(conn) >= 4 else [])
            for record in catalog["execution_accounts"]:
                record.pop("account_name", None)
            catalog["connections"] = self._connections(conn)
            return catalog

    def list_destinations(self, actor):
        """Return budget-first choices without disclosing runner/account details."""
        if (not isinstance(actor, RegistryActor) or not isinstance(actor.principal, str)
                or not actor.principal.strip() or type(actor.is_admin) is not bool):
            raise RegistryPermissionError("Authenticated registry identity is required")
        with self.storage.connect(readonly=True) as conn:
            conn.execute("BEGIN")
            revision = self._revision(conn)
            rows = conn.execute("""SELECT d.id, d.budget_id, b.label AS budget_label, d.system,
                       b.system AS managed_system,
                       b.enabled,
                       b.valid_from, b.valid_until
                FROM destinations d JOIN budgets b ON b.id=d.budget_id
                WHERE ? OR EXISTS (SELECT 1 FROM budget_managers m
                                   WHERE m.budget_id=b.id AND m.principal=?)
                ORDER BY b.label, d.system, d.id""", (actor.is_admin, actor.principal))
            return {"revision": revision, "destinations": [dict(row) for row in rows]}

    def management_catalog(self, actor):
        """Return only records this identity can manage, including scoped history."""
        if (not isinstance(actor, RegistryActor) or not isinstance(actor.principal, str)
                or not actor.principal.strip() or type(actor.is_admin) is not bool):
            raise RegistryPermissionError("Authenticated registry identity is required")
        if actor.is_admin:
            allowed = None
        else:
            allowed = []
        with self.storage.connect(readonly=True) as conn:
            conn.execute("BEGIN")
            revision = self._revision(conn)
            if allowed is not None:
                allowed = [row[0] for row in conn.execute(
                    "SELECT budget_id FROM budget_managers WHERE principal=?",
                    (actor.principal,),
                )]
                if not allowed:
                    raise RegistryPermissionError("Budget management access is not permitted")
            else:
                self._authorize(conn, actor)
            catalog = {"revision": revision, "schema_version": self._schema(conn)}
            for table in ("budgets", "budget_managers", "connections", "execution_accounts", "destinations"):
                if allowed is None:
                    rows = conn.execute(f"SELECT * FROM {table}")
                elif table in ("connections", "execution_accounts"):
                    rows = []
                else:
                    column = "id" if table == "budgets" else "budget_id"
                    placeholders = ",".join("?" for _ in allowed)
                    rows = conn.execute(f"SELECT * FROM {table} WHERE {column} IN ({placeholders})", allowed)
                catalog[table] = [dict(row) for row in rows]
            for record in catalog["execution_accounts"]:
                record.pop("account_name", None)
            if allowed is None:
                catalog["connections"] = self._connections(conn)
            catalog["budget_defaults"] = ([dict(row) for row in conn.execute("SELECT * FROM budget_defaults")]
                                          if allowed is None and self._schema(conn) >= 4 else [])
            if allowed is None:
                history = conn.execute("SELECT * FROM registry_history ORDER BY revision DESC LIMIT 20")
            else:
                placeholders = ",".join("?" for _ in allowed)
                history = conn.execute(
                    f"SELECT * FROM registry_history WHERE entity_type IN ('budgets','budget_managers') "
                    f"AND entity_id IN ({placeholders}) ORDER BY revision DESC LIMIT 20", allowed,
                )
            catalog["history"] = [dict(row) for row in history]
            return catalog

    def resolve(self, actor, destination_id, *, today=None):
        """Resolve one authorized budget @ system into an immutable value snapshot."""
        with self.storage.connect(readonly=True) as conn:
            conn.execute("BEGIN")
            revision = self._revision(conn)
            row = conn.execute("""SELECT d.*, b.label AS budget_label, b.enabled, b.system AS budget_system,
                       b.valid_from, b.valid_until, a.system AS account_system,
                       a.build_tag, a.run_tag, a.id_token_audience, c.id AS connection_id
                FROM destinations d JOIN budgets b ON b.id=d.budget_id
                JOIN execution_accounts a ON a.id=d.account_id
                JOIN connections c ON c.id=a.connection_id WHERE d.id=?""", (destination_id,)).fetchone()
            if row is None:
                raise RegistryPermissionError("Destination is unavailable or not permitted")
            self._authorize(conn, actor, row["budget_id"])
            now = (today or datetime.now(UTC).date()).isoformat()
            if (not row["enabled"] or row["budget_system"] != row["account_system"]
                    or (self._schema(conn) == 3 and row["system"] != row["budget_system"])
                    or (row["valid_from"] and now < row["valid_from"])
                    or (row["valid_until"] and now > row["valid_until"])):
                raise RegistryError("Destination is disabled or outside its validity interval")
            connection = next((item for item in self._connections(conn) if item["id"] == row["connection_id"]), None)
            if not connection or not connection["available"]:
                raise RegistryError("GitLab connection is unavailable")
            return {
                "version": 1, "registry_revision": revision, "destination_id": row["id"],
                "budget_id": row["budget_id"], "system": row["system"], "managed_system": row["budget_system"],
                "account_id": row["account_id"],
                "connection_id": row["connection_id"], "token_env": connection["token_env"],
                "target": {"server_url": connection["server_url"], "project_path": connection["project_path"]},
                "route": {"id": row["id"], "systems": [row["system"]],
                          "build_tag": row["build_tag"], "run_tag": row["run_tag"],
                          "allocation_project_id": row["allocation_project_id"],
                          "id_token_audience": row["id_token_audience"] or connection["server_url"]},
            }

    def check(self):
        self.storage.check()
        with self.storage.connect(readonly=True) as conn:
            return self._revision(conn)
