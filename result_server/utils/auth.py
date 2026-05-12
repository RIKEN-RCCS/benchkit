"""Authentication helpers shared by result_server API routes."""

from __future__ import annotations

import hmac
import os
import warnings
from collections.abc import Mapping
from typing import Optional

from flask import current_app


def parse_ingest_keys(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Parse RESULT_SERVER_KEYS/RESULT_SERVER_KEY into {api_key: runner_id}."""
    env = env or os.environ
    keys: dict[str, str] = {}

    multi_key_spec = env.get("RESULT_SERVER_KEYS", "").strip()
    if multi_key_spec:
        for entry in multi_key_spec.split(","):
            if not entry.strip():
                continue
            if ":" not in entry:
                warnings.warn(
                    "Ignoring RESULT_SERVER_KEYS entry without runner_id:key format.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            runner_id, key = (part.strip() for part in entry.split(":", 1))
            if not runner_id or not key:
                warnings.warn(
                    "Ignoring RESULT_SERVER_KEYS entry with empty runner_id or key.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            keys[key] = runner_id

    legacy_key = env.get("RESULT_SERVER_KEY", "").strip()
    if legacy_key:
        warnings.warn(
            "RESULT_SERVER_KEY is deprecated; use RESULT_SERVER_KEYS=runner-id:key.",
            DeprecationWarning,
            stacklevel=2,
        )
        keys.setdefault(legacy_key, "default")

    return keys


def verify_ingest_key(presented: str | None) -> Optional[str]:
    """Return the runner_id for a valid ingest key, otherwise None."""
    if not presented:
        return None

    keys = current_app.config.get("INGEST_KEYS")
    if keys is None:
        keys = parse_ingest_keys()

    for configured_key, runner_id in keys.items():
        if hmac.compare_digest(presented, configured_key):
            return runner_id
    return None
