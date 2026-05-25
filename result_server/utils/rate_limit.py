"""Redis-backed endpoint rate limiting helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps

from flask import abort, current_app, request
from werkzeug.exceptions import HTTPException

from utils.audit_logging import audit_event


RateKeyFunc = Callable[[object], str]


def _configured_limit(scope: str, default: int) -> int:
    """Return a scope-specific rate limit, allowing tests/deployments to override."""
    overrides = current_app.config.get("RATE_LIMITS", {})
    return int(overrides.get(scope, default))


def enforce_rate_limit(
    *,
    redis_conn,
    key_suffix: str,
    max_per_minute: int,
    scope: str,
) -> None:
    """Apply a simple Redis-backed fixed-window rate limit or abort on excess."""
    if redis_conn is None:
        if current_app.config.get("AUTH_REQUIRES_REDIS"):
            abort(503, description="Rate limiting service unavailable")
        return

    redis_prefix = current_app.config.get("REDIS_PREFIX", "")
    redis_key = f"{redis_prefix}rate:{scope}:{key_suffix}"
    limit = _configured_limit(scope, max_per_minute)

    try:
        count = redis_conn.incr(redis_key)
        if count == 1:
            redis_conn.expire(redis_key, 60)
        if count > limit:
            audit_event(
                "rate_limit_exceeded",
                actor=key_suffix,
                result="failure",
                level=logging.WARNING,
                details={
                    "scope": scope,
                    "count": count,
                    "threshold": limit,
                },
            )
            current_app.logger.warning(
                "rate_limit_exceeded",
                extra={
                    "rate_limit_scope": scope,
                    "rate_limit_key": key_suffix,
                    "rate_limit_count": count,
                    "rate_limit_threshold": limit,
                },
            )
            abort(429, description="Too many requests")
    except HTTPException:
        raise
    except Exception:
        current_app.logger.exception("Rate limit check failed")
        if current_app.config.get("AUTH_REQUIRES_REDIS"):
            abort(503, description="Rate limiting service unavailable")


def rate_limited(*, max_per_minute: int, key_fn: RateKeyFunc | None = None, scope: str):
    """Apply a simple Redis-backed fixed-window rate limit to a Flask view."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            redis_conn = current_app.config.get("REDIS_CONN")
            enforce_rate_limit(
                redis_conn=redis_conn,
                key_suffix=key_fn(request) if key_fn else (request.remote_addr or "unknown"),
                max_per_minute=max_per_minute,
                scope=scope,
            )

            return func(*args, **kwargs)

        return wrapper

    return decorator
