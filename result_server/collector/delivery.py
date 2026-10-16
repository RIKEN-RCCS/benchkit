"""Durable one-shot delivery; retry the identical pending batch before collecting."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import time
import uuid

from utils.runner_observation_protocol import ProtocolError, validate_batch
from .errors import DeliveryError
from .state import DeliveryState, _object
from .transport import MAX_RESPONSE_BYTES, validate_endpoint


RETRYABLE = {429, 500, 502, 503, 504}


def utc_now():
    return datetime.now(timezone.utc)


def _acknowledged(response, batch):
    try:
        if type(response.body) is not bytes or len(response.body) > MAX_RESPONSE_BYTES:
            raise ValueError
        value = json.loads(response.body, object_pairs_hook=_object)
        if (not isinstance(value, dict) or set(value) != {
                "schema_version", "source_id", "generation", "sequence", "batch_id", "received_at", "status"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or type(value["sequence"]) is not int
                or any(value[name] != batch[name] for name in ("source_id", "generation", "sequence", "batch_id"))
                or value["status"] not in ("accepted", "duplicate")):
            raise ValueError
        stamp = value["received_at"]
        if not isinstance(stamp, str) or not re.fullmatch(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)", stamp):
            raise ValueError
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise DeliveryError("invalid_delivery_acknowledgement") from None


def _delay(value, attempt, now):
    if value:
        try:
            if len(value) > 128:
                raise ValueError
            if value.isascii() and value.isdigit():
                return float(value)
            return max(0, (parsedate_to_datetime(value) - now).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return 2 ** attempt


def run_once(directory, policy, transport, collect, *, now=utc_now, monotonic=time.monotonic, sleep=time.sleep):
    """Send at most one batch. collect(sequence) supplies JSON bytes, not credentials.

    A replay-only invocation never calls collect, even after a successful retry.
    Initialization, configuration and scheduling are explicit caller concerns.
    """
    endpoint = validate_endpoint(transport.endpoint)
    state = DeliveryState(directory, policy, endpoint)
    with state.locked() as directory_fd:
        value = state.load(directory_fd, now=now())
        pending = value["pending"]
        if pending is None:
            raw = collect(value["next_sequence"])
            try:
                batch = validate_batch(raw, policy, received_at=now())
                if batch["sequence"] != value["next_sequence"]:
                    raise ValueError
            except (ProtocolError, ValueError):
                raise DeliveryError("invalid_collected_batch") from None
            pending = raw.decode("utf-8")
            value = {**value, "pending": pending}
            state.save(directory_fd, value)
        raw = pending.encode("utf-8")
        batch = validate_batch(raw, policy, received_at=now())
        deadline = monotonic() + 60
        for attempt in range(3):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                response = transport.send(raw, timeout=min(20, remaining))
            except DeliveryError as error:
                if error.code != "delivery_connection_failed":
                    raise
                response = None
            if response is not None:
                if response.status == 200:
                    _acknowledged(response, batch)
                    if value["next_sequence"] == 2**53 - 1:
                        raise DeliveryError("delivery_sequence_exhausted")
                    state.save(directory_fd, {**value, "pending": None,
                                              "next_sequence": value["next_sequence"] + 1})
                    return "acknowledged"
                if response.status not in RETRYABLE:
                    raise DeliveryError("delivery_rejected")
            if attempt == 2:
                break
            delay = _delay(response.retry_after if response else "", attempt, now())
            if delay >= deadline - monotonic():
                break
            sleep(delay)
        raise DeliveryError("delivery_retry_pending")


def batch_identity(policy, sequence):
    """Common envelope fields for a producer; observation content stays separate."""
    return {"schema_version": 1, "collector_id": policy.collector_id, "source_id": policy.source_id,
            "generation": policy.generation, "sequence": sequence,
            "batch_id": str(uuid.uuid5(uuid.UUID(policy.generation), str(sequence)))}
