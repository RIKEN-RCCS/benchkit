"""Atomic encrypted snapshots with separate inventory and runner observations."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import time

from .encrypted_sqlite import EncryptedSQLite, EncryptedDatabaseError
from .runner_monitor import ObservationError, RunnerClient


class RunnerObservations:
    def __init__(self, path, key_file):
        self.storage = EncryptedSQLite(path, key_file)

    def initialize(self):
        with self.storage.connect(create=True) as conn:
            conn.execute("CREATE TABLE runner_observations (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
            conn.execute("INSERT INTO runner_observations VALUES (1, ?)",
                         (json.dumps({"targets": {}, "runners": {}}),))
            conn.execute("PRAGMA user_version = 1")
            conn.commit()

    @staticmethod
    def _schema(conn):
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise EncryptedDatabaseError("Runner observation schema is unsupported")

    def read(self):
        with self.storage.connect(readonly=True) as conn:
            self._schema(conn)
            row = conn.execute("SELECT data FROM runner_observations WHERE id=1").fetchone()
            try:
                data = json.loads(row[0])
                if not isinstance(data["targets"], dict) or not isinstance(data["runners"], dict):
                    raise ValueError
                return data
            except (ValueError, TypeError, KeyError):
                raise EncryptedDatabaseError("Runner observation data is invalid") from None

    def save(self, snapshot):
        with self.storage.connect() as conn:
            self._schema(conn)
            conn.execute("UPDATE runner_observations SET data=? WHERE id=1", (json.dumps(snapshot),))
            conn.commit()


def runner_key(server, runner_id):
    return json.dumps([server, runner_id], separators=(",", ":"))


def observe(previous, fetch, now):
    result = deepcopy(previous or {})
    result["attempted_at"] = now
    try:
        result["data"] = fetch()
        result["last_success_at"] = now
        result["error"] = ""
    except ObservationError as exc:
        result["error"] = str(exc)
    return result


def collect(targets, previous, *, client_factory=RunnerClient, now=None):
    """Keep failed observations, replace only complete successful inventories.

    Runner details are read once per server/ID. Another associated project's
    credential may retry a failed read, without expanding the server boundary.
    """
    now = now or datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + 240
    snapshot = {"targets": {}, "runners": {}, "collected_at": now}
    clients, candidates = {}, {}
    for target in targets:
        old = previous.get("targets", {}).get(target.id, {})
        identity = {"server": target.server, "project": target.project, "runner_types": sorted(target.runner_types)}
        if old.get("identity") != identity:
            old = {}
        try:
            client = client_factory(target)
            client.deadline = deadline
            clients[target.id] = client
            fetch = client.inventory
        except ObservationError as exc:
            error = str(exc)
            def fetch(error=error):
                raise ObservationError(error)
        observation = observe(old.get("inventory"), fetch, now)
        snapshot["targets"][target.id] = {"identity": identity, "inventory": observation}
        for row in observation.get("data", []):
            key = runner_key(target.server, row["id"])
            if key not in snapshot["runners"]:
                snapshot["runners"][key] = deepcopy(previous.get("runners", {}).get(key, {}))
                snapshot["runners"][key].update(server=target.server, id=row["id"], targets=[], summary=row)
            snapshot["runners"][key]["targets"].append(target.id)
            if not observation["error"] and target.id in clients:
                candidates.setdefault(key, []).append(clients[target.id])
    for key, runner in snapshot["runners"].items():
        for resource in ("detail", "managers"):
            def fetch(resource=resource, key=key, runner=runner):
                error = "inventory_unavailable"
                for client in candidates.get(key, []):
                    try:
                        return getattr(client, resource)(runner["id"])
                    except ObservationError as exc:
                        error = str(exc)
                raise ObservationError(error)
            runner[resource] = observe(runner.get(resource), fetch, now)
    return snapshot


def observation_state(observation, now, max_age):
    if not observation or not observation.get("last_success_at"):
        return "unavailable" if observation and observation.get("error") else "not_observed"
    if observation.get("error"):
        return "unavailable"
    age = (now - datetime.fromisoformat(observation["last_success_at"])).total_seconds()
    return "expired" if age < 0 or age > max_age else "current"


def relative_age(value, now):
    if not value:
        return "Never"
    seconds = int((now - datetime.fromisoformat(value)).total_seconds())
    if seconds < 0:
        return "Clock mismatch"
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def presentation(snapshot, *, now=None, max_age=900):
    now = now or datetime.now(timezone.utc)
    targets = []
    for target_id, target in snapshot["targets"].items():
        observation = target["inventory"]
        targets.append({"id": target_id, **target["identity"], **observation,
                        "last_success_age": relative_age(observation.get("last_success_at"), now),
                        "state": observation_state(observation, now, max_age),
                        "count": len(observation["data"]) if "data" in observation else None})
    runners = []
    for runner in snapshot["runners"].values():
        detail = runner.get("detail", {})
        managers = runner.get("managers", {})
        state = observation_state(detail, now, max_age)
        data = detail.get("data", {})
        runners.append({**runner, "record": data, "state": state,
                        "last_success_age": relative_age(detail.get("last_success_at"), now),
                        "heartbeat": data.get("status", "unknown") if state == "current" else "unknown",
                        "manager_state": observation_state(managers, now, max_age)})
    return {"targets": sorted(targets, key=lambda item: item["id"]),
            "runners": sorted(runners, key=lambda item: (item["server"], item["id"]))}
