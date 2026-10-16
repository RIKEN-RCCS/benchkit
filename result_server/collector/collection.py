"""Fresh GitLab observations to protocol batches; no retained CX snapshot needed."""

from datetime import datetime, timezone
import json
import re
import time

from utils.runner_observation_protocol import (
    ERROR_CODES, MAX_BYTES, MAX_MANAGERS, MAX_RUNNERS, ProtocolError, validate_batch,
)
from .delivery import batch_identity
from .errors import DeliveryError
from .gitlab import ObservationError, RunnerClient


def collect_batch(policy, targets, sequence, *, client_factory=RunnerClient,
                  now=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
    """Deduplicate server/runner reads and retry with same-server credentials only."""
    expected = {spec.target_id: spec for spec in policy.targets}
    if (len(targets) != len(expected) or len({target.id for target in targets}) != len(targets)
            or any(target.id not in expected or {
                "server": target.server, "project": target.project,
                "runner_types": sorted(target.runner_types)} != expected[target.id].identity()
                for target in targets)):
        raise DeliveryError("invalid_collection_configuration")
    started = now()
    deadline = monotonic() + 240
    candidates, inventories, size = {}, [], 0

    def observe(fetch):
        try:
            if monotonic() >= deadline:
                raise ObservationError("collection_timeout")
            data = fetch()
            return {"status": "ok", "observed_at": now().isoformat(), "data": data}
        except ObservationError as error:
            code = str(error)
            if code not in ERROR_CODES and not re.fullmatch(r"http_[1-5][0-9]{2}", code):
                code = "invalid_response"
            return {"status": "error", "observed_at": now().isoformat(), "error_code": code}

    for target in sorted(targets, key=lambda target: target.id):
        client = None
        def inventory():
            nonlocal client
            client = client_factory(target)
            client.deadline = deadline
            return client.inventory()
        resource = observe(inventory)
        inventories.append({"target_id": target.id, "inventory": resource})
        size += len(json.dumps(inventories[-1], ensure_ascii=True).encode("ascii"))
        if size > MAX_BYTES:
            raise DeliveryError("invalid_collected_batch")
        if resource["status"] == "ok":
            for row in resource["data"]:
                key = (expected[target.id].server_id, row["id"])
                candidates.setdefault(key, []).append(client)
                if len(candidates) > MAX_RUNNERS:
                    raise DeliveryError("invalid_collected_batch")

    runners, managers = [], 0
    for (server_id, runner_id), clients in sorted(candidates.items()):
        runner = {"server_id": server_id, "runner_id": runner_id}
        for name in ("detail", "managers"):
            def fetch(name=name):
                error = ObservationError("invalid_response")
                for client in clients:
                    if monotonic() >= deadline:
                        raise ObservationError("collection_timeout")
                    try:
                        return getattr(client, name)(runner_id)
                    except ObservationError as exc:
                        error = exc
                raise error
            runner[name] = observe(fetch)
        if runner["managers"]["status"] == "ok":
            managers += len(runner["managers"]["data"])
        size += len(json.dumps(runner, ensure_ascii=True).encode("ascii"))
        if managers > MAX_MANAGERS or size > MAX_BYTES:
            raise DeliveryError("invalid_collected_batch")
        runners.append(runner)
    value = {**batch_identity(policy, sequence), "started_at": started.isoformat(),
             "finished_at": now().isoformat(), "targets": inventories, "runners": runners}
    try:
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
        validate_batch(raw, policy, received_at=now())
        return raw
    except (ValueError, TypeError, ProtocolError, RecursionError):
        raise DeliveryError("invalid_collected_batch") from None
