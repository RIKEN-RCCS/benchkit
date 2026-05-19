"""Structured audit logging helpers for security-relevant portal events."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from flask import current_app, has_app_context, has_request_context, request


AUDIT_LOGGER_NAME = "benchkit.audit"
_SENSITIVE_DETAIL_KEYS = frozenset({
    "api_key",
    "code",
    "password",
    "secret",
    "token",
    "totp_code",
    "x-api-key",
})


class JsonAuditFormatter(logging.Formatter):
    """Render audit records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        event_type = getattr(record, "audit_event_type", record.getMessage())
        fields = getattr(record, "audit_fields", {})
        data = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "event_type": event_type,
        }
        if isinstance(fields, dict):
            data.update(fields)
        return json.dumps(data, ensure_ascii=False, sort_keys=True)


def configure_audit_logging(app):
    """Attach the shared audit logger to a Flask app."""
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    app.audit_logger = logger
    return logger


def _audit_logger() -> logging.Logger:
    if has_app_context() and hasattr(current_app, "audit_logger"):
        return current_app.audit_logger
    return logging.getLogger(AUDIT_LOGGER_NAME)


def _request_fields() -> dict[str, str]:
    if not has_request_context():
        return {}
    return {
        "endpoint": request.path,
        "method": request.method,
        "ip": request.remote_addr or "",
        "user_agent": request.headers.get("User-Agent", ""),
    }


def _sanitize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (details or {}).items():
        key_text = str(key)
        if key_text.lower() in _SENSITIVE_DETAIL_KEYS:
            safe[key_text] = "<redacted>"
        else:
            safe[key_text] = value
    return safe


def audit_event(
    event_type: str,
    *,
    actor: str | None = None,
    target: str | None = None,
    result: str | None = None,
    details: dict[str, Any] | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a structured audit event without logging secrets."""
    audit_fields = _request_fields()
    if actor is not None:
        audit_fields["actor"] = actor
    if target is not None:
        audit_fields["target"] = target
    if result is not None:
        audit_fields["result"] = result
    sanitized_details = _sanitize_details(details)
    if sanitized_details:
        audit_fields["details"] = sanitized_details
    audit_fields.update(fields)

    _audit_logger().log(
        level,
        event_type,
        extra={
            "audit_event_type": event_type,
            "audit_fields": audit_fields,
        },
    )
