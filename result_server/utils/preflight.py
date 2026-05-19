"""Production preflight checks for result_server secrets."""

from __future__ import annotations

from collections.abc import Mapping


MIN_SECRET_LENGTH = 32

FORBIDDEN_DEFAULTS = {
    "FLASK_SECRET_KEY": frozenset({
        "",
        "changeme",
        "dev-secret-key",
        "password",
        "secret",
    }),
    "RESULT_SERVER_KEY": frozenset({"", "dev-api-key", "changeme", "key", "secret"}),
}


def _validate_secret(name: str, value: str | None) -> list[str]:
    """Return validation errors for a secret-like configuration value."""
    errors: list[str] = []
    forbidden = FORBIDDEN_DEFAULTS.get(name, frozenset({""}))
    normalized = value.strip().lower() if value else ""
    if not value:
        errors.append(f"{name} is not set")
    elif normalized in forbidden:
        errors.append(f"{name} is set to a known-insecure default")
    elif len(value) < MIN_SECRET_LENGTH:
        errors.append(f"{name} must be at least {MIN_SECRET_LENGTH} characters")
    return errors


def validate_ingest_keys(ingest_keys: Mapping[str, str]) -> list[str]:
    """Return validation errors for runner-scoped ingest keys."""
    errors: list[str] = []
    if not ingest_keys:
        return ["RESULT_SERVER_KEYS or RESULT_SERVER_KEY is not set"]

    for key, runner_id in ingest_keys.items():
        errors.extend(_validate_secret("RESULT_SERVER_KEY", key))
        if not runner_id:
            errors.append("RESULT_SERVER_KEYS contains an empty runner id")

    return errors


def validate_production_config(
    env: Mapping[str, str],
    ingest_keys: Mapping[str, str],
) -> list[str]:
    """Return production startup errors for insecure result_server config."""
    errors = _validate_secret("FLASK_SECRET_KEY", env.get("FLASK_SECRET_KEY"))
    errors.extend(validate_ingest_keys(ingest_keys))
    if env.get("FLASK_DEBUG") in {"1", "true", "True"}:
        errors.append("FLASK_DEBUG must not be enabled for app.py")
    return errors
